"""Tests for the data-formatter utilities in source_builder."""

from __future__ import annotations

import pytest

from gkl.podcast.datapack import (
    CategoryResult, DataPack, DataPackMeta, H2HRecord, MatchupRecord,
    PowerRanking, RotoEntry, StatCategoryRecord, TransactionPlayerRecord,
    TransactionRecord,
)
from gkl.podcast.source_builder import (
    format_free_agents, format_h2h_records, format_power_rankings,
    format_scoreboard, format_standings, format_target_week_transactions,
    split_suggested_topics,
)


# -- Fixtures ----------------------------------------------------------------

def _datapack() -> DataPack:
    meta = DataPackMeta(
        league_key="mlb.l.1", league_name="Test League", season="2026",
        segment="weekly-recap", target_week=4, current_week=5,
        week_start="2026-04-14", week_end="2026-04-20",
        generated_at="2026-04-24T00:00:00+00:00",
    )

    m1 = MatchupRecord(
        week=4, week_start="2026-04-14", week_end="2026-04-20", status="postevent",
        team_a_key="t.1", team_a_name="Alpha",
        team_b_key="t.2", team_b_name="Beta",
        team_a_cat_wins=12, team_b_cat_wins=6, cat_ties=0,
        winner_team_key="t.1",
        category_results=[CategoryResult(
            display_name="HR", team_a_value="10", team_b_value="5", winner="a",
        )],
    )
    m2 = MatchupRecord(
        week=4, week_start="2026-04-14", week_end="2026-04-20", status="postevent",
        team_a_key="t.3", team_a_name="Gamma",
        team_b_key="t.4", team_b_name="Delta",
        team_a_cat_wins=9, team_b_cat_wins=9, cat_ties=0,
        winner_team_key="",
        category_results=[],
    )
    m3 = MatchupRecord(
        week=4, week_start="2026-04-14", week_end="2026-04-20", status="postevent",
        team_a_key="t.5", team_a_name="Epsilon",
        team_b_key="t.6", team_b_name="Zeta",
        team_a_cat_wins=10, team_b_cat_wins=7, cat_ties=1,
        winner_team_key="t.5",
        category_results=[],
    )

    standings = [
        RotoEntry(rank=1, team_key="t.1", name="Alpha", manager="Ann",
                  total_points=180.5, category_ranks={}, category_raw={}),
        RotoEntry(rank=2, team_key="t.3", name="Gamma", manager="Cal",
                  total_points=165.0, category_ranks={}, category_raw={}),
        RotoEntry(rank=3, team_key="t.5", name="Epsilon", manager="Eve",
                  total_points=140.0, category_ranks={}, category_raw={}),
    ]
    h2h = [
        H2HRecord(team_key="t.1", name="Alpha", manager="Ann",
                  wins=4, losses=0, ties=0, cat_wins=48, cat_losses=24, cat_ties=0),
        H2HRecord(team_key="t.2", name="Beta", manager="Bob",
                  wins=1, losses=3, ties=0, cat_wins=28, cat_losses=44, cat_ties=0),
    ]
    power = [
        PowerRanking(rank=1, team_key="t.1", name="Alpha", manager="Ann",
                     hypothetical_wins=17, hypothetical_losses=0, hypothetical_ties=0,
                     win_pct=1.0),
        PowerRanking(rank=2, team_key="t.3", name="Gamma", manager="Cal",
                     hypothetical_wins=13, hypothetical_losses=4, hypothetical_ties=0,
                     win_pct=0.765),
    ]
    txn = TransactionRecord(
        transaction_key="tx.1", type="add/drop",
        timestamp_iso="2026-04-15T12:00:00+00:00", status="successful",
        in_target_week=True,
        players=[
            TransactionPlayerRecord(
                player_key="p.1", name="Player X", position="OF",
                team_abbr="NYY", action="add",
                from_team="Free Agents", to_team="Alpha",
            ),
        ],
    )
    txn_outside = TransactionRecord(
        transaction_key="tx.2", type="add",
        timestamp_iso="2026-04-22T12:00:00+00:00", status="successful",
        in_target_week=False, players=[],
    )

    return DataPack(
        meta=meta,
        categories=[StatCategoryRecord(
            stat_id="12", display_name="HR", sort_order="1",
            position_type="B", is_only_display=False,
        )],
        teams=[], roto_standings=standings, h2h_records=h2h,
        power_rankings=power, target_week_matchups=[m1, m2, m3],
        rosters=[], target_week_rosters=[],
        transactions=[txn, txn_outside], mlb_games=[],
    )


# -- Formatter tests ---------------------------------------------------------

def test_format_scoreboard_handles_win_tie_and_ties() -> None:
    dp = _datapack()
    text = format_scoreboard(dp.target_week_matchups)
    assert "Alpha defeated Beta, 12 categories to 6" in text
    assert "Gamma and Delta tied at 9 categories each" in text
    assert "Epsilon defeated Zeta, 10 categories to 7 (tied 1 category)" in text


