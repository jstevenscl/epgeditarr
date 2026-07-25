#!/usr/bin/env python3
"""
Delete cached logo files in logos/ that belonged to channels confirmed removed
from the SiriusXM lineup this run — never a blanket "unreferenced" sweep.

Takes the removed-channel-names file written by detect_channel_changes.py's
--write-removed flag (that list already excludes anything matched to a rename,
fuzzy or number-based, so it's exactly the channels that truly left the
lineup). For each removed name, computes its logo slug and deletes matching
files in logos/ — but only if that slug isn't also referenced by a channel
still in channels.json today, and isn't a SPECIAL_LOGOS key (curated logos
are never touched). A prior blanket-sweep design deleted ~80 still-valid
files because plenty of current channels' logo_url doesn't happen to point
at the cached copy today; this targeted approach avoids that entirely.

Usage:
  python scripts/cleanup_orphaned_logos.py removed.json

If removed.json is missing, empty, or not given, this is a safe no-op —
nothing is ever deleted based on guesswork.

Called automatically by .github/workflows/update-channels.yml after
detect_channel_changes.py produces removed.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cache_logos import SPECIAL_LOGOS, logo_slug  # noqa: E402

CHANNELS_PATH = Path(__file__).parent.parent / "channels.json"
LOGOS_DIR = Path(__file__).parent.parent / "logos"


def main() -> None:
    if len(sys.argv) < 2:
        print("No removed-channels file given — nothing to clean up (safe no-op).")
        return

    removed_path = Path(sys.argv[1])
    if not removed_path.exists():
        print(f"{removed_path} not found — nothing to clean up (safe no-op).")
        return

    removed_names = json.loads(removed_path.read_text(encoding="utf-8"))
    if not removed_names:
        print("No channels removed this run — nothing to clean up.")
        return

    channels: dict = json.loads(CHANNELS_PATH.read_text(encoding="utf-8"))
    current_slugs = {logo_slug(ch["name"]) for ch in channels.values()}
    special_slugs = {logo_slug(ch_key) for ch_key in SPECIAL_LOGOS}

    if not LOGOS_DIR.exists():
        print("No logos/ directory — nothing to clean up.")
        return

    candidate_slugs = set()
    for name in removed_names:
        slug = logo_slug(name)
        if slug in current_slugs:
            continue  # still in use under some current channel — never touch
        if slug in special_slugs:
            continue  # curated logo — never touch
        candidate_slugs.add(slug)

    removed_files = []
    for f in LOGOS_DIR.iterdir():
        if f.is_file() and f.stem in candidate_slugs:
            f.unlink()
            removed_files.append(f.name)

    if removed_files:
        print(f"Removed {len(removed_files)} orphaned logo file(s) for channels no longer in the lineup:")
        for name in removed_files:
            print(f"  - {name}")
    else:
        print("No matching logo files found for this run's removed channels.")


if __name__ == "__main__":
    main()
