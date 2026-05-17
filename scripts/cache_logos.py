#!/usr/bin/env python3
"""
Download and cache SiriusXM channel logos to logos/ directory.

Sources (in priority order):
  1. Official SiriusXM CDN URLs from _workshop/sxm_logos_raw.json (extracted from Dispatcharr)
  2. Hard-coded special cases for channels not covered by sxm_logos_raw.json
  3. Fallback xmplaylist.com URLs already in channels.json

Updates channels.json logo_url fields to point to GitHub Pages cached versions:
  https://jstevenscl.github.io/epgeditarr/logos/{slug}.{ext}

Idempotent: already-cached files are skipped. New logos are downloaded on every run.

Run manually:
  python scripts/cache_logos.py

Called automatically by .github/workflows/update-channels.yml after build_channels.py.
"""

import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

CHANNELS_PATH = Path(__file__).parent.parent / "channels.json"
LOGOS_RAW_PATH = Path(__file__).parent.parent / "_workshop" / "sxm_logos_raw.json"
ALIASES_PATH = Path(__file__).parent.parent / "channel_aliases.json"
LOGOS_DIR = Path(__file__).parent.parent / "logos"
GITHUB_PAGES_BASE = "https://jstevenscl.github.io/epgeditarr/logos"
UA = "EPGeditARR-build/1.0 (github.com/jstevenscl/epgeditarr)"

# Channels not covered by sxm_logos_raw.json — fetched from known stable sources.
SPECIAL_LOGOS = {
    "howard 100": {
        "url": "https://www.siriusxm.com/landing/lineup/flash/images/chref/howard_100.png",
        "ext": "png",
    },
    "howard 101": {
        "url": "https://www.siriusxm.com/landing/lineup/flash/images/chref/howard_101.png",
        "ext": "png",
    },
    # Wikipedia key is the combined entry; Dispatcharr splits them.
    # We use the combined Wikipedia key for the channels.json lookup.
    "howard 100 and howard 101": {
        "url": "https://www.siriusxm.com/landing/lineup/flash/images/chref/howard_100.png",
        "ext": "png",
    },
    "morgan wallen radio": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/Music/x-Country/morgan-wallen-radio/MorganWallenRadio-126-500x400-P1.svg",
        "ext": "svg",
    },
    "cocomelon & friends": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/Music/family/CoComelonNFriends-126-500x400-P.svg",
        "ext": "svg",
    },
    "westwood one sports": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/SportsChannels/westwood-one-sports/WestwoodOneSports-126-500x400-P.svg",
        "ext": "svg",
    },
    "new year's nation": {
        "url": "https://static.wikia.nocookie.net/logopedia/images/c/c5/New-Years-Nation.png/revision/latest?cb=20200219223518",
        "ext": "png",
    },
    "jolly christmas": {
        "url": "https://cdn.shopify.com/s/files/1/0308/5844/4932/t/2/assets/JollyChristmas-126-500x400-P.svg?v=1671594346",
        "ext": "svg",
    },
    "holiday instrumentals": {
        "url": "https://cdn.shopify.com/s/files/1/0308/5844/4932/t/2/assets/HolidayInstrumentals-126-500x400-P.svg",
        "ext": "svg",
    },
    "acoustic christmas": {
        "url": "https://cdn.shopify.com/s/files/1/0308/5844/4932/t/2/assets/AcousticChristmas-4C.svg?v=1671594342",
        "ext": "svg",
    },
    "rockin' xmas": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/Music/x-Holiday/rockinchristmas/RockinChristmas-simple-Color.svg",
        "ext": "svg",
    },
    "real jazz holiday": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/Music/x-Holiday/jazz-holidays/JazzHolidays-simple-color.svg",
        "ext": "svg",
    },
    "holiday pops": {
        "url": "https://cdn.shopify.com/s/files/1/0308/5844/4932/t/2/assets/HolidayPops-4C.svg?v=1671594340",
        "ext": "svg",
    },
    "jingle jamz": {
        "url": "https://www.siriusxm.ca/wp-content/uploads/2024/10/Feature-Jingle-Jamz.jpg",
        "ext": "jpg",
    },
    "cool jazz christmas": {
        "url": "https://www.siriusxm.ca/wp-content/uploads/2025/11/Feature-Cool-Jazz-Christmas.jpg",
        "ext": "jpg",
    },
    "kids christmas": {
        "url": "https://www.siriusxm.ca/wp-content/uploads/2025/11/Feature-Kids-Christmas.jpg",
        "ext": "jpg",
    },
    "sleep christmas": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/Music/x-Holiday/sleep-christmas/SleepChristmas-126-500x400-P1.svg",
        "ext": "svg",
    },
    "sirius xm preview": {
        "url": "https://www.siriusxm.com/content/dam/sxm-com/channel-logos/preview/sxm_preview/SXM_Preview-color.svg",
        "ext": "svg",
    },
}


def logo_slug(name: str) -> str:
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", name.lower())


def ext_from_url(url: str) -> str:
    path = url.split("?")[0].lower()
    return "svg" if path.endswith(".svg") else "png"


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    dest.write_bytes(data)
    return len(data)


def is_placeholder(path: Path) -> bool:
    """Return True if the file looks like an error page / 404 body (< 500 bytes)."""
    return path.exists() and path.stat().st_size < 500


