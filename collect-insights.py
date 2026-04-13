#!/usr/bin/env python3

import feedparser
import yaml
import requests
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def load_config(config_path="config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_state(state_path="state.json"):
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            return json.load(f)
    return {"seen_ids": [], "last_run": None}


def save_state(state, state_path="state.json"):
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:60]


def collect_geek_news(config):
    items = []
    source_cfg = config.get("sources", {}).get("geek_news", {})
    if not source_cfg.get("enabled", False):
        return items
    url = source_cfg.get("url", "https://news.hada.io/rss")
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            items.append({
                "id": entry.get("link", ""),
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": "geek_news",
                "summary": entry.get("summary", ""),
            })
    except Exception as e:
        print(f"[ERROR] Geek News collection failed: {e}")
    return items


def collect_hn(config):
    items = []
    hn_config = config.get("sources", {}).get("hacker_news", {})
    if not hn_config.get("enabled", False):
        return items
    min_points = hn_config.get("min_points", 50)
    api_url = hn_config.get("url", "https://hn.algolia.com/api/v1/search_by_date")

    now = datetime.now(timezone.utc)
    ts_24h_ago = int(now.timestamp()) - 86400

    try:
        resp = requests.get(
            api_url,
            params={
                "tags": "story",
                "numericFilters": f"points>{min_points},created_at_i>{ts_24h_ago}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        for hit in data.get("hits", []):
            object_id = hit.get("objectID", "")
            items.append({
                "id": f"hn-{object_id}",
                "title": hit.get("title", ""),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
                "source": "hacker_news",
                "summary": hit.get("story_text", "") or "",
            })
    except Exception as e:
        print(f"[ERROR] HN collection failed: {e}")
    return items


def collect_github_releases(config):
    items = []
    gh_config = config.get("sources", {}).get("github_releases", {})
    if not gh_config.get("enabled", False):
        return items
    repos = gh_config.get("repos", [])
    for repo in repos:
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/releases/latest"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                print(f"[WARN] gh api failed for {repo}: {result.stderr.strip()}")
                continue
            release = json.loads(result.stdout)
            tag_name = release.get("tag_name", "")
            items.append({
                "id": f"gh-{repo}-{tag_name}",
                "title": f"{repo} {tag_name}: {release.get('name', '')}",
                "url": release.get("html_url", ""),
                "source": "github_releases",
                "summary": (release.get("body", "") or "")[:500],
            })
        except Exception as e:
            print(f"[ERROR] GitHub release collection failed for {repo}: {e}")
    return items


def evaluate_item(item, config):
    context = config.get("evaluation", {}).get("context", "")
    model = config.get("model", "claude-sonnet-4-20250514")

    prompt = f"""You are an expert content curator. Evaluate this item for relevance, actionability, and reliability.
{context}

Title: {item['title']}
URL: {item['url']}
Source: {item['source']}
Summary: {item['summary'][:1000]}

Return ONLY a JSON object:
{{
  "relevance": <1-5>,
  "actionability": <1-5>,
  "reliability": <1-5>,
  "category": "<claude-code|architecture|tools|inbox>",
  "one_line_summary": "<concise summary>",
  "key_insight": "<the most important takeaway>"
}}"""

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    result = subprocess.run(
        ["claude", "-p", "--model", model, prompt],
        capture_output=True, text=True, timeout=60, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")

    text = result.stdout.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(text)


def send_telegram(item, evaluation, config):
    tg = config.get("telegram", {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", tg.get("bot_token"))
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", tg.get("chat_id"))
    if not token or not chat_id:
        return

    score = (
        evaluation.get("relevance", 0)
        + evaluation.get("actionability", 0)
        + evaluation.get("reliability", 0)
    )
    category = evaluation.get("category", "inbox")
    title = item.get("title", "")
    url = item.get("url", "")
    summary = evaluation.get("one_line_summary", "")
    insight = evaluation.get("key_insight", "")

    text = (
        f"⭐ *Insight* (score:{score}, {category})\n\n"
        f"*{title}*\n\n"
        f"{summary}\n\n"
        f"💡 {insight}\n\n"
        f"[원문 링크]({url})"
    )

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"  [TELEGRAM] Sent: {item['title'][:50]}")
    except Exception as e:
        print(f"  [WARN] Telegram send failed: {e}")


def send_telegram_summary(saved_items, skipped_items, all_evaluated, n_collected, config, date_str):
    tg = config.get("telegram", {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", tg.get("bot_token"))
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", tg.get("chat_id"))
    if not token or not chat_id:
        return
    if not all_evaluated:
        return

    tg_min = tg.get("min_score", 12)

    high = []    # score >= tg_min (12+)
    mid = []     # 10 <= score < tg_min (10-11)

    for item, evaluation, filepath in saved_items:
        score = (
            evaluation.get("relevance", 0)
            + evaluation.get("actionability", 0)
            + evaluation.get("reliability", 0)
        )
        category = evaluation.get("category", "inbox")
        entry = (item.get("title", ""), item.get("url", ""), score, category)
        if score >= tg_min:
            high.append(entry)
        else:
            mid.append(entry)

    n_evaluated = len(all_evaluated)
    n_saved = len(saved_items)
    n_skipped = n_evaluated - n_saved

    lines = [
        f"📊 Daily Insights ({date_str})",
        f"수집: {n_collected}건 → 평가: {n_evaluated}건 → 선별: {n_saved}건",
    ]

    if high:
        lines.append(f"\n⭐ {tg_min}+ ({len(high)}건)")
        for title, url, score, category in high:
            lines.append(f"• [{title}]({url}) ({score}) - {category}")

    if mid:
        lines.append(f"\n✅ 10-{tg_min - 1} ({len(mid)}건)")
        for title, url, score, category in mid:
            lines.append(f"• [{title}]({url}) ({score}) - {category}")

    if n_skipped:
        lines.append(f"\n⬚ 9 이하 ({n_skipped}건) - 스킵됨")

    text = "\n".join(lines)

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"  [TELEGRAM] Summary sent: {n_saved} saved, {n_skipped} skipped")
    except Exception as e:
        print(f"  [WARN] Telegram summary send failed: {e}")


def save_to_vault(item, evaluation, vault_path, date_str):
    category = evaluation.get("category", "inbox")
    title = item.get("title", "untitled")
    slug = slugify(title)
    filename = f"{date_str}-{slug}.md"

    category_dir = Path(vault_path) / category
    category_dir.mkdir(parents=True, exist_ok=True)

    filepath = category_dir / filename

    score = (
        evaluation.get("relevance", 0)
        + evaluation.get("actionability", 0)
        + evaluation.get("reliability", 0)
    )

    frontmatter = f"""---
title: "{title.replace('"', "'")}"
source: "{item.get('url', '')}"
score: {score}
date: {date_str}
category: {category}
---

"""

    body = f"""## Summary

{evaluation.get('one_line_summary', '')}

## Key Insight

{evaluation.get('key_insight', '')}

## Source

[{title}]({item.get('url', '')})
"""

    with open(filepath, "w") as f:
        f.write(frontmatter + body)

    return filepath


def commit_and_push_vault(project_dir, vault_path, date_str):
    """Stage vault/ and state.json, commit if changed, then push to origin."""
    repo_dir = str(project_dir)

    def run_git(*args, **kwargs):
        return subprocess.run(
            ["git", "-C", repo_dir] + list(args),
            capture_output=True,
            text=True,
            timeout=30,
            **kwargs,
        )

    try:
        # Stage vault directory (relative path from repo root)
        vault_rel = os.path.relpath(vault_path, repo_dir)
        stage_vault = run_git("add", vault_rel)
        if stage_vault.returncode != 0:
            print(f"  [WARN] git add vault failed: {stage_vault.stderr.strip()}")

        # Also stage wiki/ changes
        wiki_dir = os.path.join(repo_dir, "wiki")
        if os.path.exists(wiki_dir):
            wiki_rel = os.path.relpath(wiki_dir, repo_dir)
            run_git("add", wiki_rel)

        # Stage state.json
        stage_state = run_git("add", "state.json")
        if stage_state.returncode != 0:
            print(f"  [WARN] git add state.json failed: {stage_state.stderr.strip()}")

        # Check if there are staged changes
        diff_check = run_git("diff", "--cached", "--quiet")
        if diff_check.returncode == 0:
            print("  [GIT] No staged changes — skipping commit.")
            return

        # Commit
        commit_msg = f"chore: update vault {date_str} {datetime.now().strftime('%H:%M')}"
        commit_result = run_git("commit", "-m", commit_msg)
        if commit_result.returncode != 0:
            print(f"  [ERROR] git commit failed: {commit_result.stderr.strip()}")
            return
        print(f"  [GIT] Committed: {commit_msg}")

        # Push
        push_result = run_git("push", "origin")
        if push_result.returncode != 0:
            print(f"  [ERROR] git push failed: {push_result.stderr.strip()}")
            return
        print("  [GIT] Pushed to origin.")

    except subprocess.TimeoutExpired:
        print("  [ERROR] git operation timed out.")
    except Exception as e:
        print(f"  [ERROR] commit_and_push_vault failed: {e}")


def append_daily_summary(saved_items, vault_path, date_str):
    inbox_dir = Path(vault_path) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    daily_path = inbox_dir / f"daily-{date_str}.md"

    lines = [f"\n## Insights - {date_str}\n\n"]
    for item, evaluation, filepath in saved_items:
        score = (
            evaluation.get("relevance", 0)
            + evaluation.get("actionability", 0)
            + evaluation.get("reliability", 0)
        )
        category = evaluation.get("category", "inbox")
        title = item.get("title", "untitled")
        url = item.get("url", "")
        summary = evaluation.get("one_line_summary", "")
        lines.append(f"- **[{title}]({url})** (score:{score}, {category})\n  {summary}\n")

    with open(daily_path, "a") as f:
        f.writelines(lines)


def main():
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"
    state_path = script_dir / "state.json"

    config = load_config(config_path)
    state = load_state(state_path)
    seen_ids = set(state.get("seen_ids", []))

    vault_path = os.path.expanduser(config.get("vault_path", "~/obsidian-vault"))
    score_threshold = config.get("score_threshold", 10)
    date_str = datetime.now().strftime("%Y-%m-%d")

    print("Collecting items...")
    all_items = []
    all_items.extend(collect_geek_news(config))
    all_items.extend(collect_hn(config))
    all_items.extend(collect_github_releases(config))

    new_items = [item for item in all_items if item["id"] not in seen_ids]
    print(f"Collected: {len(all_items)} total, {len(new_items)} new")

    if not new_items:
        print("No new items to evaluate.")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        save_state(state, state_path)
        return

    evaluated = 0
    saved_count = 0
    saved_items = []
    skipped_items = []
    all_evaluated = []
    new_seen_ids = list(seen_ids)

    for item in new_items:
        item_id = item["id"]
        try:
            evaluation = evaluate_item(item, config)
            evaluated += 1

            score = (
                evaluation.get("relevance", 0)
                + evaluation.get("actionability", 0)
                + evaluation.get("reliability", 0)
            )

            new_seen_ids.append(item_id)
            all_evaluated.append((item, evaluation))

            if score >= score_threshold:
                filepath = save_to_vault(item, evaluation, vault_path, date_str)
                saved_items.append((item, evaluation, filepath))
                saved_count += 1
                print(f"  [SAVED] score={score} | {item['title'][:60]}")
            else:
                skipped_items.append((item, evaluation))
                print(f"  [SKIP]  score={score} | {item['title'][:60]}")

        except Exception as e:
            print(f"  [ERROR] {item_id}: {e}")
            new_seen_ids.append(item_id)

    if saved_items:
        append_daily_summary(saved_items, vault_path, date_str)
        send_telegram_summary(saved_items, skipped_items, all_evaluated, len(new_items), config, date_str)

    state["seen_ids"] = new_seen_ids
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)

    # Wiki synthesis
    wiki_path = os.path.expanduser(config.get("wiki_path", str(script_dir / "wiki")))
    if config.get("wiki_enabled", True) and saved_items:
        try:
            from wiki_ingest import ingest_items_into_wiki
            ingest_items_into_wiki(saved_items, wiki_path, config, date_str)
            print(f"  [WIKI] Synthesis complete for {len(saved_items)} items")
        except Exception as e:
            print(f"  [WARN] Wiki synthesis failed (non-fatal): {e}")

    commit_and_push_vault(script_dir, vault_path, date_str)

    print(f"\nDone. Collected: {len(new_items)}, Evaluated: {evaluated}, Saved: {saved_count}")


if __name__ == "__main__":
    main()
