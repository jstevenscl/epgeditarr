#!/usr/bin/env python3
"""
Diff two channels.json files and report meaningful lineup changes.

Usage:
  python scripts/detect_channel_changes.py old.json new.json [--apply-aliases aliases.json]

Exit codes:
  0 — no significant changes (number tweaks, description edits only)
  1 — significant changes: channels added, removed, or renumbered

Output (stdout):
  Markdown-formatted report suitable for a GitHub issue body.

--apply-aliases: when given, renames matched by identical sxm_number (the
high-confidence pass — same station number, name changed) are written into
the aliases file automatically as {old_name: new_name}, so existing
Dispatcharr channels still using the old name keep matching. Fuzzy
name-only matches stay manual-review-only in the report; confidence there
isn't high enough to auto-apply.

Called by .github/workflows/update-channels.yml to decide whether to open
an issue and (optionally) to keep channel_aliases.json current.
"""

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

GITHUB_PAGES_BASE = "https://jstevenscl.github.io/epgeditarr/logos"


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _has_logo(ch: dict) -> bool:
    return (ch.get("logo_url") or "").startswith(GITHUB_PAGES_BASE)


def _apply_aliases(aliases_path: Path, number_renames: list[tuple[str, str, str]]) -> int:
    """Write {old_name: new_name} for number-matched renames. Returns count added."""
    if not number_renames:
        return 0
    data = json.loads(aliases_path.read_text(encoding="utf-8"))
    aliases = data.setdefault("aliases", {})
    added = 0
    for old_name, new_name in number_renames:
        key = old_name.strip().lower()
        if aliases.get(key) != new_name:
            aliases[key] = new_name
            added += 1
    if added:
        aliases_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return added


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} old.json new.json [--apply-aliases aliases.json] [--write-removed removed.json]", file=sys.stderr)
        sys.exit(2)

    old: dict = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    new: dict = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    apply_aliases_path = None
    if "--apply-aliases" in sys.argv:
        apply_aliases_path = Path(sys.argv[sys.argv.index("--apply-aliases") + 1])

    write_removed_path = None
    if "--write-removed" in sys.argv:
        write_removed_path = Path(sys.argv[sys.argv.index("--write-removed") + 1])

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

    # Fuzzy-pair removed <-> added as probable renames (similarity > 0.75)
    fuzzy_renames: list[tuple[str, str]] = []
    unmatched_added = list(added)
    unmatched_removed = list(removed)
    for rem in removed:
        best_score, best_add = 0.0, None
        for add in unmatched_added:
            s = _sim(rem, add)
            if s > best_score:
                best_score, best_add = s, add
        if best_score >= 0.75 and best_add is not None:
            fuzzy_renames.append((rem, best_add))
            unmatched_added.remove(best_add)
            unmatched_removed.remove(rem)

    # Second pass: match remaining unmatched pairs by identical channel number.
    # High confidence — the physical channel didn't move, only its name did.
    number_renames: list[tuple[str, str]] = []
    num_to_added = {new[k].get("sxm_number"): k for k in unmatched_added
                    if new[k].get("sxm_number") is not None}
    for rem in list(unmatched_removed):
        rem_num = old[rem].get("sxm_number")
        if rem_num is not None and rem_num in num_to_added:
            add = num_to_added.pop(rem_num)
            number_renames.append((rem, add))
            unmatched_added.remove(add)
            unmatched_removed.remove(rem)

    applied_aliases = 0
    if apply_aliases_path is not None:
        applied_aliases = _apply_aliases(
            apply_aliases_path,
            [(old[rem]["name"], new[add]["name"]) for rem, add in number_renames],
        )

    # unmatched_removed at this point excludes anything matched to a rename (fuzzy
    # or number-based) — it's exactly the set of channels that truly left the
    # lineup, safe to hand to cleanup_orphaned_logos.py for targeted deletion.
    if write_removed_path is not None:
        write_removed_path.write_text(
            json.dumps([old[k]["name"] for k in unmatched_removed], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Build report
    lines = ["## SiriusXM Channel Lineup Changes\n"]
    significant = bool(added or removed or number_changed)

    if not significant:
        lines.append("No significant changes detected (descriptions or metadata only).\n")
        print("\n".join(lines))
        sys.exit(0)

    missing_logo_names: list[str] = []
    if unmatched_added:
        lines.append(f"### New Channels ({len(unmatched_added)})\n")
        for k in unmatched_added:
            ch = new[k]
            num = f"Ch. {ch['sxm_number']}" if ch.get("sxm_number") else "no ch#"
            logo_note = "" if _has_logo(ch) else " — **no logo yet**"
            lines.append(f"- **{ch['name']}** ({num}) — {ch.get('description','')[:80]}{logo_note}")
            if not _has_logo(ch):
                missing_logo_names.append(ch["name"])
        lines.append("")

    if unmatched_removed:
        lines.append(f"### Removed Channels ({len(unmatched_removed)})\n")
        for k in unmatched_removed:
            ch = old[k]
            num = f"Ch. {ch['sxm_number']}" if ch.get("sxm_number") else "no ch#"
            lines.append(f"- **{ch['name']}** ({num}) — {ch.get('description','')[:80]}")
        lines.append("  (orphaned logo files, if any, are cleaned up automatically)")
        lines.append("")

    if number_renames:
        lines.append(f"### Renames — auto-aliased ({len(number_renames)})\n")
        lines.append("Same station number, name changed. Added to `channel_aliases.json` automatically:\n")
        for rem, add in number_renames:
            lines.append(f"- **{old[rem]['name']}** → **{new[add]['name']}**")
        lines.append("")

    if fuzzy_renames:
        lines.append(f"### Possible Renames ({len(fuzzy_renames)}) — verify manually\n")
        lines.append("Name similarity only, no matching station number — confidence too low to auto-alias:\n")
        for rem, add in fuzzy_renames:
            lines.append(f"- **{old[rem]['name']}** → **{new[add]['name']}**")
        lines.append("")

    if number_changed:
        lines.append(f"### Channel Number Changes ({len(number_changed)})\n")
        for key, o_num, n_num, name in number_changed:
            lines.append(f"- **{name}**: Ch. {o_num} → Ch. {n_num}")
        lines.append("")

    action_items = []
    if missing_logo_names:
        action_items.append(
            "- Still no logo after automatic caching (CDN/special-case/alias/xmplaylist all missed): "
            + ", ".join(missing_logo_names)
            + " — add to `_workshop/sxm_logos_raw.json` or `cache_logos.py` SPECIAL_LOGOS."
        )
    if fuzzy_renames:
        action_items.append("- Verify the fuzzy-matched possible renames above and add confirmed ones to `channel_aliases.json`.")

    lines.append("---")
    if action_items:
        lines.append("### Action needed\n")
        lines.extend(action_items)
        lines.append("")
    else:
        lines.append("_No manual action needed — logos and high-confidence renames were handled automatically._\n")
    if applied_aliases:
        lines.append(f"_Auto-applied {applied_aliases} alias update(s) to `channel_aliases.json`._")
    lines.append(
        "_Detected automatically by [EPGeditARR](https://github.com/jstevenscl/epgeditarr) "
        "weekly channel cache update._"
    )

    print("\n".join(lines))
    sys.exit(1)


if __name__ == "__main__":
    main()
