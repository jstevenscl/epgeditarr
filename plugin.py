"""
EPGeditARR — Dispatcharr Plugin
Maintains transformed virtual copies of EPG sources using per-source, per-field
regex and find/replace rules. Fields are generated dynamically from the DB so
any user's EPG sources appear as toggles without hardcoded names.

Also generates fill EPG schedules for channels with no EPG data.
"""

import logging
import re
from django.db import transaction

LOGGER = logging.getLogger("plugins.epgeditarr")
VIRTUAL_PREFIX = "EPGeditARR: "
PLUGIN_KEY = "epgeditarr"

FILL_SOURCE_NAME = "EPGeditARR: Fill"
FILL_CACHE_KEY = "fill_channel_cache"
FILL_CACHE_UPDATED_KEY = "fill_channel_cache_updated"
FILL_CACHE_TTL_DAYS = 7
UNMATCHED_LOG_KEY = "sxm_unmatched_log"

SDP_SCHEDULE_URL = "https://api.tickarr.com/v1/schedule.json"
SPORTS_EPG_SOURCE_NAME = "EPGeditARR: Sports Editor"
SDP_CACHE_KEY = "sdp_schedule_cache"
SDP_CACHE_UPDATED_KEY = "sdp_schedule_cache_updated"
SDP_CACHE_TTL_SECS = 30 * 60

_MATCHUP_SEP_RE = re.compile(r"\s+(?:@|vs\.?|v\.?|at)\s+", re.IGNORECASE)

# Key = sports-data-platform's own league_slug (api.tickarr.com), reused directly
# as the game-thumbs league slug too for team sports. Covers every league_slug SDP
# exposes as of 2026-08-16 except: table tennis/WTT (different sport, day/session-
# based, needs its own matcher — not built yet) and "mecum-auctions" (a car auction
# livestream SDP files under motor-sports, not an actual sport — deliberately
# excluded). Two near-duplicate slugs worth knowing about, both included as-is
# rather than guessed at: "la-liga" (25 events) and "laliga" (8 events) both claim
# to be Spanish La Liga — likely two different ingest sources SDP hasn't merged;
# same for "laliga-2"/LALIGA 2. If one of a pair is consistently empty for you,
# just don't enable it for any group.
_SPORT_TEMPLATES = {
    "nfl":           "NFL",
    "nba":           "NBA",
    "mlb":           "MLB",
    "nhl":           "NHL",
    "ncaa-football": "NCAA Football",
    "mls":           "MLS",
    "atp":           "ATP (Men's Tennis)",
    "wta":           "WTA (Women's Tennis)",
    "pga":           "PGA TOUR (Golf)",
    "lpga":          "LPGA (Golf)",
    "nascar-cup-series":       "NASCAR Cup Series",
    "nascar-xfinity-series":   "NASCAR Xfinity Series",
    "nascar-craftsman-trucks": "NASCAR Craftsman Truck Series",
    # Soccer
    "premier-league":       "Premier League",
    "championship":         "EFL Championship",
    "efl-league-one":       "EFL League One",
    "efl-league-two":       "EFL League Two",
    "carabao-cup":          "Carabao Cup",
    "community-shield":     "Community Shield",
    "la-liga":              "La Liga",
    "laliga":               "LALIGA",
    "laliga-2":             "LALIGA 2",
    "bundesliga":           "Bundesliga",
    "3-liga":               "3. Liga",
    "ligue-1":              "Ligue 1",
    "serie-a":              "Serie A",
    "liga-portugal":        "Liga Portugal",
    "eredivisie":           "Eredivisie",
    "super-lig":            "Süper Lig",
    "scottish-premiership": "Scottish Premiership",
    "liga-mx":              "Liga MX",
    "usl-championship":     "USL Championship",
    "usl-league-one":       "USL League One",
    "leagues-cup":          "Leagues Cup",
    "nwsl":                 "NWSL",
    "northern-super-league": "Northern Super League",
    "j1-league":            "J1 League",
    "brasileirao":          "Brasileirão Série A",
    "copa-libertadores":    "Copa Libertadores",
    "copa-sudamericana":    "Copa Sudamericana",
    "arg-primera":          "Argentine Primera División",
    "ncaaw-soccer":         "NCAAW Soccer",
    "ncaam-soccer":         "NCAAM Soccer",
    "big-ten-soccer-w":     "Big Ten Soccer (W)",
    "big-ten-soccer-m":     "Big Ten Soccer (M)",
    "world-cup":                 "FIFA World Cup",
    "champions-league":          "UEFA Champions League",
    "ucl-qualifying":            "UCL Qualifying",
    "uecl-qualifying":           "UECL Qualifying",
    "uel-qualifying":            "UEL Qualifying",
    "mens-international-friendly": "Men's International Friendly",
    "usl-cup":                   "USL Cup",
    # Baseball
    "ncaa-baseball": "NCAA Baseball",
    "alb":           "ALB",
    "wpbl":          "WPBL",
    "jlb":           "JLB",
    "interlb":               "INTERLB",
    "little-league-baseball": "Little League Baseball",
    "necb":                  "NECB",
    "slbase":                "SLBASE",
    # Softball (all standard team-vs-team, same as baseball — no live events in the
    # rolling feed window when this was added since it's spring/summer sport
    # off-season, but a real team sport not requiring data-shape verification)
    "ausl":                   "AUSL",
    "hssoft":                 "HSSOFT",
    "jlsoft":                 "JLSOFT",
    "little-league-softball": "Little League Softball",
    "ncaa-softball":          "NCAA Softball",
    "slsoft":                 "SLSOFT",
    # Volleyball
    "ncaa-volleyball":        "NCAA Volleyball",
    "ncaa-womens-volleyball": "NCAA Women's Volleyball",
    "big-ten-volleyball-w":   "Big Ten Volleyball (W)",
    # Basketball
    "ncaam":           "NCAAM Basketball",
    "ncaaw-basketball": "NCAAW Basketball",
    "nznbl":           "NZNBL",
    # Other team sports
    "wnba":                 "WNBA",
    "afl":                  "AFL",
    "pll":                  "PLL (Lacrosse)",
    "bhslax":               "BHSLAX (Lacrosse)",
    "ghslax":               "GHSLAX (Lacrosse)",
    "wll":                  "WLL (Lacrosse)",
    "big-ten-field-hockey": "Big Ten Field Hockey",
    "ncaaf":                "NCAAF",  # separate live slug from ncaa-football, confirmed distinct in feed
    "nfl-flag":             "NFL FLAG",
    "ufl":                  "UFL",
    "ufc":                  "UFC",
    # Person-vs-person sports (boxing/MMA/darts/college tennis) — same matchup
    # shape as tennis/UFC by the nature of the sport (always exactly 2
    # competitors), used with _person_name_score. No live events to verify field
    # population against at the time these were added (see docs caveat).
    "most-valuable-promotions": "Boxing (Most Valuable Promotions)",
    "pfl":                      "PFL (MMA)",
    "legacy-alliance":          "Legacy Alliance (MMA)",
    "pdc":                      "PDC (Darts)",
    "cwten":                    "College Women's Tennis",
    # Single-title sports (no away/home split — see _SPORT_MATCH_MODE below)
    "f1":                          "Formula 1",
    "world-surf-league":           "World Surf League",
    "sport-fishing-championship":  "Sport Fishing Championship",
    "cwgol": "College Women's Golf",
    "wagc":  "World Amateur Golf Council",
}

# Estimated game length used to size the "Live" EPG block. Approximate on purpose —
# real end times aren't published by SDP, so this just needs to comfortably cover
# a typical broadcast window.
_LEAGUE_DURATION_HOURS = {
    "nfl":           3.5,
    "nba":           2.5,
    "mlb":           3.25,
    "nhl":           2.75,
    "ncaa-football": 3.5,
    "mls":           2.25,
    "atp":           2.5,
    "wta":           2.0,
    "pga":           5.5,
    # LPGA's SDP ingest is tournament-level only (no round/group breakdown like
    # PGA TOUR has) — one row per multi-day tournament, so there's no sensible
    # single-round duration to estimate. Sized to span a whole 4-day event instead
    # of one round, so the Live block covers the tournament rather than reading as
    # "Postgame" by the second day. Revisit once/if SDP adds round-level LPGA data.
    "lpga":          96.0,
    "nascar-cup-series":       3.5,
    "nascar-xfinity-series":   3.0,
    "nascar-craftsman-trucks": 2.5,
    # Soccer — standard ~2 hour broadcast (90 min + halftime + stoppage) across
    # every league here; no per-league variation known, same estimate as MLS.
    "premier-league": 2.25, "championship": 2.25, "efl-league-one": 2.25,
    "efl-league-two": 2.25, "carabao-cup": 2.25, "community-shield": 2.25,
    "la-liga": 2.25, "laliga": 2.25, "laliga-2": 2.25, "bundesliga": 2.25,
    "3-liga": 2.25, "ligue-1": 2.25, "serie-a": 2.25, "liga-portugal": 2.25,
    "eredivisie": 2.25, "super-lig": 2.25, "scottish-premiership": 2.25,
    "liga-mx": 2.25, "usl-championship": 2.25, "usl-league-one": 2.25,
    "leagues-cup": 2.25, "nwsl": 2.25, "northern-super-league": 2.25,
    "j1-league": 2.25, "brasileirao": 2.25, "copa-libertadores": 2.25,
    "copa-sudamericana": 2.25, "arg-primera": 2.25, "ncaaw-soccer": 2.25,
    "ncaam-soccer": 2.25, "big-ten-soccer-w": 2.25, "big-ten-soccer-m": 2.25,
    "world-cup": 2.25, "champions-league": 2.25, "ucl-qualifying": 2.25,
    "uecl-qualifying": 2.25, "uel-qualifying": 2.25,
    "mens-international-friendly": 2.25, "usl-cup": 2.25,
    # Baseball — same estimate as MLB.
    "ncaa-baseball": 3.25, "alb": 3.25, "wpbl": 3.25, "jlb": 3.25,
    "interlb": 3.25, "little-league-baseball": 2.0, "necb": 3.25, "slbase": 3.25,
    # Softball — shorter than baseball (7 innings standard vs 9, no fixed real
    # figure researched, this is a reasonable estimate not a confirmed one).
    "ausl": 2.5, "hssoft": 2.0, "jlsoft": 2.5, "little-league-softball": 2.0,
    "ncaa-softball": 2.5, "slsoft": 2.5,
    # Volleyball
    "ncaa-volleyball": 2.0, "ncaa-womens-volleyball": 2.0, "big-ten-volleyball-w": 2.0,
    "ncaam": 2.5, "ncaaw-basketball": 2.5, "nznbl": 2.5,
    "wnba": 2.5,
    "afl": 2.5,
    "pll": 2.0, "bhslax": 2.0, "ghslax": 2.0, "wll": 2.0,
    "big-ten-field-hockey": 2.0,
    "ncaaf": 3.5,
    "nfl-flag": 1.5,
    "ufl": 3.5,
    # UFC/boxing/MMA/darts: SDP has both whole-card summary rows (empty away
    # side, ignored by the matchup matcher) and individual-bout rows (real
    # competitor names). This is a rough single-bout broadcast-slot estimate, not
    # a researched figure — actual bout length varies enormously, so this is
    # sized for the surrounding broadcast window, not the bout itself.
    "ufc": 1.0, "most-valuable-promotions": 1.0, "pfl": 1.0, "legacy-alliance": 1.0,
    "pdc": 1.0,
    "cwten": 2.0,
    # F1 and World Surf League are single rows per race weekend / contest window,
    # not per-session — same tournament-level shape as LPGA, sized the same way
    # (span the whole weekend/window rather than one session). World Surf League's
    # duration is a rough guess given only ever seeing 1 event in the feed.
    "f1": 72.0,
    "world-surf-league": 120.0,
    # Sport Fishing Championship already has day-level granularity in its own
    # title ("Texas Billfish Open (Day 1)"), unlike LPGA/F1/WSL — treat like a
    # normal single-day broadcast block, not a multi-day span.
    "sport-fishing-championship": 8.0,
    # College golf — no live data to size against; assumed similar shape to LPGA
    # (tournament-level, not per-round) since these are lower-volume niche feeds.
    "cwgol": 96.0, "wagc": 96.0,
}

# "matchup" = existing away/home two-sided parsing (team sports + tennis singles/
# doubles). "single_title" = one descriptive broadcast-feed title with no fixed
# two-sided structure at all (golf, NASCAR, F1, surfing, fishing) — SDP puts the
# whole thing in home_team_name and leaves away_team_name empty. Any slug not
# listed here is assumed "matchup" (keeps the original 6 team sports behaving
# exactly as before).
_SPORT_MATCH_MODE = {
    "pga":                     "single_title",
    "lpga":                    "single_title",
    "nascar-cup-series":       "single_title",
    "nascar-xfinity-series":   "single_title",
    "nascar-craftsman-trucks": "single_title",
    "f1":                          "single_title",
    "world-surf-league":           "single_title",
    "sport-fishing-championship":  "single_title",
    "cwgol": "single_title",
    "wagc":  "single_title",
}

# Sports where each side of a "matchup" is one person, not a team — gets
# _person_name_score (tries the "Last, First" -> "First Last" flip) instead of
# the plain team-name matcher. Same treatment as tennis for the same reason:
# boxing/MMA/darts are always exactly 2 individual competitors, never 2 teams.
_PERSON_VS_PERSON_SPORTS = {"atp", "wta", "ufc", "most-valuable-promotions",
                            "pfl", "legacy-alliance", "pdc", "cwten"}

# Sports whose raw auto-created channel names carry provider-specific noise
# (numbered feed prefixes, trailing date/time suffixes, channel-number tags) that
# needs stripping before matchup/title parsing. Scoped to every sport added after
# the original 6 team sports — those 6 keep their exact original behavior (their
# Rename Rules step already handles this for them, and there's no reason to risk
# any regression on an already-shipped path); everything added since is new/
# unproven anyway, so there's no downside to stripping consistently.
_NOISE_STRIP_SPORTS = set(_SPORT_TEMPLATES) - {"nfl", "nba", "mlb", "nhl", "ncaa-football", "mls"}

