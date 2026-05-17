#!/usr/bin/env python3
"""
Diff two channels.json files and report meaningful lineup changes.

Usage:
  python scripts/detect_channel_changes.py old.json new.json

Exit codes:
  0 — no significant changes (number tweaks, description edits only)
  1 — significant changes: channels added, removed, or renumbered

Output (stdout):
  Markdown-formatted report suitable for a GitHub issue body.

Called by .github/workflows/update-channels.yml to decide whether to open an issue.
"""

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} old.json new.json", file=sys.stderr)
        sys.exit(2)

    old: dict = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    new: dict = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    old_keys = set(old)
    new_keys = set(new)

    added   = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)

    # Detect number changes on stable channels
    number_changed = []
    for key in old_keys & new_keys:
        o_num = old[key].get("sxm_number")
        n_num = new[key].get("sxm_number")
        if o_num != n_num:
            number_changed.append((key, o_num, n_num, new[key]["name"]))

    # Fuzzy-pair removed ↔ added as probable renames (similarity > 0.75)
    renames: list[tuple[str, str]] = []
    unmatched_added = list(added)
    unmatched_removed = list(removed)
    for rem in removed:
        best_score, best_add = 0.0, None
        for add in unmatched_added:
            s = _sim(rem, add)
            if s > best_score:
                best_score, best_add = s, add
        if best_score >= 0.75 and best_add is not None:
            renames.append((rem, best_add))
            unmatched_added.remove(best_add)
            unmatched_removed.remove(rem)

    # Build report
    lines = ["## SiriusXM Channel Lineup Changes\n"]
    significant = bool(added or removed or number_changed)

    if not significant:
        lines.append("No significant changes detected (descriptions or metadata only).\n")
        print("\n".join(lines))
        sys.exit(0)

    if unmatched_added:
        lines.append(f"### New Channels ({len(unmatched_added)})\n")
        for k in unmatched_added:
            ch = new[k]
            num = f"Ch. {ch['sxm_number']}" if ch.get("sxm_number") else "no ch#"
            lines.append(f"- **{ch['name']}** ({num}) — {ch.get('description','')[:80]}")
        lines.append("")

    if unmatched_removed:
        lines.append(f"### Removed Channels ({len(unmatched_removed)})\n")
        for k in unmatched_removed:
            ch = old[k]
            num = f"Ch. {ch['sxm_number']}" if ch.get("sxm_number") else "no ch#"
            lines.append(f"- **{ch['name']}** ({num}) — {ch.get('description','')[:80]}")
        lines.append("")

    if renames:
        lines.append(f"### Possible Renames ({len(renames)}) — verify manually\n")
        for rem, add in renames:
            lines.append(f"- **{old[rem]['name']}** → **{new[add]['name']}**")
        lines.append("")

    if number_changed:
        lines.append(f"### Channel Number Changes ({len(number_changed)})\n")
        for key, o_num, n_num, name in number_changed:
            lines.append(f"- **{name}**: Ch. {o_num} → Ch. {n_num}")
        lines.append("")

    lines.append("---")
    lines.append(
        "_Detected automatically by [EPGeditARR](https://github.com/jstevenscl/epgeditarr) "
        "weekly channel cache update. Update `channels.json`, logo cache, and plugin aliases as needed._"
    )

    print("\n".join(lines))
    sys.exit(1)


if __name__ == "__main__":
    main()
