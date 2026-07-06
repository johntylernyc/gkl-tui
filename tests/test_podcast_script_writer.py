"""Tests for the Phase 3 script writer (Opus 4.6 dialogue generator)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gkl.podcast.datapack import DataPack, DataPackMeta
from gkl.podcast.script_writer import (
    Act, DialogueTurn, NO_PRIOR_EPISODES, Script, build_data_summary,
    load_draft_prompt, load_editor_prompt, load_fact_check_prompt,
    load_takeaways_prompt, normalize_line_for_tts,
    normalize_script_for_tts, parse_script,
)


# -- Parser ------------------------------------------------------------------

VALID_SCRIPT = """\
ACT 1
HOST: Welcome to the show folks.
GUEST: Big week, huh?
HOST: Absolutely. Alpha took down Beta twelve to six.

ACT 2
HOST: And we're back.
GUEST: Let's talk transactions.

ACT 3
HOST: One more before we wrap.
GUEST: Player X is the story of the week.
HOST: Until next time.
"""


def test_parse_script_returns_three_ordered_acts() -> None:
    script = parse_script(VALID_SCRIPT)
    assert [a.number for a in script.acts] == [1, 2, 3]
    assert len(script.acts[0].turns) == 3
    assert len(script.acts[1].turns) == 2
    assert len(script.acts[2].turns) == 3


def test_parse_script_preserves_speaker_case_uppercase() -> None:
    script = parse_script(VALID_SCRIPT)
    speakers = [t.speaker for a in script.acts for t in a.turns]
    assert set(speakers) == {"HOST", "GUEST"}


def test_parse_script_tolerates_preamble_before_first_act() -> None:
    with_preamble = "Here is the script:\n\n" + VALID_SCRIPT
    script = parse_script(with_preamble)
    assert script.total_turns() == 8


def test_parse_script_raises_on_unknown_line() -> None:
    bad = "ACT 1\nNARRATOR: Nope.\n"
    with pytest.raises(ValueError, match="not `HOST:` or `GUEST:`"):
        parse_script(bad)


def test_parse_script_raises_on_missing_act() -> None:
    two_acts = """\
ACT 1
HOST: A
ACT 2
HOST: B
"""
    with pytest.raises(ValueError, match="expected 3 acts"):
        parse_script(two_acts)


def test_parse_script_raises_on_out_of_order_acts() -> None:
    jumbled = """\
ACT 1
HOST: A
ACT 3
HOST: C
ACT 2
HOST: B
"""
    with pytest.raises(ValueError, match="in order 1, 2, 3"):
        parse_script(jumbled)


def test_parse_script_raises_on_empty_act() -> None:
    empty = """\
ACT 1
HOST: A

ACT 2

