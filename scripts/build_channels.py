#!/usr/bin/env python3
"""
Build channels.json from the SiriusXM Wikipedia channel list.

Outputs a dict keyed by lowercased channel name with fields:
  name         – display name
  description  – format/description from Wikipedia
  genre        – genre if present
  sxm_number   – SiriusXM lineup channel number (int or null)
  seasonal     – [start_month, end_month] if channel is in a seasonal section, else null
  logo_url     – xmplaylist.com station logo URL (may 404 for lesser-known channels)

Run manually:
  python scripts/build_channels.py

Called automatically by .github/workflows/update-channels.yml on a weekly schedule.
"""

import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_SiriusXM_Radio_channels"
OUT_PATH = Path(__file__).parent.parent / "channels.json"

_MONTH = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def logo_slug(name):
    """Derive xmplaylist.com station slug from channel display name.

    Strips Wikipedia-specific parentheticals and bracket tags before slugifying
    so '40s Junction (formerly 40s on 4)' → '40sjunction' not '40sjunctionformerly40son4'.
    """
    name = re.sub(r'\s*\[.*?\]', '', name)   # strip [E], [explicit], etc.
    name = re.sub(r'\s*\(.*?\)', '', name)   # strip (formerly ...), (special ...), etc.
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]', '', name.lower())


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "EPGeditARR-build/1.0 (github.com/jstevenscl/epgeditarr)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for ent, rep in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&nbsp;", " "), ("&#160;", " "), ("&#39;", "'"), ("&quot;", '"'),
    ]:
        text = text.replace(ent, rep)
    return re.sub(r"\s+", " ", text).strip()


def normalize(name):
    name = re.sub(r”^[‘\”’’””\s]+”, “”, name)
    name = re.sub(r”\s*\[[^\]]{1,5}\]”, “”, name)
    name = re.sub(r”\s*\(.*”, “”, name)
    return name.lower().strip()


def display_name(name):
    name = re.sub(r”\s*\[[^\]]{1,5}\]”, “”, name)  # strip [E], [explicit], etc.
    name = re.sub(r”\s*\(.*”, “”, name)              # strip (formerly ...), etc.
    return name.strip()


def parse_season(heading):
    months = re.findall(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)",
        heading.lower(),
    )
    if len(months) >= 2:
        return [_MONTH[months[0]], _MONTH[months[1]]]
    return None


def parse_tables(html):
    channels = {}

    def process_tables(chunk, seasonal):
        for table_m in re.finditer(
            r'<table[^>]+class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>',
            chunk, re.DOTALL | re.IGNORECASE,
        ):
            table = table_m.group(1)
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL | re.IGNORECASE)
            if len(rows) < 2:
                continue

            headers = []
            for row in rows:
                ths = re.findall(r"<th[^>]*>(.*?)</th>", row, re.DOTALL | re.IGNORECASE)
                if ths:
                    headers = [clean(h).lower() for h in ths]
                    break
            if not headers:
                continue

            name_idx = next((i for i, h in enumerate(headers) if "name" in h), None)
            desc_idx = next(
                (i for i, h in enumerate(headers)
                 if "descri" in h or ("format" in h and "name" not in h)),
                None,
            )
            genre_idx = next((i for i, h in enumerate(headers) if "genre" in h), None)
            num_idx = next(
                (i for i, h in enumerate(headers)
                 if h in ("channel", "ch", "ch.", "#", "no.", "no", "number",
                          "siriusxm", "sirius xm", "sirius",
                          "siriusxm #", "xm #", "sirius #")
                 and "name" not in h),
                None,
            )
            if name_idx is None:
                continue

            for row in rows:
                tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
                if not tds or name_idx >= len(tds):
                    continue

                name = clean(tds[name_idx])
                name_key = normalize(name)
                if not name_key or len(name_key) < 2 or name_key in ("tba", "tbd", "vacant", "n/a", "—", "-"):
                    continue

                desc = clean(tds[desc_idx]) if desc_idx is not None and desc_idx < len(tds) else ""
                genre = clean(tds[genre_idx]) if genre_idx is not None and genre_idx < len(tds) else ""

                sxm_number = None
                if num_idx is not None and num_idx < len(tds):
                    num_raw = re.sub(r"\[.*?\]", "", clean(tds[num_idx])).strip()
                    m = re.match(r"\d+", num_raw)
                    if m:
                        sxm_number = int(m.group())

                slug = logo_slug(name)
                channels[name_key] = {
                    "name": display_name(name),
                    "description": desc,
                    "genre": genre,
                    "sxm_number": sxm_number,
                    "seasonal": seasonal,
                    "logo_url": f"https://xmplaylist.com/img/station/{slug}-lg.png",
                }

    parts = re.split(r"(<h[234][^>]*>.*?</h[234]>)", html, flags=re.DOTALL | re.IGNORECASE)
    current_season = None

    for part in parts:
        if re.match(r"<h[234]", part, re.IGNORECASE):
            heading_text = re.sub(r"<[^>]+>", "", part)
            if "seasonal" in heading_text.lower() or "holiday channel" in heading_text.lower():
                current_season = parse_season(heading_text)
            else:
                current_season = None
        else:
            process_tables(part, current_season)

    return channels


def main():
    print(f"Fetching {WIKI_URL} ...")
    html = fetch_html(WIKI_URL)

    print("Parsing tables ...")
    channels = parse_tables(html)

    with_nums = sum(1 for v in channels.values() if v.get("sxm_number") is not None)
    seasonal = sum(1 for v in channels.values() if v.get("seasonal"))
    print(f"  {len(channels)} channels parsed, {with_nums} with lineup numbers, {seasonal} seasonal")

    OUT_PATH.write_text(json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written: {OUT_PATH}")


if __name__ == "__main__":
    main()
