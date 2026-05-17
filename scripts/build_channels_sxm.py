#!/usr/bin/env python3
"""
Fetch SiriusXM channel list and logos from the authenticated edge-gateway API.

Writes channels.json with official names, numbers, descriptions, genres, and
GitHub-Pages-hosted logo URLs.  Downloads new/changed logos to logos/.

Logo cache invalidation: the SiriusXM player CDN embeds the image MD5 in the
URL path (e.g. "if/03/<md5>_<ts>.png"), so a changed URL means a changed image.
We store the source path in "sxm_logo_src" and only re-download on change.

Credentials (never commit — store as GitHub Actions secrets):
  SIRIUSXM_USERNAME  - SiriusXM account email
  SIRIUSXM_PASSWORD  - SiriusXM account password

Run locally:
  $env:SIRIUSXM_USERNAME="you@email.com"; $env:SIRIUSXM_PASSWORD="yourpass"
  python scripts/build_channels_sxm.py

Called by .github/workflows/update-channels.yml on a weekly schedule.
"""

import base64
import http.cookiejar
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE       = "https://api.edge-gateway.siriusxm.com"
IMG_BASE       = "https://player.siriusxm.com/image/"
# Stable content IDs for the "All channels" curated-grouping page
PAGE_ID        = "403ab6a5-d3c9-4c2a-a722-a94a6a5fd056"
CONTAINER_ID   = "3JoBfOCIwo6FmTpzM1S2H7"
SET_ID         = "5mqCLZ21qAwnufKT8puUiM"
PLATFORM       = "web-desktop"
UA             = "EPGeditARR/1.0 (github.com/jstevenscl/epgeditarr)"

ROOT             = Path(__file__).parent.parent
OUT_PATH         = ROOT / "channels.json"
LOGOS_DIR        = ROOT / "logos"
GH_PAGES_BASE    = "https://jstevenscl.github.io/epgeditarr/logos"

