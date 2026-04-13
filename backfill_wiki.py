#!/usr/bin/env python3
"""One-time backfill: ingest existing vault files into the wiki."""

import os
import re
import sys
import time
import yaml
from pathlib import Path
from wiki_ingest import (
    ingest_items_into_wiki,
    update_index,
    append_log,
)


def parse_vault_file(filepath):
    """Parse a vault markdown file into (item, evaluation) matching wiki_ingest format."""
    text = Path(filepath).read_text(encoding="utf-8")

    # Parse YAML frontmatter between --- markers
    if not text.startswith("---"):
        raise ValueError("No frontmatter found")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("Frontmatter not closed")
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4:]

    title = fm.get("title", Path(filepath).stem)
    url = fm.get("source", "")
    date = str(fm.get("date", ""))
    category = fm.get("category", "inbox")

    # Extract ## Summary and ## Key Insight sections from body
    def extract_section(text, heading):
        pattern = rf"## {heading}\s*\n(.*?)(?=\n## |\Z)"
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else ""

    summary = extract_section(body, "Summary")
    key_insight = extract_section(body, "Key Insight")

    item = {
        "title": title,
        "url": url,
        "source": "backfill",
        "summary": summary,
        "date": date,
    }
    evaluation = {
        "relevance": 0,
        "actionability": 0,
        "reliability": 0,
        "category": category,
        "one_line_summary": summary,
        "key_insight": key_insight,
    }
    return item, evaluation


def collect_vault_files(vault_path):
    """Collect .md files from vault subdirectories, grouped by category, sorted by date."""
    vault_path = Path(vault_path)
    categories = {}

    for subdir in sorted(vault_path.iterdir()):
        if not subdir.is_dir():
            continue
        files = sorted(
            f for f in subdir.glob("*.md")
            if not f.name.startswith("daily-")
        )
        if files:
            categories[subdir.name] = files

    return categories


def main():
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    vault_path = os.path.expanduser(config.get("vault_path", str(script_dir / "vault")))
    wiki_path = os.path.expanduser(config.get("wiki_path", str(script_dir / "wiki")))

    categories = collect_vault_files(vault_path)
    total = sum(len(files) for files in categories.values())
    print(f"Found {total} vault files across {len(categories)} categories")

    batch_size = 10
    processed = 0
    errors = 0

    for category, files in categories.items():
        print(f"\n=== Processing {category}/ ({len(files)} files) ===")

        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            batch_items = []

            for filepath in batch:
                try:
                    item, evaluation = parse_vault_file(filepath)
                    batch_items.append((item, evaluation))
                except Exception as e:
                    print(f"  [SKIP] {filepath.name}: {e}")
                    errors += 1

            if batch_items:
                try:
                    date_str = batch_items[0][0].get("date", "unknown")
                    ingest_items_into_wiki(batch_items, wiki_path, config, str(date_str))
                    processed += len(batch_items)
                    print(f"  [OK] Batch {i // batch_size + 1}: {len(batch_items)} items ({processed}/{total})")
                except Exception as e:
                    print(f"  [ERROR] Batch failed: {e}")
                    errors += len(batch_items)

            if i + batch_size < len(files):
                time.sleep(2)

    update_index(wiki_path)
    append_log(
        wiki_path,
        f"BACKFILL complete: {processed} processed, {errors} errors out of {total} total",
        time.strftime("%Y-%m-%d"),
    )

    print(f"\n=== Backfill Complete ===")
    print(f"Processed: {processed}/{total}")
    print(f"Errors:    {errors}")


if __name__ == "__main__":
    main()
