#!/usr/bin/env python3
"""
Build channels.json from the rebrowser/siriusxm-dataset public CSV.

The dataset is updated daily on GitHub and requires no SiriusXM credentials.
Logos are preserved from the existing logos/ cache; new channels get no logo
until cache_logos.py or manual intervention adds them (a GitHub issue is
opened automatically by the workflow when new/removed channels are detected).

Run locally:
  python scripts/build_channels_sxm.py

Called by .github/workflows/update-channels.yml on a weekly schedule.
"""

import csv
import io
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REBROWSER_CSV_URL = (
    "https://raw.githubusercontent.com/rebrowser/siriusxm-dataset/main/channels/data.csv"
)
UA = "EPGeditARR/1.0 (github.com/jstevenscl/epgeditarr)"

ROOT          = Path(__file__).parent.parent
OUT_PATH      = ROOT / "channels.json"
LOGOS_DIR     = ROOT / "logos"
GH_PAGES_BASE = "https://jstevenscl.github.io/epgeditarr/logos"

# Dynamic game-day broadcast slots — named "NFL Play-by-Play 225" etc.
# They have no permanent streaming channel number; exclude from static list.
_DYNAMIC_RE = re.compile(
    r"^(NFL|MLB|NBA|NHL|NCAA|ACC|Big\s+1[02]|Big\s+Ten|SEC|Sports|College)\s+Play.{0,20}\d+$",
    re.IGNORECASE,
)

# Rebrowser sometimes has a generic "SiriusXM N" row alongside the real named
# row for the same channel. Skip the generic one — the real row covers it.
_SXM_GENERIC_RE = re.compile(r"^SiriusXM \d+$")

# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

def _load_aliases() -> dict:
    """Load channel_aliases.json → {lowercase_variant: canonical_name}."""
    path = ROOT / "channel_aliases.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k.lower(): v for k, v in raw.get("aliases", {}).items()}
    except Exception:
        return {}


def _clean_name(name: str) -> str:
    """Normalize encoding artifacts in Rebrowser channel names.

    Rebrowser uses U+2019 RIGHT SINGLE QUOTATION MARK for apostrophes.
    Normalizing to ASCII apostrophe lets alias lookups match consistently.
    """
    name = name.replace("’", "'").replace("‘", "'")
    return unicodedata.normalize("NFC", name).strip()


def _resolve_name(raw_name: str, aliases: dict) -> str:
    """Return the canonical channel name for a Rebrowser row.

    Resolution order:
      1. Alias lookup — known variant → canonical mapping
      2. Cleaned name — curly quotes normalized, used as-is
    """
    cleaned = _clean_name(raw_name)
    return aliases.get(cleaned.lower()) or cleaned


# ---------------------------------------------------------------------------
# Logo helpers  (must match logo_slug() in cache_logos.py and build_sports_epg.py)
# ---------------------------------------------------------------------------

def logo_slug(name: str) -> str:
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_cached_logo(name: str, existing_ch: dict) -> str:
    """Return GitHub Pages logo URL if an existing cached file covers this channel."""
    existing_url = existing_ch.get("logo_url", "")
    if existing_url and existing_url.startswith(GH_PAGES_BASE):
        return existing_url
    slug = logo_slug(name)
    for ext in ("png", "svg", "jpg"):
        dest = LOGOS_DIR / f"{slug}.{ext}"
        if dest.exists() and dest.stat().st_size > 500:
            return f"{GH_PAGES_BASE}/{slug}.{ext}"
    return ""


# ---------------------------------------------------------------------------
# Fetch Rebrowser dataset
# ---------------------------------------------------------------------------

def fetch_csv() -> list:
    req = urllib.request.Request(REBROWSER_CSV_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(raw)))


# ---------------------------------------------------------------------------
# Build channels.json
# ---------------------------------------------------------------------------

def build_channels_json(rows: list, existing: dict) -> dict:
    aliases      = _load_aliases()
    channels     = {}
    seen_numbers = set()   # deduplicate rows that share a streaming channel number

    for row in rows:
        raw_name = row.get("name", "").strip()
        if not raw_name:
            continue

        # Skip generic placeholder rows — real-named row for the same channel exists
        if _SXM_GENERIC_RE.match(_clean_name(raw_name)):
            continue

        ch_str = row.get("streamingChannelNumber", "").strip()
        ch = int(ch_str) if ch_str.isdigit() else None

        # Skip dynamic game-day slots with no permanent channel number
        if ch is None and _DYNAMIC_RE.match(_clean_name(raw_name)):
            continue

        name = _resolve_name(raw_name, aliases)

        # Deduplicate: Rebrowser keeps old and new rows for renamed channels
        if ch is not None:
            if ch in seen_numbers:
                continue
            seen_numbers.add(ch)

        desc      = (row.get("longDescription") or row.get("shortDescription") or "").strip()
        genre     = row.get("genreName", "").strip()
        entity_id = row.get("channelId", "").strip()

        key = name.lower()
        # Prefer existing entry keyed by canonical name; fall back to raw-name key
        raw_key = _clean_name(raw_name).lower()
        existing_ch = existing.get(key) or existing.get(raw_key) or {}

        if key in channels:
            key = f"{key}_{ch}"

        logo_url = find_cached_logo(name, existing_ch)

        channels[key] = {
            "name":                  name,
            "description":           desc,
            "genre":                 genre,
            "sxm_number":            ch,
            "seasonal":              None,
            "logo_url":              logo_url,
            "sxm_logo_src":          existing_ch.get("sxm_logo_src", ""),
            "sxm_entity_id":         entity_id,
            "lookaround_channel_id": existing_ch.get("lookaround_channel_id"),
        }

    return channels


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    existing: dict = {}
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    print("Fetching Rebrowser SiriusXM dataset...")
    rows = fetch_csv()
    print(f"  {len(rows)} rows fetched")

    print("Building channels.json...")
    channels = build_channels_json(rows, existing)

    with_nums = sum(1 for v in channels.values() if v.get("sxm_number") is not None)
    with_logo = sum(1 for v in channels.values() if v.get("logo_url"))
    print(f"  {len(channels)} channels, {with_nums} with numbers, {with_logo} with logos")

    OUT_PATH.write_text(
        json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Written: {OUT_PATH}")


if __name__ == "__main__":
    main()
