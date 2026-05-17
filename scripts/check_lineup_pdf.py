#!/usr/bin/env python3
"""
Check for a new SiriusXM lineup PDF and compare channel names against channels.json.

https://www.siriusxm.com/lineup/siriusxm always redirects to the current PDF.
We follow that redirect, extract the filename, and compare to the last downloaded PDF.

Usage:
  python scripts/check_lineup_pdf.py            # check + download if new, then compare
  python scripts/check_lineup_pdf.py --compare  # compare current PDF against channels.json only
"""

import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber not installed. Run: pip install pdfplumber")

ROOT        = Path(__file__).parent.parent
CHANNELS_JSON = ROOT / "channels.json"
PDF_STATE   = ROOT / "lineup_pdf_state.json"  # tracks last known PDF filename

LINEUP_URL  = "https://www.siriusxm.com/lineup/siriusxm"
PDF_BASE    = "https://www.siriusxm.com/content/dam/sxm-com/pdf/lineup/"
UA          = "EPGeditARR/1.0 (github.com/jstevenscl/epgeditarr)"


# -- PDF discovery ------------------------------------------------------------

def get_current_pdf_url():
    """Follow the redirect from /lineup/siriusxm and return the final PDF URL."""
    req = urllib.request.Request(LINEUP_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.url.split("?")[0]  # strip tracking params


def pdf_filename(url):
    return url.rstrip("/").split("/")[-1]


def download_pdf(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        dest.write_bytes(r.read())


def check_for_new_pdf():
    """Return (current_url, is_new, local_path)."""
    current_url = get_current_pdf_url()
    filename    = pdf_filename(current_url)
    local_path  = ROOT / filename

    state = {}
    if PDF_STATE.exists():
        try:
            state = json.loads(PDF_STATE.read_text())
        except Exception:
            pass

    last_filename = state.get("filename")
    is_new = filename != last_filename

    if is_new or not local_path.exists():
        print(f"New PDF detected: {filename} (was: {last_filename or 'none'})")
        print(f"Downloading {current_url} ...")
        download_pdf(current_url, local_path)
        print(f"Saved to {local_path} ({local_path.stat().st_size:,} bytes)")
        PDF_STATE.write_text(json.dumps({"filename": filename, "url": current_url}, indent=2))
    else:
        print(f"PDF unchanged: {filename}")

    return current_url, is_new, local_path


# -- PDF parsing --------------------------------------------------------------

def _slug(name):
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", name.lower())


def extract_pdf_channels(pdf_path):
    """
    Extract (channel_number, description) pairs from the PDF text layer.

    NOTE: The PDF shows channel descriptions next to channel logos.
    The channel's branded name is embedded in the logo image (not extractable as text).
    So what we get here is: channel number + marketing description, not the guide name.
    This is still useful for number validation and description quality checks.
    """
    channels = {}
    # Match patterns like "02 Pop Hits, Now to Next" or "308 Deep Classic Album Rock"
    entry_re = re.compile(r"\b(\d{2,4})\s+([A-Z][^\d]{3,60}?)(?=\s{2,}|\d{2,4}\s+[A-Z]|$)")

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if not line or line.isupper():  # skip section headers
                    continue
                for m in entry_re.finditer(line):
                    num = int(m.group(1))
                    desc = m.group(2).strip().rstrip(",")
                    if 1 <= num <= 9999 and len(desc) > 3:
                        channels[num] = desc

    return sorted(channels.items())


# -- Comparison ---------------------------------------------------------------

def load_channels_json():
    data = json.loads(CHANNELS_JSON.read_text(encoding="utf-8"))
    return {v["sxm_number"]: v["name"] for v in data.values() if v.get("sxm_number")}


def compare(pdf_channels, json_channels):
    pdf_by_num = dict(pdf_channels)
    all_nums   = sorted(set(pdf_by_num) | set(json_channels))

    only_in_pdf  = []   # number in PDF but missing from channels.json
    only_in_json = []   # number in channels.json but missing from PDF

    for num in all_nums:
        if num in pdf_by_num and num not in json_channels:
            only_in_pdf.append((num, pdf_by_num[num]))
        elif num in json_channels and num not in pdf_by_num:
            only_in_json.append((num, json_channels[num]))

    matched = len(set(pdf_by_num) & set(json_channels))
    return matched, only_in_pdf, only_in_json


def print_report(pdf_path, pdf_channels, matched, only_in_pdf, only_in_json):
    total_pdf  = len(pdf_channels)
    total_json = len(json.loads(CHANNELS_JSON.read_text(encoding="utf-8")))

    print(f"\n{'='*70}")
    print(f"PDF:  {pdf_path.name}  ({total_pdf} numbered channels extracted)")
    print(f"JSON: channels.json  ({total_json} total channels)")
    print()
    print("NOTE: PDF text contains marketing descriptions, not official channel")
    print("names. Logo images in the PDF hold the branded names. This report")
    print("validates channel NUMBER coverage, not names.")
    print(f"{'='*70}")
    print(f"  Channel numbers in both:          {matched}")
    print(f"  In PDF but missing from JSON:     {len(only_in_pdf)}")
    print(f"  In JSON but not found in PDF:     {len(only_in_json)}")

    if only_in_pdf:
        print(f"\n{'-'*70}")
        print("IN PDF BUT MISSING FROM channels.json  (new or unnumbered channels)")
        print(f"{'-'*70}")
        for num, desc in only_in_pdf:
            print(f"  {num:>4}  {desc}")

    if only_in_json:
        print(f"\n{'-'*70}")
        print("IN channels.json BUT NOT FOUND IN PDF  (may be removed or renumbered)")
        print(f"{'-'*70}")
        for num, name in only_in_json:
            print(f"  {num:>4}  {name}")

    print(f"\n{'-'*70}")
    print("ALL PDF CHANNELS  (ch# | PDF description)")
    print(f"{'-'*70}")
    for num, desc in sorted(pdf_channels):
        print(f"  {num:>4}  {desc}")
    print()


# -- Main ---------------------------------------------------------------------

def main():
    compare_only = "--compare" in sys.argv

    if compare_only:
        # Use whichever PDF we already have
        state = {}
        if PDF_STATE.exists():
            state = json.loads(PDF_STATE.read_text())
        filename = state.get("filename")
        if not filename:
            pdfs = sorted(ROOT.glob("SXM-WebLine*.pdf"))
            if not pdfs:
                sys.exit("No PDF found. Run without --compare first.")
            filename = pdfs[-1].name
        pdf_path = ROOT / filename
        print(f"Using existing PDF: {pdf_path.name}")
    else:
        _, _, pdf_path = check_for_new_pdf()

    print(f"\nExtracting channel names from {pdf_path.name} ...")
    pdf_channels = extract_pdf_channels(pdf_path)
    print(f"Found {len(pdf_channels)} numbered channels in PDF")

    print("Loading channels.json ...")
    json_channels = load_channels_json()

    matched, only_in_pdf, only_in_json = compare(pdf_channels, json_channels)
    print_report(pdf_path, pdf_channels, matched, only_in_pdf, only_in_json)


if __name__ == "__main__":
    main()
