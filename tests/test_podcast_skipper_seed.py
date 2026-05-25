"""Tests for the podcast Skipper-seed prompt extraction + substitution (Phase 2)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gkl.podcast.skipper_seed import (
    DEFAULT_SEGMENT_ARTIFACT, EpisodeContext, _extract_section, _substitute,
    load_segment_prompt,
)


# -- Section extraction ------------------------------------------------------

SAMPLE_MD = """\
# Segment Title

Intro prose.

## Skipper seed (Phase 2)

Some pre-amble paragraph here.

### System addendum

First paragraph of system addendum.

Second paragraph.

### User prompt

User prompt body line 1.
User prompt body line 2.

## Ad assets

Some ad prose.
"""


def test_extract_section_pulls_body_between_headings() -> None:
    body = _extract_section(SAMPLE_MD, "Skipper seed (Phase 2)", "System addendum")
    assert "First paragraph of system addendum." in body
    assert "Second paragraph." in body
    # Should NOT leak into the next sub-heading
    assert "User prompt body line 1." not in body


def test_extract_section_stops_at_next_top_level() -> None:
    body = _extract_section(SAMPLE_MD, "Skipper seed (Phase 2)", "User prompt")
    assert "User prompt body line 1." in body
    assert "User prompt body line 2." in body
    # Should NOT bleed into the Ad assets section
    assert "Some ad prose." not in body


def test_extract_section_raises_on_missing_parent() -> None:
    with pytest.raises(KeyError, match="Section '## Missing' not found"):
        _extract_section(SAMPLE_MD, "Missing", "System addendum")


def test_extract_section_raises_on_missing_sub() -> None:
    with pytest.raises(KeyError, match="Sub-section '### Nothing' not found"):
        _extract_section(SAMPLE_MD, "Skipper seed (Phase 2)", "Nothing")


# -- Token substitution ------------------------------------------------------

def test_substitute_replaces_known_tokens() -> None:
    result = _substitute(
        "Hello {league_name}, week {target_week}",
        {"league_name": "GKL", "target_week": "4"},
    )
    assert result == "Hello GKL, week 4"


def test_substitute_raises_on_unknown_token() -> None:
    with pytest.raises(KeyError, match=r"Unknown prompt token: \{bogus\}"):
        _substitute("Hello {bogus}", {"league_name": "GKL"})


def test_episode_context_serializes_all_fields() -> None:
    ctx = EpisodeContext(
        league_name="GKL", season="2026", target_week=4,
        week_start="2026-04-14", week_end="2026-04-20",
    )
    subs = ctx.as_substitutions()
    assert subs == {
        "league_name": "GKL", "season": "2026", "target_week": "4",
        "week_start": "2026-04-14", "week_end": "2026-04-20",
    }


# -- Live segment artifact ---------------------------------------------------

def test_weekly_recap_segment_artifact_parses() -> None:
    """The shipped weekly-recap.md must have both Phase 2 sub-sections."""
    assert DEFAULT_SEGMENT_ARTIFACT.exists()
    prompt = load_segment_prompt(DEFAULT_SEGMENT_ARTIFACT)
    assert len(prompt.system_addendum) > 200
    assert len(prompt.user_prompt) > 200
    # Sanity: user prompt must contain all 5 tokens so callers can substitute
    for tok in ("{league_name}", "{season}", "{target_week}",
                "{week_start}", "{week_end}"):
        assert tok in prompt.user_prompt, f"missing token {tok} in user prompt"


# -- Availability tag (lives in skipper.py, used by datapack + podcast) -----

def _tag_for(selected_position: str, position: str = "OF") -> str:
    """Helper: build a PlayerStats stub and run it through the tag function."""
    from gkl.skipper import _availability_tag
    from gkl.yahoo_api import PlayerStats
    p = PlayerStats(
        player_key="p.x", name="Test Player", position=position,
        team_abbr="NYY", selected_position=selected_position,
    )
    return _availability_tag(p)


def test_availability_tag_for_starting_pitcher_on_bench_avoids_word_bench() -> None:
    """SPs naturally sit on the BN slot between starts. The script writer
    kept calling them 'bench players' — removing the word 'bench' from the
    tag stops the LLM from latching onto it."""
    tag = _tag_for("BN", position="SP")
    assert "BENCH" not in tag.upper().replace("BENCH PLAYER", "")  # word check
    assert "STARTING PITCHER" in tag
    assert "resting between" in tag.lower()


def test_availability_tag_for_generic_p_on_bench_also_treated_as_pitcher() -> None:
    tag = _tag_for("BN", position="P")
    assert "STARTING PITCHER" in tag


def test_availability_tag_for_position_player_on_bench_keeps_bench_label() -> None:
    """Position players on BN are real bench decisions, not rotation rest."""
    tag = _tag_for("BN", position="3B")
    assert "BENCH" in tag


def test_availability_tag_for_active_player() -> None:
    tag = _tag_for("3B", position="3B")
    assert "ACTIVE" in tag


def test_availability_tag_for_il_and_na() -> None:
    assert "INJURED" in _tag_for("IL", position="3B")
    assert "INJURED" in _tag_for("IL+", position="3B")
    assert "NOT-ACTIVE" in _tag_for("NA", position="3B")


def test_weekly_recap_user_prompt_fully_substitutes() -> None:
    prompt = load_segment_prompt(DEFAULT_SEGMENT_ARTIFACT)
    ctx = EpisodeContext(
        league_name="Test League", season="2026", target_week=3,
        week_start="2026-04-07", week_end="2026-04-13",
    )
    filled = _substitute(prompt.user_prompt, ctx.as_substitutions())
    # After substitution, no unsubstituted `{token}` patterns should remain
    assert not re.search(r"\{[a-z_]+\}", filled)
    assert "Test League" in filled
    assert "Week **3**" in filled
    # The extractor must strip the trailing `---` horizontal rule
    assert not filled.rstrip().endswith("---")