# ── Provider-noise stripping (golf/NASCAR/tennis auto-sync channel names) ──
# Heuristic on purpose — real provider channel-naming conventions are wildly
# inconsistent (see docs/SPORT_TEMPLATES.md for real examples this was built and
# tested against). This strips the common shapes seen in practice; new provider
# formats may need new patterns added here over time.
_LEADING_FEED_TAG_RE = re.compile(
    r'^(?:\(?[A-Z]{2,3}\)?\s+)?'                       # optional country code: "US ", "(CA) "
    r'(?:'
    r'\([A-Za-z0-9+.\s]{2,24}\d{1,3}\)\s*[|:]\s*'      # "(ESPN+ 001) |"
    r'|[A-Za-z0-9+.\s]{2,24}\d{1,3}\s*[|:]\s*'         # "ESPN+ 04:", "Kayo AU 01:", "TSN+ 01:"
    r')+',
    re.IGNORECASE,
)
_MONTHS_RE_FRAG = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
_TRAILING_AT_DATE_RE = re.compile(
    rf'\s+@\s+(?:\d{{1,2}}\s+)?{_MONTHS_RE_FRAG}\s+\d{{1,2}}\b.*$', re.IGNORECASE,
)
_TRAILING_ISO_DT_RE = re.compile(r'\s*\(\d{4}-\d{2}-\d{2}[^)]*\)\s*$')
_TRAILING_CHANNEL_TAG_RE = re.compile(r'\s*:\s*[A-Za-z][A-Za-z ]{1,20}\d{1,4}\s*$')
# "TSN+ | Event 1 | 7:45AM PGA TOUR Live: ..." -- no digit before the first "|" so
# _LEADING_FEED_TAG_RE doesn't catch it; handled as its own pipe-delimited shape.
_LEADING_PIPE_EVENT_RE = re.compile(
    r'^[A-Za-z0-9+]{2,10}\s*\|\s*Event\s*\d+\s*\|\s*\d{1,2}(?::\d{2})?(?:AM|PM)\s+', re.IGNORECASE,
)

# Golf/NASCAR single-title scoring: words too generic to identify *which event
# this is* (shared across nearly every broadcast in the sport) — excluded from
# the identity-overlap gate so they can't paper over a genuinely different event.
_SINGLE_TITLE_STOPWORDS = {
    "the", "a", "an", "of", "and", "live", "main", "feed", "tour", "tv", "plus",
    "presented", "by", "pga", "on", "at", "featured", "feat",
}
_IDENTITY_EXTRA_STOPWORDS = {
    "championship", "open", "classic", "invitational", "tournament", "round",
    "first", "second", "third", "fourth", "final", "group", "groups",
    "marquee", "hole", "holes",
    "golf", "lpga", "uspga", "uslpga", "elpga",
}
_ROUND_WORDS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "final": 99,
}
_ROUND_NUM_RE = re.compile(r'\bround\s*(\d)\b', re.IGNORECASE)
_ROUND_DIGIT_RE = re.compile(r'\bround\s*\d\b', re.IGNORECASE)

# Per-mode starter templates. Team sports (and tennis, which reuses the same
# away/home matching path) get away/home-shaped defaults; golf/NASCAR have no
# away/home split at all, so their defaults are built around {event_title}.
_MATCHUP_DEFAULTS = {
    "channel_name": "{away_team_pascal} @ {home_team_pascal}",
    "logo_url": "{gamethumbs_base}/{league_slug}/{away_team}/{home_team}/logo?style=1",
    "pre_title": "{away_team_pascal} @ {home_team_pascal} - Pregame",
    "pre_desc": "{start_day}, {start_date} at {start_time_et_ct}{broadcast_line}{venue_line}",
    "live_title": "{away_team_pascal} @ {home_team_pascal}",
    "live_desc": "Live: {away_team_pascal} at {home_team_pascal}{broadcast_line}{venue_line}",
    "post_title": "{away_team_pascal} @ {home_team_pascal} - Final",
    "post_desc": "{score_line}{venue_line}",
}
_PERSON_VS_DEFAULTS = {
    "channel_name": "{away_team_pascal} vs {home_team_pascal}",
    "logo_url": "{gamethumbs_base}/{league_slug}/{away_team}/{home_team}/logo?style=1",
    "pre_title": "{away_team_pascal} vs {home_team_pascal} - Pregame",
    "pre_desc": "{start_day}, {start_date} at {start_time_et_ct}{broadcast_line}{venue_line}",
    "live_title": "{away_team_pascal} vs {home_team_pascal}",
    "live_desc": "Live: {away_team_pascal} vs {home_team_pascal}{broadcast_line}{venue_line}",
    "post_title": "{away_team_pascal} vs {home_team_pascal} - Final",
    "post_desc": "{score_line}{venue_line}",
}
_TENNIS_DEFAULTS = {
    "channel_name": "{away_team_pascal} vs {home_team_pascal}",
    "logo_url": "",
    "pre_title": "{away_team_pascal} vs {home_team_pascal} - {round_name}",
    "pre_desc": "{tournament_name}{court_line}, {start_day} {start_date} at {start_time_et_ct}{broadcast_line}",
    "live_title": "{away_team_pascal} vs {home_team_pascal}",
    "live_desc": "Live: {tournament_name} {round_name}{court_line}{broadcast_line}",
    "post_title": "{away_team_pascal} vs {home_team_pascal} - Final",
    "post_desc": "{result}{court_line}",
}
_SINGLE_TITLE_DEFAULTS = {
    "channel_name": "{event_title}",
    "logo_url": "",
    "pre_title": "{event_title} - Pregame",
    "pre_desc": "{start_day}, {start_date} at {start_time_et_ct}{broadcast_line}{venue_line}",
    "live_title": "{event_title}",
    "live_desc": "Live: {event_title}{broadcast_line}{venue_line}",
    "post_title": "{event_title} - Final",
    "post_desc": "{score_line}{venue_line}",
}

_RULE_FORMAT_HELP = (
    "One rule per line. Lines starting with # are comments.\n"
    "Formats:\n"
    "  regex::PATTERN::REPLACEMENT\n"
    "  replace::FIND::REPLACEMENT\n"
    "Leave REPLACEMENT empty to strip the match.\n"
    "Use $1 $2 in REPLACEMENT to insert capture groups.\n"
    "To add text: regex::$:: (New)  or  regex::^::PREFIX: \n"
    "Examples:\n"
    "  regex::S\\d+E\\d+\\s*::\n"
    "  replace::[HD]::\n"
    "  regex::^(.+)$::$1 [HD]\n"
    "  regex::$:: (New)"
)


