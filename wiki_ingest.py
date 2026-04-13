#!/usr/bin/env python3
"""
wiki_ingest.py — Synthesise collected insights into the personal knowledge wiki.

Entry point: ingest_items_into_wiki(saved_items, wiki_path, config, date_str)
"""

import glob
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_items_into_wiki(saved_items, wiki_path, config, date_str):
    """
    saved_items : list of (item, evaluation) tuples
                  item       — {title, url, source, summary}
                  evaluation — {relevance, actionability, reliability,
                                category, one_line_summary, key_insight}
    wiki_path   : path to wiki/ directory (str or Path)
    config      : loaded config dict
    date_str    : YYYY-MM-DD
    """
    wiki_path = Path(wiki_path)
    wiki_path.mkdir(parents=True, exist_ok=True)

    script_dir = Path(__file__).parent
    claude_md = read_claude_md(script_dir)

    for item, evaluation in saved_items:
        title = item.get("title", "untitled")
        try:
            related = find_related_pages(item, wiki_path)
            operations = call_claude_for_synthesis(
                item, evaluation, related, claude_md, config
            )
            applied = apply_file_operations(operations, wiki_path)
            msg = f"Ingested '{title[:60]}' → {applied} file(s) written"
            print(f"  [WIKI] {msg}")
            append_log(wiki_path, msg, date_str)
        except Exception as exc:
            err = f"Failed to ingest '{title[:60]}': {exc}"
            print(f"  [WIKI][ERROR] {err}")
            append_log(wiki_path, f"ERROR: {err}", date_str)

    update_index(wiki_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_claude_md(script_dir):
    """Read CLAUDE.md schema document from script directory."""
    path = Path(script_dir) / "CLAUDE.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def find_related_pages(item, wiki_path):
    """
    Scan wiki/entities/ and wiki/concepts/ for pages whose filenames or
    opening lines relate to the item title/category.

    Returns a dict: {relative_path: first_5_lines_content}
    """
    wiki_path = Path(wiki_path)
    keywords = _extract_keywords(item)
    related = {}

    for subdir in ("entities", "concepts"):
        scan_dir = wiki_path / subdir
        if not scan_dir.exists():
            continue
        for md_file in scan_dir.glob("*.md"):
            stem = md_file.stem.lower()
            # Check filename match
            if any(kw in stem for kw in keywords):
                related[str(md_file.relative_to(wiki_path.parent))] = _read_head(md_file)
                continue
            # Check first 5 lines
            head = _read_head(md_file)
            if any(kw in head.lower() for kw in keywords):
                related[str(md_file.relative_to(wiki_path.parent))] = head

    return related


def call_claude_for_synthesis(item, evaluation, related_pages, claude_md, config):
    """
    Call Claude CLI to synthesise wiki updates.
    Returns a list of file operation dicts: [{op, path, content}, ...]
    """
    model = config.get("model", "claude-sonnet-4-20250514")

    if related_pages:
        pages_block = "\n\n".join(
            f"--- {path} ---\n{content}" for path, content in related_pages.items()
        )
    else:
        pages_block = "None found"

    prompt = _build_prompt(item, evaluation, claude_md, pages_block)

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--max-tokens", "4096", prompt],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")

    return _parse_operations(result.stdout.strip())


