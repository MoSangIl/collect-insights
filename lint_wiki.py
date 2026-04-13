#!/usr/bin/env python3
"""Weekly wiki health check: find orphans, broken links, missing pages, stale content."""

import os
import re
import yaml
from pathlib import Path
from datetime import datetime, timedelta


def load_config():
    script_dir = Path(__file__).parent
    with open(script_dir / "config.yaml") as f:
        return yaml.safe_load(f), script_dir


def scan_wiki_pages(wiki_path):
    """Scan all wiki .md files, return dict: {relative_path: {frontmatter, content, wiki_links}}"""
    pages = {}
    for root, dirs, files in os.walk(wiki_path):
        for fname in files:
            if not fname.endswith(".md") or fname in ("index.md", "log.md"):
                continue
            filepath = os.path.join(root, fname)
            rel = os.path.relpath(filepath, wiki_path)

            with open(filepath) as f:
                content = f.read()

            # Parse frontmatter
            frontmatter = {}
            fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
            if fm_match:
                try:
                    frontmatter = yaml.safe_load(fm_match.group(1)) or {}
                except:
                    pass

            # Extract wiki links [[Page Name]]
            wiki_links = re.findall(r'\[\[([^\]]+)\]\]', content)

            pages[rel] = {
                "frontmatter": frontmatter,
                "content": content,
                "wiki_links": wiki_links,
                "path": filepath,
            }

    return pages


def check_orphan_pages(pages):
    """Find pages with no incoming links from other pages."""
    # Build set of all page names (stem without extension, from all paths)
    all_targets = set()
    for rel in pages:
        stem = Path(rel).stem
        all_targets.add(stem)

    # Build set of pages that ARE linked to
    linked_to = set()
    for rel, info in pages.items():
        for link in info["wiki_links"]:
            # Normalize: lowercase and slugify for matching
            linked_to.add(link.lower().replace(" ", "-"))
            linked_to.add(link)  # also keep original

    orphans = []
    for rel in pages:
        stem = Path(rel).stem
        if stem.lower() not in linked_to and stem not in linked_to:
            orphans.append(rel)

    return orphans


def check_broken_links(pages):
    """Find [[wiki-links]] that don't match any existing page filename."""
    all_stems = set()
    for rel in pages:
        stem = Path(rel).stem
        all_stems.add(stem.lower())
        all_stems.add(stem)

    broken = []
    for rel, info in pages.items():
        for link in info["wiki_links"]:
            slug = link.lower().replace(" ", "-")
            if slug not in all_stems and link not in all_stems:
                broken.append({"page": rel, "link": link})

    return broken


def check_stale_pages(pages, days=30):
    """Find pages not updated in N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    stale = []
    for rel, info in pages.items():
        last_updated = str(info["frontmatter"].get("last_updated", ""))
        if last_updated and last_updated < cutoff:
            stale.append({"page": rel, "last_updated": last_updated})
    return stale


def check_missing_concept_pages(pages, wiki_path):
    """Find concepts mentioned frequently in entities but lacking their own page."""
    # Collect all tags from entity pages
    tag_counts = {}
    for rel, info in pages.items():
        if "entities/" in rel:
            for tag in info["frontmatter"].get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Check which tags don't have concept pages
    concept_stems = set()
    for rel in pages:
        if "concepts/" in rel:
            concept_stems.add(Path(rel).stem)

    missing = []
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        slug = tag.lower().replace(" ", "-")
        if slug not in concept_stems and count >= 2:
            missing.append({"concept": tag, "mentions": count})

    return missing


def generate_report(wiki_path, pages):
    """Generate lint report markdown."""
    date_str = datetime.now().strftime("%Y-%m-%d")

    orphans = check_orphan_pages(pages)
    broken = check_broken_links(pages)
    stale = check_stale_pages(pages)
    missing = check_missing_concept_pages(pages, wiki_path)

    total_issues = len(orphans) + len(broken) + len(stale) + len(missing)

    report = f"""---
title: "Lint Report {date_str}"
type: lint
date: {date_str}
total_issues: {total_issues}
---

# Wiki Lint Report — {date_str}

Total pages: {len(pages)} | Total issues: {total_issues}

## Orphan Pages ({len(orphans)})
Pages with no incoming [[wiki-links]] from other pages.

"""
    if orphans:
        for p in orphans:
            report += f"- `{p}`\n"
    else:
        report += "None found.\n"

    report += f"\n## Broken Links ({len(broken)})\n[[wiki-links]] pointing to non-existent pages.\n\n"
    if broken:
        for b in broken:
            report += f"- `{b['page']}` → [[{b['link']}]]\n"
    else:
        report += "None found.\n"

    report += f"\n## Stale Pages ({len(stale)})\nPages not updated in 30+ days.\n\n"
    if stale:
        for s in stale:
            report += f"- `{s['page']}` (last: {s['last_updated']})\n"
    else:
        report += "None found.\n"

    report += f"\n## Missing Concept Pages ({len(missing)})\nTags mentioned in 2+ entity pages but without a dedicated concept page.\n\n"
    if missing:
        for m in missing:
            report += f"- **{m['concept']}** ({m['mentions']} mentions)\n"
    else:
        report += "None found.\n"

    return report, total_issues


def main():
    config, script_dir = load_config()
    wiki_path = os.path.expanduser(config.get("wiki_path", str(script_dir / "wiki")))

    print(f"Scanning wiki at {wiki_path}...")
    pages = scan_wiki_pages(wiki_path)
    print(f"Found {len(pages)} wiki pages")

    report, total_issues = generate_report(wiki_path, pages)

    # Write report
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(wiki_path, f"lint-report-{date_str}.md")
    with open(report_path, "w") as f:
        f.write(report)

    # Append to log
    log_path = os.path.join(wiki_path, "log.md")
    with open(log_path, "a") as f:
        f.write(f"\n{date_str} {datetime.now().strftime('%H:%M')} | LINT | {total_issues} issues found across {len(pages)} pages")

    print(f"\nLint report written to {report_path}")
    print(f"Issues found: {total_issues}")


if __name__ == "__main__":
    main()