def test_format_standings_respects_top_n() -> None:
    dp = _datapack()
    text = format_standings(dp.roto_standings, top_n=2)
    assert "Alpha" in text
    assert "Gamma" in text
    assert "Epsilon" in text  # falls into "Remaining" tail
    assert "Remaining" in text


def test_format_target_week_player_stats_emits_per_team_blocks() -> None:
    """The fact-checker section must show every roster's players with their
    week stats — that's the lookup table for verifying script claims."""
    from gkl.podcast.datapack import RosterPlayer, TeamRoster
    from gkl.podcast.source_builder import format_target_week_player_stats

    dp = _datapack()
    # Inject two target-week rosters: one batter team, one pitcher team.
    dp.target_week_rosters = [
        TeamRoster(
            team_key="t.1", team_name="Alpha", manager="Ann",
            players=[
                RosterPlayer(
                    player_key="p.muncy", name="Max Muncy", position="3B",
                    team_abbr="LAD", selected_position="3B",
                    availability_tag="[ACTIVE — in starting lineup]",
                    season_stats={}, last30_stats={},
                    week_stats={"3": ".304", "12": "2", "85": "3"},
                ),
            ],
        ),
        TeamRoster(
            team_key="t.2", team_name="Beta", manager="Bob",
            players=[
                RosterPlayer(
                    player_key="p.skubal", name="Tarik Skubal", position="SP",
                    team_abbr="DET", selected_position="SP",
                    availability_tag="[ACTIVE — in starting lineup]",
                    season_stats={}, last30_stats={},
                    week_stats={"26": "1.50", "27": "0.95"},
                ),
            ],
        ),
    ]
    text = format_target_week_player_stats(dp)
    assert "Alpha (Ann):" in text
    assert "Beta (Bob):" in text
    assert "Max Muncy (3B, LAD)" in text
    assert "Tarik Skubal (SP, DET)" in text


def test_format_target_week_player_stats_uses_only_position_relevant_categories() -> None:
    """A 3B should NOT show pitching stats; an SP should NOT show batting."""
    from gkl.podcast.datapack import RosterPlayer, TeamRoster
    from gkl.podcast.source_builder import format_target_week_player_stats

    dp = _datapack()
    # Categories fixture contains stat_id "12" with display_name "HR" (batting).
    # Add a pitching category for completeness.
    from gkl.podcast.datapack import StatCategoryRecord
    dp.categories = [
        StatCategoryRecord(
            stat_id="12", display_name="HR", sort_order="1",
            position_type="B", is_only_display=False,
        ),
        StatCategoryRecord(
            stat_id="26", display_name="ERA", sort_order="0",
            position_type="P", is_only_display=False,
        ),
    ]
    dp.target_week_rosters = [
        TeamRoster(
            team_key="t.1", team_name="Alpha", manager="Ann",
            players=[
                RosterPlayer(
                    player_key="p.b", name="Some Batter", position="3B",
                    team_abbr="LAD", selected_position="3B",
                    availability_tag="[ACTIVE]",
                    season_stats={}, last30_stats={},
                    week_stats={"12": "2", "26": "1.50"},
                ),
                RosterPlayer(
                    player_key="p.p", name="Some Pitcher", position="SP",
                    team_abbr="DET", selected_position="SP",
                    availability_tag="[ACTIVE]",
                    season_stats={}, last30_stats={},
                    week_stats={"12": "0", "26": "1.50"},
                ),
            ],
        ),
    ]
    text = format_target_week_player_stats(dp)
    # Batter shows HR but NOT ERA
    batter_line = next(ln for ln in text.splitlines() if "Some Batter" in ln)
    assert "HR" in batter_line
    assert "ERA" not in batter_line
    # Pitcher shows ERA but NOT HR
    pitcher_line = next(ln for ln in text.splitlines() if "Some Pitcher" in ln)
    assert "ERA" in pitcher_line
    assert "HR" not in pitcher_line


def test_format_target_week_player_stats_with_no_data() -> None:
    from gkl.podcast.source_builder import format_target_week_player_stats
    dp = _datapack()
    dp.target_week_rosters = []
    text = format_target_week_player_stats(dp)
    assert "no target-week rosters" in text


def test_format_target_week_transactions_excludes_outside_window() -> None:
    dp = _datapack()
    text = format_target_week_transactions(dp)
    assert "Player X" in text
    assert "tx.2" not in text


def test_format_h2h_records_sorts_by_wins() -> None:
    dp = _datapack()
    text = format_h2h_records(dp.h2h_records)
    assert text.index("Alpha") < text.index("Beta")


