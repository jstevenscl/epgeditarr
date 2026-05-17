#!/usr/bin/env python3
"""
Monitor sports EPG output for season changes and anomalies.
Run automatically by update-sports-epg.yml after each successful build.

Reads sports_schedule.json for current event counts per sport.
Compares against sports_counts.json from the previous run.
Creates GitHub issues (via gh CLI) when attention is needed:
  - A sport goes from 0 events to having events (season/pre-season starting)
  - A sport drops from having events to 0 mid-run (possible scraper regression)
  - ALL sports drop to 0 when they previously had events
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT          = Path(__file__).parent.parent
SCHEDULE_JSON = ROOT / "sports_schedule.json"
COUNTS_JSON   = ROOT / "sports_counts.json"

SPORT_LABELS = {
    "nfl":     "NFL",
    "nba":     "NBA",
    "mlb":     "MLB",
    "nhl":     "NHL",
    "soccer":  "Soccer",
    "nascar":  "NASCAR",
    "pga":     "PGA Tour",
    "indycar": "IndyCar",
    "f1":      "Formula 1",
}

LABEL = "sports-epg"


def gh_issue_create(title, body):
    try:
        subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body, "--label", LABEL],
            check=True, capture_output=True, text=True,
        )
        print(f"  [issue created] {title}")
    except subprocess.CalledProcessError as e:
        print(f"  [issue create failed] {e.stderr.strip()}", file=sys.stderr)


def gh_open_issue_titles():
    """Return set of title strings for all currently open sports-epg issues."""
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--label", LABEL, "--state", "open",
             "--json", "title", "--limit", "50"],
            capture_output=True, text=True, check=True,
        )
        return {i["title"] for i in json.loads(result.stdout)}
    except Exception:
        return set()


def ensure_label():
    """Create the sports-epg label if it doesn't exist yet."""
    try:
        subprocess.run(
            ["gh", "label", "create", LABEL, "--color", "0075ca",
             "--description", "Sports EPG monitoring alerts"],
            capture_output=True, text=True,
        )
    except Exception:
        pass  # already exists or gh not available


def main():
    ensure_label()

    # Load previous counts
    prev_counts = {}
    if COUNTS_JSON.exists():
        try:
            prev_counts = json.loads(COUNTS_JSON.read_text())
        except Exception:
            pass

    # Load current schedule
    try:
        schedule = json.loads(SCHEDULE_JSON.read_text())
    except Exception as e:
        gh_issue_create(
            f"Sports EPG: sports_schedule.json unreadable ({datetime.now(timezone.utc).date()})",
            f"Could not read `sports_schedule.json` after a successful build run.\n\n"
            f"Error: `{e}`\n\n"
            f"This likely means the build script crashed before writing output. "
            f"Check the workflow run logs.",
        )
        sys.exit(1)

    events = schedule.get("events", [])

    # Count events per sport
    current_counts = {slug: 0 for slug in SPORT_LABELS}
    for ev in events:
        slug = ev.get("slug")
        if slug in current_counts:
            current_counts[slug] += 1

    total_now  = sum(current_counts.values())
    total_prev = sum(prev_counts.values())

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    open_titles = gh_open_issue_titles()

    print(f"Previous counts: {prev_counts}")
    print(f"Current counts : {current_counts}")

    # ── Season start: sport went from 0 to having events ────────────────────
    for slug, count in current_counts.items():
        prev  = prev_counts.get(slug, 0)
        label = SPORT_LABELS[slug]
        if prev == 0 and count > 0:
            title = f"{label} season detected -- verify EPG scraping ({date_str})"
            if not any(f"{label} season detected" in t for t in open_titles):
                gh_issue_create(
                    title,
                    f"## {label} season is starting\n\n"
                    f"The scraper picked up **{count} upcoming event(s)** for {label} "
                    f"for the first time this season.\n\n"
                    f"**Please verify the data looks correct before the season matters:**\n\n"
                    f"- [ ] Run `build_sports_epg.py` locally and inspect `sports_schedule.json`\n"
                    f"- [ ] Confirm game titles match expected format "
                    f"(e.g. `Away Team @ Home Team`)\n"
                    f"- [ ] Confirm channel numbers are mapping to correct channel names\n"
                    f"- [ ] Confirm start/end times look reasonable for that sport\n"
                    f"- [ ] Run `fill_sports_epg` in Dispatcharr and check the guide\n"
                    f"- [ ] Check Upcoming / LIVE / Post-game block titles look right\n\n"
                    f"Close this issue once verified.",
                )

    # ── Mid-season dropout: sport had events, now has 0 ─────────────────────
    for slug, count in current_counts.items():
        prev  = prev_counts.get(slug, 0)
        label = SPORT_LABELS[slug]
        if prev > 0 and count == 0:
            title = f"{label} dropped to 0 events -- possible scraper issue ({date_str})"
            if not any(f"{label} dropped to 0" in t for t in open_titles):
                gh_issue_create(
                    title,
                    f"## {label} went from {prev} events to 0\n\n"
                    f"This may be normal (end of season, bye week, no games scheduled "
                    f"in the next 14-day window) or it may indicate the SiriusXM "
                    f"schedule page changed structure.\n\n"
                    f"**Please check:**\n\n"
                    f"- [ ] Visit https://www.siriusxm.com/sports/{slug} manually "
                    f"— are games listed?\n"
                    f"- [ ] If games are listed but the scraper missed them, "
                    f"the page HTML structure may have changed\n"
                    f"- [ ] Run `build_sports_epg.py` locally with extra print statements "
                    f"to debug\n\n"
                    f"Close this issue once confirmed (season over) or fixed (scraper updated).",
                )

    # ── All sports dropped to 0 when they had events before ─────────────────
    if total_now == 0 and total_prev > 0:
        title = f"Sports EPG: all sports showing 0 events ({date_str})"
        if not any("all sports showing 0 events" in t for t in open_titles):
            gh_issue_create(
                title,
                f"## All sports dropped to 0 events\n\n"
                f"Previous total: **{total_prev} events** across all sports.\n"
                f"Current total: **0 events**.\n\n"
                f"Previous per-sport breakdown:\n"
                f"```\n{json.dumps(prev_counts, indent=2)}\n```\n\n"
                f"Possible causes:\n"
                f"- All sports are genuinely in off-season\n"
                f"- SiriusXM changed page structure for all schedule pages\n"
                f"- Network issue during the build run\n\n"
                f"Check the workflow run logs and visit a few schedule pages manually.",
            )

    # Save current counts for next run
    COUNTS_JSON.write_text(json.dumps(current_counts, indent=2))
    print(f"Counts saved to {COUNTS_JSON}")
    print(f"Total: {total_now} events")


if __name__ == "__main__":
    main()
