"""Tests for the Phase 3 script writer (Opus 4.6 dialogue generator)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gkl.podcast.datapack import DataPack, DataPackMeta
from gkl.podcast.script_writer import (
    Act, DialogueTurn, Script, build_data_summary, load_draft_prompt,
    load_editor_prompt, load_fact_check_prompt,
    normalize_line_for_tts, normalize_script_for_tts, parse_script,
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
    # Act 3 (free-agent pickups) needs the FA pool always present in the
    # summary so the fact-checker has something to validate against.
    assert "Top free agents available right now" in summary


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


def test_load_fact_check_prompt_parses_both_sections() -> None:
    from gkl.podcast.skipper_seed import DEFAULT_SEGMENT_ARTIFACT
    prompt = load_fact_check_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert len(prompt.system) > 500
    # Fact checker needs the data pack + the draft to validate against
    for tok in ("{league_name}", "{target_week}",
                "{data_summary}", "{draft_script}"):
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
