# EPGeditARR

A [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) plugin that creates clean, transformed copies of your EPG sources, fills in missing EPG data, and includes a Sports Editor for auto-synced sports channel groups.

> **SiriusXM channel management has moved.** As of this version, EPGeditARR no longer includes SiriusXM channel Fill/Sort/Rename/Logo tooling — that functionality is now maintained in the [Tickarr](https://github.com/jstevenscl/tickarr) plugin, which has a more advanced EPG and up-to-date logos. See the release notes for details.

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

Per-source, you can also **Force Category (Series Mode)** and **Synthesize Episode Numbers From Air Date** — useful when an EPG's bare-bones programs (title/description only, no episode data) get treated as duplicate movies by Plex instead of recordable series episodes. See Settings Reference below.

### Fill EPG

For channels that have no EPG data at all, EPGeditARR can generate a repeating placeholder schedule. This gives every channel at least a title block in your TV guide instead of a blank entry.

### Sports Editor

For channel groups that Dispatcharr's Auto Channel Sync populates automatically (e.g. an NFL Game Pass stream group), EPGeditARR can rename the auto-created channels using a dedicated rule set — configured per channel group, separate from the EPG Sources rules above. It runs automatically right after each successful M3U refresh, and only ever touches auto-created channels, never manually-added ones.

Each channel group can also opt into **Sport Templates** (below) instead of, or alongside, plain rename rules — matching auto-created channels against a live public sports schedule and generating real channel names, logos, and a Pregame/Live/Postgame EPG from actual game data.

### Sport Templates

For groups with a Sport Template selected, EPGeditARR fetches live schedule data from [sports-data-platform](https://api.tickarr.com) (a public feed shared across several sports-IPTV tools) and matches each auto-created channel against a real event in that sport, then — on a match — automatically:

- **Renames the channel** using a `{variable}`-driven template (e.g. `Denver Broncos @ Atlanta Falcons`, or `Alex Michelsen vs Taylor Fritz` for tennis)
- **Assigns a logo** via a matchup thumbnail/logo API ([sethwv/game-thumbs](https://github.com/sethwv/game-thumbs) — self-hostable, or use the public default instance) for team sports
- **Generates three EPG program blocks** around the real event time: Pregame, Live (event start through an estimated end based on the sport), and Postgame — each with its own title/description template

**93 leagues are supported** — every major US team sport (NFL, NBA, MLB, NHL, NCAA Football, MLS, and dozens more including softball, volleyball, lacrosse, and NCAA variants), 30+ soccer competitions worldwide (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, FIFA World Cup, and more), tennis (ATP/WTA), golf (PGA TOUR/LPGA), all three NASCAR series, Formula 1, UFC/MMA/boxing/darts, and a few niche sports (surfing, fishing). Two different matching engines run under the hood depending on the sport — team/individual matchup sports split the channel name into two competitors, while golf/NASCAR/F1-style sports match one descriptive event title instead — but this is automatic per sport, nothing to configure. See the **[Sport Templates Guide](docs/SPORT_TEMPLATES.md#full-league-list)** for the complete list.

All scheduling is UTC-anchored, matching Dispatcharr's own timezone-neutral convention — every variable is also available in a US Eastern/Central-formatted flavor (`{start_time_et_ct}`, etc., matching broadcast-standard convention for these leagues) and a plain UTC flavor (`{start_time_utc}`, etc.) side by side, so templates read correctly for viewers anywhere.

If a channel can't be confidently matched to a real game, the group's regular Rename Rules still apply as a fallback (or run standalone if no Sport Template is selected). See **Sport Templates Guide** below for the full setup walkthrough, variable reference, matching-engine caveats, and starter templates per league.

### Community SiriusXM EPG

EPGeditARR publishes a ready-to-use XMLTV EPG file covering all SiriusXM channels — no plugin required. Add it directly to any IPTV player or DVR that accepts an XMLTV URL:

```
https://jstevenscl.github.io/epgeditarr/siriusxm_epg.xml
```

- **771 channels** — all SiriusXM channels from the official lineup plus sport play-by-play feeds
- **Sports channels** get smart blocks: Upcoming → LIVE → Post-game
- **All other channels** get repeating fill blocks with real SiriusXM descriptions
- **14 days** of schedule generated, refreshed every 4 hours
- **Channel logos** included via `<icon>` tags for matched channels
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

## Quick Start — Sports Editor

> The Sports Editor operates per channel group — each channel group you enable gets its own Rename Rules, independent of every other group's rules.

### Step 1 — Set up Auto Channel Sync in Dispatcharr

In Dispatcharr's M3U account settings, enable Auto Channel Sync for the stream group you want (e.g. an NFL Game Pass group), and optionally target a dedicated channel group via the override option so auto-created channels land somewhere isolated from your production lineup.

### Step 2 — Enable the channel group in EPGeditARR

In Settings, find the section for that channel group and toggle it on, then add Rename Rules (same `regex::`/`replace::` format as EPG Sources rules — see Rule Format below).

### Step 3 — Let it run automatically, or trigger it manually

After Dispatcharr's Auto Channel Sync creates channels on the next M3U refresh, EPGeditARR renames them automatically — no manual step needed. To apply rule changes to already-existing auto-created channels without waiting for the next refresh, click **Rename Sports Channels Now**.

### Step 4 — (Optional) Turn on Sport Templates for real game data

Want real channel names, logos, and a Pregame/Live/Postgame EPG instead of just cleaned-up names? Pick a **Sport Template** from that same group's section in Settings. See the **[Sport Templates Guide](docs/SPORT_TEMPLATES.md)** for the full walkthrough — matching, variables, and starter templates per league.

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
| **Rename Sports Channels Now** | Apply each enabled channel group's Sports Channel Rename Rules to its auto-created channels right now, without waiting for the next M3U refresh. |
| **Run Sport Templates Now** | Match each Sport-Template-enabled group's auto-created channels against the live schedule right now — renames matches, assigns logos, and generates Pregame/Live/Postgame EPG data. |
| **Show Status** | Shows which sources are enabled, program counts, Fill EPG status, and configured rules. |
| **Teardown** | Removes all virtual EPG sources (including Fill EPG) and reassigns channels back to their originals. |
| **Restart Dispatcharr** | Reloads Dispatcharr's backend process so it picks up a plugin update — run this after every EPGeditARR install/update. Not a full container restart; the page goes offline for about 15 seconds. |

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
| **Force Category (Series Mode)** | Adds an XMLTV `<category>` tag to every program on this source's virtual copy. Setting this to `Series` tells Plex to treat repeating programs that share a title as episodes of a show instead of duplicate movies, so DVR can record more than one. Comma-separated for multiple categories. Leave blank to disable. |
| **Synthesize Episode Numbers From Air Date** | Adds a unique `<episode-num system="xmltv_ns">` tag per program, derived from its air date (year + day-of-year), so Plex sees each airing as a distinct episode instead of collapsing same-titled programs into one recordable movie. Pair with Force Category above. |
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

### Sports Editor

One section appears per Dispatcharr channel group. Per-group settings:

| Setting | Description |
|---|---|
| **Enable Sports Editor for this group** | Toggle the Sports Editor on/off for this channel group |
| **Sport Template** | Pick a sport (93 supported — see the [full league list](docs/SPORT_TEMPLATES.md#full-league-list)), or none, to match this group's auto-created channels against live game data instead of/alongside rename rules. See the **[Sport Templates Guide](docs/SPORT_TEMPLATES.md)**. |
| **Sports Channel Rename Rules** | Rules applied to auto-created channel names in this group. Same format as EPG Sources rules above, but a separate rule set per group. Used as a fallback when no Sport Template match is found (or always, if no Sport Template is selected). |

### Sport Templates

One section appears per sport. Each defines the templates used when a channel group with that sport selected matches a live game. Full variable reference and starter templates: **[Sport Templates Guide](docs/SPORT_TEMPLATES.md)**.

| Setting | Description |
|---|---|
| **Channel Name** | Renames the matched auto-created channel |
| **Logo URL** | Assigned as the channel's logo |
| **Pregame Title / Description** | EPG block covering midnight UTC through kickoff on game day |
| **Live Title / Description** | EPG block covering the estimated game window |
| **Postgame Title / Description** | EPG block covering 1 hour after the estimated end |

| Setting | Description |
|---|---|
| **Game Thumbs Base URL** | Base URL of a [sethwv/game-thumbs](https://github.com/sethwv/game-thumbs) instance used by Logo URL templates via `{gamethumbs_base}`. Defaults to a publicly hosted instance — point this at your own self-hosted instance if you run one. |

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

**Clicking Dispatcharr's own refresh icon (⟳) on an "EPGeditARR: ..." row in M3U & EPG Manager gives an error about the source URL.**
Expected — EPGeditARR's virtual/generated EPG sources (transform virtuals, Fill EPG, Sports Editor) intentionally have no URL, since EPGeditARR writes their program data directly instead of Dispatcharr fetching it. Dispatcharr's native per-source refresh only knows how to fetch a URL, so it always fails on these with something like "Failed to download EPG data, cannot parse programs." This only flips that source's Status column to "Error" — it never touches your actual EPG data. Always use the plugin's own Actions tab buttons (**Apply Now**, **Fill**, **Run Sport Templates Now**) to refresh EPGeditARR-managed data; running any of them restores the Status column to "Success."

**The unicode broadcast flags (`ᴺᵉʷ`, `ᴸᶦᵛᵉ`) show zero matches in Sample Data.**
These are provider-specific — not all EPG sources include them. Use Sample Data with each enabled source individually to find which one has them. They're typically found in Gracenote-sourced or aggregator feeds.

**I updated Dispatcharr and now plugin action buttons don't show any output.**
This is a known display-only regression, present since Dispatcharr v0.25.0 and still occurring as of v0.29.0. When you click an action button (Status, Fill, Run Sport Templates, etc.) the action runs correctly on the backend and all data is written — the result text just doesn't render in the modal UI. To confirm an action completed, click **Show Status** which will show current program counts and source state. All functionality continues to work normally. No change to EPGeditARR is needed.

**Where did SiriusXM channel management go?**
It's been removed from EPGeditARR as of this version — see the note at the top of this README and the release notes. Active SiriusXM development (Now Playing overlays, logos, and a more advanced EPG) is now in the [Tickarr](https://github.com/jstevenscl/tickarr) plugin.

---

## Credits & Attribution

- **Sport Templates UX** — the per-sport Channel Name / Logo URL / Pregame / Live / Postgame template design was inspired by [Pharaoh-Labs' Teamarr](https://github.com/Pharaoh-Labs/teamarr), used with their permission.
- **Matchup logos & thumbnails** — powered by [sethwv/game-thumbs](https://github.com/sethwv/game-thumbs) (MIT), used with the author's permission. Self-host your own instance or use the public default — see the [Sport Templates Guide](docs/SPORT_TEMPLATES.md).
- **Game schedule data** — [sports-data-platform](https://api.tickarr.com), a public schedule feed.

## License

MIT
