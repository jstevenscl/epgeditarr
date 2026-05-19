#!/usr/bin/env python3
"""
Smoke-test for the player.siriusxm.com REST v2 API.

Tests login -> authenticate -> channel list fetch and prints
enough detail to verify the data is usable before we rewrite
build_channels_sxm.py.

Run:
  $env:SIRIUSXM_USERNAME="you@email.com"
  $env:SIRIUSXM_PASSWORD="yourpass"
  python scripts/test_player_api.py
"""

import json
import os
import sys

import requests

BASE     = "https://player.siriusxm.com/rest/v2/experience/modules"
UA       = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/604.5.6 (KHTML, like Gecko) Version/11.0.3 Safari/604.5.6"
DEVICE   = {
    "osVersion":        "Mac",
    "platform":         "Web",
    "sxmAppVersion":    "3.1802.10011.0",
    "browser":          "Safari",
    "browserVersion":   "11.0.3",
    "appRegion":        "US",
    "deviceModel":      "K2WebClient",
    "clientDeviceId":   "null",
    "player":           "html5",
    "clientDeviceType": "web",
}

session = requests.Session()
session.headers.update({"User-Agent": UA})


def _post(endpoint, payload):
    url = f"{BASE}/{endpoint}"
    r = session.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def check_status(data, step):
    try:
        code = data["ModuleListResponse"]["messages"][0]["code"]
        msg  = data["ModuleListResponse"]["messages"][0]["message"]
    except (KeyError, IndexError, TypeError):
        code, msg = None, "(no message)"
    if code is not None and code != 100:
        print(f"  FAIL  {step} — code={code}  msg={msg}")
        return False
    print(f"  OK    {step}" + (f"  (code={code})" if code else ""))
    return True


def main():
    username = os.environ.get("SIRIUSXM_USERNAME", "").strip()
    password = os.environ.get("SIRIUSXM_PASSWORD", "").strip()
    if not username or not password:
        sys.exit("Set SIRIUSXM_USERNAME and SIRIUSXM_PASSWORD")

    print("=== SiriusXM player.siriusxm.com API smoke test ===\n")

    # -------------------------------------------------------------------------
    # Step 1: Login
    # -------------------------------------------------------------------------
    print("Step 1: Login  (modules/modify/authentication)")
    login_data = _post("modify/authentication", {"moduleList": {"modules": [{"moduleRequest": {
        "resultTemplate": "web",
        "deviceInfo":     DEVICE,
        "standardAuth":   {"username": username, "password": password},
    }}]}})
    if not check_status(login_data, "login"):
        sys.exit(1)

    print(f"  Cookies after login: {list(session.cookies.keys())}")
    if "SXMDATA" not in session.cookies:
        print("  WARN: SXMDATA cookie missing — subsequent requests may fail")

    # -------------------------------------------------------------------------
    # Step 2: Authenticate session
    # -------------------------------------------------------------------------
    print("\nStep 2: Authenticate session  (modules/authenticate)")
    auth_data = _post("authenticate", {"moduleList": {"modules": [{"moduleRequest": {
        "resultTemplate": "web",
        "deviceInfo":     DEVICE,
    }}]}})
    auth_ok = check_status(auth_data, "authenticate")
    print(f"  Cookies after authenticate: {list(session.cookies.keys())}")

    # -------------------------------------------------------------------------
    # Step 3: Channel list  (attempt regardless of step 2 result)
    # -------------------------------------------------------------------------
    print("\nStep 3: Fetch channel list  (modules/get — ChannelListing)")
    chan_data = _post("get", {"moduleList": {"modules": [{"moduleArea": "Discovery",
        "moduleType": "ChannelListing",
        "moduleRequest": {
            "consumeRequests": [],
            "resultTemplate":  "responsive",
            "alerts":          [],
            "profileInfos":    [],
        },
    }]}})
    if not check_status(chan_data, "channel listing"):
        sys.exit(1)

    # -------------------------------------------------------------------------
    # Parse and display sample data
    # -------------------------------------------------------------------------
    try:
        modules  = chan_data["ModuleListResponse"]["moduleList"]["modules"]
        channels = modules[0]["moduleResponse"]["contentData"]["channelListing"]["channels"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"  Could not parse channel list: {e}")
        print("  Top-level keys:", list((chan_data or {}).get("ModuleListResponse", {}).keys()))
        sys.exit(1)

    total = len(channels)
    print(f"\n  Total channels: {total}")

    # Verify key fields exist
    has_number = sum(1 for ch in channels if ch.get("channelNumber"))
    has_name   = sum(1 for ch in channels if ch.get("name"))
    has_img    = sum(1 for ch in channels if ch.get("images", {}).get("images"))
    has_desc   = sum(1 for ch in channels if ch.get("longDescription") or ch.get("shortDescription"))
    print(f"  With channel number : {has_number}/{total}")
    print(f"  With name           : {has_name}/{total}")
    print(f"  With image          : {has_img}/{total}")
    print(f"  With description    : {has_desc}/{total}")

    print("\n  Sample (first 5 with a channel number):")
    shown = 0
    for ch in channels:
        if not ch.get("channelNumber"):
            continue
        name   = ch.get("name", "?")
        number = ch.get("channelNumber", "?")
        cats   = [c.get("name", "") for c in ch.get("categories", [])]
        imgs   = ch.get("images", {}).get("images", [])
        img_url = imgs[0].get("url", "") if imgs else ""
        desc   = (ch.get("longDescription") or ch.get("shortDescription") or "")[:70]
        print(f"    ch#{str(number):>4}  {name:<35}  genre={cats}  img={'yes' if img_url else 'NO'}")
        if desc:
            print(f"           {desc}")
        shown += 1
        if shown >= 5:
            break

    print("\n=== All steps passed — player API is usable ===")


if __name__ == "__main__":
    main()
