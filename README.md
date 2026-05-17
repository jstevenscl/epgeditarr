# EPGeditARR

A [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) plugin that creates clean, transformed copies of your EPG sources, fills in missing EPG data, and provides a full SiriusXM channel management toolkit.

> **Think of it as a filter layer between your raw EPG feed and what your players see.** Original sources are never touched.

---

## What It Does

### EPG Transformation

Many EPG sources contain noise in program titles and descriptions: broadcast flags, quality tags, episode codes, and other artifacts injected by the data provider.

| Raw title (what your EPG contains) | After EPGeditARR |
|---|---|
| `The Daily Show  ᴺᵉʷ` | `The Daily Show` |
| `Breaking Bad S01E01` | `Breaking Bad` |
| `Movie Night [HD] (2019)` | `Movie Night (2019)` |
| `Live Sports [LIVE]` | `Live Sports` |

EPGeditARR creates a virtual copy of your EPG source and writes the transformed programs there. Your channels are reassigned automatically. The original EPG is left untouched.

### Fill EPG

For channels that have no EPG data at all, EPGeditARR can generate a repeating placeholder schedule. This gives every channel at least a title block in your TV guide instead of a blank entry.

### SiriusXM Tools

For SiriusXM channel groups specifically, EPGeditARR provides a complete channel management toolkit:

- **Fill EPG** — Downloads the community SiriusXM XMLTV directly and assigns real EPG to every channel in your SiriusXM group in one step — no separate EPG refresh needed. Sports channels (NFL, NBA, MLB, NHL, Soccer, NASCAR, PGA Tour, IndyCar, F1) get smart schedule blocks: Upcoming announcements before each game, a LIVE block during the game, and a Post-game block after. All other channels get repeating fill blocks with real SiriusXM descriptions.
- **Sort** — Reorder your SiriusXM channels into SiriusXM's official lineup order, assigning sequential channel numbers starting from wherever your current range begins
- **Rename Channels** — Rename channels in your group to their official SiriusXM names, correcting provider name variants automatically using a built-in alias library
- **Assign Logos** — Assign channel logos to every matched SiriusXM channel from a self-hosted logo cache (714 channels, 100% coverage, served via GitHub Pages — no third-party CDN dependency)
- **Defer seasonal channels** — Holiday channels (e.g. Holly, Country Christmas) are placed at the end of the list when out of season, and sort to their correct lineup positions when active
- **Fill, Sort & Logos** — Run all three SiriusXM setup steps in one click

The SiriusXM channel list is sourced from the official SiriusXM API and rebuilt weekly by a GitHub Actions workflow, served from GitHub Pages — no load on your Dispatcharr server.

### Community SiriusXM EPG

EPGeditARR publishes a ready-to-use XMLTV EPG file covering all SiriusXM channels — no plugin required. Add it directly to any IPTV player or DVR that accepts an XMLTV URL:

```
https://jstevenscl.github.io/epgeditarr/siriusxm_epg.xml
```

- **741 channels** — all SiriusXM channels from the official API lineup plus sport play-by-play feeds
- **Sports channels** get smart blocks: Upcoming → LIVE → Post-game
- **All other channels** get repeating fill blocks with real SiriusXM descriptions
- **14 days** of schedule generated, refreshed every 4 hours
- **Channel logos** included via `<icon>` tags for all 714 channels (100% coverage)
- Set your channel's `tvg-id` to the SiriusXM channel name (e.g. `SiriusXM NFL Radio`, `SiriusXM NBA Radio`) to match the EPG

---

![EPGeditARR installed in Dispatcharr](docs/screenshots/01_plugin_installed.png)

## Installation

### Recommended: Via Plugin Repository

1. In Dispatcharr, go to **Plugins → Find Plugins → Manage Repos → Add Repository**
2. Paste this URL:
   ```
   https://jstevenscl.github.io/epgeditarr/manifest.json
   ```
3. Click **Add Repo**, then find **EPGeditARR** in the list and install it

### Manual Install

Copy `plugin.py` and `plugin.json` into your Dispatcharr plugins directory and reload plugins.

---

## Quick Start — EPG Transformation

### Step 1 — Find out what's in your EPG

Before writing any rules, use **Sample Data** to see what tags and patterns actually exist in your sources.

1. Open EPGeditARR → **Actions tab**
2. Click **Sample Data**

The output groups programs by category (episode codes, broadcast flags, quality tags, unicode flags, etc.) and shows real before/after examples.

![Sample Data output showing category breakdown](docs/screenshots/04_sample_data.png)

### Step 2 — Build your rules

