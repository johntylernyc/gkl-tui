"""Tests for the deterministic scoreline validator."""

from __future__ import annotations

from gkl.nextgenpodcast.factguard import (
    find_scoreline_violations, official_record_tuples, spoken_number_tuples,
)

SUMS = {18, 17}  # 18 scored categories, 17 all-play opponents


PACK = {
    "teams": [
        {"name": "IWU Tang Clan"},
        {"name": "Big Daddy's Funk"},
        {"name": "The Revs."},
        {"name": "Tybee Island Tides"},
    ],
    "target_week_matchups": [
        {
            "team_a_name": "IWU Tang Clan",
            "team_b_name": "Big Daddy's Funk",
            "team_a_cat_wins": 13, "team_b_cat_wins": 4, "cat_ties": 1,
        },
        {
            "team_a_name": "Tybee Island Tides",
            "team_b_name": "The Revs.",
            "team_a_cat_wins": 1, "team_b_cat_wins": 15, "cat_ties": 2,
        },
    ],
    "weekly_power_rankings": [
        {"hypothetical_wins": 16, "hypothetical_losses": 0,
         "hypothetical_ties": 1},
    ],
}


# ---------- spoken_number_tuples ----------

def test_parses_spelled_triple():
    assert spoken_number_tuples("edged ten-seven-one on innings", SUMS) == [(10, 7, 1)]


def test_parses_and_oh_joiners():
    assert spoken_number_tuples(
        "Sixteen-and-oh-and-one on the all-play", SUMS,
    ) == [(16, 0, 1)]


def test_parses_two_part_record():
    assert spoken_number_tuples("survived eleven-seven, mortal", SUMS) == [(11, 7)]


def test_parses_digit_tuples():
    assert spoken_number_tuples("won 13-4-1 going away", SUMS) == [(13, 4, 1)]


def test_compound_numbers_are_not_tuples():
    # "sixty-nine" is one number, not (60, 9)
    assert spoken_number_tuples("sixty-nine strikeouts to twenty-six", SUMS) == []


def test_spoken_decimals_excluded_by_sum_guard():
    # "eight-oh-two" sums to 10 — not a plausible record in this league
    assert spoken_number_tuples("slugging eight-oh-two over thirty days", SUMS) == []


def test_price_and_stat_followers_excluded():
    assert spoken_number_tuples("a twenty-seven-dollar outfielder", SUMS) == []
    assert spoken_number_tuples("a one-seventeen ERA since June", SUMS) == []


def test_non_number_chains_ignored():
    assert spoken_number_tuples("a three-skillet breakfast, boom-or-bust", SUMS) == []


# ---------- official_record_tuples ----------

def test_collects_matchup_and_allplay_records():
    tuples = official_record_tuples(PACK)
    assert (13, 4, 1) in tuples
    assert (1, 15, 2) in tuples
    assert (16, 0, 1) in tuples


# ---------- find_scoreline_violations ----------

def _check(script: str) -> list[str]:
    return find_scoreline_violations(
        script, PACK, scored_categories=18, num_teams=18,
    )


def test_official_score_passes():
    assert _check("WEBB: IWU took Big Daddy's thirteen-four-one.") == []


def test_loser_perspective_passes():
    assert _check("HAWK: Big Daddy's fell four-thirteen-one to IWU.") == []


def test_wrong_score_flagged():
    problems = _check("WEBB: IWU edged Big Daddy's ten-seven-one on innings.")
    assert len(problems) == 1
    assert "10-7-1" in problems[0]


def test_wrong_score_without_team_name_not_hard_flagged():
    # No team named on the line — too ambiguous to fail the run on.
    assert _check("WEBB: somebody went ten-seven-one this week.") == []


def test_two_part_form_of_official_score_passes():
    assert _check("HAWK: The Revs. buried Tybee fifteen-one.") == []
