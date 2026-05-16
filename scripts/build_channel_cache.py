#!/usr/bin/env python3
"""Build SiriusXM channel cache for the EPGeditARR plugin.

Sources:
  1. Wikipedia (List_of_SiriusXM_Radio_channels) — structured tables with names/descriptions
  2. siriusxm.com sitemap — slug-numbered channels (sports/conference slots) where the
     channel number is encoded directly in the URL slug (e.g. nfl-play-by-play-234 → ch 234)

No individual SiriusXM page fetching — that approach is fragile (wrong channel numbers
appear from related-channel navigation elements in the HTML).

Output: docs/channels.json served by GitHub Pages.
Plugin fetches this file instead of scraping Wikipedia at runtime.

Run locally:  python scripts/build_channel_cache.py
GitHub Action runs this weekly and commits any changes.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / "channels.json"
HEADERS = {"User-Agent": "EPGeditARR-CacheBuilder/1.0 (github.com/jstevenscl/epgeditarr)"}

SXM_SITEMAP_URL = "https://www.siriusxm.com/sitemap.xml"

# Acronyms to fix when converting slug words to display names
ACRONYMS = {
    'Nfl': 'NFL', 'Nba': 'NBA', 'Mlb': 'MLB', 'Nhl': 'NHL',
    'Sec': 'SEC', 'Acc': 'ACC', 'Pac': 'PAC',
    'Byu': 'BYU', 'Abc': 'ABC', 'Nbc': 'NBC', 'Cbs': 'CBS',
    'Cbc': 'CBC', 'Bbc': 'BBC', 'Npr': 'NPR', 'Cnbc': 'CNBC',
    'Espn': 'ESPN', 'Pga': 'PGA', 'F1': 'F1', 'Cnn': 'CNN',
    'Xm': 'XM', 'Vsn': 'VSN',
}

# Slug patterns that are generic numbered sports slots — no stable channel name to match against
SKIP_GENERIC = re.compile(
    r'^(sports|soccer)-play-by-play-\d+$'
    r'|^(nfl|mlb)-play-by-play-en-espanol(-\d+)?$'
)

# Slugs where the trailing number is NOT a channel number (it's part of the content name)
# e.g. "country-top-1000" = "Top 1000 Countdown", "pop-top-500" = "Top 500 Countdown"
SKIP_COUNTDOWN = re.compile(r'-top-\d+$|-countdown-\d+$')

# Only slugs whose trailing number is in a realistic SiriusXM channel range
MAX_CHANNEL_NUMBER = 999


# ---------------------------------------------------------------------------
# Normalization (mirrors plugin's Plugin._normalize_channel_name exactly)
# ---------------------------------------------------------------------------

def normalize_name(name):
    name = re.sub(r"^[\'\"''\"\s]+", '', name)
    name = re.sub(r'\s*\[[^\]]{1,5}\]', '', name)
    name = re.sub(r'\s*\(.*', '', name)
    return name.lower().strip()


def slug_to_display(slug):
    """Convert slug (trailing number already stripped) to a display name with correct acronyms.

    'nfl-play-by-play' → 'NFL Play By Play'
    'big-ten'          → 'Big Ten'
    'pac-12'           → 'PAC-12'
    'jam-on'           → 'Jam On'
    """
    # Preserve hyphenated number suffixes like "pac-12" → keep hyphen before 2-digit numbers
    # that are part of the name (not a channel number we stripped)
    words = slug.replace('-', ' ').split()
    fixed = []
    for w in words:
        titled = w.title()
        fixed.append(ACRONYMS.get(titled, titled))
    return ' '.join(fixed)


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

def fetch_wikipedia():
    pages = [
        "List_of_SiriusXM_Radio_channels",
        "List_of_SiriusXM_channels",
        "List_of_Sirius_XM_channels",
    ]
    for page in pages:
        url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=parse&page={page}&prop=text&format=json&redirects=1"
        )
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [wiki] network error for '{page}': {e}", file=sys.stderr)
            continue

        if "error" in raw:
            print(f"  [wiki] API error for '{page}': {raw['error'].get('info', '')}", file=sys.stderr)
            continue

        html = raw.get("parse", {}).get("text", {}).get("*", "")
        if not html:
            continue

        result = _parse_wiki_tables(html)
        if result:
            with_numbers = sum(1 for v in result.values() if v.get('sxm_number') is not None)
            print(f"  [wiki] {len(result)} channels from '{page}' ({with_numbers} with lineup positions)")
            return result

    print("  [wiki] FAILED — no parseable data", file=sys.stderr)
    return {}


def _parse_wiki_tables(html):
    channels = {}

    def clean(text):
        text = re.sub(r'<[^>]+>', ' ', text)
        for ent, rep in [
            ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
            ('&nbsp;', ' '), ('&#160;', ' '), ('&#39;', "'"),
            ('&quot;', '"'), ('&mdash;', '—'), ('&ndash;', '–'),
            ('&lsquo;', '‘'), ('&rsquo;', '’'),
            ('&ldquo;', '“'), ('&rdquo;', '”'),
            ('&trade;', '™'), ('&reg;', '®'),
        ]:
            text = text.replace(ent, rep)
        return re.sub(r'\s+', ' ', text).strip()

    for table_m in re.finditer(
        r'<table[^>]+class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>',
        html, re.DOTALL | re.IGNORECASE
    ):
        table = table_m.group(1)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL | re.IGNORECASE)
        if len(rows) < 2:
            continue

        headers = []
        for row in rows:
            ths = re.findall(r'<th[^>]*>(.*?)</th>', row, re.DOTALL | re.IGNORECASE)
            if ths:
                headers = [clean(h).lower() for h in ths]
                break
        if not headers:
            continue

        name_idx = next((i for i, h in enumerate(headers) if 'name' in h), None)
        desc_idx = next((
            i for i, h in enumerate(headers)
            if 'descri' in h or ('format' in h and 'name' not in h)
        ), None)
        genre_idx = next((i for i, h in enumerate(headers) if 'genre' in h), None)
        num_idx = next((
            i for i, h in enumerate(headers)
            if h in ('channel', 'ch', 'ch.', '#', 'no.', 'no', 'number',
                     'siriusxm', 'sirius xm', 'sirius',
                     'siriusxm #', 'xm #', 'sirius #') and 'name' not in h
        ), None)

        if name_idx is None:
            continue

        for row in rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            if not tds or name_idx >= len(tds):
                continue

            name = clean(tds[name_idx])
            key = normalize_name(name)
            if not key or len(key) < 2 or key in ('tba', 'tbd', 'vacant', 'n/a', '—', '-'):
                continue

            desc = clean(tds[desc_idx]) if desc_idx is not None and desc_idx < len(tds) else ''
            genre = clean(tds[genre_idx]) if genre_idx is not None and genre_idx < len(tds) else ''

            sxm_number = None
            if num_idx is not None and num_idx < len(tds):
                num_raw = re.sub(r'\[.*?\]', '', clean(tds[num_idx])).strip()
                m = re.match(r'\d+', num_raw)
                if m:
                    sxm_number = int(m.group())

            channels[key] = {
                'name': name,
                'description': desc,
                'genre': genre,
                'sxm_number': sxm_number,
            }

    return channels


# ---------------------------------------------------------------------------
# SiriusXM sitemap — slug-numbered channels only (no page fetching)
# ---------------------------------------------------------------------------

def fetch_sxm_sitemap():
    req = urllib.request.Request(SXM_SITEMAP_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        sitemap = resp.read().decode('utf-8')

    slugs = re.findall(r'https://www\.siriusxm\.com/channels/([^<\s/]+)', sitemap)
    seen, result = set(), []
    for s in slugs:
        if s and '/' not in s and s != 'lineup-changes' and s not in seen:
            seen.add(s)
            result.append(s)
    return result


def build_slug_channels(slugs):
    """Extract channels from slugs where the trailing number IS the SiriusXM channel number.

    Skips:
      - Generic sports slots (sports-play-by-play-NNN) — no stable name to match
      - Countdown/format slugs (country-top-1000, pop-top-500)
      - Any number > MAX_CHANNEL_NUMBER
      - Named slugs with no trailing number (Wikipedia covers those)
    """
    channels = {}
    skipped_generic = 0
    skipped_countdown = 0
    skipped_range = 0
    added = 0

    for slug in slugs:
        # Skip generic sports slots
        if SKIP_GENERIC.match(slug):
            skipped_generic += 1
            continue

        # Must have a trailing number
        num_m = re.search(r'-(\d+)$', slug)
        if not num_m:
            continue  # Named channel without number — Wikipedia covers these

        ch_num = int(num_m.group(1))

        # Skip countdown/format slugs (number is song count, not channel number)
        if SKIP_COUNTDOWN.search(slug):
            skipped_countdown += 1
            continue

        # Skip out-of-range numbers
        if ch_num > MAX_CHANNEL_NUMBER:
            skipped_range += 1
            continue

        # Convert slug (without trailing number) to display name
        base_slug = re.sub(r'-\d+$', '', slug)
        display = slug_to_display(base_slug)
        # Strip "SiriusXM " prefix so it matches normalized Dispatcharr names
        key_name = re.sub(r'^SiriusXM\s+', '', display, flags=re.IGNORECASE)
        key = normalize_name(key_name)

        if not key or len(key) < 2:
            continue

        # For multi-slot leagues (e.g. nfl-play-by-play-225 through 234),
        # keep the lowest channel number as the sort anchor for the block.
        if key not in channels or ch_num < channels[key]['sxm_number']:
            channels[key] = {
                'name': display,
                'description': '',
                'genre': '',
                'sxm_number': ch_num,
            }
            added += 1

    print(f"  [sxm] {added} slug-numbered channels "
          f"(skipped: {skipped_generic} generic sports, {skipped_countdown} countdown, "
          f"{skipped_range} out-of-range)")
    return channels


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Building SiriusXM channel cache...")

    print("\n1. Fetching Wikipedia data...")
    channels = fetch_wikipedia()

    print("\n2. Fetching SiriusXM sitemap (slug-numbered channels only)...")
    try:
        slugs = fetch_sxm_sitemap()
        print(f"  [sxm] sitemap: {len(slugs)} total slugs")
        sxm = build_slug_channels(slugs)

        # Add SiriusXM entries not already covered by Wikipedia
        new_from_sxm = 0
        for key, val in sxm.items():
            if key not in channels:
                channels[key] = val
                new_from_sxm += 1
        print(f"  [sxm] {new_from_sxm} new channels added (not in Wikipedia)")

    except Exception as e:
        print(f"  [sxm] FAILED: {e}", file=sys.stderr)

    total = len(channels)
    with_numbers = sum(1 for v in channels.values() if v.get('sxm_number') is not None)
    without = total - with_numbers
    print(f"\nTotal: {total} channels")
    print(f"  With lineup positions : {with_numbers}")
    print(f"  Without               : {without}")
    if without:
        missing = [v['name'] for v in channels.values() if v.get('sxm_number') is None]
        for n in missing:
            print(f"    - {n}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

    print(f"\nSaved → {OUTPUT_PATH}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
