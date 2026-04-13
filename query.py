#!/usr/bin/env python3
"""Query the wiki knowledge base using Claude."""

import argparse
import os
import subprocess
import sys
import yaml
import re
from pathlib import Path
from datetime import datetime


def load_config():
    script_dir = Path(__file__).parent
    with open(script_dir / "config.yaml") as f:
        return yaml.safe_load(f), script_dir


def read_wiki_index(wiki_path):
    """Read wiki/index.md for page catalog."""
    index_path = os.path.join(wiki_path, "index.md")
    if os.path.exists(index_path):
        with open(index_path) as f:
            return f.read()
    return ""


def find_relevant_pages(query, wiki_path, max_pages=10):
    """Find wiki pages relevant to the query.
    Strategy: keyword match on filenames and first lines, then read top matches in full."""
    keywords = set(query.lower().split())
    scored_pages = []

    for root, dirs, files in os.walk(wiki_path):
        for fname in files:
            if not fname.endswith(".md") or fname in ("index.md", "log.md"):
                continue
            filepath = os.path.join(root, fname)
            # Score by keyword overlap in filename
            name_lower = fname.lower().replace("-", " ").replace(".md", "")
            score = sum(1 for k in keywords if k in name_lower)

            # Also check first 10 lines for keyword hits
            try:
                with open(filepath) as f:
                    head = f.read(1000).lower()
                score += sum(1 for k in keywords if k in head)
            except:
                pass

            if score > 0:
                scored_pages.append((score, filepath))

    scored_pages.sort(reverse=True)

    # Read full content of top pages
    result = []
    for _, filepath in scored_pages[:max_pages]:
        with open(filepath) as f:
            rel = os.path.relpath(filepath, wiki_path)
            result.append(f"=== {rel} ===\n{f.read()}")

    # If no keyword matches, read all pages (small wiki fallback)
    if not result:
        for root, dirs, files in os.walk(wiki_path):
            for fname in files:
                if not fname.endswith(".md") or fname in ("index.md", "log.md"):
                    continue
                filepath = os.path.join(root, fname)
                with open(filepath) as f:
                    rel = os.path.relpath(filepath, wiki_path)
                    result.append(f"=== {rel} ===\n{f.read()}")
                if len(result) >= max_pages:
                    break

    return result


def query_wiki(query, config, wiki_path, script_dir, save=False):
    """Query the wiki using Claude."""
    # Read CLAUDE.md
    claude_md = ""
    claude_md_path = script_dir / "CLAUDE.md"
    if claude_md_path.exists():
        with open(claude_md_path) as f:
            claude_md = f.read()

    # Find relevant pages
    pages = find_relevant_pages(query, wiki_path)

    if not pages:
        print("Wiki is empty. Run collect-insights.py or backfill_wiki.py first.")
        return

    # Read index for overview
    index_content = read_wiki_index(wiki_path)

    pages_content = "\n\n".join(pages)

    prompt = f"""You are answering a question based on a personal knowledge wiki.

=== WIKI SCHEMA ===
{claude_md}
=== END SCHEMA ===

=== WIKI INDEX ===
{index_content}
=== END INDEX ===

=== RELEVANT WIKI PAGES ===
{pages_content}
=== END PAGES ===

Question: {query}

Answer the question based ONLY on what's in the wiki pages above.
Cite specific pages using [[Page Name]] format.
If the wiki doesn't contain enough information, say so.
Answer in the same language as the question."""

    model = config.get("model", "claude-sonnet-4-20250514")

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--max-tokens", "4096"],
            capture_output=True, text=True, timeout=120, env=env
        )

        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return

        answer = result.stdout.strip()
        print(answer)

        # Optionally save answer to wiki
        if save and answer:
            slug = re.sub(r'[^a-z0-9]+', '-', query.lower())[:50].strip('-')
            save_path = os.path.join(wiki_path, "summaries", f"{datetime.now().strftime('%Y-%m-%d')}-{slug}.md")

            content = f"""---
title: "Query: {query}"
type: summary
period: {datetime.now().strftime('%Y-%m-%d')}
tags: [query]
last_updated: {datetime.now().strftime('%Y-%m-%d')}
---

## Question
{query}

## Answer
{answer}
"""
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w") as f:
                f.write(content)
            print(f"\n[Saved to {save_path}]")

    except subprocess.TimeoutExpired:
        print("Error: Claude query timed out")


def main():
    parser = argparse.ArgumentParser(description="Query the wiki knowledge base")
    parser.add_argument("query", help="Question to ask the wiki")
    parser.add_argument("--save", action="store_true", help="Save the answer to wiki/summaries/")
    args = parser.parse_args()

    config, script_dir = load_config()
    wiki_path = os.path.expanduser(config.get("wiki_path", str(script_dir / "wiki")))

    query_wiki(args.query, config, wiki_path, script_dir, save=args.save)


if __name__ == "__main__":
    main()