Use the **[Rule Designer](https://jstevenscl.github.io/epgeditarr/designer.html)** to pick rules from a preset library or build your own. Copy the generated rules text when you're done.

![Rule Designer — preset selected with live results](docs/screenshots/05_rule_designer_active.png)

Common presets:
- Episode codes (`S01E01`, `E05`, `1x05`)
- Broadcast flags (`(New)`, `(Live)`, `(Repeat)`, `[LIVE]`)
- Quality tags (`[HD]`, `[4K]`, `[UHD]`)
- Technical tags (`(CC)`, `(SAP)`, `(Stereo)`)
- Year tags (`(2023)`)
- Unicode broadcast flags (`ᴺᵉʷ`, `ᴸᶦᵛᵉ` — Gracenote-based providers)

### Step 3 — Enable a source and add rules

1. Open EPGeditARR → **Settings tab**
2. Find the EPG source you want to clean
3. Toggle **Enable transformation** ON
4. Paste your rules into **Title Rules** (and/or Sub-Title / Description Rules)

![Settings tab — source toggle and rule fields](docs/screenshots/03_settings_tab.png)

### Step 4 — Preview (optional but recommended)

Click **Preview** in the Actions tab. Shows exactly which programs would change and the before/after values — no data is modified.

### Step 5 — Run Setup

Click **Setup** in the Actions tab. This:
- Creates a virtual EPG source (`EPGeditARR: [Your Source Name]`)
- Transforms all programs and writes them to the virtual source
- Reassigns your channels to the virtual source automatically

![Actions tab](docs/screenshots/02_actions_tab.png)

From this point on, **every EPG refresh automatically re-runs the transformation**. You never have to touch Setup again unless you add a new source.

---

## Quick Start — Fill EPG

Fill EPG generates a repeating placeholder schedule for channels that have no EPG data.

### Step 1 — Configure Fill Groups

In **Settings → Fill EPG**, enter the names of the channel groups you want to fill (comma-separated). Example: `SiriusXM, Radio`.

Also set **Block Duration** (how long each placeholder program block is) and **Days Ahead** (how many days of schedule to generate).

### Step 2 — Scan to see what will be filled

Click **Scan** in the Actions tab. This shows all channels with no EPG data, grouped by channel group, and marks which groups are targeted by Fill EPG.

### Step 3 — Fill

Click **Fill** to generate the schedules. Channels in your Fill Groups that have no EPG get a repeating block schedule. This runs automatically after every EPG refresh.

---

## Quick Start — SiriusXM Channels

> All SiriusXM features operate on the **SiriusXM Channel Group** configured in **Settings → SiriusXM Channels Only** — completely separate from the general Fill Groups setting.

![SiriusXM settings section](docs/screenshots/06_settings_siriusxm.png)

### Step 1 — Enable Enrichment

In **Settings → SiriusXM Channels Only**, enable **Enable SiriusXM Enrichment** and set your **SiriusXM Channel Group** name. This loads the official SiriusXM API channel data needed for all SiriusXM actions.

### Step 2 — Rename Channels (optional but recommended)

Click **Rename Channels** to correct any provider name variants. EPGeditARR uses a built-in alias library that maps known mislabeled or old channel names (e.g. "Green Day's Idiot Nation" → "FACTION PUNK", "VSiN Radio" → "VSiN") to their official SiriusXM names. Only matched channels are renamed.

### Step 3 — Fill, Sort & Assign Logos

Click **Fill, Sort & Logos** to run all three steps at once:

1. **Fill SiriusXM EPG** — Downloads the community XMLTV and assigns EPG with real SiriusXM channel descriptions to all matched channels in your SiriusXM Channel Group
2. **Sort Channels** — Reorders channels to match SiriusXM's official lineup order and assigns sequential channel numbers
3. **Assign Logos** — Assigns channel logos from the self-hosted GitHub Pages logo cache (~460 channels covered)

Or run each step individually with the dedicated action buttons.

#### Sorting output example

```
Sort complete — 312 channels renumbered from 1001 (auto-detected)

  Matched via SiriusXM API   : 148
  Seasonal (out of season)   :  11
  Matched via sport block    :  96
  Matched via name number    :  38
  No match (placed at end)   :  19

Seasonal channels (out of season — will sort correctly when active):
  Holly
  Country Christmas
  Hallmark Radio
  ...
```

**Seasonal channels** are placed at the end while out of season and automatically sort to their correct Wikipedia lineup positions when the season begins — no manual intervention needed.

**Sport play-by-play channels** (NFL, NBA, NHL, MLB team feeds) are grouped with their league's block using a built-in team roster.

**Embedded channel numbers** (e.g. `Sports 963`, `ACC 955`) are used as a fallback sort key for channels not in the Wikipedia lineup.

---

## Actions Reference

| Button | What it does |
|---|---|
| **Setup** | First time you enable a source, or after adding a new source. Creates the virtual EPG and reassigns channels. |
| **Apply Now** | After changing rules — re-runs the transform immediately without waiting for the next EPG refresh. |
| **Preview** | Dry-run your current rules. Shows before/after for affected programs. No changes made. |
| **Sample Data** | Discover what tags/patterns exist in your sources. Run this before writing rules. |
| **Test Rule** | Test a single rule against live data from any source and field. Uses the Rule Tester settings. |
| **Scan** | List all channels with no EPG data, grouped by channel group. Shows which groups are targeted by Fill EPG. |
| **Fill** | Generate repeating placeholder EPG schedules for channels in your Fill Groups with no EPG data. |
| **Fill SiriusXM EPG** | *(SiriusXM)* Download the community SiriusXM XMLTV and assign EPG to all channels in your SiriusXM Channel Group. Sports channels get smart Upcoming/LIVE/Post-game blocks; all other channels get repeating fill blocks with real SiriusXM descriptions. Creates the `EPGeditARR: SiriusXM` source automatically if it doesn't exist. |
| **Sort** | *(SiriusXM)* Reorder channels in your SiriusXM Channel Group to match SiriusXM's official lineup order. |
| **Fill & Sort** | *(SiriusXM)* Run Fill SiriusXM EPG and Sort together in one step. |
| **Fill, Sort & Logos** | *(SiriusXM)* Run Fill SiriusXM EPG, Sort, and Assign Logos in one step — the full SiriusXM setup. |
| **Rename Channels** | *(SiriusXM)* Rename channels in your SiriusXM Channel Group to their official SiriusXM names using the built-in alias library. |
| **Assign Logos** | *(SiriusXM)* Assign channel logos from the self-hosted GitHub Pages logo cache to matched channels. |
| **Refresh Channel Data** | *(SiriusXM)* Force an immediate refresh of the SiriusXM channel list from Wikipedia. |
| **Show Status** | Shows which sources are enabled, program counts, Fill EPG status, and configured rules. |
| **Teardown** | Removes all virtual EPG sources (including Fill EPG) and reassigns channels back to their originals. |

---

## Rule Format

Rules go in the **Title Rules**, **Sub-Title Rules**, or **Description Rules** fields in Settings. One rule per line. Lines starting with `#` are comments.

### Regex rule
```
regex::PATTERN::REPLACEMENT
```
- `PATTERN` is a Python regex
- Leave `REPLACEMENT` empty to strip the match entirely
- Use `$1`, `$2` for capture groups (EPGeditARR converts these to `\1`, `\2` internally)

### Find/replace rule
```
replace::FIND::REPLACEMENT
```
- Literal text match (not a regex)
- Leave `REPLACEMENT` empty to strip the match

### Examples

Strip episode codes from titles:
```
regex::S\d+E\d+\s*::
regex::\bE\d{2,3}\b\s*::
```

Strip broadcast flags:
```
regex::\s*\(New\)\s*::
regex::\s*\(Live\)\s*::
regex::\s*\[LIVE\]\s*::
```

Strip quality tags:
```
replace::[HD]::
replace::[4K]::
```

Strip unicode broadcast flags (Gracenote-style):
```
regex::\s{2,}(?:ᴺᵉʷ|ᴸᶦᵛᵉ|ᴾʳᵉ|ᴿᵉᵖ|ᴵⁿᶠᵒ|ᴼᵛᵉʷ)::
```

Strip a year from the end of a title:
```
regex::\s*\((19|20)\d{2}\)\s*$::
```

### Adding tags

Inject text by anchoring to the start (`^`) or end (`$`) of a field:

```
regex::$:: [LIVE]
regex::^::ESPN: 
```

Conditionally add `[LIVE]` only when the title contains the word "live":
```
regex::^(.*\blive\b.*)$::$1 [LIVE]
```

> **Tip:** Use the **Inject / Add Tags** preset group in the Rule Designer to build these without typing regex by hand.

---

## Settings Reference

### EPG Sources

Each EPG source in Dispatcharr gets its own section. Per-source settings:

| Setting | Description |
|---|---|
| **Enable transformation** | Toggle transformation on/off for this source |
| **Title Rules** | Rules applied to program titles |
| **Sub-Title Rules** | Rules applied to episode sub-titles |
| **Description Rules** | Rules applied to program descriptions |
| **Auto-Reassign Channels on Setup** | Toggle channel reassignment on/off for this source |
| **Include Channel Groups** | Comma-separated group names — only these groups are reassigned |
| **Exclude Channel Groups** | Comma-separated group names — these groups are skipped |

### Fill EPG

| Setting | Description |
|---|---|
| **Fill Groups** | Comma-separated channel group names. Channels in these groups with no EPG get a generated schedule. |
| **Skip Channels** | One channel name per line. These channels are excluded from Fill EPG even if in a Fill Group. |
| **Block Duration** | Duration of each generated program block (1–24 hours). |
| **Days Ahead** | How many days of schedule to generate ahead (7, 14, or 30). |

### SiriusXM Channels Only

| Setting | Description |
|---|---|
| **Enable SiriusXM Enrichment** | Match channel names against the official SiriusXM API channel database and add real descriptions to generated EPG entries. Required for Sort, Rename, and Assign Logos to function. |
| **SiriusXM Channel Group** | The Dispatcharr channel group containing your SiriusXM channels. All SiriusXM actions operate on this group exclusively. |
| **Sort Start Number** | Channel number for the first sorted channel. Leave blank to auto-detect from the lowest number currently in your SiriusXM Channel Group. |

---

## Rule Tester

The Rule Tester lets you test a single rule against live data from any source without modifying anything.

1. Go to **Settings tab** → scroll to **Rule Tester**
2. Select the source and field (Title, Sub-Title, or Description)
3. Enter a pattern and optional replacement
4. Click **Test Rule** in the Actions tab

You can also paste specific text into **Test Text** to test against that instead of pulling live data.

---

## Rule Designer

The **[Rule Designer](https://jstevenscl.github.io/epgeditarr/designer.html)** is a standalone web tool for building rules visually.

- Browse the preset library and add rules with one click
- Test patterns against sample text in real time
- Copy the finished rules text and paste into the plugin settings

![Rule Designer](docs/screenshots/05_rule_designer.png)

---

## FAQ

**Do my original EPG sources get modified?**
No. EPGeditARR only writes to the virtual (dummy) EPG sources it creates. Your original sources are read-only.

**What happens when my EPG refreshes?**
The plugin listens for Dispatcharr's EPG refresh completion signal. When a source you've enabled finishes refreshing, the transform and Fill EPG both run automatically.

**I added a new source after running Setup. What do I do?**
Enable the new source in Settings, add rules, then click **Setup** again. It's safe to run multiple times — it won't duplicate virtual sources or reassign already-correct channels.

**I changed my rules. Do I need to run Setup again?**
No — click **Apply Now**. Setup is only needed when adding a new source for the first time.

**Something looks wrong. How do I undo everything?**
Click **Teardown**. This deletes all virtual EPG sources (including Fill EPG) and reassigns your channels back to their original sources.

**My SiriusXM channel didn't get a description even though enrichment is on.**
The Fill output shows how many channels matched and lists any unmatched names. If a channel missed, the most common cause is a name difference between your Dispatcharr channel and the official SiriusXM channel name. Run **Refresh Channel Data** to pull the latest API data, or use **Rename Channels** to correct provider name variants first.

**Rename Channels changed a name I didn't want changed.**
The rename is based on a built-in alias library that maps known provider variants to official SiriusXM names. If a match is wrong, the channel can be manually renamed back in Dispatcharr. You can also run **Rename Channels** selectively — only matched channels are renamed, unmatched ones are left alone.

**Why are my holiday channels at the end of the sort even though they have Wikipedia numbers?**
Channels in SiriusXM's seasonal holiday section (active early November – early January) are automatically placed at the end of the list when they're out of season. They'll sort to their correct positions — Holly at #4, Country Christmas at #58, etc. — as soon as the season begins. No action needed.

**The unicode broadcast flags (`ᴺᵉʷ`, `ᴸᶦᵛᵉ`) show zero matches in Sample Data.**
These are provider-specific — not all EPG sources include them. Use Sample Data with each enabled source individually to find which one has them. They're typically found in Gracenote-sourced or aggregator feeds.

**How does the SiriusXM channel list stay up to date?**
A GitHub Actions workflow fetches the latest channel list directly from the official SiriusXM API every week and commits it to the repo. It's served via GitHub Pages so your Dispatcharr server never hits the API directly. You can also force a refresh any time with **Refresh Channel Data**.

**Where do the channel logos come from?**
All 714 SiriusXM channel logos are downloaded directly from the official SiriusXM player CDN and cached in this repository, served via GitHub Pages. This gives 100% logo coverage across all channels in the official lineup. There is no dependency on any third-party logo service. Logo URLs are content-addressed (the CDN embeds an MD5 hash) so logos are only re-downloaded when they actually change.

---

## License

MIT