def apply_file_operations(operations, wiki_path):
    """
    Write / update files described by operations list.
    Validates all paths are within wiki/.
    Returns count of files written.
    """
    wiki_path = Path(wiki_path)
    count = 0
    for op in operations:
        raw_path = op.get("path", "")
        content = op.get("content", "")

        if not raw_path.startswith("wiki/"):
            print(f"  [WIKI][WARN] Rejected unsafe path: {raw_path}")
            continue

        # Resolve relative to parent of wiki/ (i.e. the repo root)
        target = (wiki_path.parent / raw_path).resolve()

        # Second safety check: must be inside wiki_path
        try:
            target.relative_to(wiki_path.resolve())
        except ValueError:
            print(f"  [WIKI][WARN] Path escapes wiki dir: {raw_path}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        count += 1

    return count


def update_index(wiki_path):
    """Rebuild wiki/index.md by scanning all wiki pages' YAML frontmatter."""
    wiki_path = Path(wiki_path)
    pages_by_type = {}

    for md_file in sorted(wiki_path.rglob("*.md")):
        if md_file.name in ("index.md", "log.md"):
            continue
        fm = _parse_frontmatter(md_file)
        if not fm:
            continue
        page_type = fm.get("type", md_file.parent.name)
        pages_by_type.setdefault(page_type, []).append((md_file, fm))

    lines = [
        "# Wiki Index\n",
        f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
    ]

    for page_type, entries in sorted(pages_by_type.items()):
        lines.append(f"\n## {page_type.capitalize()}\n")
        lines.append("| Page | Description | Tags |\n")
        lines.append("|------|-------------|------|\n")
        for md_file, fm in entries:
            rel = md_file.relative_to(wiki_path)
            title = fm.get("title", md_file.stem)
            desc = fm.get("description", fm.get("summary", ""))
            tags = ", ".join(fm.get("tags", []) or [])
            lines.append(f"| [[{rel}\\|{title}]] | {desc} | {tags} |\n")

    index_path = wiki_path / "index.md"
    index_path.write_text("".join(lines), encoding="utf-8")


def append_log(wiki_path, message, date_str):
    """Append entry to wiki/log.md: YYYY-MM-DD HH:MM | OPERATION | message"""
    wiki_path = Path(wiki_path)
    log_path = wiki_path / "log.md"

    op = "ERROR" if message.startswith("ERROR") else "INGEST"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"{timestamp} | {op} | {message}\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _extract_keywords(item):
    """Return a set of lowercase keyword tokens from the item's title/category."""
    text = " ".join([
        item.get("title", ""),
        item.get("source", ""),
    ])
    # Split on non-alphanumeric, filter short tokens and stopwords
    stopwords = {"the", "a", "an", "is", "in", "of", "to", "and", "or", "for", "with"}
    tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
    return {t for t in tokens if t not in stopwords}


def _read_head(md_file, lines=5):
    """Read first N lines of a file as a single string."""
    try:
        with open(md_file, encoding="utf-8") as f:
            return "".join(f.readline() for _ in range(lines))
    except OSError:
        return ""


def _parse_operations(response_text):
    """
    Extract a JSON array of file operations from Claude's response.
    Handles responses wrapped in ```json ... ``` fences.
    """
    # Try to find a JSON array (possibly multi-line)
    match = re.search(r"\[.*\]", response_text, re.DOTALL)
    if not match:
        return []
    try:
        ops = json.loads(match.group(0))
        if isinstance(ops, list):
            return ops
    except json.JSONDecodeError:
        pass
    return []


def _parse_frontmatter(md_file):
    """Parse YAML frontmatter between --- markers. Returns dict or {}."""
    try:
        text = md_file.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _build_prompt(item, evaluation, claude_md, pages_block):
    title = item.get("title", "")
    url = item.get("url", "")
    category = evaluation.get("category", "inbox")
    one_line = evaluation.get("one_line_summary", "")
    key_insight = evaluation.get("key_insight", "")

    return f"""You are maintaining a personal knowledge wiki. Follow the schema rules below.

=== SCHEMA ===
{claude_md}
=== END SCHEMA ===

A new insight has been collected:

TITLE: {title}
CATEGORY: {category}
SUMMARY: {one_line}
KEY INSIGHT: {key_insight}
SOURCE: {url}
DATE: {datetime.now().strftime('%Y-%m-%d')}

=== EXISTING RELATED WIKI PAGES ===
{pages_block}
=== END EXISTING PAGES ===

Tasks:
1. Identify entities (tools, services, companies, protocols, languages) mentioned
2. Identify concepts (patterns, ideas, techniques) this relates to
3. For each entity/concept: CREATE a new page or UPDATE an existing one
4. Include [[wiki-links]] to cross-reference related pages
5. Follow the frontmatter schema exactly

Output ONLY a JSON array of file operations. No other text.
Format: [{{"op": "create"|"update", "path": "wiki/entities/slug-name.md", "content": "full markdown with frontmatter"}}]

Rules:
- For "update" ops, merge new info into existing content. Add a "## {datetime.now().strftime('%Y-%m-%d')} 업데이트" section. Never delete existing content.
- Slugify names for filenames: lowercase, hyphens, no special chars
- Maximum 3 entities + 2 concepts per item
- If no meaningful entities/concepts found, return empty array []"""