ENTITY_TYPES = [
    "artist-station", "brand", "channel-linear", "channel-xtra",
    "container", "curated-grouping", "episode-audio", "episode-linear",
    "episode-podcast", "episode-video", "event", "experience", "genre",
    "league", "show", "show-podcast", "station", "tag-topic",
    "talent", "team", "user-signal",
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def _api(url, data=None, headers=None):
    h = {
        "Accept":        "application/json",
        "Content-Type":  "application/json",
        "User-Agent":    UA,
        "x-sxm-clock":  "[0,37]",
    }
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if data is not None else None
    req  = urllib.request.Request(url, data=body, headers=h,
                                  method="POST" if body else "GET")
    try:
        with _opener.open(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"HTTP {e.code} from {url}: {e.read().decode('utf-8','replace')[:400]}"
        ) from e


def _download(url, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    dest.write_bytes(data)
    return len(data)


# ---------------------------------------------------------------------------
# Logo helpers  (must match logo_slug() in cache_logos.py and build_sports_epg.py)
# ---------------------------------------------------------------------------

def logo_slug(name: str) -> str:
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _sxm_img_path(entity: dict) -> str:
    """Return the raw CDN path (e.g. 'if/03/<md5>_<ts>.png') or ''."""
    images = entity.get("images", {})
    for key in ("logo", "tile", "tile_background"):
        img  = images.get(key, {})
        data = (
            img.get("aspect_1x1",  {}).get("default")
            or img.get("aspect_16x9", {}).get("default")
        )
        if data and data.get("url"):
            return data["url"]
    return ""


def cache_logo(name: str, img_path: str, existing_src: str) -> tuple[str, str]:
    """Download logo if new/changed. Returns (gh_pages_url, img_path)."""
    if not img_path:
        return "", ""

    slug     = logo_slug(name)
    dest     = LOGOS_DIR / f"{slug}.png"
    gh_url   = f"{GH_PAGES_BASE}/{slug}.png"
    src_url  = IMG_BASE + img_path

    # Skip if already cached with the same source image
    if dest.exists() and dest.stat().st_size > 500 and img_path == existing_src:
        return gh_url, img_path

    try:
        size = _download(src_url, dest)
        if size < 500:
            dest.unlink(missing_ok=True)
            return "", ""
        return gh_url, img_path
    except Exception as e:
        print(f"  WARN logo {name}: {e}")
        # Keep existing file if it's good
        if dest.exists() and dest.stat().st_size > 500:
            return gh_url, existing_src
        return "", ""


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> str:
    device_id = str(uuid.uuid4())

    print("  Step 1: password auth...")
    auth_resp = _api(
        f"{API_BASE}/identity/v1/identities/authenticate/password",
        data={
            "username":       username,
            "password":       password,
            "rememberMe":     False,
            "clientDeviceId": device_id,
            "platform":       PLATFORM,
        },
    )

    identity_token = (
        auth_resp.get("identityToken")
        or auth_resp.get("token")
        or auth_resp.get("accessToken")
    )

    print("  Step 2: create session...")
    sess_payload: dict = {"clientDeviceId": device_id, "platform": PLATFORM}
    if identity_token:
        sess_payload["identityToken"] = identity_token

    sess_resp = _api(
        f"{API_BASE}/session/v1/sessions/authenticated",
        data=sess_payload,
    )

    token = (
        sess_resp.get("token")
        or sess_resp.get("accessToken")
        or sess_resp.get("bearerToken")
        or sess_resp.get("jwt")
        or (sess_resp.get("session") or {}).get("token")
    )
    if not token:
        raise RuntimeError(
            f"Bearer token not found in session response. "
            f"Keys: {list(sess_resp.keys())}  Body: {json.dumps(sess_resp)[:400]}"
        )
    return token


# ---------------------------------------------------------------------------
# Channel fetch
# ---------------------------------------------------------------------------

def fetch_all_channels(token: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    channels, offset, limit, total = [], 0, 100, None

    while True:
        q_obj = {
            "filter": {"one": {"filterId": "all"}},
            "sets": {
                SET_ID: {
                    "sort": {"sortId": "CHANNEL_NUMBER_ASC"},
                    "pagination": {"offset": {
                        "setItemsLimit":  limit,
                        "setItemsOffset": offset,
                    }},
                }
            },
            "pagination": {"offset": {"setItemsLimit": limit}},
            "constraints": {"supportedEntityTypes": ENTITY_TYPES},
        }
        q = "1." + base64.b64encode(
            json.dumps(q_obj, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        url = (
            f"{API_BASE}/browse/v1/pages/curated-grouping"
            f"/{PAGE_ID}/containers/{CONTAINER_ID}"
            f"?q={urllib.parse.quote(q)}"
        )

        data     = _api(url, headers=headers)
        set_data = data["container"]["sets"][0]
        items    = set_data["items"]
        pg       = set_data.get("pagination", {}).get("offset", {})

        if total is None:
            total = pg.get("size", 0)
            print(f"  Total: {total}")

        channels.extend(items)
        offset += len(items)
        print(f"  {offset}/{total} ...")

        if len(items) < limit or offset >= total:
            break

    return channels


# ---------------------------------------------------------------------------
# Build channels.json
# ---------------------------------------------------------------------------

def build_channels_json(items: list, existing: dict) -> dict:
    """Transform API items into channels.json format, downloading logos."""
    LOGOS_DIR.mkdir(exist_ok=True)
    channels = {}
    downloaded = skipped = failed = 0

    for item in items:
        entity = item.get("entity", {})
        deco   = item.get("decorations", {})

        name = entity.get("texts", {}).get("title", {}).get("default", "").strip()
        if not name:
            continue

        desc      = (entity.get("texts", {}).get("description") or {}).get("default", "") or ""
        genre_raw = deco.get("genre")
        genre     = genre_raw if isinstance(genre_raw, str) else ""
        ch        = deco.get("channelNumber")
        key       = name.lower()
        # Disambiguate if two channels share a name (e.g. same channel on satellite + app)
        if key in channels:
            key = f"{key}_{ch}"

        img_path    = _sxm_img_path(entity)
        existing_ch = existing.get(key, {})
        existing_src = existing_ch.get("sxm_logo_src", "")

        gh_url, cached_src = cache_logo(name, img_path, existing_src)
        if gh_url:
            if cached_src != existing_src:
                downloaded += 1
            else:
                skipped += 1
        elif img_path:
            failed += 1

        channels[key] = {
            "name":                  name,
            "description":           desc,
            "genre":                 genre,
            "sxm_number":            ch,
            "seasonal":              None,
            "logo_url":              gh_url,
            "sxm_logo_src":          cached_src,
            "sxm_entity_id":         entity.get("id", ""),
            "lookaround_channel_id": deco.get("lookaroundChannelId"),
        }

    print(f"  Logos: {downloaded} downloaded, {skipped} cached, {failed} failed")
    return channels


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    username = os.environ.get("SIRIUSXM_USERNAME", "").strip()
    password = os.environ.get("SIRIUSXM_PASSWORD", "").strip()
    if not username or not password:
        sys.exit(
            "Set SIRIUSXM_USERNAME and SIRIUSXM_PASSWORD environment variables.\n"
            "  PowerShell: $env:SIRIUSXM_USERNAME='you@email.com'\n"
            "  GitHub CI:  stored as repository secrets"
        )

    # Load existing channels.json to enable logo cache-hit detection
    existing: dict = {}
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    print("Authenticating with SiriusXM API...")
    token = authenticate(username, password)
    print("  OK")

    print("Fetching channel list...")
    items = fetch_all_channels(token)

    print("Building channels.json + downloading logos...")
    channels = build_channels_json(items, existing)

    with_nums = sum(1 for v in channels.values() if v.get("sxm_number") is not None)
    with_logo = sum(1 for v in channels.values() if v.get("logo_url"))
    print(f"  {len(channels)} channels, {with_nums} with numbers, {with_logo} with logos")

    OUT_PATH.write_text(
        json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Written: {OUT_PATH}")


if __name__ == "__main__":
    main()
