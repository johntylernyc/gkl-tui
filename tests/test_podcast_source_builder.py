"""Tests for the data-formatter utilities in source_builder."""

from __future__ import annotations

import pytest

from gkl.podcast.datapack import (
    CategoryResult, DataPack, DataPackMeta, H2HRecord, HistoricalAdd,
    MatchupRecord, PowerRanking, RotoEntry, StatCategoryRecord, TeamMomentum,
    TransactionPlayerRecord, TransactionRecord,
)
from gkl.podcast.datapack import RosterPlayer, TeamRoster
from gkl.podcast.source_builder import (
    format_category_leaders, format_free_agents, format_h2h_records,
    format_historical_adds, format_power_rankings, format_roster_form,
    format_scoreboard, format_standings, format_target_week_transactions,
    format_team_momentum, format_weekly_standouts, split_suggested_topics,
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


# -- Team momentum + historical adds -----------------------------------------

def test_format_team_momentum_sorts_hottest_first_with_window_label() -> None:
    dp = _datapack()
    dp.team_momentum = [
        TeamMomentum(
            team_key="t.1", name="Alpha", manager="Ann",
            weeks_covered=[3, 4, 5, 6, 7],
            wins=5, losses=0, ties=0,
            cat_wins=50, cat_losses=30, cat_ties=10,
        ),
        TeamMomentum(
            team_key="t.2", name="Beta", manager="Bob",
            weeks_covered=[3, 4, 5, 6, 7],
            wins=1, losses=4, ties=0,
            cat_wins=30, cat_losses=50, cat_ties=10,
        ),
    ]

    text = format_team_momentum(dp)

    assert "Alpha (Ann): 5-0-0 over weeks 3-7" in text
    assert "50-30-10 in categories" in text
    # Alpha listed before Beta (hotter)
    assert text.index("Alpha") < text.index("Beta")


def test_format_team_momentum_reports_teams_with_no_window_data() -> None:
    dp = _datapack()
    dp.team_momentum = [
        TeamMomentum(
            team_key="t.99", name="Cold", manager="Cam",
            weeks_covered=[], wins=0, losses=0, ties=0,
            cat_wins=0, cat_losses=0, cat_ties=0,
        ),
    ]
    text = format_team_momentum(dp)
    assert "no recent matchup data" in text


def test_format_team_momentum_empty() -> None:
    dp = _datapack()
    dp.team_momentum = []
    assert format_team_momentum(dp) == "(no momentum data)"


def test_format_historical_adds_groups_by_team_and_includes_stats() -> None:
    dp = _datapack()
    dp.historical_adds = [
        HistoricalAdd(
            player_key="p.1", player_name="Hot Bat", position="OF",
            team_abbr="NYY", added_week=4, weeks_ago=4,
            fantasy_team_key="t.1", fantasy_team_name="Alpha", manager="Ann",
            still_on_roster=True, selected_position="OF",
            availability_tag="[ACTIVE]",
            season_stats={"12": "8"}, last30_stats={"12": "5"},
        ),
    ]
    text = format_historical_adds(dp)
    assert "Alpha (Ann):" in text
    assert "Added Week 4 (4 weeks ago)" in text
    assert "Hot Bat" in text
    assert "HR 5" in text  # last30 line uses the HR category
    assert "HR 8" in text  # season line


def test_format_historical_adds_calls_out_dropped() -> None:
    dp = _datapack()
    dp.historical_adds = [
        HistoricalAdd(
            player_key="p.99", player_name="Cut Bait", position="OF",
            team_abbr="NYY", added_week=5, weeks_ago=3,
            fantasy_team_key="t.1", fantasy_team_name="Alpha", manager="Ann",
            still_on_roster=False, selected_position="",
            availability_tag="[DROPPED]",
            season_stats={}, last30_stats={},
        ),
    ]
    text = format_historical_adds(dp)
    assert "dropped after pickup" in text


def test_format_historical_adds_empty() -> None:
    dp = _datapack()
    dp.historical_adds = []
    assert format_historical_adds(dp) == "(no qualifying adds from 3-4 weeks ago)"


# -- Category Kings / Weekly Awards / roster form formatters ------------------

def _cat_categories() -> list[StatCategoryRecord]:
    return [
        StatCategoryRecord(stat_id="12", display_name="HR", sort_order="1",
                           position_type="B", is_only_display=False),
        StatCategoryRecord(stat_id="16", display_name="SB", sort_order="1",
                           position_type="B", is_only_display=False),
        StatCategoryRecord(stat_id="26", display_name="ERA", sort_order="0",
                           position_type="P", is_only_display=False),
        StatCategoryRecord(stat_id="3", display_name="AVG", sort_order="1",
                           position_type="B", is_only_display=False),
    ]


def _cat_standings() -> list[RotoEntry]:
    # roto "rank" == points: higher is better (worst team gets 1).
    # Power leads HR (3 pts) and ERA (3 pts); Speed leads SB (3 pts).
    return [
        RotoEntry(rank=1, team_key="t.1", name="Power", manager="Pat",
                  total_points=9.0,
                  category_ranks={"12": 3.0, "16": 1.0, "26": 3.0, "3": 2.0},
                  category_raw={"12": "120", "16": "30", "26": "3.10", "3": ".270"}),
        RotoEntry(rank=2, team_key="t.2", name="Speed", manager="Sam",
                  total_points=8.0,
                  category_ranks={"12": 2.0, "16": 3.0, "26": 2.0, "3": 3.0},
                  category_raw={"12": "95", "16": "88", "26": "3.50", "3": ".281"}),
        RotoEntry(rank=3, team_key="t.3", name="Cellar", manager="Cam",
                  total_points=4.0,
                  category_ranks={"12": 1.0, "16": 2.0, "26": 1.0, "3": 1.0},
                  category_raw={"12": "70", "16": "60", "26": "4.80", "3": ".240"}),
    ]


def _cat_datapack() -> DataPack:
    dp = _datapack()
    dp.categories = _cat_categories()
    dp.roto_standings = _cat_standings()
    return dp


def test_format_category_leaders_crowns_highest_points_team() -> None:
    text = format_category_leaders(_cat_datapack())
    lines = {ln.split(":")[0].lstrip("- "): ln for ln in text.splitlines() if ln.startswith("- ")}
    # HR leader is Power (3 pts), with raw value first.
    assert lines["HR"].startswith("- HR: Power (120)")
    # SB leader is Speed (3 pts) — even though Power has fewer raw SB.
    assert lines["SB"].startswith("- SB: Speed (88)")


def test_format_category_leaders_handles_low_is_better() -> None:
    """ERA leader must be the team with the LOWEST ERA (highest roto points)."""
    text = format_category_leaders(_cat_datapack())
    era = next(ln for ln in text.splitlines() if ln.startswith("- ERA:"))
    # Power has 3 ERA pts and the lowest ERA (3.10) — it should lead.
    assert era.startswith("- ERA: Power (3.10)")
    # Cellar (4.80 ERA) must NOT be first.
    assert "Cellar" not in era.split(">")[0]


def test_format_category_leaders_counts_most_categories_led() -> None:
    text = format_category_leaders(_cat_datapack())
    # Power leads HR + ERA = 2; Speed leads SB + AVG = 2.
    assert "Most categories led:" in text
    summary = text.split("Most categories led:")[1]
    assert "Power (2)" in summary
    assert "Speed (2)" in summary


def _standout_datapack() -> DataPack:
    dp = _datapack()
    dp.categories = _cat_categories()
    # target-week rosters carry week_stats; current rosters carry season/last30
    dp.target_week_rosters = [
        TeamRoster(team_key="t.1", team_name="Power", manager="Pat", players=[
            RosterPlayer(player_key="p.bomber", name="Big Bomber", position="1B",
                         team_abbr="NYY", selected_position="1B",
                         availability_tag="[ACTIVE — in starting lineup]",
                         season_stats={}, last30_stats={},
                         week_stats={"12": "5", "16": "0", "3": ".400"}),
        ]),
        TeamRoster(team_key="t.2", team_name="Speed", manager="Sam", players=[
            RosterPlayer(player_key="p.burner", name="Speedy Burner", position="OF",
                         team_abbr="TB", selected_position="OF",
                         availability_tag="[ACTIVE — in starting lineup]",
                         season_stats={}, last30_stats={},
                         week_stats={"12": "0", "16": "6", "3": ".333"}),
        ]),
    ]
    dp.rosters = [
        TeamRoster(team_key="t.1", team_name="Power", manager="Pat", players=[
            RosterPlayer(player_key="p.bomber", name="Big Bomber", position="1B",
                         team_abbr="NYY", selected_position="1B",
                         availability_tag="[ACTIVE]",
                         season_stats={"12": "30", "3": ".280"},
                         last30_stats={"12": "12", "3": ".320"}),
        ]),
    ]
    return dp


def test_format_weekly_standouts_bundles_three_windows() -> None:
    text = format_weekly_standouts(_standout_datapack())
    bomber = next(ln for ln in text.splitlines() if "Big Bomber" in ln)
    # Week headline + last-30 + season context all present for the joined player.
    assert "week — " in bomber and "HR 5" in bomber
    assert "last 30 — " in bomber and "HR 12" in bomber
    assert "season — " in bomber and "HR 30" in bomber
    # The category it topped is annotated.
    assert "[topped this week: HR]" in bomber


def test_format_weekly_standouts_surfaces_category_leaders_only() -> None:
    """A player who topped a counting cat for the week is surfaced; the
    per-category leaders differ (Bomber tops HR, Burner tops SB)."""
    text = format_weekly_standouts(_standout_datapack())
    assert "Big Bomber" in text
    assert "Speedy Burner" in text
    # Burner has no season/last30 join (absent from current rosters) — degrades
    # gracefully to week-only without crashing.
    burner = next(ln for ln in text.splitlines() if "Speedy Burner" in ln)
    assert "week — " in burner


def test_format_weekly_standouts_empty_when_no_rosters() -> None:
    dp = _datapack()
    dp.target_week_rosters = []
    assert format_weekly_standouts(dp) == "(no target-week rosters in this data pack)"


def test_format_roster_form_lists_season_and_last30() -> None:
    text = format_roster_form(_standout_datapack())
    assert "Power (Pat):" in text
    bomber = next(ln for ln in text.splitlines() if "Big Bomber" in ln)
    assert "season — " in bomber
    assert "last 30 — " in bomber


# -- Weekly power rankings / near-tie / category-record leader ---------------

def _pr(rank, key, name, mgr, w, l, t, pct):
    return PowerRanking(rank=rank, team_key=key, name=name, manager=mgr,
                        hypothetical_wins=w, hypothetical_losses=l,
                        hypothetical_ties=t, win_pct=pct)


def test_format_weekly_power_rankings_uses_weekly_field() -> None:
    from gkl.podcast.source_builder import format_weekly_power_rankings
    dp = _datapack()
    dp.weekly_power_rankings = [
        _pr(1, "t.1", "Boys", "Ryan", 16, 1, 0, 0.941),
        _pr(2, "t.2", "Revs", "Aaron", 15, 1, 1, 0.882),
    ]
    text = format_weekly_power_rankings(dp)
    assert "1. Boys (Ryan): 16-1-0 for Week 4" in text
    assert "2. Revs (Aaron): 15-1-1 for Week 4" in text


def test_format_weekly_power_rankings_degrades_when_absent() -> None:
    from gkl.podcast.source_builder import format_weekly_power_rankings
    dp = _datapack()  # no weekly_power_rankings attr set on this fixture path
    dp.weekly_power_rankings = []
    assert format_weekly_power_rankings(dp) == "(no weekly power rankings)"


def test_format_standings_flags_near_ties() -> None:
    standings = [
        RotoEntry(rank=1, team_key="t.1", name="Alpha", manager="Ann",
                  total_points=241.5, category_ranks={}, category_raw={}),
        RotoEntry(rank=2, team_key="t.2", name="Beta", manager="Bob",
                  total_points=219.5, category_ranks={}, category_raw={}),
        RotoEntry(rank=3, team_key="t.3", name="Gamma", manager="Cal",
                  total_points=219.0, category_ranks={}, category_raw={}),
    ]
    text = format_standings(standings, top_n=3)
    # Beta (219.5) and Gamma (219.0) are 0.5 apart -> flagged near-tied.
    assert "Near-tied in roto" in text
    assert "Beta and Gamma (0.5 apart)" in text
    # Alpha (241.5) is 22 clear of Beta -> NOT flagged.
    assert "Alpha and Beta" not in text


def test_format_h2h_records_surfaces_winpct_leader() -> None:
    # ShapeShifters have MORE raw category wins but trail My Name on win%
    # because of ties — My Name must be named the leader.
    recs = [
        H2HRecord(team_key="t.1", name="My Name", manager="Jon",
                  wins=10, losses=1, ties=0,
                  cat_wins=112, cat_losses=64, cat_ties=22),
        H2HRecord(team_key="t.2", name="ShapeShifters", manager="Al",
                  wins=8, losses=3, ties=0,
                  cat_wins=113, cat_losses=68, cat_ties=17),
    ]
    text = format_h2h_records(recs)
    leader_line = text.splitlines()[-1]
    assert "BY WIN PERCENTAGE" in leader_line
    # My Name first despite fewer raw category wins.
    assert leader_line.index("My Name") < leader_line.index("ShapeShifters")
    assert "0.621" in leader_line and "0.614" in leader_line
