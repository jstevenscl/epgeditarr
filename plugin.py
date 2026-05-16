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

# Sport team → sort anchor (float places teams at end of their league's play-by-play block)
# MLB 175-189, NBA 212-217, NHL 219-223, NFL 225-234
_SPORT_TEAM_SORT = {
    # NFL (anchor 234.5 — after slot 234, before next block)
    "arizona cardinals": 234.5, "atlanta falcons": 234.5, "baltimore ravens": 234.5,
    "buffalo bills": 234.5, "carolina panthers": 234.5, "chicago bears": 234.5,
    "cincinnati bengals": 234.5, "cleveland browns": 234.5, "dallas cowboys": 234.5,
    "denver broncos": 234.5, "detroit lions": 234.5, "green bay packers": 234.5,
    "houston texans": 234.5, "indianapolis colts": 234.5, "jacksonville jaguars": 234.5,
    "kansas city chiefs": 234.5, "las vegas raiders": 234.5, "los angeles chargers": 234.5,
    "los angeles rams": 234.5, "miami dolphins": 234.5, "minnesota vikings": 234.5,
    "new england patriots": 234.5, "new orleans saints": 234.5, "new york giants": 234.5,
    "new york jets": 234.5, "philadelphia eagles": 234.5, "pittsburgh steelers": 234.5,
    "san francisco 49ers": 234.5, "seattle seahawks": 234.5, "tampa bay buccaneers": 234.5,
    "tennessee titans": 234.5, "washington commanders": 234.5,
    # NBA (anchor 217.5 — after slot 217, before NHL at 219)
    "atlanta hawks": 217.5, "boston celtics": 217.5, "brooklyn nets": 217.5,
    "charlotte hornets": 217.5, "chicago bulls": 217.5, "cleveland cavaliers": 217.5,
    "dallas mavericks": 217.5, "denver nuggets": 217.5, "detroit pistons": 217.5,
    "golden state warriors": 217.5, "houston rockets": 217.5, "indiana pacers": 217.5,
    "los angeles clippers": 217.5, "los angeles lakers": 217.5, "memphis grizzlies": 217.5,
    "miami heat": 217.5, "milwaukee bucks": 217.5, "minnesota timberwolves": 217.5,
    "new orleans pelicans": 217.5, "new york knicks": 217.5, "oklahoma city thunder": 217.5,
    "orlando magic": 217.5, "philadelphia 76ers": 217.5, "phoenix suns": 217.5,
    "portland trail blazers": 217.5, "sacramento kings": 217.5, "san antonio spurs": 217.5,
    "toronto raptors": 217.5, "utah jazz": 217.5, "washington wizards": 217.5,
    # NHL (anchor 223.5 — after slot 223, before NFL at 225)
    "anaheim ducks": 223.5, "boston bruins": 223.5, "buffalo sabres": 223.5,
    "calgary flames": 223.5, "carolina hurricanes": 223.5, "chicago blackhawks": 223.5,
    "colorado avalanche": 223.5, "columbus blue jackets": 223.5, "dallas stars": 223.5,
    "detroit red wings": 223.5, "edmonton oilers": 223.5, "florida panthers": 223.5,
    "los angeles kings": 223.5, "minnesota wild": 223.5, "montreal canadiens": 223.5,
    "nashville predators": 223.5, "new jersey devils": 223.5, "new york islanders": 223.5,
    "new york rangers": 223.5, "ottawa senators": 223.5, "philadelphia flyers": 223.5,
    "pittsburgh penguins": 223.5, "san jose sharks": 223.5, "seattle kraken": 223.5,
    "st. louis blues": 223.5, "tampa bay lightning": 223.5, "toronto maple leafs": 223.5,
    "utah mammoth": 223.5, "vancouver canucks": 223.5, "vegas golden knights": 223.5,
    "washington capitals": 223.5, "winnipeg jets": 223.5,
    # MLB (anchor 189.5 — after slot 189, before SEC at 190)
    "arizona diamondbacks": 189.5, "atlanta braves": 189.5, "athletics": 189.5,
    "baltimore orioles": 189.5, "boston red sox": 189.5, "chicago cubs": 189.5,
    "chicago white sox": 189.5, "cincinnati reds": 189.5, "cleveland guardians": 189.5,
    "colorado rockies": 189.5, "detroit tigers": 189.5, "houston astros": 189.5,
    "kansas city royals": 189.5, "los angeles angels": 189.5, "los angeles dodgers": 189.5,
    "miami marlins": 189.5, "milwaukee brewers": 189.5, "minnesota twins": 189.5,
    "new york mets": 189.5, "new york yankees": 189.5, "philadelphia phillies": 189.5,
    "pittsburgh pirates": 189.5, "san diego padres": 189.5, "san francisco giants": 189.5,
    "seattle mariners": 189.5, "st. louis cardinals": 189.5, "tampa bay rays": 189.5,
    "texas rangers": 189.5, "toronto blue jays": 189.5, "washington nationals": 189.5,
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
    version = "0.1.1"
    description = (
        "Transform EPG program data into virtual EPG sources using "
        "per-source, per-field regex and find/replace rules. "
        "Also generates fill EPG schedules for channels with no EPG data."
    )

    def __init__(self):
        self._signal_uid = "epgeditarr_transform"
        self.fields = self._build_fields()
        LOGGER.info("EPGeditARR: initialized")
        self._connect_signal()

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
                "Generate a repeating dummy EPG schedule for channels that have no EPG data. "
                "Use 'Scan' to discover which channels need filling, then set Fill Groups "
                "and optionally add channel names to Skip Channels.\n\n"
                "Enable SiriusXM Enrichment to match channel names against SiriusXM's lineup "
                "from Wikipedia, giving matched channels real descriptions in the generated schedule."
            ),
        },
        {
            "id": "fill_groups",
            "label": "Fill Groups",
            "type": "text",
            "default": "",
            "placeholder": "e.g. SiriusXM, Radio",
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
        {
            "id": "_section_siriusxm",
            "label": "── SiriusXM Channels Only ──────────────────────",
            "type": "info",
            "description": (
                "The settings and actions below apply exclusively to SiriusXM channels. "
                "Channel data (names, descriptions, lineup order) is fetched from Wikipedia "
                "and cached locally. Cache auto-refreshes every 7 days — use 'Refresh Channel Data' "
                "to force an immediate update. Channel names are matched case-insensitively with "
                "fuzzy fallbacks for common variations (leading quotes, 'The ' prefix, '&' vs 'and')."
            ),
        },
        {
            "id": "fill_sxm_enrich",
            "label": "Enable SiriusXM Enrichment",
            "type": "boolean",
            "default": False,
            "help_text": (
                "SiriusXM only — matches channel names against the Wikipedia lineup and adds real "
                "descriptions to generated EPG entries. Also required for Sort to work."
            ),
        },
        {
            "id": "sort_start_number",
            "label": "Sort Start Number",
            "type": "text",
            "default": "",
            "placeholder": "Auto-detect from current channel range",
            "help_text": (
                "SiriusXM only — channel number assigned to the first sorted channel. "
                "Leave blank to automatically use the lowest channel number in your Fill Groups."
            ),
        },
    ]

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
            sources = list(EPGSource.objects.exclude(source_type="dummy").order_by("name"))
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

        return fields + self._channel_scope_fields + self._fill_fields + tester_fields

    # ── Signal management ─────────────────────────────────────────────────
    # One signal watches all EPGSources. On each successful refresh it reads
    # current settings from the DB (so rule changes take effect immediately
    # without re-running Setup) and transforms the matching source.

    def _connect_signal(self):
        from apps.epg.models import EPGSource
        from django.db.models.signals import post_save

        def _on_epg_refresh(sender, instance, **kwargs):
            if instance.source_type == "dummy":
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

    def stop(self, context):
        self._disconnect_signal()

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
        return "\n".join(lines) if lines else "    (no rules configured)"

    # ── EPG helpers ───────────────────────────────────────────────────────

    def _get_enabled_sources(self, settings):
        """Return list of EPGSource instances that have been enabled in settings."""
        from apps.epg.models import EPGSource
        results = []
        for source in EPGSource.objects.exclude(source_type="dummy").order_by("name"):
            if settings.get(f"src_{source.id}_enabled", False):
                results.append(source)
        return results

    def _get_or_create_virtual(self, source):
        from apps.epg.models import EPGSource
        virtual_name = f"{VIRTUAL_PREFIX}{source.name}"
        virtual, created = EPGSource.objects.get_or_create(
            name=virtual_name,
            defaults={
                "source_type": "dummy",
                "custom_properties": {"epgeditarr_source_id": source.id},
            },
        )
        if not created:
            props = dict(virtual.custom_properties or {})
            props["epgeditarr_source_id"] = source.id
            virtual.custom_properties = props
            virtual.save(update_fields=["custom_properties"])
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

    @staticmethod
    def _normalize_channel_name(name):
        """Return a consistent lowercase key for channel name matching.

        Handles leading curly/straight quotes (e.g. Wikipedia ‘'40s Junction’),
        trailing parentheticals, and Wikipedia footnote markers.
        """
        name = re.sub(r"^[\'\"‘’“”\s]+", '', name)
        name = re.sub(r'\s*\[[^\]]{1,5}\]', '', name)
        name = re.sub(r'\s*\(.*', '', name)
        return name.lower().strip()

    @staticmethod
    def _fuzzy_channel_keys(name):
        """Return normalized lookup keys to try for a channel name (most specific first).

        Generates prefix variants (strip/add 'the '/'siriusxm ') and suffix variants
        (strip/add ' radio'/' channel'/' network'/' live') so names like 'Holly' match
        'SiriusXM Holly', 'Grateful Dead' matches 'The Grateful Dead Channel', etc.
        Also strips trailing lone digits so 'Limited Edition 1' matches 'Limited Edition'.
        """
        base = Plugin._normalize_channel_name(name)
        seen, keys = {base}, [base]

        def add(k):
            if k and len(k) >= 2 and k not in seen:
                seen.add(k)
                keys.append(k)

        # Prefix variants: strip or add 'the ' / 'siriusxm '
        no_the  = base[4:] if base.startswith('the ') else None
        no_sxm  = base[9:] if base.startswith('siriusxm ') else None
        with_the = None if base.startswith('the ') else 'the ' + base
        with_sxm = None if base.startswith('siriusxm ') else 'siriusxm ' + base
        for v in (no_the, no_sxm, with_the, with_sxm):
            if v: add(v)

        # Suffix variants for each prefix variant
        SUFFIXES = (' radio', ' channel', ' network', ' live')
        for b in (base, no_the, no_sxm, with_the, with_sxm):
            if not b:
                continue
            for sfx in SUFFIXES:
                if b.endswith(sfx):
                    add(b[:-len(sfx)])
                else:
                    add(b + sfx)

        # & ↔ and for all variants collected so far
        for k in list(keys):
            amp = re.sub(r'\s+&\s+', ' and ', k)
            if amp != k: add(amp)
            andd = re.sub(r'\band\b', '&', k)
            if andd != k: add(andd)

        return keys

    def _lookup_enrich(self, cache, name):
        """Try multiple normalized variants of name against cache; return first hit or {}."""
        for key in self._fuzzy_channel_keys(name):
            hit = cache.get(key)
            if hit:
                return hit
        return {}

    def _channel_tvg_id(self, channel_name):
        slug = re.sub(r'[^a-z0-9]+', '-', channel_name.lower()).strip('-')
        return f"epgeditarr-fill-{slug}"

    def _get_fill_channels(self, settings):
        """Return Channel objects eligible for fill EPG (in fill groups, no EPG or already on fill source)."""
        from django.db.models import Q
        from apps.channels.models import Channel
        from apps.epg.models import EPGSource

        fill_group_names = [g.strip() for g in (settings.get('fill_groups') or '').split(',') if g.strip()]
        if not fill_group_names:
            return []

        try:
            fill_src = EPGSource.objects.get(name=FILL_SOURCE_NAME)
            qs = Channel.objects.filter(channel_group__name__in=fill_group_names).filter(
                Q(epg_data__isnull=True) | Q(epg_data__epg_source=fill_src)
            )
        except EPGSource.DoesNotExist:
            qs = Channel.objects.filter(
                channel_group__name__in=fill_group_names,
                epg_data__isnull=True,
            )

        skip = {n.strip().lower() for n in (settings.get('fill_skip_channels') or '').splitlines() if n.strip()}
        return [c for c in qs.select_related('channel_group') if c.name.lower() not in skip]

    def _load_sxm_cache(self, settings):
        """Return (cache_dict, was_refreshed). Auto-refreshes if stale or missing.

        Always reads from the database — frontend-provided settings may carry a
        stale cached blob that pre-dates a recent Refresh Channel Data call.
        """
        from datetime import datetime
        from apps.plugins.models import PluginConfig

        cfg = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
        db_settings = cfg.settings or {} if cfg else {}

        cache = db_settings.get(FILL_CACHE_KEY) or {}
        updated_str = db_settings.get(FILL_CACHE_UPDATED_KEY) or ''

        has_sxm = any(v.get('sxm_number') is not None for v in cache.values())
        if cache and updated_str and has_sxm:
            try:
                updated = datetime.fromisoformat(updated_str)
                if (datetime.utcnow() - updated).days < FILL_CACHE_TTL_DAYS:
                    return cache, False
            except Exception:
                pass

        fresh = self._fetch_sxm_data()
        self._save_fill_cache(fresh)
        return fresh, True

    def _save_fill_cache(self, data):
        from datetime import datetime
        from apps.plugins.models import PluginConfig

        cfg = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
        if not cfg:
            return
        s = dict(cfg.settings or {})
        s[FILL_CACHE_KEY] = data
        s[FILL_CACHE_UPDATED_KEY] = datetime.utcnow().isoformat()
        cfg.settings = s
        cfg.save(update_fields=['settings'])

    def _fetch_sxm_data(self):
        """Fetch SiriusXM channel data. Tries GitHub Pages pre-built cache first, falls back to Wikipedia."""
        import urllib.request
        import json

        headers = {"User-Agent": "EPGeditARR-Plugin/2.0 (Dispatcharr plugin; github.com/jstevenscl/epgeditarr)"}

        # Primary: GitHub Pages pre-built cache (Wikipedia + siriusxm.com merged)
        cache_url = "https://jstevenscl.github.io/epgeditarr/channels.json"
        try:
            req = urllib.request.Request(cache_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data:
                has_numbers = sum(1 for v in data.values() if v.get("sxm_number") is not None)
                LOGGER.info(f"EPGeditARR: fetched {len(data)} channels from GitHub cache ({has_numbers} with lineup positions)")
                return data
        except Exception as e:
            LOGGER.warning(f"EPGeditARR: GitHub cache unavailable ({e}), falling back to Wikipedia")

        # Fallback: fetch Wikipedia directly
        return self._fetch_from_wikipedia()

    def _fetch_from_wikipedia(self):
        """Fetch SiriusXM channel data directly from Wikipedia (fallback)."""
        import urllib.request
        import json

        headers = {"User-Agent": "EPGeditARR-Plugin/2.0 (Dispatcharr plugin; github.com/jstevenscl/epgeditarr)"}

        candidate_pages = [
            "List_of_SiriusXM_Radio_channels",
            "List_of_SiriusXM_channels",
            "List_of_Sirius_XM_channels",
        ]
        last_error = "no candidates tried"

        for page in candidate_pages:
            url = (
                f"https://en.wikipedia.org/w/api.php"
                f"?action=parse&page={page}&prop=text&format=json&redirects=1"
            )
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_error = f"network error fetching '{page}': {e}"
                continue

            if "error" in raw:
                last_error = f"Wikipedia API error for '{page}': {raw['error'].get('info', raw['error'])}"
                LOGGER.debug(f"EPGeditARR: {last_error}")
                continue

            html = raw.get("parse", {}).get("text", {}).get("*", "")
            if not html:
                last_error = f"empty HTML for '{page}' (keys: {list(raw.get('parse', {}).keys())})"
                continue

            result = self._parse_wiki_tables(html)
            if result:
                LOGGER.info(f"EPGeditARR: fetched {len(result)} SiriusXM channels from Wikipedia '{page}'")
                return result
            last_error = f"no parseable channel tables found in '{page}'"

        raise RuntimeError(f"Could not fetch SiriusXM data — {last_error}")

    def _parse_wiki_tables(self, html):
        """Parse MediaWiki HTML tables → dict of lowercased_name → {name, description, genre}."""
        channels = {}

        def clean(text):
            text = re.sub(r'<[^>]+>', ' ', text)
            for ent, rep in [
                ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                ('&nbsp;', ' '), ('&#160;', ' '), ('&#39;', "'"), ('&quot;', '"'),
            ]:
                text = text.replace(ent, rep)
            return re.sub(r'\s+', ' ', text).strip()

        for table_m in re.finditer(
            r'<table[^>]+class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>',
            html, re.DOTALL | re.IGNORECASE
        ):
            table = table_m.group(1)
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL | re.IGNORECASE)
            if len(rows) < 2:
                continue

            headers = []
            for row in rows:
                ths = re.findall(r'<th[^>]*>(.*?)</th>', row, re.DOTALL | re.IGNORECASE)
                if ths:
                    headers = [clean(h).lower() for h in ths]
                    break
            if not headers:
                continue

            name_idx = next((i for i, h in enumerate(headers) if 'name' in h), None)
            desc_idx = next((i for i, h in enumerate(headers) if 'descri' in h or ('format' in h and 'name' not in h)), None)
            genre_idx = next((i for i, h in enumerate(headers) if 'genre' in h), None)
            num_idx = next((
                i for i, h in enumerate(headers)
                if h in ('channel', 'ch', 'ch.', '#', 'no.', 'no', 'number',
                         'siriusxm', 'sirius xm', 'sirius',
                         'siriusxm #', 'xm #', 'sirius #') and 'name' not in h
            ), None)
            if name_idx is None:
                continue

            for row in rows:
                tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
                if not tds or name_idx >= len(tds):
                    continue

                name = clean(tds[name_idx])
                name_key = self._normalize_channel_name(name)
                if not name_key or len(name_key) < 2 or name_key in ('tba', 'tbd', 'vacant', 'n/a', '—', '-'):
                    continue

                desc = clean(tds[desc_idx]) if desc_idx is not None and desc_idx < len(tds) else ''
                genre = clean(tds[genre_idx]) if genre_idx is not None and genre_idx < len(tds) else ''

                sxm_number = None
                if num_idx is not None and num_idx < len(tds):
                    num_raw = re.sub(r'\[.*?\]', '', clean(tds[num_idx])).strip()
                    m = re.match(r'\d+', num_raw)
                    if m:
                        sxm_number = int(m.group())

                channels[name_key] = {'name': name, 'description': desc, 'genre': genre, 'sxm_number': sxm_number}

        return channels

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
            ).prefetch_related("programs")
        else:
            source_entries = EPGData.objects.filter(epg_source=source).prefetch_related("programs")

        total = 0
        with transaction.atomic():
            ProgramData.objects.filter(epg__epg_source=virtual).delete()
            batch = []
            for se in source_entries:
                ve = virtual_map.get(se.tvg_id)
                if not ve:
                    continue
                for prog in se.programs.all():
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
                        custom_properties=prog.custom_properties,
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
            "sort_epg":               self._action_sort_epg,
            "fill_and_sort":          self._action_fill_and_sort,
            "refresh_channel_data":   self._action_refresh_channel_data,
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

        sources = list(EPGSource.objects.exclude(source_type="dummy").order_by("name"))
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

        channels_no_epg = (
            Channel.objects
            .filter(epg_data__isnull=True)
            .select_related('channel_group')
            .order_by('channel_group__name', 'name')
        )

        by_group = defaultdict(list)
        for ch in channels_no_epg:
            gname = ch.channel_group.name if ch.channel_group else '(no group)'
            by_group[gname].append(ch.name)

        fill_count = 0
        try:
            fill_src = EPGSource.objects.get(name=FILL_SOURCE_NAME)
            fill_count = Channel.objects.filter(epg_data__epg_source=fill_src).count()
        except EPGSource.DoesNotExist:
            pass

        if not by_group and not fill_count:
            return {"success": True, "message": "No channels without EPG found. All channels have EPG data assigned."}

        total = sum(len(v) for v in by_group.values())
        in_fill = sum(len(v) for g, v in by_group.items() if g in fill_group_names)

        lines = ["── Channels with no EPG ──\n"]
        for gname in sorted(by_group.keys()):
            names = sorted(by_group[gname])
            tag = "✓ Fill Group" if gname in fill_group_names else "not in Fill Groups"
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
        use_enrich = settings.get('fill_sxm_enrich', False)

        enrich_cache = {}
        enrich_msg = ''
        if use_enrich:
            try:
                enrich_cache, refreshed = self._load_sxm_cache(settings)
                enrich_msg = (
                    f' — SiriusXM data refreshed ({len(enrich_cache):,} channels)'
                    if refreshed else
                    f' — SiriusXM cache: {len(enrich_cache):,} channels'
                )
            except Exception as e:
                enrich_msg = f' — SiriusXM enrichment unavailable: {e}'
                LOGGER.warning(f"EPGeditARR: SiriusXM enrichment failed: {e}")

        channels = self._get_fill_channels(settings)
        if not channels:
            return {
                "success": False,
                "message": (
                    f"No channels found in Fill Groups {fill_group_names!r} with no EPG "
                    f"(or all are in Skip Channels). Run Scan to see what's available."
                ),
            }

        fill_source, _ = EPGSource.objects.get_or_create(
            name=FILL_SOURCE_NAME,
            defaults={"source_type": "dummy", "custom_properties": {"epgeditarr_fill": True}},
        )

        existing_epgdata = {e.tvg_id: e for e in EPGData.objects.filter(epg_source=fill_source)}
        total_programs = 0
        matched_enrich = 0

        with transaction.atomic():
            ProgramData.objects.filter(epg__epg_source=fill_source).delete()

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

                enrich = self._lookup_enrich(enrich_cache, ch.name)
                if enrich:
                    matched_enrich += 1
                description = enrich.get('description', '')

                programs = self._generate_fill_blocks(epg_entry, ch.name, description, block_hours, days_ahead)
                batch.extend(programs)
                total_programs += len(programs)

                if len(batch) >= 2000:
                    ProgramData.objects.bulk_create(batch)
                    batch = []

            if batch:
                ProgramData.objects.bulk_create(batch)

        fill_source.status = "success"
        fill_source.last_message = f"Fill EPG: {len(channels):,} channels, {total_programs:,} program blocks"
        fill_source.save(update_fields=["status", "last_message"])

        skip_count = len({n.strip().lower() for n in (settings.get('fill_skip_channels') or '').splitlines() if n.strip()})
        lines = [
            f"Fill EPG complete{enrich_msg}\n",
            f"  Channels filled : {len(channels):,}",
            f"  Programs written: {total_programs:,}  ({block_hours}h blocks × {days_ahead} days)",
            f"  Groups targeted : {', '.join(fill_group_names)}",
        ]
        if skip_count:
            lines.append(f"  Channels skipped: {skip_count:,}")
        if use_enrich:
            lines.append(f"  SiriusXM matched: {matched_enrich:,} / {len(channels):,} channels")

        return {"success": True, "message": "\n".join(lines)}

    def _action_refresh_channel_data(self, settings, logger):
        try:
            data = self._fetch_sxm_data()
            self._save_fill_cache(data)
            has_numbers = sum(1 for v in data.values() if v.get('sxm_number') is not None)
            return {
                "success": True,
                "message": (
                    f"SiriusXM channel data refreshed from Wikipedia.\n"
                    f"{len(data):,} channels cached ({has_numbers} with lineup position)."
                ),
            }
        except Exception as e:
            LOGGER.error(f"EPGeditARR: Wikipedia fetch failed: {e}")
            return {"success": False, "message": f"Failed to fetch SiriusXM data: {e}"}

    def _action_sort_epg(self, settings, logger):
        fill_group_names = [g.strip() for g in (settings.get('fill_groups') or '').split(',') if g.strip()]
        if not fill_group_names:
            return {"success": False, "message": "No Fill Groups configured. Add group names in Settings → EPG Fill."}

        start_number_raw = (settings.get('sort_start_number') or '').strip()
        if start_number_raw:
            try:
                start_number = int(start_number_raw)
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid Sort Start Number: {start_number_raw!r} — enter a whole number or leave blank to auto-detect."}
            auto_detected = False
        else:
            auto_detected = True
            start_number = None  # resolved after channels are loaded

        try:
            enrich_cache, _ = self._load_sxm_cache(settings)
        except Exception as e:
            return {
                "success": False,
                "message": (
                    f"SiriusXM lineup data unavailable: {e}\n"
                    "Enable SiriusXM Enrichment and run 'Refresh Channel Data' first."
                ),
            }

        if not enrich_cache:
            return {
                "success": False,
                "message": "SiriusXM channel cache is empty. Enable SiriusXM Enrichment and run 'Refresh Channel Data'.",
            }

        from apps.channels.models import Channel
        skip = {n.strip().lower() for n in (settings.get('fill_skip_channels') or '').splitlines() if n.strip()}
        all_channels = [
            ch for ch in
            Channel.objects.filter(channel_group__name__in=fill_group_names)
                           .select_related('channel_group')
                           .order_by('channel_number', 'name')
            if ch.name.lower() not in skip
        ]

        if not all_channels:
            return {"success": False, "message": f"No channels found in Fill Groups {fill_group_names!r}."}

        if auto_detected:
            nums = [ch.channel_number for ch in all_channels if ch.channel_number is not None]
            start_number = int(min(nums)) if nums else 1

        # Build sort key for each channel:
        # 1. Wikipedia sxm_number (authoritative)
        # 2. Number embedded in channel name (e.g. "Sports 963" → 963, "ACC 955" → 955)
        # 3. float('inf') — truly unresolvable, placed at the very end
        def _name_number(name):
            m = re.search(r'\b(\d{3,4})\b', name)
            return int(m.group(1)) if m else None

        numbered = []    # (sort_key, ch) — Wikipedia match, sport block, or embedded number
        no_number = []   # no number source at all → placed after numbered
        wiki_matched = 0
        sport_matched = 0
        name_matched = 0

        for ch in all_channels:
            enrich = self._lookup_enrich(enrich_cache, ch.name)
            sxm_num = enrich.get('sxm_number')
            if sxm_num is not None:
                numbered.append((sxm_num, ch))
                wiki_matched += 1
            else:
                sport_anchor = _SPORT_TEAM_SORT.get(self._normalize_channel_name(ch.name))
                if sport_anchor is not None:
                    numbered.append((sport_anchor, ch))
                    sport_matched += 1
                else:
                    embedded = _name_number(ch.name)
                    if embedded is not None:
                        numbered.append((embedded, ch))
                        name_matched += 1
                    else:
                        no_number.append(ch)

        numbered.sort(key=lambda x: x[0])
        # Sort truly-unmatched by current channel_number then name for stability
        no_number.sort(key=lambda ch: (ch.channel_number if ch.channel_number is not None else float('inf'), ch.name))
        ordered = [ch for _, ch in numbered] + no_number

        updated = 0
        for i, ch in enumerate(ordered):
            new_num = start_number + i
            if getattr(ch, 'channel_number', None) != new_num:
                ch.channel_number = new_num
                ch.save(update_fields=['channel_number'])
                updated += 1

        start_note = " (auto-detected)" if auto_detected else ""
        lines = [
            f"Sort complete — {len(ordered):,} channels renumbered from {start_number}{start_note}\n",
            f"  Matched via Wikipedia      : {wiki_matched:,}",
            f"  Matched via sport block    : {sport_matched:,}",
            f"  Matched via name number    : {name_matched:,}",
            f"  No match (placed at end)   : {len(no_number):,}",
            f"  Channel numbers updated    : {updated:,}",
        ]
        if no_number:
            lines.append(f"\nChannels with no lineup position (placed at end):")
            for ch in no_number:
                lines.append(f"  {ch.name}")
            lines.append(
                "\nTip: Check these names against SiriusXM's lineup for abbreviations "
                "or alternate names. Run 'Refresh Channel Data' to pull the latest list."
            )

        return {"success": True, "message": "\n".join(lines)}

    def _action_fill_and_sort(self, settings, logger):
        fill_result = self._action_fill_epg(settings, logger)
        sort_result = self._action_sort_epg(settings, logger)
        parts = []
        if fill_result.get("message"):
            parts.append("── Fill EPG ──\n" + fill_result["message"])
        if sort_result.get("message"):
            parts.append("── Sort ──\n" + sort_result["message"])
        success = fill_result.get("success", False) or sort_result.get("success", False)
        return {"success": success, "message": "\n\n".join(parts)}

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