def test_format_h2h_records_includes_both_framings() -> None:
    """The script writer needs both the W-L-T format AND the 'X of Y matchups'
    narrative so it can rotate between them."""
    dp = _datapack()
    text = format_h2h_records(dp.h2h_records)
    # Formal record format
    assert "4-0-0 record" in text
    # Narrative format
    assert "won 4 of 4 matchups" in text


def test_format_h2h_records_handles_ties() -> None:
    from gkl.podcast.datapack import H2HRecord
    records = [
        H2HRecord(
            team_key="t.x", name="Tied Team", manager="Manager",
            wins=2, losses=1, ties=1, cat_wins=20, cat_losses=18, cat_ties=2,
        ),
    ]
    text = format_h2h_records(records)
    assert "2-1-1 record" in text
    assert "won 2 of 4 matchups, with 1 tie" in text


def test_format_h2h_records_pluralizes_ties() -> None:
    from gkl.podcast.datapack import H2HRecord
    records = [
        H2HRecord(
            team_key="t.y", name="Many Ties", manager="Manager",
            wins=1, losses=1, ties=2, cat_wins=10, cat_losses=10, cat_ties=4,
        ),
    ]
    text = format_h2h_records(records)
    assert "won 1 of 4 matchups, with 2 ties" in text


def test_format_power_rankings_respects_top_n() -> None:
    dp = _datapack()
    text = format_power_rankings(dp.power_rankings, top_n=1)
    assert "Alpha" in text
    assert "Gamma" not in text


def test_format_free_agents_groups_hitters_and_pitchers() -> None:
    """Act 3 needs to see free agents split by position type so the hosts
    can pair pickups with the right team needs."""
    from gkl.podcast.datapack import RosterPlayer
    dp = _datapack()
    dp.categories = [
        StatCategoryRecord(
            stat_id="12", display_name="HR", sort_order="1",
            position_type="B", is_only_display=False,
        ),
        StatCategoryRecord(
            stat_id="26", display_name="ERA", sort_order="0",
            position_type="P", is_only_display=False,
        ),
    ]
    dp.free_agents = [
        RosterPlayer(
            player_key="p.hit", name="Hit Guy", position="OF",
            team_abbr="NYY", selected_position="",
            availability_tag="[FREE AGENT]",
            season_stats={"12": "10"}, last30_stats={"12": "3"},
        ),
        RosterPlayer(
            player_key="p.sp", name="Arm Guy", position="SP",
            team_abbr="LAD", selected_position="",
            availability_tag="[FREE AGENT]",
            season_stats={"26": "3.25"}, last30_stats={"26": "2.10"},
        ),
    ]
    text = format_free_agents(dp)
    assert "Top free-agent hitters:" in text
    assert "Top free-agent pitchers:" in text
    assert "Hit Guy (OF, NYY)" in text
    assert "Arm Guy (SP, LAD)" in text
    assert "season — HR 10" in text
    assert "last 30 — HR 3" in text
    # Pitcher block omits hitter categories and vice-versa
    assert "ERA 3.25" in text
    assert "Hit Guy" not in text.split("Top free-agent pitchers:")[1]


def test_format_free_agents_with_no_data() -> None:
    dp = _datapack()
    dp.free_agents = []
    assert "no free agents" in format_free_agents(dp)


def test_format_free_agents_respects_top_n() -> None:
    from gkl.podcast.datapack import RosterPlayer
    dp = _datapack()
    dp.categories = [
        StatCategoryRecord(
            stat_id="12", display_name="HR", sort_order="1",
            position_type="B", is_only_display=False,
        ),
    ]
    dp.free_agents = [
        RosterPlayer(
            player_key=f"p.{i}", name=f"Player {i}", position="OF",
            team_abbr="NYY", selected_position="",
            availability_tag="[FREE AGENT]",
            season_stats={"12": str(i)}, last30_stats={},
        )
        for i in range(5)
    ]
    text = format_free_agents(dp, top_n=2)
    assert "Player 0" in text
    assert "Player 1" in text
    assert "Player 2" not in text


# -- Splitter (kept for inspection/debugging) -------------------------------

SAMPLE_TOPICS = """\
## Act 1 — Scoreboard

Alpha story.

## Act 2 — Transactions

Pickups.

## Act 3 — Standouts

Breakout.
"""


def test_split_suggested_topics_returns_three_acts() -> None:
    acts = split_suggested_topics(SAMPLE_TOPICS)
    assert set(acts.keys()) == {1, 2, 3}
    assert "Alpha story." in acts[1]
    assert "Pickups." in acts[2]
    assert "Breakout." in acts[3]


def test_split_suggested_topics_raises_on_missing_act() -> None:
    incomplete = "## Act 1\nhook\n\n## Act 2\nhook"
    with pytest.raises(ValueError, match="missing act"):
        split_suggested_topics(incomplete)


def test_split_suggested_topics_raises_on_no_headers() -> None:
    with pytest.raises(ValueError, match="no `## Act N` headings"):
        split_suggested_topics("no headers here")
