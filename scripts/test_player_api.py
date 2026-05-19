#!/usr/bin/env python3
"""
Quick smoke-test for the player.siriusxm.com REST v2 API.

Tests login -> authenticate -> channel list fetch.
Prints pass/fail + key fields from the response so we can verify
the data matches what we need before rewriting build_channels_sxm.py.

Run:
  $env:SIRIUSXM_USERNAME="you@email.com"
  $env:SIRIUSXM_PASSWORD="yourpass"
  python scripts/test_player_api.py
"""

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://player.siriusxm.com/rest/v2/experience/modules"
UA   = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/604.5.6 (KHTML, like Gecko) Version/11.0.3 Safari/604.5.6"

_jar    = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _post(endpoint, payload):
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{BASE}/{endpoint}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent":   UA,
        },
        method="POST",
    )
    try:
        with _opener.open(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        print(f"  HTTP {e.code} from {e.url}")
        print(f"  Body: {body}")
        return None


def check_status(data, step):
    if data is None:
        print(f"  FAIL: {step} — no response")
        return False
    try:
        code = data["ModuleListResponse"]["messages"][0]["code"]
        msg  = data["ModuleListResponse"]["messages"][0]["message"]
    except (KeyError, IndexError, TypeError):
        code, msg = None, "(no message)"
    if code is not None and code != 100:
        print(f"  FAIL: {step} — code={code} msg={msg}")
        return False
    print(f"  OK:   {step}" + (f" (code={code})" if code else ""))
    return True


def main():
    username = os.environ.get("SIRIUSXM_USERNAME", "").strip()
    password = os.environ.get("SIRIUSXM_PASSWORD", "").strip()
    if not username or not password:
        sys.exit("Set SIRIUSXM_USERNAME and SIRIUSXM_PASSWORD")

    print("=== SiriusXM player.siriusxm.com API smoke test ===\n")

    # Step 1: Login
    print("Step 1: Login (player.siriusxm.com/rest/v2/experience/modules/login)")
    login_payload = {
        "moduleList": {
            "modules": [{
                "moduleRequest": {
                    "resultTemplate": "web",
                    "deviceInfo": {
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
                    },
                    "standardAuth": {
                        "username": username,
                        "password": password,
                    },
                }
            }]
        }
    }
    login_data = _post("login", login_payload)
    if not check_status(login_data, "login"):
        sys.exit(1)

    # Show cookies set
    cookies = {c.name: c.value for c in _jar}
    print(f"  Cookies set: {list(cookies.keys())}")
    if "SXMDATA" not in cookies:
        print("  WARN: SXMDATA cookie not found — auth may be incomplete")

    # Step 2: Authenticate session
    print("\nStep 2: Authenticate session (modules/authenticate)")
    auth_payload = {
        "moduleList": {
            "modules": [{
                "moduleRequest": {
                    "resultTemplate": "web",
                    "deviceInfo": {
                        "osVersion":        "Mac",
                        "platform":         "Web",
                        "clientDeviceType": "web",
                        "sxmAppVersion":    "3.1802.10011.0",
                        "browser":          "Safari",
                        "browserVersion":   "11.0.3",
                        "appRegion":        "US",
                        "deviceModel":      "K2WebClient",
                        "clientDeviceId":   "null",
                        "player":           "html5",
                    },
                }
            }]
        }
    }
    auth_data = _post("authenticate", auth_payload)
    check_status(auth_data, "authenticate")

    # Step 3: Fetch channel list
    print("\nStep 3: Fetch channel list (modules/get — ChannelListing)")
    chan_payload = {
        "moduleList": {
            "modules": [{
                "moduleArea": "Discovery",
                "moduleType": "ChannelListing",
                "moduleRequest": {
                    "consumeRequests": [],
                    "resultTemplate":  "responsive",
                    "alerts":          [],
                    "profileInfos":    [],
                },
            }]
        }
    }
    chan_data = _post("get", chan_payload)
    if not check_status(chan_data, "channel listing"):
        sys.exit(1)

    # Parse and show sample
    try:
        modules   = chan_data["ModuleListResponse"]["moduleList"]["modules"]
        channels  = modules[0]["moduleResponse"]["contentData"]["channelListing"]["channels"]
        total     = len(channels)
        sample    = channels[:3]
        print(f"\n  Total channels returned: {total}")
        print("  Sample (first 3):")
        for ch in sample:
            name   = ch.get("name", "?")
            number = ch.get("channelNumber", "?")
            cats   = [c.get("name", "") for c in ch.get("categories", [])]
            imgs   = ch.get("images", {}).get("images", [])
            img    = imgs[0].get("url", "") if imgs else ""
            desc   = ch.get("longDescription") or ch.get("shortDescription") or ""
            print(f"    ch#{number:>4}  {name:<35}  cats={cats}  img={'yes' if img else 'NO'}")
            if desc:
                print(f"           desc: {desc[:80]}")
    except (KeyError, IndexError, TypeError) as e:
        print(f"  Could not parse channel list: {e}")
        print("  Raw keys:", list((chan_data or {}).get("ModuleListResponse", {}).keys()))
        sys.exit(1)

    print("\n=== All steps passed — player API is usable ===")


if __name__ == "__main__":
    main()
