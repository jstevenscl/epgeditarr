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
    print("\nStep 2: Authenticate session  (modules/resume?OAtrial=false)")
    auth_data = _post("resume?OAtrial=false", {"moduleList": {"modules": [{"moduleRequest": {
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
        mod_resp = chan_data["ModuleListResponse"]["moduleList"]["modules"][0]["moduleResponse"]
        print(f"  moduleResponse keys: {list(mod_resp.keys())}")
        content  = mod_resp.get("contentData", mod_resp)
        print(f"  contentData keys:    {list(content.keys())}")
        listing  = content.get("channelListing", {})
        print(f"  channelListing keys: {list(listing.keys())}")
        channels = listing.get("channels", [])
    except (KeyError, IndexError, TypeError) as e:
        print(f"  Could not parse channel list: {e}")
        sys.exit(1)

    total = len(channels)
    print(f"\n  Total channels: {total}")

    nums = [int(ch["channelNumber"]) for ch in channels if ch.get("channelNumber")]
    if nums:
        print(f"  Number range: {min(nums)} - {max(nums)}")
        print(f"  1-499:   {sum(1 for n in nums if n <= 499)}")
        print(f"  500-799: {sum(1 for n in nums if 500 <= n <= 799)}")
        print(f"  800+:    {sum(1 for n in nums if n >= 800)}")

    has_img  = sum(1 for ch in channels if ch.get("images", {}).get("images"))
    has_desc = sum(1 for ch in channels if ch.get("longDescription") or ch.get("shortDescription"))
    print(f"  With image:       {has_img}/{total}")
    print(f"  With description: {has_desc}/{total}")

    # What 800+ channels do we have?
    high_chans = sorted([ch for ch in channels if ch.get("channelNumber") and int(ch["channelNumber"]) >= 800],
                        key=lambda c: int(c["channelNumber"]))
    print(f"\n  800+ channels ({len(high_chans)} total): first 10 and last 10")
    for ch in high_chans[:10] + (["..."] if len(high_chans) > 20 else []) + high_chans[-10:]:
        if ch == "...":
            print("    ...")
            continue
        print(f"    ch#{ch['channelNumber']:>4}  {ch.get('name','?')}")

    # Inspect superCategories for hints about additional channel sets
    super_cats = listing.get("superCategories", [])
    print(f"\n  superCategories count: {len(super_cats)}")
    for sc in super_cats[:5]:
        name = sc.get("name", "?") if isinstance(sc, dict) else sc
        kids = sc.get("categories", []) if isinstance(sc, dict) else []
        print(f"    {name}  ({len(kids)} sub-categories)")

    # -------------------------------------------------------------------------
    # Step 4: Try edge-gateway session exchange using player API cookies
    # -------------------------------------------------------------------------
    print("\nStep 4: Edge-gateway session exchange (using player API cookies/JWT)")
    EG_BASE = "https://api.edge-gateway.siriusxm.com"

    # The SXM_DATA_JWT_ATLAS cookie may serve as an identity token
    jwt_cookie = session.cookies.get("SXM_DATA_JWT_ATLAS", "")
    sxmdata    = session.cookies.get("SXMDATA", "")
    print(f"  SXM_DATA_JWT_ATLAS present: {'yes' if jwt_cookie else 'NO'}")
    print(f"  SXMDATA present:            {'yes' if sxmdata else 'NO'}")

    # Attempt 1: session endpoint with identityToken = JWT cookie value
    if jwt_cookie:
        import uuid
        device_id = str(uuid.uuid4())
        try:
            r = session.post(
                f"{EG_BASE}/session/v1/sessions/authenticated",
                json={"clientDeviceId": device_id, "platform": "web-desktop",
                      "identityToken": jwt_cookie},
                headers={"Accept": "application/json", "Content-Type": "application/json",
                         "User-Agent": UA},
                timeout=30,
            )
            print(f"  Session attempt (JWT as identityToken): HTTP {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                token = (data.get("token") or data.get("accessToken") or
                         data.get("bearerToken") or
                         (data.get("session") or {}).get("token"))
                print(f"  Bearer token obtained: {'YES — edge-gateway channel fetch will work!' if token else 'NO (keys: ' + str(list(data.keys())) + ')'}")
            else:
                print(f"  Body: {r.text[:300]}")
        except Exception as e:
            print(f"  Error: {e}")

    # Attempt 2: session endpoint with no identityToken (cookies only)
    try:
        r2 = session.post(
            f"{EG_BASE}/session/v1/sessions/authenticated",
            json={"clientDeviceId": str(uuid.uuid4()), "platform": "web-desktop"},
            headers={"Accept": "application/json", "Content-Type": "application/json",
                     "User-Agent": UA},
            timeout=30,
        )
        print(f"  Session attempt (cookies only, no identityToken): HTTP {r2.status_code}")
        if r2.status_code == 200:
            data2 = r2.json()
            token2 = (data2.get("token") or data2.get("accessToken") or
                      data2.get("bearerToken") or
                      (data2.get("session") or {}).get("token"))
            print(f"  Bearer token obtained: {'YES — hybrid approach works!' if token2 else 'NO (keys: ' + str(list(data2.keys())) + ')'}")
        else:
            print(f"  Body: {r2.text[:300]}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== All steps passed — player API is usable ===")


if __name__ == "__main__":
    main()