ACT 3
HOST: C
"""
    with pytest.raises(ValueError, match="no dialogue turns"):
        parse_script(empty)


def test_parse_script_allows_lowercase_act_header() -> None:
    lower = VALID_SCRIPT.replace("ACT 1", "act 1").replace(
        "ACT 2", "act 2").replace("ACT 3", "act 3")
    script = parse_script(lower)
    assert len(script.acts) == 3


def test_script_as_markdown_roundtrips() -> None:
    script = parse_script(VALID_SCRIPT)
    rendered = script.as_markdown()
    reparsed = parse_script(rendered)
    assert [t.speaker for a in reparsed.acts for t in a.turns] == \
           [t.speaker for a in script.acts for t in a.turns]
    assert [t.line for a in reparsed.acts for t in a.turns] == \
           [t.line for a in script.acts for t in a.turns]


# -- Data summary ------------------------------------------------------------

def _minimal_datapack() -> DataPack:
    meta = DataPackMeta(
        league_key="mlb.l.1", league_name="X", season="2026",
        segment="weekly-recap", target_week=4, current_week=5,
        week_start="2026-04-14", week_end="2026-04-20",
        generated_at="now",
    )
    return DataPack(
        meta=meta, categories=[], teams=[], roto_standings=[], h2h_records=[],
        power_rankings=[], target_week_matchups=[], rosters=[],
        target_week_rosters=[], transactions=[], mlb_games=[],
    )


def test_build_data_summary_includes_every_section() -> None:
    summary = build_data_summary(_minimal_datapack())
    assert "Scoreboard for Week 4" in summary
    assert "roto standings" in summary.lower()
    assert "Head-to-head records" in summary
    assert "Power rankings" in summary
    assert "Transactions during Week 4" in summary
    # Occasional FA topic needs the FA pool present so the fact-checker has
    # something to validate against.
    assert "Top free agents available right now" in summary
    # Act 3 momentum + occasional look-back data
    assert "momentum" in summary.lower()
    assert "Historical adds" in summary
    # New Act 2 rotating-topic data: Category Kings + Weekly Awards sources
    assert "Category leaders by scoring category" in summary
    assert "Standout individual performances this week" in summary
    # Both power-ranking tables must be present and clearly distinguished so
    # weekly claims aren't checked against the season table (and vice versa).
    assert "SEASON-cumulative all-play" in summary
    assert "WEEK 4 ONLY" in summary


def test_build_data_summary_fact_checker_gets_form_table() -> None:
    """The fact-checker variant must carry the season/last-30 form table so
    trend claims layered onto a weekly performance are verifiable."""
    summary = build_data_summary(_minimal_datapack(), include_player_stats=True)
    assert "Per-player performance for Week 4" in summary
    assert "Season and last-30-day form for every rostered player" in summary
    # The lean draft-writer variant must NOT carry the heavy form table.
    lean = build_data_summary(_minimal_datapack(), include_player_stats=False)
    assert "Season and last-30-day form for every rostered player" not in lean


# -- write_draft_script + write_takeaways (mocked Opus) ----------------------

def _three_act_script_md() -> str:
    return (
        "ACT 1\nHOST: line one.\nGUEST: line two.\n\n"
        "ACT 2\nHOST: line three.\nGUEST: line four.\n\n"
        "ACT 3\nHOST: line five.\nGUEST: line six.\n"
    )


@pytest.mark.anyio
async def test_write_draft_script_substitutes_prior_takeaways(monkeypatch) -> None:
    """Draft writer must thread prior_takeaways into the user prompt."""
    from gkl.podcast import script_writer
    captured: dict[str, str] = {}

    async def fake_call(system, user, *, model, max_tokens=8192):
        captured["system"] = system
        captured["user"] = user
        return _three_act_script_md()

    monkeypatch.setattr(script_writer, "_call_opus", fake_call)

    await script_writer.write_draft_script(
        _minimal_datapack(),
        suggested_topics_md="## Act 1\nhook\n## Act 2\nhook\n## Act 3\nhook",
        prior_takeaways="UNIQUE_PRIOR_MARKER_42",
    )

    assert "UNIQUE_PRIOR_MARKER_42" in captured["user"]


@pytest.mark.anyio
async def test_write_draft_script_uses_no_prior_sentinel_when_empty(monkeypatch) -> None:
    """Empty prior_takeaways → '(no prior episodes)' sentinel in the prompt."""
    from gkl.podcast import script_writer
    captured: dict[str, str] = {}

    async def fake_call(system, user, *, model, max_tokens=8192):
        captured["user"] = user
        return _three_act_script_md()

    monkeypatch.setattr(script_writer, "_call_opus", fake_call)

    await script_writer.write_draft_script(
        _minimal_datapack(),
        suggested_topics_md="## Act 1\nh\n## Act 2\nh\n## Act 3\nh",
        prior_takeaways="",
    )

    assert NO_PRIOR_EPISODES in captured["user"]


@pytest.mark.anyio
async def test_write_takeaways_feeds_script_into_prompt(monkeypatch) -> None:
    """Phase 3d — takeaways generator must see the final script content."""
    from gkl.podcast import script_writer
    captured: dict[str, str] = {}

    async def fake_call(system, user, *, model, max_tokens=8192):
        captured["user"] = user
        return "# Weekly Recap Takeaways — Week 4\n\nstub"

    monkeypatch.setattr(script_writer, "_call_opus", fake_call)

    script = parse_script(_three_act_script_md())
    result = await script_writer.write_takeaways(
        script, _minimal_datapack(),
    )

    # Script content flows into the user prompt
    assert "line one" in captured["user"]
    assert "line six" in captured["user"]
    # Metadata is substituted
    assert "Week **4**" in captured["user"] or "Week 4" in captured["user"]
    # Output is returned verbatim — caller writes to disk
    assert result.startswith("# Weekly Recap Takeaways")


# -- Segment prompt loading --------------------------------------------------

def test_load_draft_prompt_parses_both_sections() -> None:
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert len(prompt.system) > 500
    assert len(prompt.user) > 100
    for tok in (
        "{league_name}", "{season}", "{target_week}",
        "{week_start}", "{week_end}",
        "{suggested_topics}", "{data_summary}",
    ):
        assert tok in prompt.user, f"missing {tok} in draft user prompt"


def test_draft_prompt_requires_my_guy_greeting_in_act_1_cold_open() -> None:
    """Signature greeting: HOST addresses GUEST as 'my guy' at the top of Act 1."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    # The directive itself (look-fors anything mentioning the rule)
    assert "my guy" in prompt.system.lower(), (
        "draft prompt missing 'my guy' greeting directive"
    )