def main() -> None:
    LOGOS_DIR.mkdir(exist_ok=True)

    channels: dict = json.loads(CHANNELS_PATH.read_text(encoding="utf-8"))
    sxm_logos: dict = json.loads(LOGOS_RAW_PATH.read_text(encoding="utf-8"))
    raw_aliases: dict = json.loads(ALIASES_PATH.read_text(encoding="utf-8")).get("aliases", {})

    # Build normalized alias lookup: variant_slug → official_name
    # This lets us find a Dispatcharr logo even when the Wikipedia/channel name differs.
    alias_to_official: dict[str, str] = {}
    for variant, official in raw_aliases.items():
        alias_to_official[logo_slug(variant)] = official

    # Build Dispatcharr name → cached GitHub Pages URL (populated in Step 1)
    disp_name_to_gh: dict[str, str] = {}  # logo_slug(dispatcharr_name) -> gh_url

    # ── Step 1: Cache every logo in sxm_logos_raw.json ────────────────────────
    print("=== Caching official SiriusXM CDN logos ===")
    sxm_cached: dict[str, str] = {}   # cdn_url -> github_pages_url
    sxm_slug_map: dict[str, str] = {} # logo_slug(display_name) -> github_pages_url

    ok = fail = skip = 0
    for display_name, cdn_url in sxm_logos.items():
        slug = logo_slug(display_name)
        ext = ext_from_url(cdn_url)
        dest = LOGOS_DIR / f"{slug}.{ext}"
        gh_url = f"{GITHUB_PAGES_BASE}/{slug}.{ext}"

        sxm_cached[cdn_url] = gh_url
        sxm_slug_map[slug] = gh_url
        disp_name_to_gh[slug] = gh_url

        if dest.exists() and not is_placeholder(dest):
            skip += 1
            continue
        try:
            size = download(cdn_url, dest)
            if size < 500:
                dest.unlink()
                print(f"  EMPTY ({size}B): {display_name}")
                fail += 1
            else:
                ok += 1
        except Exception as e:
            print(f"  FAIL: {display_name}: {e}")
            fail += 1

    print(f"  {ok} downloaded, {skip} already cached, {fail} failed\n")

    # ── Step 2: Cache special-case logos ──────────────────────────────────────
    print("=== Caching special logos ===")
    special_gh: dict[str, str] = {}  # ch_key -> github_pages_url

    for ch_key, spec in SPECIAL_LOGOS.items():
        slug = logo_slug(ch_key)
        ext = spec["ext"]
        dest = LOGOS_DIR / f"{slug}.{ext}"
        gh_url = f"{GITHUB_PAGES_BASE}/{slug}.{ext}"
        special_gh[ch_key] = gh_url

        if dest.exists() and not is_placeholder(dest):
            print(f"  SKIP (cached): {ch_key}")
            continue
        try:
            size = download(spec["url"], dest)
            if size < 500:
                dest.unlink()
                print(f"  EMPTY: {ch_key}")
            else:
                print(f"  OK: {ch_key} ({size} B)")
        except Exception as e:
            print(f"  FAIL: {ch_key}: {e}")

    # ── Step 3: Update channels.json logo_url fields ──────────────────────────
    print("\n=== Updating channels.json ===")
    updated = unchanged = missing = 0

    for ch_key, ch_data in channels.items():
        current_url: str = ch_data.get("logo_url", "")

        # Priority 1: special case
        if ch_key in special_gh and (LOGOS_DIR / f"{logo_slug(ch_key)}.{SPECIAL_LOGOS[ch_key]['ext']}").exists():
            new_url = special_gh[ch_key]

        # Priority 2: current URL is an official CDN URL we just cached
        elif current_url in sxm_cached:
            new_url = sxm_cached[current_url]

        # Priority 3: alias lookup — channel name variant maps to an official Dispatcharr name
        elif logo_slug(ch_data["name"]) in alias_to_official or ch_key in alias_to_official:
            variant_slug = logo_slug(ch_data["name"]) if logo_slug(ch_data["name"]) in alias_to_official else ch_key
            official_name = alias_to_official[variant_slug]
            official_slug = logo_slug(official_name)
            if official_slug in disp_name_to_gh:
                new_url = disp_name_to_gh[official_slug]
                print(f"  alias match: {ch_data['name']} -> {official_name}")
            else:
                missing += 1
                continue

        # Priority 5: try xmplaylist.com fallback — download and cache it
        elif "xmplaylist.com" in current_url:
            slug = logo_slug(ch_data["name"])
            dest = LOGOS_DIR / f"{slug}.png"
            gh_url = f"{GITHUB_PAGES_BASE}/{slug}.png"
            if dest.exists() and not is_placeholder(dest):
                new_url = gh_url
            else:
                try:
                    size = download(current_url, dest)
                    if size < 500:
                        dest.unlink(missing_ok=True)
                        print(f"  xmplaylist empty: {ch_data['name']}")
                        missing += 1
                        continue
                    new_url = gh_url
                    print(f"  xmplaylist cached: {ch_data['name']}")
                except Exception as e:
                    print(f"  xmplaylist FAIL: {ch_data['name']}: {e}")
                    missing += 1
                    continue

        # Priority 4: already a GitHub Pages URL — nothing to do
        elif current_url.startswith(GITHUB_PAGES_BASE):
            unchanged += 1
            continue

        else:
            missing += 1
            continue

        if ch_data.get("logo_url") != new_url:
            ch_data["logo_url"] = new_url
            updated += 1
        else:
            unchanged += 1

    CHANNELS_PATH.write_text(
        json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  {updated} URL(s) updated, {unchanged} already correct, {missing} no logo found")
    print(f"\nDone. Logos cached in {LOGOS_DIR}/")
    print(f"Serve via GitHub Pages: {GITHUB_PAGES_BASE}/")


if __name__ == "__main__":
    main()