class Plugin:
    name = "EPGeditARR"
    version = "0.3.01"
    description = (
        "Transform EPG program data into virtual EPG sources using "
        "per-source, per-field regex and find/replace rules. "
        "Also generates fill EPG schedules for channels with no EPG data, "
        "and includes a Sports Editor that auto-renames channels created by "
        "Dispatcharr's Auto Channel Sync."
    )

    def __init__(self):
        self._signal_uid = "epgeditarr_transform"
        self._m3u_signal_uid = "epgeditarr_sports_editor"
        self.fields = self._build_fields()
        LOGGER.info("EPGeditARR: initialized")
        self._connect_signal()
        self._connect_m3u_signal()

    # ── Dynamic field generation ──────────────────────────────────────────
    # Fields are built from the live DB so every user sees their own EPG
    # sources as toggles — no hardcoded names required.

    _channel_scope_fields = [
        {
            "id": "_section_channels",
            "label": "Channel Scope",
            "type": "info",
            "description": (
                "Controls which channels get reassigned to each virtual EPG "
                "during Setup. Leave both group fields empty to reassign all "
                "channels currently mapped to that source."
            ),
        },
        {
            "id": "auto_reassign",
            "label": "Auto-Reassign Channels on Setup",
            "type": "boolean",
            "default": True,
            "help_text": (
                "When ON, channels mapped to each enabled source are "
                "automatically moved to its virtual EPG when Setup runs."
            ),
        },
        {
            "id": "include_groups",
            "label": "Include Channel Groups",
            "type": "text",
            "default": "",
            "placeholder": "e.g. Sports, News, Movies",
            "help_text": (
                "Comma-separated group names. Only channels in these groups "
                "will be reassigned. Leave empty to include all groups."
            ),
        },
        {
            "id": "exclude_groups",
            "label": "Exclude Channel Groups",
            "type": "text",
            "default": "",
            "placeholder": "e.g. PPV, Adult",
            "help_text": "Comma-separated group names to skip. Applied after Include Groups.",
        },
    ]

    _fill_fields = [
        {
            "id": "_section_fill",
            "label": "EPG Fill",
            "type": "info",
            "description": (
                "Generate a repeating placeholder EPG schedule for channels that have no EPG data. "
                "Use 'Scan' to discover which channels need filling, then set Fill Groups "
                "and optionally add channel names to Skip Channels."
            ),
        },
        {
            "id": "fill_groups",
            "label": "Fill Groups",
            "type": "text",
            "default": "",
            "placeholder": "e.g. Radio, Local",
            "help_text": (
                "Comma-separated channel group names. Channels in these groups "
                "with no EPG will get a generated schedule. Leave empty to disable."
            ),
        },
        {
            "id": "fill_skip_channels",
            "label": "Skip Channels",
            "type": "text",
            "default": "",
            "placeholder": "Sports 969\nSports 970\nSports 971",
            "help_text": (
                "One channel name per line. These channels are excluded from Fill EPG "
                "even if they are in a Fill Group. Copy names from Scan output."
            ),
        },
        {
            "id": "_section_schedule",
            "label": "── Schedule Settings ───────────────────────────",
            "type": "info",
            "description": "Block Duration and Days Ahead used to generate the Fill EPG schedule.",
        },
        {
            "id": "fill_block_hours",
            "label": "Block Duration",
            "type": "select",
            "options": [
                {"value": "1",  "label": "1 hour"},
                {"value": "2",  "label": "2 hours"},
                {"value": "4",  "label": "4 hours"},
                {"value": "6",  "label": "6 hours"},
                {"value": "12", "label": "12 hours"},
                {"value": "24", "label": "24 hours"},
            ],
            "default": "1",
            "help_text": "Duration of each generated program block.",
        },
        {
            "id": "fill_days_ahead",
            "label": "Days Ahead",
            "type": "select",
            "options": [
                {"value": "7",  "label": "7 days"},
                {"value": "14", "label": "14 days"},
                {"value": "30", "label": "30 days"},
            ],
            "default": "14",
            "help_text": "How many days of schedule to generate ahead.",
        },
    ]

    def _build_sports_editor_fields(self):
        """One Sports Editor section per Dispatcharr channel group, each with its own
        independent enable toggle and rename rule set — mirrors the per-EPGSource
        section pattern above, but keyed by ChannelGroup id instead of EPGSource id.
        """
        from apps.channels.models import ChannelGroup, Channel
        groups = []
        try:
            # ChannelGroup includes every raw group name Dispatcharr has ever seen from
            # M3U/XC providers (often 1000+), most with zero actual channels assigned.
            # Only show groups that have at least one real Channel — that's the set a
            # user could plausibly want Sports Editor rules for.
            group_ids_with_channels = Channel.objects.values_list("channel_group_id", flat=True).distinct()
            groups = list(ChannelGroup.objects.filter(id__in=group_ids_with_channels).order_by("name"))
        except Exception as e:
            LOGGER.debug(f"EPGeditARR: could not load channel groups for field generation: {e}")

        fields = [
            {
                "id": "_section_sports_editor",
                "label": "══════════════ SPORTS EDITOR ══════════════",
                "type": "info",
                "description": (
                    "Automatically renames channels that Dispatcharr's Auto Channel Sync just "
                    "created, using a dedicated rule set per channel group below (separate from "
                    "the EPG Sources rules above — each group's rules are independent of every "
                    "other group's). Runs automatically right after each successful M3U refresh — "
                    "no manual step needed. Only touches auto-created channels, so it never "
                    "renames manually-added channels.\n\n"
                    + _RULE_FORMAT_HELP
                ),
            },
        ]

        for group in groups:
            gid = group.id
            fields += [
                {
                    "id": f"_section_sports_editor_{gid}",
                    "label": group.name,
                    "type": "info",
                    "description": (
                        f"Enable to rename auto-created channels in '{group.name}' using the "
                        f"rules below. This group's rules only apply to this group."
                    ),
                },
                {
                    "id": f"sports_editor_{gid}_enabled",
                    "label": "Enable Sports Editor for this group",
                    "type": "boolean",
                    "default": False,
                    "help_text": f"Rename auto-created channels in '{group.name}'.",
                },
                {
                    "id": f"sports_editor_{gid}_sport",
                    "label": "Sport Template",
                    "type": "select",
                    "default": "none",
                    "options": (
                        [{"value": "none", "label": "(none — regex rules only)"}]
                        + [{"value": k, "label": v} for k, v in _SPORT_TEMPLATES.items()]
                    ),
                    "help_text": (
                        "When set, auto-created channels are matched against live schedule data "
                        "(sports-data-platform) and renamed/EPG-generated from that sport's "
                        "templates (configured further down). When a channel can't be matched to "
                        "a real game, the Rename Rules below still apply as a fallback."
                    ),
                },
                {
                    "id": f"sports_editor_{gid}_rename_rules",
                    "label": "Sports Channel Rename Rules",
                    "type": "text",
                    "default": "",
                    "placeholder": "regex::^NFL Game Pass \\d+:\\s*::NFL: ",
                    "help_text": "Rules applied to auto-created channel names in this group. One per line. Used as a fallback when no Sport Template match is found (or always, if no Sport Template is selected).",
                },
            ]

        if not groups:
            fields.append({
                "id": "_section_sports_editor_none",
                "label": "No channel groups found",
                "type": "info",
                "description": (
                    "No channel groups exist yet in Dispatcharr. Create a channel group (or let "
                    "Auto Channel Sync create one), then reload this page to configure the "
                    "Sports Editor for it."
                ),
            })

        fields.append({
            "id": "sports_editor_gamethumbs_url",
            "label": "Game Thumbs Base URL",
            "type": "text",
            "default": "https://game-thumbs.tickarr.com",
            "placeholder": "https://game-thumbs.tickarr.com",
            "help_text": (
                "Base URL of a sethwv/game-thumbs instance (https://github.com/sethwv/game-thumbs), "
                "used for matchup thumbnail/logo generation. Defaults to a publicly hosted instance — "
                "point this at your own self-hosted instance instead if you run one."
            ),
        })

        return fields

    # Template variable placeholders offered for every Sport Template field —
    # kept as one shared help string so every field's help_text stays consistent.
    _SPORT_TEMPLATE_VAR_HELP = (
        "Variables: {away_team} {home_team} {away_team_pascal} {home_team_pascal} "
        "{start_short} {start_day} {start_date} {start_time_et_ct} "
        "{start_short_utc} {start_day_utc} {start_date_utc} {start_time_utc} {game_number_suffix} "
        "{broadcast} {broadcast_line} {venue} {venue_line} {winner} {loser} {score_line} "
        "{league} {league_slug} {gamethumbs_base} {phase}\n"
        "Tennis (ATP/WTA) also has: {tournament_name} {round_name} {court} {court_line} "
        "{result} {result_line} (away/home vars above are the two players).\n"
        "Golf/NASCAR (single-broadcast sports with no away/home split) use "
        "{event_title} instead of away/home team vars, plus {tournament_name} where available."
    )

    @staticmethod
    def _sport_default_templates(slug):
        if slug in ("atp", "wta"):
            return _TENNIS_DEFAULTS
        if slug in _PERSON_VS_PERSON_SPORTS:
            return _PERSON_VS_DEFAULTS
        if _SPORT_MATCH_MODE.get(slug) == "single_title":
            return _SINGLE_TITLE_DEFAULTS
        return _MATCHUP_DEFAULTS

    def _build_sport_template_fields(self):
        """One section per sport in _SPORT_TEMPLATES, each defining the Channel Name /
        Logo URL / Pregame / Live / Postgame title+description templates used to render
        real EPG data once a channel group's auto-created channel is matched to a live
        game from sports-data-platform. A channel group opts into a sport via its own
        'Sport Template' dropdown (see _build_sports_editor_fields above); the templates
        themselves are defined once per sport here, not per group.
        """
        fields = [
            {
                "id": "_section_sport_templates",
                "label": "══════════════ SPORT TEMPLATES ══════════════",
                "type": "info",
                "description": (
                    "Define how each sport's channels, logos, and EPG titles/descriptions "
                    "are generated from live schedule data (sports-data-platform, "
                    "api.tickarr.com). A channel group picks one of these sports from its "
                    "'Sport Template' dropdown above to use it.\n\n" + self._SPORT_TEMPLATE_VAR_HELP
                ),
            },
        ]

        for slug, label in _SPORT_TEMPLATES.items():
            defaults = self._sport_default_templates(slug)
            fields += [
                {
                    "id": f"_section_sport_template_{slug}",
                    "label": label,
                    "type": "info",
                    "description": f"Templates used for channel groups with Sport Template set to '{label}'.",
                },
                {
                    "id": f"sport_tpl_{slug}_channel_name",
                    "label": "Channel Name",
                    "type": "text",
                    "default": defaults["channel_name"],
                    "help_text": "Renames the auto-created channel when matched to a game. " + self._SPORT_TEMPLATE_VAR_HELP,
                },
                {
                    "id": f"sport_tpl_{slug}_logo_url",
                    "label": "Logo URL",
                    "type": "text",
                    "default": defaults["logo_url"],
                    "help_text": "Assigned as the channel's logo when matched.",
                },
                {
                    "id": f"sport_tpl_{slug}_pre_title",
                    "label": "Pregame Title",
                    "type": "text",
                    "default": defaults["pre_title"],
                },
                {
                    "id": f"sport_tpl_{slug}_pre_desc",
                    "label": "Pregame Description",
                    "type": "text",
                    "default": defaults["pre_desc"],
                },
                {
                    "id": f"sport_tpl_{slug}_live_title",
                    "label": "Live Title",
                    "type": "text",
                    "default": defaults["live_title"],
                },
                {
                    "id": f"sport_tpl_{slug}_live_desc",
                    "label": "Live Description",
                    "type": "text",
                    "default": defaults["live_desc"],
                },
                {
                    "id": f"sport_tpl_{slug}_post_title",
                    "label": "Postgame Title",
                    "type": "text",
                    "default": defaults["post_title"],
                },
                {
                    "id": f"sport_tpl_{slug}_post_desc",
                    "label": "Postgame Description",
                    "type": "text",
                    "default": defaults["post_desc"],
                },
            ]

        return fields

    # Regex patterns used by _action_sample — one section per category shown
    _SAMPLE_PATTERNS = {
        "episode":   r"S\d+E\d+|\bE\d{2,3}\b|\b\d+x\d+\b",
        "broadcast": r"\((New|Live|Rerun|Re-run|Repeat|Encore|Premiere|Finale|Special)\)|\[LIVE\]",
        "quality":   r"\[(HD|4K|UHD|FHD|SD|HDR)\]",
        "technical": r"\((CC|SAP|DVS|Stereo|Widescreen|Subtitled)\)",
        "year":      r"\((19|20)\d{2}\)",
        "gracenote": r"\(INFO\)|\(Censored\)|\[as\]",
        "unicode":   r"ᴺᵉʷ|ᴸᶦᵛᵉ|ᴾʳᵉ|ᴿᵉᵖ|ᴵⁿᶠᵒ|ᴼᵛᵉʳ",
        "any":       r"[\(\[]",
    }

    def _build_fields(self):
        sources = []
        try:
            from apps.epg.models import EPGSource
            sources = list(EPGSource.objects.exclude(name__startswith=VIRTUAL_PREFIX).order_by("name"))
        except Exception as e:
            LOGGER.debug(f"EPGeditARR: could not load sources for field generation: {e}")

        # ── Source rule sections ──
        fields = [
            {
                "id": "_section_sources",
                "label": "EPG Sources",
                "type": "info",
                "description": (
                    "Each non-dummy EPG source configured in Dispatcharr appears "
                    "below as its own section. Enable the sources you want to "
                    "transform and add rules for each field you want to modify.\n\n"
                    + _RULE_FORMAT_HELP
                ),
            }
        ]
        if sources:
            for source in sources:
                sid = source.id
                fields += [
                    {
                        "id": f"_section_src_{sid}",
                        "label": source.name,
                        "type": "info",
                        "description": (
                            f"Virtual EPG will be named '{VIRTUAL_PREFIX}{source.name}'. "
                            f"Enable the toggle below to activate transformation for this source."
                        ),
                    },
                    {
                        "id": f"src_{sid}_enabled",
                        "label": "Enable transformation",
                        "type": "boolean",
                        "default": False,
                        "help_text": (
                            f"Create and keep a virtual transformed copy of "
                            f"'{source.name}' in sync after each refresh."
                        ),
                    },
                    {
                        "id": f"src_{sid}_title_rules",
                        "label": "Title Rules",
                        "type": "text",
                        "default": "",
                        "placeholder": "regex::S\\d+E\\d+\\s*::\nreplace::[HD]::",
                        "help_text": "Rules applied to the program title. One per line.",
                    },
                    {
                        "id": f"src_{sid}_subtitle_rules",
                        "label": "Sub-Title Rules",
                        "type": "text",
                        "default": "",
                        "placeholder": "replace::(New)::",
                        "help_text": "Rules applied to the episode sub-title. One per line.",
                    },
                    {
                        "id": f"src_{sid}_description_rules",
                        "label": "Description Rules",
                        "type": "text",
                        "default": "",
                        "placeholder": "regex::^\\[.*?\\]\\s*::",
                        "help_text": "Rules applied to the program description. One per line.",
                    },
                    {
                        "id": f"src_{sid}_force_category",
                        "label": "Force Category (Series Mode)",
                        "type": "text",
                        "default": "",
                        "placeholder": "Series",
                        "help_text": (
                            "Adds an XMLTV <category> tag to every program on this source's virtual "
                            "copy. Setting this to 'Series' tells Plex to treat repeating programs "
                            "that share a title as episodes of a show instead of duplicate movies, "
                            "so DVR can record more than one. Comma-separated for multiple "
                            "categories. Leave blank to disable."
                        ),
                    },
                    {
                        "id": f"src_{sid}_synth_episode_num",
                        "label": "Synthesize Episode Numbers From Air Date",
                        "type": "boolean",
                        "default": False,
                        "help_text": (
                            "Adds a unique <episode-num system=\"xmltv_ns\"> tag per program, derived "
                            "from its air date (year + day-of-year), so Plex sees each airing as a "
                            "distinct episode instead of collapsing same-titled programs into one "
                            "recordable movie. Pair with Force Category above."
                        ),
                    },
                ]
        else:
            fields.append({
                "id": "_no_sources_info",
                "label": "Sources unavailable",
                "type": "info",
                "description": (
                    "EPG sources could not be loaded from the database. "
                    "Ensure sources are configured in M3U & EPG Manager, "
                    "then reload the plugin."
                ),
            })

        # ── Rule Tester (dynamic: source dropdown built from live DB) ──
        source_options = [{"value": str(s.id), "label": s.name} for s in sources]
        default_source = str(sources[0].id) if sources else ""

        tester_fields = [
            {
                "id": "_section_tester",
                "label": "Rule Tester",
                "type": "info",
                "description": (
                    "Test a rule against live data from any source before adding it to the rules list. "
                    "Select a source and field, enter a pattern, then click 'Test Rule'. "
                    "A diverse sample of real values will be pulled automatically — "
                    "or paste your own text into 'Test Text' to test against that instead."
                ),
            },
            {
                "id": "test_source_id",
                "label": "Test Source",
                "type": "select",
                "options": source_options,
                "default": default_source,
                "help_text": "Which EPG source to pull live test data from.",
            },
            {
                "id": "test_field",
                "label": "Test Field",
                "type": "select",
                "options": [
                    {"value": "title", "label": "Title"},
                    {"value": "sub_title", "label": "Sub-Title"},
                    {"value": "description", "label": "Description"},
                ],
                "default": "title",
                "help_text": "Which program field to test the rule against.",
            },
            {
                "id": "test_type",
                "label": "Use Regex (OFF = literal find/replace)",
                "type": "boolean",
                "default": True,
                "help_text": "ON = regex pattern, OFF = literal text find/replace.",
            },
            {
                "id": "test_pattern",
                "label": "Pattern / Find",
                "type": "text",
                "default": "",
                "placeholder": "e.g. S\\d+E\\d+\\s*",
                "help_text": "The regex pattern or literal text to find.",
            },
            {
                "id": "test_replacement",
                "label": "Replacement",
                "type": "text",
                "default": "",
                "placeholder": "Leave empty to strip the match",
                "help_text": "What to replace the match with. Leave empty to remove it entirely.",
            },
            {
                "id": "test_input",
                "label": "Test Text (optional)",
                "type": "text",
                "default": "",
                "placeholder": "Leave empty to use live source data automatically",
                "help_text": (
                    "Optional. Paste specific text to test against. "
                    "If empty, real values are sampled automatically from the selected source and field."
                ),
            },
        ]

        return (
            fields
            + self._channel_scope_fields
            + self._fill_fields
            + self._build_sports_editor_fields()
            + self._build_sport_template_fields()
            + tester_fields
        )

    # ── Signal management ─────────────────────────────────────────────────
    # One signal watches all EPGSources. On each successful refresh it reads
    # current settings from the DB (so rule changes take effect immediately
    # without re-running Setup) and transforms the matching source.

    def _connect_signal(self):
        from apps.epg.models import EPGSource
        from django.db.models.signals import post_save

        def _on_epg_refresh(sender, instance, **kwargs):
            if instance.source_type == "dummy" or instance.name.startswith(VIRTUAL_PREFIX):
                return
            update_fields = kwargs.get("update_fields")
            status_saved = update_fields is None or "status" in (update_fields or [])
            if not status_saved or instance.status != "success":
                return
            try:
                from apps.plugins.models import PluginConfig
                cfg = PluginConfig.objects.filter(key=PLUGIN_KEY, enabled=True).first()
                if not cfg:
                    return
                settings = cfg.settings
            except Exception as e:
                LOGGER.debug(f"EPGeditARR: signal could not read settings: {e}")
                return

            if settings.get(f"src_{instance.id}_enabled", False):
                LOGGER.info(f"EPGeditARR: '{instance.name}' refreshed — transforming")
                try:
                    self._do_transform_source(instance, settings)
                except Exception as e:
                    LOGGER.error(f"EPGeditARR: transform failed for '{instance.name}': {e}")

            if settings.get("fill_groups", "").strip():
                LOGGER.info(f"EPGeditARR: running Fill EPG after '{instance.name}' refresh")
                try:
                    self._action_fill_epg(settings, LOGGER)
                except Exception as e:
                    LOGGER.error(f"EPGeditARR: auto Fill EPG failed: {e}")

        post_save.connect(
            _on_epg_refresh,
            sender=EPGSource,
            weak=False,
            dispatch_uid=self._signal_uid,
        )
        LOGGER.info("EPGeditARR: refresh signal connected")

    def _disconnect_signal(self):
        from apps.epg.models import EPGSource
        from django.db.models.signals import post_save
        post_save.disconnect(sender=EPGSource, dispatch_uid=self._signal_uid)
        LOGGER.info("EPGeditARR: signal disconnected")

    # One signal watches M3UAccount. Auto Channel Sync (Dispatcharr core) already
    # runs and finishes by the time the account's status flips to "success", so
    # this fires the Sports Editor rename pass right after auto-created channels
    # exist — no dependency on Dispatcharr's newer per-action "events" hooks.
    def _connect_m3u_signal(self):
        from apps.m3u.models import M3UAccount
        from django.db.models.signals import post_save

        def _on_m3u_refresh(sender, instance, **kwargs):
            update_fields = kwargs.get("update_fields")
            status_saved = update_fields is None or "status" in (update_fields or [])
            if not status_saved or instance.status != "success":
                return
            try:
                from apps.plugins.models import PluginConfig
                cfg = PluginConfig.objects.filter(key=PLUGIN_KEY, enabled=True).first()
                if not cfg:
                    return
                settings = cfg.settings
            except Exception as e:
                LOGGER.debug(f"EPGeditARR: sports editor signal could not read settings: {e}")
                return

            try:
                result = self._run_sports_editor_rename(instance, settings)
                if result.get("renamed"):
                    LOGGER.info(
                        f"EPGeditARR: Sports Editor renamed {result['renamed']} channel(s) "
                        f"after '{instance.name}' refresh"
                    )
            except Exception as e:
                LOGGER.error(f"EPGeditARR: Sports Editor rename failed after '{instance.name}' refresh: {e}")

            try:
                epg_result = self._run_sports_editor_epg(instance, settings)
                if epg_result.get("matched"):
                    LOGGER.info(
                        f"EPGeditARR: Sports Editor generated EPG for {epg_result['matched']} "
                        f"channel(s) after '{instance.name}' refresh"
                    )
            except Exception as e:
                LOGGER.error(f"EPGeditARR: Sports Editor EPG generation failed after '{instance.name}' refresh: {e}")

        post_save.connect(
            _on_m3u_refresh,
            sender=M3UAccount,
            weak=False,
            dispatch_uid=self._m3u_signal_uid,
        )
        LOGGER.info("EPGeditARR: sports editor M3U signal connected")

    def _disconnect_m3u_signal(self):
        from apps.m3u.models import M3UAccount
        from django.db.models.signals import post_save
        post_save.disconnect(sender=M3UAccount, dispatch_uid=self._m3u_signal_uid)
        LOGGER.info("EPGeditARR: sports editor M3U signal disconnected")

    def stop(self, context):
        self._disconnect_signal()
        self._disconnect_m3u_signal()

    # ── Rule engine ───────────────────────────────────────────────────────

    def _parse_rules(self, text):
        rules = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("::")
            if len(parts) < 3:
                LOGGER.warning(f"EPGeditARR: malformed rule skipped: {line!r}")
                continue
            kind, arg1, arg2 = parts[0].strip().lower(), parts[1], parts[2]
            if kind == "regex":
                try:
                    # Convert $1 $2 capture-group syntax → Python's \1 \2
                    replacement = re.sub(r'\$(\d+)', r'\\\1', arg2)
                    rules.append({
                        "type": "regex",
                        "pattern": re.compile(arg1),
                        "replacement": replacement,
                        "raw": arg1,
                    })
                except re.error as e:
                    LOGGER.warning(f"EPGeditARR: bad regex '{arg1}': {e}")
            elif kind in ("replace", "find_replace"):
                rules.append({"type": "replace", "find": arg1, "replacement": arg2})
            else:
                LOGGER.warning(f"EPGeditARR: unknown rule type '{kind}' — skipping")
        return rules

    def _apply_rules(self, value, rules):
        if not value or not rules:
            return value
        for rule in rules:
            if rule["type"] == "regex":
                value = rule["pattern"].sub(rule["replacement"], value)
            else:
                value = value.replace(rule["find"], rule["replacement"])
        return value.strip() if value else value

    # ── Sports Editor ────────────────────────────────────────────────────

    def _enabled_sports_editor_groups(self, settings):
        """Return [(ChannelGroup, rules), ...] for every group with the Sports
        Editor enabled and at least one valid rename rule configured."""
        from apps.channels.models import ChannelGroup
        result = []
        for group in ChannelGroup.objects.all().order_by("name"):
            if not settings.get(f"sports_editor_{group.id}_enabled"):
                continue
            rules = self._parse_rules(settings.get(f"sports_editor_{group.id}_rename_rules", ""))
            if rules:
                result.append((group, rules))
        return result

    def _run_sports_editor_rename(self, m3u_account, settings):
        """Rename auto-created channels in every enabled Sports Editor group.

        Only touches channels Dispatcharr's Auto Channel Sync created for this
        M3U account (auto_created=True, auto_created_by=m3u_account) — manually-added
        channels are never renamed. Each channel group applies only its own rules.
        """
        from apps.channels.models import Channel

        enabled_groups = self._enabled_sports_editor_groups(settings)
        if not enabled_groups:
            return {"renamed": 0, "total_scanned": 0}

        renamed = 0
        scanned = 0
        with transaction.atomic():
            for group, rules in enabled_groups:
                channels = Channel.objects.filter(
                    auto_created=True,
                    auto_created_by=m3u_account,
                    channel_group=group,
                )
                for ch in channels:
                    scanned += 1
                    new_name = self._apply_rules(ch.name, rules)
                    if new_name and new_name != ch.name:
                        ch.name = new_name
                        ch.save(update_fields=["name"])
                        renamed += 1

        return {"renamed": renamed, "total_scanned": scanned}

    def _action_sports_editor_rename_now(self, settings, logger):
        from apps.channels.models import Channel

        enabled_groups = self._enabled_sports_editor_groups(settings)
        if not enabled_groups:
            return {
                "success": False,
                "message": (
                    "No channel groups have the Sports Editor enabled with rename rules "
                    "configured. Enable a channel group's section in Settings → Sports Editor."
                ),
            }

        total_renamed = 0
        total_scanned = 0
        lines = []
        with transaction.atomic():
            for group, rules in enabled_groups:
                channels = list(Channel.objects.filter(auto_created=True, channel_group=group))
                group_renamed = 0
                examples = []
                for ch in channels:
                    new_name = self._apply_rules(ch.name, rules)
                    if new_name and new_name != ch.name:
                        if len(examples) < 5:
                            examples.append(f"  '{ch.name}' -> '{new_name}'")
                        ch.name = new_name
                        ch.save(update_fields=["name"])
                        group_renamed += 1
                total_scanned += len(channels)
                total_renamed += group_renamed
                lines.append(f"{group.name}: scanned {len(channels)}, renamed {group_renamed}")
                lines.extend(examples)

        lines.insert(
            0,
            f"Sports Editor: {total_renamed} renamed across {len(enabled_groups)} "
            f"group(s), {total_scanned} auto-created channel(s) scanned.",
        )
        return {"success": True, "message": "\n".join(lines)}

    # ── Sports Editor: SDP schedule matching + EPG generation ──────────────

    def _save_plugin_setting(self, key, value):
        """Persist a single key into this plugin's PluginConfig.settings blob,
        independent of whatever `settings` dict a caller happens to hold — used
        for cache state (e.g. the fetched SDP schedule) that must survive across
        separate signal/action invocations."""
        try:
            from apps.plugins.models import PluginConfig
            cfg = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
            if not cfg:
                return
            data = dict(cfg.settings or {})
            data[key] = value
            cfg.settings = data
            cfg.save(update_fields=["settings"])
        except Exception as e:
            LOGGER.debug(f"EPGeditARR: could not save plugin setting '{key}': {e}")

    def _fetch_sdp_schedule(self, settings):
        """Fetch the public sports-data-platform schedule feed (api.tickarr.com),
        cached ~30 min in PluginConfig.settings so every M3U refresh doesn't
        re-fetch it. Falls back to a stale cache on fetch failure."""
        import time

        cfg_settings = {}
        try:
            from apps.plugins.models import PluginConfig
            cfg = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
            cfg_settings = cfg.settings or {} if cfg else {}
        except Exception:
            pass

        cached = cfg_settings.get(SDP_CACHE_KEY)
        updated = cfg_settings.get(SDP_CACHE_UPDATED_KEY, 0) or 0
        now = time.time()
        if cached and (now - updated) < SDP_CACHE_TTL_SECS:
            return self._inherit_tournament_names(cached)

        try:
            import requests
            resp = requests.get(SDP_SCHEDULE_URL, timeout=15)
            resp.raise_for_status()
            events = resp.json().get("events", [])
        except Exception as e:
            LOGGER.warning(f"EPGeditARR: SDP schedule fetch failed, using cache if available: {e}")
            return self._inherit_tournament_names(cached or [])

        self._save_plugin_setting(SDP_CACHE_KEY, events)
        self._save_plugin_setting(SDP_CACHE_UPDATED_KEY, now)
        return self._inherit_tournament_names(events)

    @staticmethod
    def _inherit_tournament_names(events):
        """SDP's PGA TOUR ingest (the 'pga' league_slug) puts tournament_name on a
        standalone marker row per tournament (e.g. a 'BMW Championship' row with
        round_name=null) and leaves every actual round/feed row under that
        tournament with tournament_name=null — confirmed directly against the live
        feed. Backfill it forward chronologically per league so every row can be
        matched/rendered as if it carried its own tournament name. Idempotent and
        safe to run on every call: rows that already have tournament_name (every
        other sport) are left untouched."""
        from datetime import datetime, timezone

        def _sort_key(ev):
            try:
                return datetime.fromisoformat((ev.get("start_time_utc") or "").replace("Z", "+00:00"))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)

        by_league = {}
        for ev in events:
            by_league.setdefault(ev.get("league_slug"), []).append(ev)
        for league_events in by_league.values():
            current = None
            for ev in sorted(league_events, key=_sort_key):
                if ev.get("tournament_name"):
                    current = ev["tournament_name"]
                elif current:
                    ev["tournament_name"] = current
        return events

    @staticmethod
    def _strip_provider_noise(name):
        """Clean provider-specific noise (numbered feed prefixes, trailing date/
        time suffixes, channel-number tags) off a raw auto-sync channel name before
        matchup/title parsing. Only called for the sports in _NOISE_STRIP_SPORTS —
        see docs/SPORT_TEMPLATES.md for the real provider formats this was built
        and tested against."""
        s = (name or "").strip()
        s = _LEADING_PIPE_EVENT_RE.sub("", s).strip()
        s = _LEADING_FEED_TAG_RE.sub("", s).strip()
        s = _TRAILING_AT_DATE_RE.sub("", s).strip()
        s = _TRAILING_ISO_DT_RE.sub("", s).strip()
        s = _TRAILING_CHANNEL_TAG_RE.sub("", s).strip()
        return s

    def _extract_matchup_teams(self, channel_name, strip_noise=False):
        """Split a channel name like 'Kansas City Chiefs @ Buffalo Bills' (already
        renamed by the group's regex rules, if any) into (away, home) text."""
        text = channel_name or ""
        if strip_noise:
            text = self._strip_provider_noise(text)
        parts = _MATCHUP_SEP_RE.split(text.strip(), maxsplit=1)
        if len(parts) != 2:
            return None
        away, home = parts[0].strip(), parts[1].strip()
        if not away or not home:
            return None
        return away, home

    @staticmethod
    def _team_match_score(text, *candidates):
        import difflib
        text_l = (text or "").lower().strip()
        if not text_l:
            return 0.0
        best = 0.0
        for cand in candidates:
            cand_l = (cand or "").lower().strip()
            if not cand_l:
                continue
            if cand_l == text_l:
                return 1.0
            if cand_l in text_l or text_l in cand_l:
                best = max(best, 0.85)
            best = max(best, difflib.SequenceMatcher(None, text_l, cand_l).ratio())
        return best

    @classmethod
    def _person_name_score(cls, text, *candidates):
        """Like _team_match_score, but also tries the 'Last, First' -> 'First
        Last' flip that tennis providers use (SDP's player names are 'First
        Last'). Doubles pairs ('Arevalo M, Pavic M') don't cleanly flip into a
        single name either way, so they'll score low on both variants and
        correctly fail to match a singles row rather than false-positive —
        doubles disambiguation isn't supported."""
        variants = {text or ""}
        if text and ',' in text:
            parts = [p.strip() for p in text.split(',', 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                variants.add(f"{parts[1]} {parts[0]}")
        return max(cls._team_match_score(v, *candidates) for v in variants)

    def _find_sdp_event(self, away_text, home_text, league_slug, events, score_fn=None):
        """Best-match a channel's parsed away/home team text against cached SDP
        events for the given league, within a sensible time window. Returns the
        event dict, or None if nothing scores well enough to be confident."""
        from datetime import datetime, timezone, timedelta

        score_fn = score_fn or self._team_match_score
        now = datetime.now(timezone.utc)
        # Past bound is generous — a game that aired earlier today should still
        # resolve so its Postgame template/recap can show. Duration-aware trimming
        # happens later when EPG blocks are built from the matched event's own start time.
        window_start = now - timedelta(hours=20)
        window_end = now + timedelta(days=10)

        best_event, best_score = None, 0.0
        for ev in events:
            if ev.get("league_slug") != league_slug:
                continue
            raw_start = ev.get("start_time_utc")
            if not raw_start:
                continue
            try:
                start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            except ValueError:
                continue
            if start < window_start or start > window_end:
                continue

            ev_away = (ev.get("away_team_name"), ev.get("away_team_abbr"), ev.get("away_team_short_name"))
            ev_home = (ev.get("home_team_name"), ev.get("home_team_abbr"), ev.get("home_team_short_name"))
            # Try both side alignments. Team sports have a real home/away, but
            # SDP's home/away assignment for individual sports (tennis) has no
            # relationship to the order a provider lists "Player1 vs Player2" in —
            # direct-only comparison silently missed every correct match in
            # testing whenever SDP happened to list the two players the other way.
            direct = min(score_fn(away_text, *ev_away), score_fn(home_text, *ev_home))
            swapped = min(score_fn(away_text, *ev_home), score_fn(home_text, *ev_away))
            combined = max(direct, swapped)
            # Require BOTH sides to independently match well — averaging let one
            # strong match mask a completely wrong other team, so use the weaker
            # of the two rather than the mean.
            if combined > best_score:
                best_score, best_event = combined, ev

        return best_event if best_score >= 0.6 else None

    # ── Single-title matching (golf, NASCAR) ────────────────────────────────
    # No away/home split exists for these — SDP puts one descriptive broadcast-
    # feed title in home_team_name and leaves away_team_name empty. Matching is
    # token-overlap + fuzzy-ratio scoring, gated by an "identity" check so generic
    # broadcast vocabulary ("Championship", "Round", "Main Feed") shared by every
    # event in the sport can't paper over a genuinely different tournament/player/
    # round — see docs/SPORT_TEMPLATES.md for the false-positive cases this gate
    # was built to catch during testing.

    @staticmethod
    def _normalize_title_tokens(text):
        text = re.sub(r'[^a-z0-9]+', ' ', (text or '').lower())
        return [t for t in text.split() if t and t not in _SINGLE_TITLE_STOPWORDS]

    @classmethod
    def _identity_tokens(cls, text):
        """Tokens specific enough to identify *which event this is* (sponsor/
        place/player names, hole numbers, distinctive product names like
        BetCast) — as opposed to generic broadcast vocabulary shared by every
        event in the sport."""
        # Length floor lowered from 4 to 3 after real testing against SDP's PGA
        # TOUR data caught a live regression: "BMW Championship" and "TOUR
        # Championship" both reduce to a single 3-letter distinguishing word once
        # generic vocabulary is stripped ("tour" itself is a hardcoded generic
        # stopword) — a 4-char floor silently dropped "BMW" from identity
        # entirely, reopening the exact cross-tournament false-positive class
        # this gate exists to catch.
        text = _ROUND_DIGIT_RE.sub('round', text or '')
        result = set()
        for t in cls._normalize_title_tokens(text):
            if t.isdigit():
                result.add(t)
            elif len(t) >= 3 and t not in _IDENTITY_EXTRA_STOPWORDS:
                result.add(t)
        return result

    @staticmethod
    def _extract_round(text):
        t = (text or "").lower()
        m = _ROUND_NUM_RE.search(t)
        if m:
            return int(m.group(1))
        for word, num in _ROUND_WORDS.items():
            if re.search(rf'\b{word}\b', t):
                return num
        return None

    @classmethod
    def _title_match_score(cls, text, candidate, candidate_round_name=None):
        import difflib
        t_tokens = set(cls._normalize_title_tokens(text))
        c_tokens = set(cls._normalize_title_tokens(candidate))
        if not t_tokens or not c_tokens:
            return 0.0
        # Asymmetric on purpose: a provider that drops the sponsor prefix
        # ("USPGA St Jude Championship" for SDP's "FedEx St. Jude Championship")
        # shouldn't be punished for having FEWER identity words than SDP's title,
        # only for having DIFFERENT ones — score against the shorter side's
        # coverage, not the union.
        t_id, c_id = cls._identity_tokens(text), cls._identity_tokens(candidate)
        identity_score = (len(t_id & c_id) / min(len(t_id), len(c_id))) if (t_id and c_id) else 1.0
        # Jaccard (intersection/union), NOT min-based, for the general token
        # overlap — min-based asymmetry belongs on identity_score only (where a
        # provider legitimately dropping a sponsor prefix shouldn't be punished).
        # Applying it here too let a short, mostly-generic SDP candidate (e.g.
        # "Main Feed" -> just {bmw, championship} once stopwords are stripped)
        # trivially score 1.0 against ANY text sharing those two words, found in
        # testing — a 6-word provider title and a 2-word candidate title are not
        # equally specific just because the shorter one is a subset.
        overlap = len(t_tokens & c_tokens) / len(t_tokens | c_tokens)
        ratio = difflib.SequenceMatcher(None, text.lower(), (candidate or '').lower()).ratio()
        base = max(overlap, ratio)
        r1 = cls._extract_round(text)
        # Prefer SDP's own structured round_name field over parsing it back out of
        # candidate text — PGA TOUR's 'pga' slug rows (e.g. "Marquee Group - R.
        # McIlroy, K. Reitan") often don't have the round written into the title
        # text at all anymore, only in round_name, so text-only parsing would miss
        # it and silently disable this check.
        r2 = cls._extract_round(candidate_round_name) if candidate_round_name else cls._extract_round(candidate)
        round_penalty = 0.3 if (r1 is not None and r2 is not None and r1 != r2) else 1.0
        return base * identity_score * round_penalty

    def _find_sdp_event_single_title(self, title_text, league_slug, events):
        """Best-match a golf/NASCAR channel's cleaned title text against cached
        SDP events for the given league. Providers rename these streams same-day
        (confirmed against real Dispatcharr auto-sync behavior), so the window is
        anchored to *now* and kept tight — unlike the away/home matcher's wide
        multi-day window, a loose window here just invites two similarly-worded
        same-tournament events from different weeks to collide.

        Window width scales with the sport's estimated event duration: PGA TOUR/
        NASCAR (single-round/single-race rows) keep the tight 30h default, but
        LPGA's SDP data is tournament-level only (one row spanning a whole 4-day
        event, not per-round) — a fixed 30h window would lose the match by the
        second day, since the row's start_time is the tournament's start, not a
        same-day marker."""
        from datetime import datetime, timezone, timedelta

        window_hrs = max(30, _LEAGUE_DURATION_HOURS.get(league_slug, 3.0) + 24)
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=window_hrs)
        window_end = now + timedelta(hours=window_hrs)

        best_event, best_score = None, 0.0
        for ev in events:
            if ev.get("league_slug") != league_slug:
                continue
            raw_start = ev.get("start_time_utc")
            if not raw_start:
                continue
            try:
                start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            except ValueError:
                continue
            if start < window_start or start > window_end:
                continue
            # Fold the (now tournament-name-backfilled) tournament into the
            # candidate text so identity scoring has something to compare a
            # provider's "FedEx St. Jude Championship: McIlroy Group" against —
            # SDP's own per-row title alone often doesn't name the tournament.
            candidate = " ".join(x for x in [ev.get("tournament_name"), ev.get("home_team_name")] if x)
            text_score = self._title_match_score(title_text, candidate, candidate_round_name=ev.get("round_name"))
            hours_off = abs((start - now).total_seconds()) / 3600.0
            time_score = max(0.0, 1.0 - hours_off / window_hrs)
            combined = (text_score * 0.7) + (time_score * 0.3)
            if combined > best_score:
                best_score, best_event = combined, ev

        return best_event if best_score >= 0.55 else None

    @staticmethod
    def _slugify_team(text):
        return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')

    @staticmethod
    def _us_time_strs(dt_utc):
        """Return (start_short, start_day, start_date, start_time_et_ct) for a UTC
        datetime, formatted for US sports audiences (Eastern + Central)."""
        from datetime import timedelta
        _DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        is_dst = 3 <= dt_utc.month <= 11
        et = dt_utc + timedelta(hours=-4 if is_dst else -5)
        ct = dt_utc + timedelta(hours=-5 if is_dst else -6)

        def fmt(d):
            hour = d.hour % 12 or 12
            ampm = "AM" if d.hour < 12 else "PM"
            return f"{hour}:{d.minute:02d} {ampm}"

        start_short = fmt(et)
        start_day = _DAYS[et.weekday()]
        start_date = f"{_MONTHS[et.month - 1]} {et.day}"
        start_time_et_ct = f"{fmt(et)} ET / {fmt(ct)} CT"
        return start_short, start_day, start_date, start_time_et_ct

    @staticmethod
    def _utc_midnight_before(dt_utc):
        """Return midnight UTC on the same UTC calendar date as dt_utc — used as the
        Pregame block's start time, so a game-dedicated channel shows as pregame all
        day rather than just the hour before kickoff. Anchored to UTC (not a US
        timezone) since Dispatcharr itself is timezone-neutral and this plugin is
        used by viewers worldwide."""
        return dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _utc_time_strs(dt_utc):
        """Return (start_short_utc, start_day_utc, start_date_utc, start_time_utc) —
        the UTC-only counterparts to _us_time_strs, for templates that want a
        timezone-neutral alternative to the US Eastern/Central variables."""
        _DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        def fmt(d):
            hour = d.hour % 12 or 12
            ampm = "AM" if d.hour < 12 else "PM"
            return f"{hour}:{d.minute:02d} {ampm}"

        start_short_utc = fmt(dt_utc)
        start_day_utc = _DAYS[dt_utc.weekday()]
        start_date_utc = f"{_MONTHS[dt_utc.month - 1]} {dt_utc.day}"
        start_time_utc = f"{fmt(dt_utc)} UTC"
        return start_short_utc, start_day_utc, start_date_utc, start_time_utc

    def _build_sdp_template_vars(self, event, gamethumbs_base, league_label, phase):
        from datetime import datetime

        away_name = event.get("away_team_name") or event.get("away_team_abbr") or "Away"
        home_name = event.get("home_team_name") or event.get("home_team_abbr") or "Home"
        away_slug = self._slugify_team(event.get("away_team_abbr") or away_name)
        home_slug = self._slugify_team(event.get("home_team_abbr") or home_name)

        start = datetime.fromisoformat(event["start_time_utc"].replace("Z", "+00:00"))
        start_short, start_day, start_date, start_time_et_ct = self._us_time_strs(start)
        start_short_utc, start_day_utc, start_date_utc, start_time_utc = self._utc_time_strs(start)

        game_number = event.get("game_number")
        game_number_suffix = f" (Game {game_number})" if game_number else ""

        broadcast = event.get("broadcast") or ""
        broadcast_line = f" on {broadcast}" if broadcast else ""

        venue = ", ".join(v for v in [event.get("venue_name") or "", event.get("venue_city") or ""] if v)
        venue_line = f" at {venue}" if venue else ""

        away_score, home_score = event.get("away_score"), event.get("home_score")
        winner = loser = score_line = ""
        if away_score is not None and home_score is not None:
            score_line = f"Final: {away_name} {away_score} - {home_name} {home_score}"
            if away_score > home_score:
                winner, loser = away_name, home_name
            elif home_score > away_score:
                winner, loser = home_name, away_name

        # Tennis-only (populated by SDP's per-match ATP/WTA ingest). Blank for
        # every other sport — safe no-ops in templates that don't reference them.
        tournament_name = event.get("tournament_name") or ""
        round_name = event.get("round_name") or ""
        court = event.get("court") or ""
        court_line = f" on {court}" if court else ""
        # Tennis scores arrive as free text in `notes` (e.g. "Djokovic bt Tirante
        # 6-2 6-4"), not the numeric away_score/home_score team sports use.
        result = event.get("notes") or ""
        result_line = f" — {result}" if result else ""

        # Golf/NASCAR/motorsport-only (single_title mode): the one descriptive
        # broadcast-feed title IS the event, stored in home_team_name since
        # there's no away side. PGA TOUR's rows ("Marquee Group - R. McIlroy,
        # K. Reitan") don't repeat the tournament name themselves — SDP puts that
        # on a separate marker row per tournament, backfilled by
        # _inherit_tournament_names onto every row under it — so prepend it here
        # when present (tournament_name is "" for sports that never had one, and
        # for F1/NASCAR it already equals home_team_name, so this is a harmless
        # no-op there rather than a duplicate).
        home_title = event.get("home_team_name") or ""
        event_title = (
            f"{tournament_name}: {home_title}"
            if tournament_name and tournament_name != home_title and tournament_name not in home_title
            else home_title
        )

        return {
            "away_team": away_slug,
            "home_team": home_slug,
            "away_team_pascal": away_name,
            "home_team_pascal": home_name,
            "start_short": start_short,
            "start_day": start_day,
            "start_date": start_date,
            "start_time_et_ct": start_time_et_ct,
            "start_short_utc": start_short_utc,
            "start_day_utc": start_day_utc,
            "start_date_utc": start_date_utc,
            "start_time_utc": start_time_utc,
            "game_number_suffix": game_number_suffix,
            "broadcast": broadcast,
            "broadcast_line": broadcast_line,
            "venue": venue,
            "venue_line": venue_line,
            "winner": winner,
            "loser": loser,
            "score_line": score_line,
            "league": event.get("league_name") or league_label,
            "league_slug": event.get("league_slug") or "",
            "gamethumbs_base": (gamethumbs_base or "").rstrip("/"),
            "phase": phase,
            "tournament_name": tournament_name,
            "round_name": round_name,
            "court": court,
            "court_line": court_line,
            "result": result,
            "result_line": result_line,
            "event_title": event_title,
        }

    @staticmethod
    def _render_sports_template(template_str, vars_dict):
        if not template_str:
            return ""
        class _SafeDict(dict):
            def __missing__(self, key):
                return ""
        try:
            return template_str.format_map(_SafeDict(vars_dict))
        except Exception as e:
            LOGGER.warning(f"EPGeditARR: sport template render failed ({e}): {template_str!r}")
            return template_str

    def _sports_editor_epg_source(self):
        # source_type is deliberately "xmltv", not "dummy" — Dispatcharr's EPGGridAPIView
        # unconditionally generates its own on-the-fly placeholder programming (ignoring
        # any real ProgramData rows) for every channel whose assigned EPG source is
        # source_type="dummy", and the frontend hardcodes dummy sources' Status to "idle"
        # with no refresh button. "xmltv" with no url sidesteps both — Dispatcharr's own
        # refresh task just fails gracefully (status="error", no data loss) if a user ever
        # clicks Refresh on it, since we write ProgramData ourselves and never rely on
        # Dispatcharr's fetch/parse cycle for this source. Matches the same source_type
        # EDM's Sports Engine and Tickarr use for their own generated EPG sources.
        from apps.epg.models import EPGSource
        source, created = EPGSource.objects.get_or_create(
            name=SPORTS_EPG_SOURCE_NAME,
            defaults={"source_type": "xmltv", "custom_properties": {"epgeditarr_sports": True}},
        )
        if not created and source.source_type != "xmltv":
            EPGSource.objects.filter(pk=source.pk).update(source_type="xmltv")
            source.source_type = "xmltv"
        return source

    @staticmethod
    def _mark_epg_source_success(epg_source, message):
        # Dispatcharr's core pre_save signal for EPGSource unconditionally forces
        # dummy-type sources' status back to "idle" with no message on every
        # instance.save() call ("Dummy EPGs should always be idle..." — apps/epg/
        # signals.py). A queryset-level .update() bypasses model signals entirely,
        # so it's the only way to make a dummy source's Status/Updated columns in
        # M3U & EPG Manager reflect that it actually ran and wrote real data.
        from django.utils import timezone
        from apps.epg.models import EPGSource
        EPGSource.objects.filter(pk=epg_source.pk).update(
            status="success", last_message=message, updated_at=timezone.now()
        )

    def _enabled_sport_template_groups(self, settings):
        """Return [(ChannelGroup, sport_slug), ...] for every group with the Sports
        Editor enabled AND a Sport Template selected."""
        from apps.channels.models import ChannelGroup
        result = []
        for group in ChannelGroup.objects.all().order_by("name"):
            if not settings.get(f"sports_editor_{group.id}_enabled"):
                continue
            sport = (settings.get(f"sports_editor_{group.id}_sport") or "").strip()
            if sport in _SPORT_TEMPLATES:
                result.append((group, sport))
        return result

    def _process_sports_editor_channel(self, ch, sport_slug, events, settings, epg_source):
        """Try to match `ch` (already renamed by regex rules, if any) to a live SDP
        event for `sport_slug`. On a match: rename the channel via the sport's
        Channel Name template, assign its Logo URL, and (re)generate Pregame/Live/
        Postgame ProgramData blocks around the real game time. Returns True if matched."""
        from apps.epg.models import EPGData, ProgramData
        from apps.channels.models import Logo
        from datetime import datetime, timedelta, timezone

        mode = _SPORT_MATCH_MODE.get(sport_slug, "matchup")
        strip_noise = sport_slug in _NOISE_STRIP_SPORTS

        if mode == "single_title":
            title_text = self._strip_provider_noise(ch.name)
            if not title_text:
                return False
            event = self._find_sdp_event_single_title(title_text, sport_slug, events)
        else:
            matchup = self._extract_matchup_teams(ch.name, strip_noise=strip_noise)
            if not matchup:
                return False
            away_text, home_text = matchup
            # _person_name_score only kicks in its "Last, First" flip when a comma
            # is actually present, so it's a strict superset of _team_match_score —
            # safe default for every person-vs-person (rather than team-vs-team)
            # sport, not just tennis.
            score_fn = self._person_name_score if sport_slug in _PERSON_VS_PERSON_SPORTS else None
            event = self._find_sdp_event(away_text, home_text, sport_slug, events, score_fn=score_fn)
        if not event:
            return False

        # A game whose entire Pregame/Live/Postgame window has already elapsed is
        # useless to match — it would rename the channel and write EPG blocks that
        # are already 100% in the past by the time anyone looks at the guide. Treat
        # it as no match so the group's Rename Rules fallback (or no-op) applies instead.
        start = datetime.fromisoformat(event["start_time_utc"].replace("Z", "+00:00"))
        duration_hours = _LEAGUE_DURATION_HOURS.get(sport_slug, 3.0)
        est_end = start + timedelta(hours=duration_hours)
        # Pregame runs from midnight ET on game day through kickoff, not just an hour
        # before — a channel dedicated to one game should show as "pregame" all day,
        # not sit on generic/no-data content until an hour prior.
        pre_start = self._utc_midnight_before(start)
        post_end = est_end + timedelta(hours=1)
        if post_end < datetime.now(timezone.utc):
            return False

        gamethumbs_base = settings.get("sports_editor_gamethumbs_url") or "https://game-thumbs.tickarr.com"
        league_label = _SPORT_TEMPLATES.get(sport_slug, sport_slug)
        defaults = self._sport_default_templates(sport_slug)
        vars_base = self._build_sdp_template_vars(event, gamethumbs_base, league_label, "pregame")

        channel_name_tpl = settings.get(f"sport_tpl_{sport_slug}_channel_name") or defaults["channel_name"]
        new_name = self._render_sports_template(channel_name_tpl, vars_base)
        if new_name and new_name != ch.name:
            ch.name = new_name
            ch.save(update_fields=["name"])

        logo_url_tpl = settings.get(f"sport_tpl_{sport_slug}_logo_url") or ""
        logo_url = self._render_sports_template(logo_url_tpl, vars_base)
        if logo_url:
            logo_obj, _ = Logo.objects.get_or_create(url=logo_url, defaults={"name": ch.name})
            if ch.logo_id != logo_obj.id:
                ch.logo = logo_obj
                ch.save(update_fields=["logo"])

        tvg_id = f"epgeditarr-sports-{ch.id}"
        epg_entry, _ = EPGData.objects.get_or_create(
            tvg_id=tvg_id, epg_source=epg_source, defaults={"name": ch.name, "icon_url": ""},
        )
        if epg_entry.name != ch.name:
            epg_entry.name = ch.name
            epg_entry.save(update_fields=["name"])
        if ch.epg_data_id != epg_entry.id:
            ch.epg_data = epg_entry
            ch.save(update_fields=["epg_data"])

        # This EPGData is created and owned exclusively for this one channel (tvg_id
        # is keyed off the channel's own id), so it's always safe to wipe and rebuild
        # its whole timeline each run — otherwise a channel that gets re-matched to a
        # different game than a previous run leaves orphaned stale blocks behind.
        ProgramData.objects.filter(epg=epg_entry).delete()

        batch = []
        for b_start, b_end, title_key, desc_key, phase in [
            (pre_start, start, "pre_title", "pre_desc", "pregame"),
            (start, est_end, "live_title", "live_desc", "live"),
            (est_end, post_end, "post_title", "post_desc", "postgame"),
        ]:
            default_title, default_desc = defaults[title_key], defaults[desc_key]
            v = self._build_sdp_template_vars(event, gamethumbs_base, league_label, phase)
            title = self._render_sports_template(
                settings.get(f"sport_tpl_{sport_slug}_{title_key}") or default_title, v
            )
            desc = self._render_sports_template(
                settings.get(f"sport_tpl_{sport_slug}_{desc_key}") or default_desc, v
            )
            batch.append(ProgramData(
                epg=epg_entry, start_time=b_start, end_time=b_end,
                title=title or ch.name, sub_title=None, description=desc or None,
                tvg_id=tvg_id, custom_properties={},
            ))
        ProgramData.objects.bulk_create(batch)
        return True

    def _run_sports_editor_epg(self, m3u_account, settings):
        """Automatic path — runs right after _run_sports_editor_rename for the same
        M3U refresh, scoped to that account's newly auto-created channels."""
        from apps.channels.models import Channel

        sport_groups = self._enabled_sport_template_groups(settings)
        if not sport_groups:
            return {"matched": 0, "scanned": 0}

        events = self._fetch_sdp_schedule(settings)
        if not events:
            return {"matched": 0, "scanned": 0}

        epg_source = self._sports_editor_epg_source()
        matched = scanned = 0
        with transaction.atomic():
            for group, sport in sport_groups:
                channels = Channel.objects.filter(
                    auto_created=True, auto_created_by=m3u_account, channel_group=group,
                )
                for ch in channels:
                    scanned += 1
                    try:
                        if self._process_sports_editor_channel(ch, sport, events, settings, epg_source):
                            matched += 1
                    except Exception as e:
                        LOGGER.warning(f"EPGeditARR: sports editor EPG match failed for '{ch.name}': {e}")

        self._mark_epg_source_success(
            epg_source, f"Sports Editor: {matched} channel(s) matched, {scanned} scanned"
        )
        return {"matched": matched, "scanned": scanned}

    def _action_sports_editor_epg_now(self, settings, logger):
        """Manual path — scans every enabled+sport-selected group's auto-created
        channels right now, without waiting for the next M3U refresh."""
        from apps.channels.models import Channel

        sport_groups = self._enabled_sport_template_groups(settings)
        if not sport_groups:
            return {
                "success": False,
                "message": (
                    "No channel groups have both the Sports Editor enabled and a Sport "
                    "Template selected. Configure a group's section in Settings → Sports Editor."
                ),
            }

        events = self._fetch_sdp_schedule(settings)
        if not events:
            return {
                "success": False,
                "message": (
                    "Could not fetch the sports schedule from sports-data-platform "
                    "(api.tickarr.com). Check network access from this container and try again."
                ),
            }

        epg_source = self._sports_editor_epg_source()
        lines = []
        total_matched = total_scanned = 0
        with transaction.atomic():
            for group, sport in sport_groups:
                channels = list(Channel.objects.filter(auto_created=True, channel_group=group))
                group_matched = 0
                examples = []
                for ch in channels:
                    old_name = ch.name
                    try:
                        if self._process_sports_editor_channel(ch, sport, events, settings, epg_source):
                            group_matched += 1
                            if len(examples) < 5:
                                examples.append(f"  '{old_name}' -> '{ch.name}'")
                    except Exception as e:
                        LOGGER.warning(f"EPGeditARR: sports editor EPG match failed for '{ch.name}': {e}")
                total_scanned += len(channels)
                total_matched += group_matched
                lines.append(
                    f"{group.name} ({_SPORT_TEMPLATES.get(sport, sport)}): "
                    f"scanned {len(channels)}, matched {group_matched}"
                )
                lines.extend(examples)

        self._mark_epg_source_success(
            epg_source, f"Sports Editor: {total_matched} channel(s) matched, {total_scanned} scanned"
        )
        lines.insert(
            0,
            f"Sports Editor EPG: {total_matched} channel(s) matched to live games across "
            f"{len(sport_groups)} group(s), {total_scanned} auto-created channel(s) scanned.",
        )
        return {"success": True, "message": "\n".join(lines)}

    def _get_source_field_rules(self, source_id, settings):
        return {
            "title": self._parse_rules(settings.get(f"src_{source_id}_title_rules", "")),
            "sub_title": self._parse_rules(settings.get(f"src_{source_id}_subtitle_rules", "")),
            "description": self._parse_rules(settings.get(f"src_{source_id}_description_rules", "")),
        }

    def _rule_summary_for_source(self, source_id, settings):
        lines = []
        for label, key in [
            ("Title", f"src_{source_id}_title_rules"),
            ("Sub-Title", f"src_{source_id}_subtitle_rules"),
            ("Description", f"src_{source_id}_description_rules"),
        ]:
            rules = self._parse_rules(settings.get(key, ""))
            if rules:
                descs = []
                for r in rules:
                    if r["type"] == "regex":
                        descs.append(f"regex({r['raw']!r} → {r['replacement']!r})")
                    else:
                        descs.append(f"replace({r['find']!r} → {r['replacement']!r})")
                lines.append(f"    {label}: " + ", ".join(descs))
        force_category = (settings.get(f"src_{source_id}_force_category", "") or "").strip()
        if force_category:
            lines.append(f"    Force Category: {force_category}")
        if settings.get(f"src_{source_id}_synth_episode_num", False):
            lines.append("    Synthesized Episode Numbers: on")
        return "\n".join(lines) if lines else "    (no rules configured)"

    # ── EPG helpers ───────────────────────────────────────────────────────

    def _get_enabled_sources(self, settings):
        """Return list of EPGSource instances that have been enabled in settings."""
        from apps.epg.models import EPGSource
        results = []
        for source in EPGSource.objects.exclude(name__startswith=VIRTUAL_PREFIX).order_by("name"):
            if settings.get(f"src_{source.id}_enabled", False):
                results.append(source)
        return results

    def _get_or_create_virtual(self, source):
        # source_type="xmltv" (not "dummy") — see _sports_editor_epg_source for why.
        from apps.epg.models import EPGSource
        virtual_name = f"{VIRTUAL_PREFIX}{source.name}"
        virtual, created = EPGSource.objects.get_or_create(
            name=virtual_name,
            defaults={
                "source_type": "xmltv",
                "custom_properties": {"epgeditarr_source_id": source.id},
            },
        )
        if not created:
            fields_to_update = {}
            props = dict(virtual.custom_properties or {})
            if props.get("epgeditarr_source_id") != source.id:
                props["epgeditarr_source_id"] = source.id
                fields_to_update["custom_properties"] = props
            if virtual.source_type != "xmltv":
                fields_to_update["source_type"] = "xmltv"
            if fields_to_update:
                EPGSource.objects.filter(pk=virtual.pk).update(**fields_to_update)
                for k, v in fields_to_update.items():
                    setattr(virtual, k, v)
        return virtual, created

    def _sync_epgdata(self, source, virtual):
        """Ensure virtual EPGSource has an EPGData entry for every entry in source."""
        from apps.epg.models import EPGData
        source_entries = list(EPGData.objects.filter(epg_source=source))
        existing = {e.tvg_id: e for e in EPGData.objects.filter(epg_source=virtual)}
        to_create = [
            EPGData(tvg_id=se.tvg_id, name=se.name, icon_url=se.icon_url, epg_source=virtual)
            for se in source_entries
            if se.tvg_id not in existing
        ]
        if to_create:
            EPGData.objects.bulk_create(to_create, ignore_conflicts=True)
        return {e.tvg_id: e for e in EPGData.objects.filter(epg_source=virtual)}

    def _channel_qs(self, source, settings):
        from apps.channels.models import Channel
        qs = Channel.objects.filter(epg_data__epg_source=source)
        include = [g.strip() for g in (settings.get("include_groups") or "").split(",") if g.strip()]
        exclude = [g.strip() for g in (settings.get("exclude_groups") or "").split(",") if g.strip()]
        if include:
            qs = qs.filter(channel_group__name__in=include)
        if exclude:
            qs = qs.exclude(channel_group__name__in=exclude)
        return qs

    def _channel_tvg_id(self, channel_name):
        slug = re.sub(r'[^a-z0-9]+', '-', channel_name.lower()).strip('-')
        return f"epgeditarr-fill-{slug}"

    def _get_fill_channels(self, settings):
        """Return Channel objects eligible for fill EPG (in fill groups, no EPG or on a dummy source)."""
        from django.db.models import Q
        from apps.channels.models import Channel
        from apps.epg.models import EPGSource

        fill_group_names = [g.strip() for g in (settings.get('fill_groups') or '').split(',') if g.strip()]
        if not fill_group_names:
            return []

        # Include channels with no EPG, already on our fill, or on any (other) dummy
        # source (covers Dispatcharr's built-in dummy fill so we can replace it). Our
        # own Fill source is deliberately typed "xmltv" (see _action_fill_epg), so it's
        # named explicitly here rather than relying on source_type='dummy' to catch it.
        qs = Channel.objects.filter(channel_group__name__in=fill_group_names).filter(
            Q(epg_data__isnull=True)
            | Q(epg_data__epg_source__source_type='dummy')
            | Q(epg_data__epg_source__name=FILL_SOURCE_NAME)
        )

        skip = {n.strip().lower() for n in (settings.get('fill_skip_channels') or '').splitlines() if n.strip()}
        return [c for c in qs.select_related('channel_group') if c.name.lower() not in skip]

    def _generate_fill_blocks(self, epg_entry, title, description, block_hours, days_ahead):
        """Return list of unsaved ProgramData objects covering days_ahead days in block_hours slots."""
        from apps.epg.models import ProgramData
        from datetime import datetime, timedelta, timezone

        programs = []
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        end_dt = now + timedelta(days=days_ahead)
        delta = timedelta(hours=block_hours)
        current = now

        while current < end_dt:
            programs.append(ProgramData(
                epg=epg_entry,
                start_time=current,
                end_time=current + delta,
                title=title,
                sub_title=None,
                description=description or None,
                tvg_id=epg_entry.tvg_id,
                custom_properties={},
            ))
            current += delta

        return programs

    # ── Transform ─────────────────────────────────────────────────────────

    def _do_transform_source(self, source, settings):
        """Copy ProgramData from source into its virtual EPG, applying rules.
        Only processes channels actually mapped to user channels (pre- or post-setup).
        Returns the number of programs written."""
        from apps.epg.models import EPGData, ProgramData
        from apps.channels.models import Channel

        virtual, _ = self._get_or_create_virtual(source)
        virtual_map = self._sync_epgdata(source, virtual)
        field_rules = self._get_source_field_rules(source.id, settings)
        series_categories = [
            c.strip() for c in (settings.get(f"src_{source.id}_force_category", "") or "").split(",") if c.strip()
        ]
        synth_episode_num = bool(settings.get(f"src_{source.id}_synth_episode_num", False))

        # Channels may be on the original source (pre-setup) or virtual (post-setup).
        # Checking both ensures we always find the right set regardless of state.
        assigned_tvg_ids = set(
            Channel.objects.filter(
                epg_data__epg_source__in=[source, virtual]
            ).values_list("epg_data__tvg_id", flat=True).distinct()
        )

        if assigned_tvg_ids:
            source_entries = EPGData.objects.filter(
                epg_source=source, tvg_id__in=assigned_tvg_ids
            )
        else:
            source_entries = EPGData.objects.filter(epg_source=source)

        total = 0
        with transaction.atomic():
            ProgramData.objects.filter(epg__epg_source=virtual).delete()
            batch = []
            for se in source_entries.iterator(chunk_size=200):
                ve = virtual_map.get(se.tvg_id)
                if not ve:
                    continue
                for prog in ProgramData.objects.filter(epg=se).iterator(chunk_size=500):
                    custom_props = dict(prog.custom_properties or {})
                    if series_categories:
                        existing_cats = custom_props.get("categories") or []
                        custom_props["categories"] = list(dict.fromkeys([*existing_cats, *series_categories]))
                    if synth_episode_num:
                        custom_props["season"] = prog.start_time.year
                        custom_props["episode"] = prog.start_time.timetuple().tm_yday
                    batch.append(ProgramData(
                        epg=ve,
                        start_time=prog.start_time,
                        end_time=prog.end_time,
                        title=self._apply_rules(prog.title, field_rules["title"]) or prog.title,
                        sub_title=(
                            self._apply_rules(prog.sub_title, field_rules["sub_title"])
                            if prog.sub_title is not None else None
                        ),
                        description=(
                            self._apply_rules(prog.description, field_rules["description"])
                            if prog.description is not None else None
                        ),
                        tvg_id=prog.tvg_id,
                        custom_properties=custom_props,
                    ))
                    if len(batch) >= 1000:
                        ProgramData.objects.bulk_create(batch)
                        total += len(batch)
                        batch = []
            if batch:
                ProgramData.objects.bulk_create(batch)
                total += len(batch)

        n_channels = len(assigned_tvg_ids) if assigned_tvg_ids else "all"
        LOGGER.info(
            f"EPGeditARR: '{source.name}' — {total} programs written "
            f"({n_channels} channel(s) scoped)"
        )
        return total

    # ── Action dispatch ───────────────────────────────────────────────────

    def run(self, action, params, context):
        settings = context.get("settings", {})
        logger = context.get("logger", LOGGER)
        handlers = {
            "setup":                  self._action_setup,
            "apply_now":              self._action_apply_now,
            "sample":                 self._action_sample,
            "preview":                self._action_preview,
            "status":                 self._action_status,
            "teardown":               self._action_teardown,
            "test_rule":              self._action_test_rule,
            "scan":                   self._action_scan,
            "fill_epg":               self._action_fill_epg,
            "sports_editor_rename_now": self._action_sports_editor_rename_now,
            "sports_editor_epg_now":  self._action_sports_editor_epg_now,
        }
        handler = handlers.get(action)
        if not handler:
            return {"success": False, "message": f"Unknown action: {action}"}
        try:
            return handler(settings, logger)
        except Exception as e:
            LOGGER.exception(f"EPGeditARR: action '{action}' raised an exception")
            return {"success": False, "message": f"Error: {e}"}

    # ── Actions ───────────────────────────────────────────────────────────

    def _action_setup(self, settings, logger):
        enabled = self._get_enabled_sources(settings)
        if not enabled:
            return {"success": False, "message": "No sources enabled. Toggle at least one source on and try again."}

        lines = []
        for source in enabled:
            virtual, created = self._get_or_create_virtual(source)
            virtual_map = self._sync_epgdata(source, virtual)
            total = self._do_transform_source(source, settings)

            lines.append(f"── {source.name} ──")
            lines.append(f"  Virtual EPG : '{virtual.name}' ({'created' if created else 'already exists'})")
            lines.append(f"  Programs    : {total:,} transformed and written")

            if settings.get("auto_reassign", True):
                channels = self._channel_qs(source, settings).select_related("epg_data")
                reassigned, skipped = 0, 0
                for ch in channels:
                    tvg_id = ch.epg_data.tvg_id if ch.epg_data else None
                    ve = virtual_map.get(tvg_id)
                    if ve:
                        ch.epg_data = ve
                        ch.save(update_fields=["epg_data"])
                        reassigned += 1
                    else:
                        skipped += 1
                lines.append(f"  Channels    : {reassigned} reassigned ({skipped} skipped)")
            lines.append("")

        lines.append("Auto-sync active — transforms run automatically after every EPG refresh.")
        return {"success": True, "message": "\n".join(lines)}

    def _action_apply_now(self, settings, logger):
        enabled = self._get_enabled_sources(settings)
        if not enabled:
            return {"success": False, "message": "No sources enabled."}
        lines = ["Transform complete:\n"]
        for source in enabled:
            total = self._do_transform_source(source, settings)
            lines.append(f"  {source.name}: {total:,} programs written")
        return {"success": True, "message": "\n".join(lines)}

    def _action_sample(self, settings, logger):
        """Show 4 example programs per tag category for each enabled source."""
        import random
        from django.db.models import Q
        from apps.epg.models import ProgramData

        enabled = self._get_enabled_sources(settings)
        if not enabled:
            return {"success": False, "message": "No sources enabled."}

        _LABELS = {
            "episode":   "Episode Codes  (S##E##, E##, ##x##)",
            "broadcast": "Broadcast Flags  (New, Live, Rerun, Premiere...)",
            "quality":   "Quality Tags  ([HD], [4K], [UHD])",
            "technical": "Technical Tags  (CC, SAP, DVS, Stereo...)",
            "year":      "Year Tags  (1951), (2023)",
            "gracenote": "Gracenote Tags  (INFO, Censored, [as])",
            "unicode":   "Unicode Broadcast Flags  (ᴺᵉʷ, ᴸᶦᵛᵉ — Gracenote/Jesmann style)",
        }
        categories = [(k, v) for k, v in self._SAMPLE_PATTERNS.items() if k != "any"]

        lines = []
        for source in enabled:
            total_in_db = ProgramData.objects.filter(epg__epg_source=source).count()
            raw_titles = list(
                ProgramData.objects.filter(epg__epg_source=source)
                .values_list("title", flat=True)[:3]
            )
            lines.append(f"{'═' * 60}")
            lines.append(f"  {source.name}  (id={source.id})")
            lines.append(f"{'═' * 60}")
            lines.append(f"  Total programs in DB : {total_in_db:,}")
            if raw_titles:
                lines.append(f"  Sample raw titles    : {raw_titles}")
            lines.append("")

            for cat_key, pattern in categories:
                if cat_key == "unicode":
                    # iregex doesn't reliably match Unicode modifier letters;
                    # use contains (LIKE) queries for each known flag literal
                    flags = ["ᴺᵉʷ", "ᴸᶦᵛᵉ", "ᴾʳᵉ", "ᴿᵉᵖ", "ᴵⁿᶠᵒ", "ᴼᵛᵉʳ"]
                    tag_q = Q()
                    for flag in flags:
                        tag_q |= (
                            Q(title__contains=flag) |
                            Q(sub_title__contains=flag) |
                            Q(description__contains=flag)
                        )
                else:
                    tag_q = (
                        Q(title__iregex=pattern) |
                        Q(sub_title__iregex=pattern) |
                        Q(description__iregex=pattern)
                    )
                tagged_ids = list(
                    ProgramData.objects.filter(epg__epg_source=source)
                    .filter(tag_q)
                    .values_list("id", flat=True)[:5000]
                )
                total = len(tagged_ids)
                label = _LABELS.get(cat_key, cat_key)

                if total == 0:
                    lines.append(f"── {label}: no matches ──\n")
                    continue

                sample_ids = random.sample(tagged_ids, min(4, total))
                programs = list(
                    ProgramData.objects.filter(id__in=sample_ids).select_related("epg")
                )
                lines.append(f"── {label}  ({total:,} matches) ──")
                for prog in programs:
                    lines.append(f"  Channel : {prog.epg.name}")
                    lines.append(f"  Title   : {prog.title}")
                    if prog.sub_title:
                        lines.append(f"  SubTitle: {prog.sub_title}")
                    if prog.description:
                        desc = prog.description[:200]
                        if len(prog.description) > 200:
                            desc += "…"
                        lines.append(f"  Desc    : {desc}")
                    lines.append("")

            lines.append("")

        return {"success": True, "message": "\n".join(lines)}

    def _action_preview(self, settings, logger):
        """Dry run: show change counts and before/after examples for each enabled source."""
        from apps.epg.models import ProgramData
        enabled = self._get_enabled_sources(settings)
        if not enabled:
            return {"success": False, "message": "No sources enabled."}

        all_lines = []
        for source in enabled:
            field_rules = self._get_source_field_rules(source.id, settings)
            if not any(field_rules.values()):
                all_lines.append(f"── {source.name}: no rules configured — skipping ──\n")
                continue

            counts = {"title": 0, "sub_title": 0, "description": 0}
            examples = []
            scanned = 0

            for prog in ProgramData.objects.filter(
                epg__epg_source=source
            ).select_related("epg")[:2000]:
                scanned += 1
                for field_name, rules in field_rules.items():
                    if not rules:
                        continue
                    original = getattr(prog, field_name) or ""
                    transformed = self._apply_rules(original, rules)
                    if transformed != original:
                        counts[field_name] += 1
                        if len(examples) < 10:
                            examples.append(
                                f"  [{field_name}] {prog.epg.name}\n"
                                f"    BEFORE: {original[:100]}\n"
                                f"     AFTER: {transformed[:100]}"
                            )

            all_lines.append(f"── {source.name} ({scanned} programs scanned) ──")
            for field_name, count in counts.items():
                if field_rules[field_name]:
                    all_lines.append(f"  {field_name}: {count} program(s) would change")
            if examples:
                all_lines.append("")
                all_lines.extend(examples)
            elif any(field_rules.values()):
                all_lines.append("  No programs would be changed by current rules.")
            all_lines.append("")

        return {"success": True, "message": "\n".join(all_lines)}

    def _action_status(self, settings, logger):
        from apps.epg.models import EPGSource, EPGData, ProgramData

        sources = list(EPGSource.objects.exclude(name__startswith=VIRTUAL_PREFIX).order_by("name"))
        if not sources:
            return {"success": True, "message": "No EPG sources found in Dispatcharr."}

        lines = ["EPG Sources:\n"]
        for source in sources:
            enabled = settings.get(f"src_{source.id}_enabled", False)
            tag = "ENABLED" if enabled else "disabled"
            lines.append(f"  [{tag}] {source.name}")
            if enabled:
                virtual_name = f"{VIRTUAL_PREFIX}{source.name}"
                try:
                    virtual = EPGSource.objects.get(name=virtual_name)
                    src_count = ProgramData.objects.filter(epg__epg_source=source).count()
                    virt_count = ProgramData.objects.filter(epg__epg_source=virtual).count()
                    lines.append(f"    Source: {src_count:,} programs  →  Virtual: {virt_count:,} programs")
                except EPGSource.DoesNotExist:
                    lines.append("    Virtual EPG not created yet — run Setup")
                lines.append(self._rule_summary_for_source(source.id, settings))
            lines.append("")

        # Fill EPG status
        try:
            fill_src = EPGSource.objects.get(name=FILL_SOURCE_NAME)
            fill_epg_count = EPGData.objects.filter(epg_source=fill_src).count()
            fill_prog_count = ProgramData.objects.filter(epg__epg_source=fill_src).count()
            lines.append(f"Fill EPG: ACTIVE — {fill_epg_count:,} channel(s), {fill_prog_count:,} program blocks")
        except EPGSource.DoesNotExist:
            lines.append("Fill EPG: not created — run Fill EPG")

        # Unmatched channel name log — grows each time Fill/Sort/Rename finds a miss
        try:
            from apps.plugins.models import PluginConfig
            cfg = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
            unmatched_log = (cfg.settings or {}).get(UNMATCHED_LOG_KEY, []) if cfg else []
        except Exception:
            unmatched_log = []
        if unmatched_log:
            lines.append(f"\nUnmatched channel names ({len(unmatched_log)}) — copy and share to grow alias list:")
            for name in unmatched_log:
                lines.append(f"  {name}")

        return {"success": True, "message": "\n".join(lines)}

    def _action_test_rule(self, settings, logger):
        """Test a rule against live source data or manually supplied text."""
        import random

        test_pattern = (settings.get("test_pattern") or "").strip()
        test_replacement = settings.get("test_replacement") or ""
        use_regex = settings.get("test_type", True)
        test_input = (settings.get("test_input") or "").strip()
        test_field = settings.get("test_field") or "title"
        test_source_id = (settings.get("test_source_id") or "").strip()

        if not test_pattern:
            return {"success": False, "message": "No pattern provided. Enter a pattern to test."}

        # Compile regex up front so we can report errors before doing any DB work
        compiled = None
        if use_regex:
            try:
                compiled = re.compile(test_pattern)
            except re.error as e:
                return {"success": False, "message": f"Invalid regex: {e}"}

        # ── Determine values to test against ─────────────────────────────
        if test_input:
            values = [l for l in test_input.splitlines() if l.strip()]
            source_label = "manually supplied text"
        else:
            # Pull a diverse sample from the real EPG source
            if not test_source_id:
                return {"success": False, "message": "Select a source in 'Test Source' or paste text into 'Test Text'."}
            try:
                from apps.epg.models import EPGSource, EPGData, ProgramData
                source = EPGSource.objects.get(id=int(test_source_id))
            except Exception:
                return {"success": False, "message": f"Source ID {test_source_id!r} not found."}

            source_label = f"'{source.name}' ({test_field})"

            # Sample across many channels to get diverse values
            epg_ids = list(EPGData.objects.filter(epg_source=source).values_list("id", flat=True))
            if not epg_ids:
                return {"success": False, "message": f"No EPG data found for '{source.name}'. Has it been refreshed?"}

            sampled_ids = random.sample(epg_ids, min(100, len(epg_ids)))
            raw_values = list(
                ProgramData.objects.filter(epg__id__in=sampled_ids)
                .exclude(**{f"{test_field}__isnull": True})
                .exclude(**{f"{test_field}__exact": ""})
                .values_list(test_field, flat=True)[:500]
            )
            random.shuffle(raw_values)
            values = raw_values[:200]

            if not values:
                return {"success": False, "message": f"No {test_field} values found in '{source.name}'."}

        # ── Apply rule to each value ──────────────────────────────────────
        matched, unmatched = [], []
        for val in values:
            if use_regex:
                if compiled.search(val):
                    result = compiled.sub(test_replacement, val).strip()
                    matched.append((val, result))
                else:
                    unmatched.append(val)
            else:
                if test_pattern in val:
                    result = val.replace(test_pattern, test_replacement).strip()
                    matched.append((val, result))
                else:
                    unmatched.append(val)

        # ── Format output ─────────────────────────────────────────────────
        rule_str = (
            f"regex::{test_pattern}::{test_replacement}"
            if use_regex else
            f"replace::{test_pattern}::{test_replacement}"
        )
        lines = [
            f"Tested against {source_label} — {len(values)} values sampled",
            f"Matches: {len(matched)} of {len(values)}  |  Unchanged: {len(unmatched)}",
            "",
        ]

        if matched:
            lines.append(f"── Matching (showing up to 15) ──")
            for before, after in matched[:15]:
                lines.append(f"  BEFORE: {before[:120]}")
                lines.append(f"   AFTER: {after[:120]}")
                lines.append("")
        else:
            lines.append("  No matches found in sample.")
            lines.append("")

        if unmatched:
            lines.append(f"── Unchanged examples (showing up to 5) ──")
            for val in unmatched[:5]:
                lines.append(f"  {val[:120]}")
            lines.append("")

        lines.append(f"── Rule to copy ──")
        lines.append(f"  {rule_str}")

        return {"success": True, "message": "\n".join(lines)}

    def _action_scan(self, settings, logger):
        from collections import defaultdict
        from apps.channels.models import Channel
        from apps.epg.models import EPGSource

        fill_group_names = {g.strip() for g in (settings.get('fill_groups') or '').split(',') if g.strip()}

        from django.db.models import Q

        fill_src = None
        try:
            fill_src = EPGSource.objects.get(name=FILL_SOURCE_NAME)
        except EPGSource.DoesNotExist:
            pass

        fill_count = Channel.objects.filter(epg_data__epg_source=fill_src).count() if fill_src else 0

        # Channels with no EPG or only Dispatcharr's built-in dummy (excludes our fill source)
        dummy_q = Q(epg_data__isnull=True) | Q(epg_data__epg_source__source_type='dummy')
        if fill_src:
            dummy_q &= ~Q(epg_data__epg_source=fill_src)

        channels_no_epg = (
            Channel.objects
            .filter(dummy_q)
            .select_related('channel_group')
            .order_by('channel_group__name', 'name')
        )

        by_group = defaultdict(list)
        for ch in channels_no_epg:
            gname = ch.channel_group.name if ch.channel_group else '(no group)'
            by_group[gname].append(ch.name)

        if not by_group and not fill_count:
            return {"success": True, "message": "No channels without EPG found. All channels have EPG data assigned."}

        total = sum(len(v) for v in by_group.values())
        in_fill = sum(len(v) for g, v in by_group.items() if g in fill_group_names)

        lines = ["── Channels with no EPG ──\n"]
        for gname in sorted(by_group.keys()):
            names = sorted(by_group[gname])
            tag = "✓ Fill Group" if gname in fill_group_names else "not targeted"
            lines.append(f"{gname}  ({len(names)} channels)  [{tag}]")
            for n in names:
                lines.append(f"  {n}")
            lines.append("")

        lines.append("─" * 55)
        lines.append(f"Total: {total:,} channels across {len(by_group)} group(s) have no EPG")
        if fill_group_names:
            lines.append(f"In Fill Groups: {in_fill:,} channel(s) will be filled")
        if fill_count:
            lines.append(f"Already on Fill EPG: {fill_count:,} channel(s)")
        lines.append("\nPaste channel names into 'Skip Channels' to exclude them from Fill EPG.")

        return {"success": True, "message": "\n".join(lines)}

    def _action_fill_epg(self, settings, logger):
        from apps.epg.models import EPGSource, EPGData, ProgramData

        fill_group_names = [g.strip() for g in (settings.get('fill_groups') or '').split(',') if g.strip()]
        if not fill_group_names:
            return {"success": False, "message": "No Fill Groups configured. Add group names in Settings → EPG Fill."}

        block_hours = int(settings.get('fill_block_hours') or 1)
        days_ahead = int(settings.get('fill_days_ahead') or 14)

        channels = self._get_fill_channels(settings)
        if not channels:
            return {
                "success": False,
                "message": (
                    f"No channels found in Fill Groups {fill_group_names!r} with no EPG "
                    f"(or all are in Skip Channels). Run Scan to see what's available."
                ),
            }

        # source_type="xmltv" (not "dummy") — see _sports_editor_epg_source for why.
        fill_source, created = EPGSource.objects.get_or_create(
            name=FILL_SOURCE_NAME,
            defaults={"source_type": "xmltv", "custom_properties": {"epgeditarr_fill": True}},
        )
        if not created and fill_source.source_type != "xmltv":
            EPGSource.objects.filter(pk=fill_source.pk).update(source_type="xmltv")
            fill_source.source_type = "xmltv"

        existing_epgdata = {e.tvg_id: e for e in EPGData.objects.filter(epg_source=fill_source)}
        total_programs = 0
        tvg_ids_to_fill = [self._channel_tvg_id(ch.name) for ch in channels]

        with transaction.atomic():
            ProgramData.objects.filter(epg__epg_source=fill_source, epg__tvg_id__in=tvg_ids_to_fill).delete()

            batch = []
            for ch in channels:
                tvg_id = self._channel_tvg_id(ch.name)

                if tvg_id in existing_epgdata:
                    epg_entry = existing_epgdata[tvg_id]
                else:
                    epg_entry = EPGData.objects.create(
                        tvg_id=tvg_id, name=ch.name, icon_url='', epg_source=fill_source,
                    )
                    existing_epgdata[tvg_id] = epg_entry

                if ch.epg_data_id != epg_entry.id:
                    ch.epg_data = epg_entry
                    ch.save(update_fields=['epg_data'])

                programs = self._generate_fill_blocks(epg_entry, ch.name, '', block_hours, days_ahead)
                batch.extend(programs)
                total_programs += len(programs)

                if len(batch) >= 2000:
                    ProgramData.objects.bulk_create(batch)
                    batch = []

            if batch:
                ProgramData.objects.bulk_create(batch)

        self._mark_epg_source_success(
            fill_source, f"Fill EPG: {len(channels):,} channels, {total_programs:,} program blocks"
        )

        skip_count = len({n.strip().lower() for n in (settings.get('fill_skip_channels') or '').splitlines() if n.strip()})
        lines = [
            f"Fill EPG complete\n",
            f"  Channels filled : {len(channels):,}",
            f"  Programs written: {total_programs:,}  ({block_hours}h blocks × {days_ahead} days)",
            f"  Groups targeted : {', '.join(fill_group_names)}",
        ]
        if skip_count:
            lines.append(f"  Channels skipped: {skip_count:,}")

        return {"success": True, "message": "\n".join(lines)}

    @staticmethod
    def _format_game_time_et(dt_utc):
        """Format a UTC datetime as Eastern Time string, e.g. 'Sun, May 17 12:15 PM EDT'."""
        from datetime import timedelta
        _DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        is_edt = 3 <= dt_utc.month <= 11
        local = dt_utc + timedelta(hours=-4 if is_edt else -5)
        tz = "EDT" if is_edt else "EST"
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        return f"{_DAYS[local.weekday()]}, {_MONTHS[local.month - 1]} {local.day} {hour}:{local.minute:02d} {ampm} {tz}"

    @staticmethod
    def _build_sports_segments(ch_name, fill_desc, ev_list, window_start, window_end, block_delta):
        """Build the full EPG segment list for a sports channel over the fill window.

        Block sequence around each game:
          [generic fill] → [Upcoming: title — Day, Mon D H:MM AM/PM TZ] → [LIVE: title] → [Post-game: title] → ...

        The Upcoming block starts at the block boundary 1 full block_delta before game start,
        so there is always at least ~1 block of pre-game announcement.
        The Post-game block runs for 1 block_delta after the game ends (or until the next
        game's Upcoming window starts, whichever is sooner).
        """
        from datetime import timedelta

        sorted_evs = sorted(ev_list, key=lambda x: x[1])
        segments = []   # (start, end, title, description)
        current = window_start

        for i, (ev, start_dt, end_dt) in enumerate(sorted_evs):
            if start_dt >= window_end:
                break

            # Clamp end to window
            end_dt = min(end_dt, window_end)

            # upcoming_anchor: last block boundary at least 1 block_delta before game start
            elapsed_s = (start_dt - window_start).total_seconds()
            block_s = block_delta.total_seconds()
            n_before_upcoming = max(0, int(elapsed_s / block_s) - 1)
            upcoming_anchor = window_start + timedelta(seconds=n_before_upcoming * block_s)
            if upcoming_anchor < current:
                upcoming_anchor = current

            # Generic fill from current to upcoming_anchor
            slot = current
            while slot < upcoming_anchor:
                slot_end = min(slot + block_delta, upcoming_anchor)
                segments.append((slot, slot_end, ch_name, fill_desc or None))
                slot = slot_end
            current = slot

            # Upcoming block(s): from upcoming_anchor to game start
            if current < start_dt:
                time_str = Plugin._format_game_time_et(start_dt)
                up_title = f"Upcoming: {ev['title']} — {time_str}"
                up_desc = f"Upcoming on {ch_name}: {ev['title']} — {time_str}"
                slot = current
                while slot < start_dt:
                    slot_end = min(slot + block_delta, start_dt)
                    segments.append((slot, slot_end, up_title, up_desc))
                    slot = slot_end
                current = slot

            # LIVE block (exact game times)
            if start_dt < window_end:
                live_desc = ev.get("description") or f"Live coverage on {ch_name}"
                segments.append((start_dt, end_dt, f"LIVE: {ev['title']}", live_desc or None))
                current = end_dt

            # Post-game block — 1 block_delta, capped at next game's upcoming_anchor
            next_ev = sorted_evs[i + 1] if i + 1 < len(sorted_evs) else None
            if next_ev:
                next_start = next_ev[1]
                next_elapsed_s = (next_start - window_start).total_seconds()
                next_n = max(0, int(next_elapsed_s / block_s) - 1)
                next_upcoming = window_start + timedelta(seconds=next_n * block_s)
                post_end = min(current + block_delta, next_upcoming, window_end)
            else:
                post_end = min(current + block_delta, window_end)

            if post_end > current:
                pg_title = f"Post-game: {ev['title']}"
                pg_desc = f"Post-game coverage following {ev['title']} on {ch_name}"
                segments.append((current, post_end, pg_title, pg_desc))
                current = post_end

        # Generic fill for the remainder of the window
        while current < window_end:
            slot_end = min(current + block_delta, window_end)
            segments.append((current, slot_end, ch_name, fill_desc or None))
            current = slot_end

        return segments

    def _action_teardown(self, settings, logger):
        from apps.epg.models import EPGSource, EPGData
        from apps.channels.models import Channel

        enabled = self._get_enabled_sources(settings)
        from apps.epg.models import EPGSource as _ES
        has_fill = _ES.objects.filter(name=FILL_SOURCE_NAME).exists()
        if not enabled and not has_fill:
            return {"success": False, "message": "No virtual EPGs found to remove."}

        lines = ["Teardown complete:\n"]
        for source in enabled:
            virtual_name = f"{VIRTUAL_PREFIX}{source.name}"
            try:
                virtual = EPGSource.objects.get(name=virtual_name)
            except EPGSource.DoesNotExist:
                lines.append(f"  {source.name}: virtual EPG not found — skipped")
                continue

            source_map = {e.tvg_id: e for e in EPGData.objects.filter(epg_source=source)}
            channels = Channel.objects.filter(
                epg_data__epg_source=virtual
            ).select_related("epg_data")
            reassigned = 0
            for ch in channels:
                tvg_id = ch.epg_data.tvg_id if ch.epg_data else None
                se = source_map.get(tvg_id)
                if se:
                    ch.epg_data = se
                    ch.save(update_fields=["epg_data"])
                    reassigned += 1

            virtual.delete()
            lines.append(f"  {source.name}: virtual EPG deleted, {reassigned} channel(s) reassigned back")

        try:
            from apps.epg.models import EPGSource
            fill_src = EPGSource.objects.get(name=FILL_SOURCE_NAME)
            from apps.channels.models import Channel as _Ch
            cleared = _Ch.objects.filter(epg_data__epg_source=fill_src).count()
            _Ch.objects.filter(epg_data__epg_source=fill_src).update(epg_data=None)
            fill_src.delete()
            lines.append(f"  Fill EPG: virtual source deleted, {cleared} channel(s) cleared")
        except EPGSource.DoesNotExist:
            pass

        self._disconnect_signal()
        return {"success": True, "message": "\n".join(lines)}