def test_draft_prompt_threads_prior_takeaways_token() -> None:
    """Continuity input — draft user prompt expects {prior_takeaways}."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert "{prior_takeaways}" in prompt.user, (
        "draft user prompt missing {prior_takeaways} token"
    )
    assert "continuity" in prompt.system.lower(), (
        "draft system prompt missing continuity guidance"
    )


def test_draft_prompt_act3_calls_for_momentum_framing() -> None:
    """Act 3 (standings tour) must instruct on momentum / heater-slump framing."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    assert "momentum" in sys_lc, "draft system prompt missing momentum guidance"
    # Both heater and slump framings should be mentioned
    assert "heater" in sys_lc or "skid" in sys_lc or "slump" in sys_lc, (
        "draft system prompt missing heater/slump language"
    )


def test_draft_prompt_act2_lists_primary_rotating_pool() -> None:
    """Act 2 must name the three primary rotating topics."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    for topic in ("category kings", "weekly awards", "regression watch"):
        assert topic in sys_lc, f"draft prompt Act 2 missing '{topic}'"


def test_draft_prompt_act2_follows_seed_topic_selection() -> None:
    """Draft prompt Act 2 must defer to the seed's 2-of-N selection and
    still know the occasional pool + the Act 3 week-ahead close."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    assert "rotating" in sys_lc, "draft prompt missing rotating-topic framing"
    assert "trade pairing" in sys_lc, "draft prompt missing trade-pairings topic"
    assert "look-back" in sys_lc, "draft prompt missing look-back topic"
    assert "week-ahead" in sys_lc or "week ahead" in sys_lc, (
        "draft prompt missing the week-ahead close"
    )


def test_draft_prompt_has_stat_layering_guidance() -> None:
    """The conditional multi-window + manager-category-color enrichment."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    assert "headline" in sys_lc, "draft prompt missing stat-layering section"
    assert "last-30" in sys_lc or "last 30" in sys_lc
    assert "conditional" in sys_lc, (
        "stat-layering must be conditional, not automatic"
    )


def test_draft_prompt_has_act_boundary_rules() -> None:
    """Acts must not poach each other's angle (awards, kings, regression)."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    assert "overlap" in sys_lc or "boundary" in sys_lc or "trap" in sys_lc, (
        "draft prompt missing act-boundary guidance"
    )
    # Regression Watch (Act 2) vs fall/rise (Act 3) must be kept distinct
    assert "fall/rise" in sys_lc or "fall and rise" in sys_lc


def test_fact_check_prompt_verifies_momentum_claims() -> None:
    """Fact checker must validate Act 3 recent-form streak claims."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_fact_check_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert "momentum" in prompt.system.lower(), (
        "fact checker missing momentum-verification rule"
    )


def test_fact_check_prompt_covers_all_rotating_topic_types() -> None:
    """Fact checker must verify every rotating topic — new primary + old."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_fact_check_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    for topic in ("category kings", "weekly awards", "regression watch"):
        assert topic in sys_lc, f"fact checker missing '{topic}' rule"
    assert "free-agent" in sys_lc or "free agent" in sys_lc
    assert "trade pairing" in sys_lc, "fact checker missing trade-pairing rule"
    assert "look-back" in sys_lc or "historical adds" in sys_lc, (
        "fact checker missing look-back rule"
    )


def test_fact_check_prompt_has_stat_accuracy_guardrails() -> None:
    """Rules for the recurring error classes we root-caused from Week 11."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_fact_check_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    # Weekly vs season power rankings
    assert "week n only" in sys_lc or "week vs season" in sys_lc
    # Player stat vs team total conflation
    assert "team total" in sys_lc
    # Near-tie ordinals
    assert "near-tie" in sys_lc or "neck-and-neck" in sys_lc
    # Category-record leadership by win percentage
    assert "win percentage" in sys_lc


def test_draft_prompt_has_stat_accuracy_traps() -> None:
    """Draft writer must be warned about the same recurring traps."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_draft_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    assert "best team this week" in sys_lc
    assert "team total" in sys_lc
    assert "near-tie" in sys_lc or "neck and neck" in sys_lc


def test_fact_check_prompt_verifies_layered_and_statcast_claims() -> None:
    """Fact checker must verify trend/season context, category-rank color,
    and Statcast figures (via the seed's suggested-topics)."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_fact_check_prompt(DEFAULT_SEGMENT_ARTIFACT)
    sys_lc = prompt.system.lower()
    # Trend/season verification against the form table
    assert "season and last-30-day form" in sys_lc or "form table" in sys_lc
    # Category-rank color verification
    assert "category leaders" in sys_lc
    # Statcast cross-checked against the seed
    assert "statcast" in sys_lc
    assert "{suggested_topics}" in prompt.user, (
        "fact-check user prompt missing {suggested_topics} token"
    )


def test_load_takeaways_prompt_parses_both_sections() -> None:
    """Phase 3d — takeaways generator must have System + User sections."""
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_takeaways_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert len(prompt.system) > 200
    for tok in (
        "{league_name}", "{season}", "{target_week}", "{final_script}",
    ):
        assert tok in prompt.user, f"missing {tok} in takeaways user prompt"
    # Takeaways must NOT receive the data pack — it's a script summarizer,
    # not a fact source.
    assert "{data_summary}" not in prompt.user


def test_load_fact_check_prompt_parses_both_sections() -> None:
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_fact_check_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert len(prompt.system) > 500
    # Fact checker needs the data pack + the seed + the draft to validate
    for tok in ("{league_name}", "{target_week}",
                "{data_summary}", "{suggested_topics}", "{draft_script}"):
        assert tok in prompt.user, f"missing {tok} in fact-check user prompt"


def test_load_editor_prompt_parses_both_sections() -> None:
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_editor_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert len(prompt.system) > 500
    # Editor only needs the fact-checked script — no new stats to inject
    for tok in ("{league_name}", "{target_week}", "{fact_checked_script}"):
        assert tok in prompt.user, f"missing {tok} in editor user prompt"
    # Editor must NOT get the raw data summary (no new stats, by design)
    assert "{data_summary}" not in prompt.user


# -- Orchestrator ----------------------------------------------------------

@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# -- TTS-readability normalization -------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    # Batting averages / OBP / SLG — .XXX form
    ("hit .316 last week", "hit three sixteen last week"),
    ("with a .563 slugging", "with a five sixty-three slugging"),
    ("OBP of 0.392", "on base percentage of three ninety-two"),
    ("a .500 average", "a five hundred average"),
    ("only .023", "only twenty-three"),
    ("a .105 mark", "a one oh five mark"),
    ("hit .000 in the series", "hit zero in the series"),
    # Rate stats — X.XX form. ERA/WHIP themselves stay as-is per
    # _TTS_NORMALIZATIONS (TTS handles them naturally).
    ("with a 2.85 ERA", "with a two eighty-five ERA"),
    ("WHIP of 1.21", "WHIP of one twenty-one"),
    ("0.95 WHIP this month", "zero ninety-five WHIP this month"),
    ("3.00 ERA flat", "three flat ERA flat"),
    # Don't touch things that aren't stats
    ("12 home runs", "12 home runs"),
    ("won 3 of 4 matchups", "won 3 of 4 matchups"),
])
def test_normalize_line_for_tts_converts_decimal_stats(
    raw: str, expected: str,
) -> None:
    assert normalize_line_for_tts(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("His OBP is up", "His on base percentage is up"),
    ("xBA is 340", "expected batting average is 340"),
    ("an xSLG of 550", "an expected slugging percentage of 550"),
    ("wRC+ of 160", "weighted runs created plus of 160"),
    ("wOBA is elite", "weighted on base average is elite"),
    ("his K/9 is ridiculous", "his strikeouts per nine is ridiculous"),
    ("top of the BB% leaderboard", "top of the walk rate leaderboard"),
    ("over the L30", "over the last thirty days"),
    ("in the L7", "in the last seven days"),
    ("stashed on IL", "stashed on injured list"),
    ("buried on BN", "buried on bench"),
    ("his SP depth", "his starting pitcher depth"),
    ("every RP on the roster", "every relief pitcher on the roster"),
    ("top H2H record", "top head to head record"),
    ("their h2h numbers", "their head to head numbers"),
    ("an h2H mix", "an head to head mix"),
    ("babip neutralized", "babip neutralized"),  # kept as word
])
def test_normalize_line_for_tts_expands_common_abbreviations(
    raw: str, expected: str,
) -> None:
    assert normalize_line_for_tts(raw) == expected


@pytest.mark.parametrize("line", [
    "His ERA was elite",
    "14 RBI last week",
    "MLB Network had the breakdown",
    "OPS leader for the week",
    "AVG is just decoration",
    "three HR on Tuesday",
    "one SB on a bad jump",
    "solid WHIP numbers",
])
def test_normalize_leaves_common_pronounced_abbreviations(line: str) -> None:
    """ERA, RBI, MLB, OPS, AVG, HR, SB, WHIP are said naturally as-is —
    real broadcasters pronounce them, so TTS gets them right. Lines here
    are chosen without decimal stats so this test isolates abbreviation
    behavior from the decimal-normalization pass."""
    assert normalize_line_for_tts(line) == line


def test_normalize_uses_word_boundaries() -> None:
    """We must not corrupt substrings that happen to contain an abbreviation.
    E.g. 'IL' should not match inside 'pivotal' or 'will'."""
    assert normalize_line_for_tts("pivotal week") == "pivotal week"
    assert normalize_line_for_tts("will IL him again") == "will injured list him again"


def test_normalize_script_for_tts_preserves_structure() -> None:
    script = Script(acts=[
        Act(number=1, turns=[
            DialogueTurn(speaker="HOST", line="His OBP is elite"),
            DialogueTurn(speaker="GUEST", line="Agreed"),
        ]),
        Act(number=2, turns=[
            DialogueTurn(speaker="HOST", line="Stashed on IL for now"),
        ]),
        Act(number=3, turns=[
            DialogueTurn(speaker="GUEST", line="xBA says he's for real"),
        ]),
    ])
    normalized = normalize_script_for_tts(script)
    # Structure preserved
    assert [a.number for a in normalized.acts] == [1, 2, 3]
    assert [len(a.turns) for a in normalized.acts] == [2, 1, 1]
    # Speakers preserved
    assert normalized.acts[0].turns[0].speaker == "HOST"
    # Abbreviations expanded
    assert normalized.acts[0].turns[0].line == "His on base percentage is elite"
    assert normalized.acts[1].turns[0].line == "Stashed on injured list for now"
    assert normalized.acts[2].turns[0].line == \
        "expected batting average says he's for real"
    # Original untouched (immutable-friendly)
    assert script.acts[0].turns[0].line == "His OBP is elite"


# -- Orchestrator -----------------------------------------------------------

@pytest.mark.anyio
async def test_write_script_runs_all_three_steps_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator must run draft → fact-check → edit in that order,
    passing each step's output forward."""
    from gkl.podcast import script_writer
    calls: list[str] = []

    def _one_act_script(label: str) -> Script:
        return Script(acts=[
            Act(number=n, turns=[
                DialogueTurn(speaker="HOST", line=f"{label} act {n}"),
            ])
            for n in (1, 2, 3)
        ])

    async def fake_draft(datapack, suggested_topics_md, **kw):
        calls.append("draft")
        return _one_act_script("draft")

    async def fake_fact_check(draft, datapack, **kw):
        calls.append(f"fact_check(input={draft.acts[0].turns[0].line})")
        return _one_act_script("fact_checked")

    async def fake_edit(fact_checked, datapack, **kw):
        calls.append(f"edit(input={fact_checked.acts[0].turns[0].line})")
        return _one_act_script("final")

    monkeypatch.setattr(script_writer, "write_draft_script", fake_draft)
    monkeypatch.setattr(script_writer, "fact_check_script", fake_fact_check)
    monkeypatch.setattr(script_writer, "edit_script", fake_edit)

    versions = await script_writer.write_script(
        datapack=_minimal_datapack(), suggested_topics_md="topics",
    )

    # Steps ran in order
    assert calls[0] == "draft"
    # Fact-check received the draft's output
    assert calls[1] == "fact_check(input=draft act 1)"
    # Editor received the fact-checker's output
    assert calls[2] == "edit(input=fact_checked act 1)"
    # All three versions returned
    assert versions.draft.acts[0].turns[0].line == "draft act 1"
    assert versions.fact_checked.acts[0].turns[0].line == "fact_checked act 1"
    assert versions.final.acts[0].turns[0].line == "final act 1"
