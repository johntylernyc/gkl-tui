"""Tests for the podcast data pack builder (Phase 1)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from gkl.podcast.datapack import (
    DataPack, DataPackMeta, RosterPlayer, StatCategoryRecord, TeamRoster,
    _h2h_records, _historical_adds, _matchup_record, _roto_entries,
    _team_momentum, _transaction_records, datapack_dir,
)
from gkl.yahoo_api import (
    Matchup, PlayerStats, StatCategory, TeamStats, Transaction, TransactionPlayer,
)


# -- Fixtures ----------------------------------------------------------------

def _cat(stat_id: str, name: str, higher_better: bool = True,
         ptype: str = "B") -> StatCategory:
    return StatCategory(
        stat_id=stat_id, display_name=name,
        sort_order="1" if higher_better else "0",
        position_type=ptype,
    )


def _team(key: str, name: str, manager: str, stats: dict[str, str]) -> TeamStats:
    return TeamStats(
        team_key=key, name=name, manager=manager,
        points=0.0, projected_points=0.0, stats=stats,
    )


def _matchup(week: int, a: TeamStats, b: TeamStats, *, status: str = "postevent") -> Matchup:
    return Matchup(
        week=week, week_start="2026-04-14", week_end="2026-04-20",
        status=status, is_playoffs=False, is_tied=False,
        winner_team_key=a.team_key, team_a=a, team_b=b,
    )


def _matchup_with_winner(
    week: int, a: TeamStats, b: TeamStats, winner: TeamStats,
    *, status: str = "postevent",
) -> Matchup:
    return Matchup(
        week=week, week_start="2026-04-14", week_end="2026-04-20",
        status=status, is_playoffs=False, is_tied=False,
        winner_team_key=winner.team_key, team_a=a, team_b=b,
    )


HR = _cat("12", "HR", higher_better=True)
AVG = _cat("3", "AVG", higher_better=True)
ERA = _cat("26", "ERA", higher_better=False, ptype="P")


# -- Tests -------------------------------------------------------------------

def test_roto_entries_orders_by_total_and_includes_per_category_ranks() -> None:
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10", "3": ".300", "26": "3.50"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "20", "3": ".250", "26": "4.00"})
    t3 = _team("t.3", "Gamma", "Cal", {"12": "5",  "3": ".280", "26": "3.80"})

    entries = _roto_entries([t1, t2, t3], [HR, AVG, ERA])

    # Highest total roto points should be rank 1
    assert entries[0].rank == 1
    totals = [e.total_points for e in entries]
    assert totals == sorted(totals, reverse=True)

    for e in entries:
        assert set(e.category_ranks.keys()) == {"12", "3", "26"}
        assert set(e.category_raw.keys()) == {"12", "3", "26"}


def test_h2h_records_counts_only_completed_matchups() -> None:
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10", "3": ".300"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "5",  "3": ".250"})

    # Two weeks: one completed (t1 wins both categories), one in-progress (ignored)
    completed = _matchup(1, t1, t2, status="postevent")
    in_progress = _matchup(2, t1, t2, status="midevent")

    recs = _h2h_records([completed, in_progress], [t1, t2], [HR, AVG])
    by_key = {r.team_key: r for r in recs}

    assert by_key["t.1"].wins == 1
    assert by_key["t.1"].losses == 0
    assert by_key["t.1"].cat_wins == 2  # both HR and AVG in the single completed week
    assert by_key["t.2"].losses == 1
    assert by_key["t.2"].cat_losses == 2


def test_matchup_record_categorizes_per_stat() -> None:
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10", "3": ".300", "26": "3.50"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "20", "3": ".250", "26": "4.00"})
    m = _matchup(1, t1, t2)

    rec = _matchup_record(m, [HR, AVG, ERA])

    # t1 wins AVG + ERA (lower), t2 wins HR
    assert rec.team_a_cat_wins == 2
    assert rec.team_b_cat_wins == 1
    winners = {c.display_name: c.winner for c in rec.category_results}
    assert winners == {"HR": "b", "AVG": "a", "ERA": "a"}


def test_matchup_record_uses_yahoo_stat_winners_over_rounded_display() -> None:
    # Regression for the 2026-w07 Braun vs Tides bug: both teams display
    # AVG of .255 (rounded from .25510 and .25531), but Yahoo's underlying
    # H/AB tiebreaker awards the category to team_b. Local rounding would
    # call this a tie; we must trust Yahoo's stat_winners.
    t1 = _team("t.1", "Alpha", "Ann", {"3": ".255", "12": "10"})
    t2 = _team("t.2", "Beta",  "Bob", {"3": ".255", "12": "11"})
    m = Matchup(
        week=7, week_start="2026-05-04", week_end="2026-05-10",
        status="postevent", is_playoffs=False, is_tied=False,
        winner_team_key=t2.team_key, team_a=t1, team_b=t2,
        stat_winners={"3": t2.team_key, "12": t2.team_key},
    )

    rec = _matchup_record(m, [AVG, HR])

    winners = {c.display_name: c.winner for c in rec.category_results}
    assert winners == {"AVG": "b", "HR": "b"}
    assert rec.team_a_cat_wins == 0
    assert rec.team_b_cat_wins == 2
    assert rec.cat_ties == 0


def test_matchup_record_yahoo_can_classify_unequal_display_as_tie() -> None:
    # Yahoo occasionally records a stat as tied even when raw values differ
    # (rounding rules, suspended games, etc.). Stat_winners is authoritative.
    t1 = _team("t.1", "Alpha", "Ann", {"3": ".280"})
    t2 = _team("t.2", "Beta",  "Bob", {"3": ".275"})
    m = Matchup(
        week=1, week_start="2026-04-14", week_end="2026-04-20",
        status="postevent", is_playoffs=False, is_tied=False,
        winner_team_key=t1.team_key, team_a=t1, team_b=t2,
        stat_winners={"3": ""},
    )

    rec = _matchup_record(m, [AVG])

    assert rec.category_results[0].winner == "tie"
    assert rec.cat_ties == 1


def test_matchup_record_falls_back_to_rounded_compare_when_stat_winners_missing() -> None:
    # Preevent / midevent matchups don't carry stat_winners. Fall back to the
    # rounded display comparison so the rest of the pipeline still works.
    t1 = _team("t.1", "Alpha", "Ann", {"3": ".300", "12": "10"})
    t2 = _team("t.2", "Beta",  "Bob", {"3": ".250", "12": "20"})
    m = Matchup(
        week=8, week_start="2026-05-11", week_end="2026-05-17",
        status="midevent", is_playoffs=False, is_tied=False,
        winner_team_key="", team_a=t1, team_b=t2,
        stat_winners={},
    )

    rec = _matchup_record(m, [AVG, HR])

    winners = {c.display_name: c.winner for c in rec.category_results}
    assert winners == {"AVG": "a", "HR": "b"}


def test_h2h_records_trusts_yahoo_winner_team_key_for_outcome() -> None:
    # If category counts come out 9-9 locally but Yahoo's stat_winners
    # gives one side the edge, our matchup tally must follow Yahoo's
    # winner_team_key — not our local "tied on category counts" inference.
    t1 = _team("t.1", "Alpha", "Ann", {"3": ".255", "12": "10"})
    t2 = _team("t.2", "Beta",  "Bob", {"3": ".255", "12": "10"})
    # Two categories, both display equal; Yahoo gives one to each team.
    # Locally that's 1-1 (would default to a tie matchup), but Yahoo says
    # team_a won the matchup outright.
    m = Matchup(
        week=1, week_start="2026-04-14", week_end="2026-04-20",
        status="postevent", is_playoffs=False, is_tied=False,
        winner_team_key=t1.team_key, team_a=t1, team_b=t2,
        stat_winners={"3": t1.team_key, "12": t2.team_key},
    )

    recs = _h2h_records([m], [t1, t2], [AVG, HR])
    by_key = {r.team_key: r for r in recs}

    # Local cat counts still come out 1-1, but the matchup outcome follows
    # Yahoo: t1 wins the matchup, t2 loses. No tie inferred.
    assert by_key["t.1"].wins == 1
    assert by_key["t.1"].losses == 0
    assert by_key["t.1"].ties == 0
    assert by_key["t.2"].wins == 0
    assert by_key["t.2"].losses == 1
    assert by_key["t.2"].ties == 0
    # Category tallies still reflect the per-category truth (1 each).
    assert by_key["t.1"].cat_wins == 1
    assert by_key["t.1"].cat_losses == 1


def test_transaction_records_flags_in_target_week_window() -> None:
    # 2026-04-15 12:00 UTC — inside the week window 04-14..04-20
    inside_ts = 1776254400
    # 2026-04-21 12:00 UTC — outside the week window
    outside_ts = 1776772800

    p = TransactionPlayer(
        player_key="p.1", name="Player A", position="OF", team_abbr="NYY",
        action="add", from_team="Free Agents", to_team="Alpha",
    )
    tx_inside = Transaction(
        transaction_key="tx.1", type="add", timestamp=inside_ts,
        status="successful", players=[p],
    )
    tx_outside = Transaction(
        transaction_key="tx.2", type="drop", timestamp=outside_ts,
        status="successful", players=[p],
    )

    records = _transaction_records(
        [tx_inside, tx_outside],
        week_start="2026-04-14", week_end="2026-04-20",
    )
    assert records[0].transaction_key == "tx.1"
    assert records[0].in_target_week is True
    assert records[1].in_target_week is False


def test_datapack_roundtrips_to_json(tmp_path: Path) -> None:
    meta = DataPackMeta(
        league_key="mlb.l.1", league_name="Test", season="2026",
        segment="weekly-recap", target_week=1, current_week=2,
        week_start="2026-04-14", week_end="2026-04-20",
        generated_at="2026-04-24T00:00:00+00:00",
    )
    pack = DataPack(
        meta=meta,
        categories=[StatCategoryRecord(
            stat_id="12", display_name="HR", sort_order="1",
            position_type="B", is_only_display=False,
        )],
        teams=[], roto_standings=[], h2h_records=[], power_rankings=[],
        target_week_matchups=[], rosters=[], target_week_rosters=[],
        transactions=[], mlb_games=[],
    )

    path = tmp_path / "mlb.l.1" / "2026-w01" / "datapack.json"
    pack.write_to(path)
    loaded = json.loads(path.read_text())

    assert loaded["meta"]["league_key"] == "mlb.l.1"
    assert loaded["meta"]["target_week"] == 1
    assert loaded["categories"][0]["display_name"] == "HR"


def test_datapack_dir_uses_season_and_week_slug(tmp_path: Path) -> None:
    d = datapack_dir(tmp_path, "mlb.l.12345", "2026", 4)
    assert d == tmp_path / "mlb.l.12345" / "2026-w04"


# -- Team momentum (last-N played weeks) -------------------------------------

def test_team_momentum_aggregates_last_n_played_weeks() -> None:
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10", "3": ".300"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "5",  "3": ".250"})
    # 6 weeks of matchups; target_week=6 with window=5 → covers weeks 2-6
    matchups = [
        _matchup_with_winner(w, t1, t2, winner=t1)
        for w in range(1, 7)
    ]
    recs = _team_momentum(matchups, [t1, t2], [HR, AVG], target_week=6, window=5)
    by_key = {r.team_key: r for r in recs}

    # t1 swept all 5 weeks in the window
    assert by_key["t.1"].wins == 5
    assert by_key["t.1"].losses == 0
    assert by_key["t.1"].weeks_covered == [2, 3, 4, 5, 6]
    # Each week is 2 cats won, so 5 weeks × 2 cats = 10 cat_wins
    assert by_key["t.1"].cat_wins == 10
    # t2 took the same beatings from the other side
    assert by_key["t.2"].losses == 5
    assert by_key["t.2"].cat_losses == 10


def test_team_momentum_ignores_in_progress_matchups() -> None:
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10", "3": ".300"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "5",  "3": ".250"})
    completed = _matchup_with_winner(5, t1, t2, winner=t1, status="postevent")
    in_progress = _matchup_with_winner(6, t1, t2, winner=t1, status="midevent")

    recs = _team_momentum(
        [completed, in_progress], [t1, t2], [HR, AVG],
        target_week=6, window=5,
    )
    by_key = {r.team_key: r for r in recs}

    # Only the postevent matchup counts
    assert by_key["t.1"].wins == 1
    assert by_key["t.1"].weeks_covered == [5]


def test_team_momentum_auto_shortens_when_season_too_young() -> None:
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10", "3": ".300"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "5",  "3": ".250"})
    # Only weeks 1-2 played; target_week=2 with window=5 means window
    # would start at -2, but it should clamp to week 1.
    matchups = [
        _matchup_with_winner(w, t1, t2, winner=t1) for w in (1, 2)
    ]
    recs = _team_momentum(matchups, [t1, t2], [HR, AVG], target_week=2, window=5)
    by_key = {r.team_key: r for r in recs}

    assert by_key["t.1"].weeks_covered == [1, 2]
    assert by_key["t.1"].wins == 2


def test_team_momentum_reports_teams_with_no_window_data() -> None:
    # Mid-season trade target team with no matchups in window — still listed.
    t1 = _team("t.1", "Alpha", "Ann", {"12": "10"})
    t2 = _team("t.2", "Beta",  "Bob", {"12": "5"})
    # Only one matchup, in week 1; window for target_week=6 starts at week 2.
    matchups = [_matchup_with_winner(1, t1, t2, winner=t1)]
    recs = _team_momentum(matchups, [t1, t2], [HR], target_week=6, window=5)
    by_key = {r.team_key: r for r in recs}

    assert by_key["t.1"].weeks_covered == []
    assert by_key["t.1"].wins == 0


# -- Historical adds (3-4 weeks ago) -----------------------------------------

def _add_tx(player_key: str, player_name: str, to_team_name: str,
            timestamp: int, *, to_team_key: str = "") -> Transaction:
    p = TransactionPlayer(
        player_key=player_key, name=player_name, position="OF",
        team_abbr="NYY", action="add",
        from_team="Free Agents", to_team=to_team_name,
        to_team_key=to_team_key,
    )
    return Transaction(
        transaction_key=f"tx.{player_key}", type="add",
        timestamp=timestamp, status="successful", players=[p],
    )


def _ros(team_key: str, name: str, manager: str,
         players: list[RosterPlayer]) -> TeamRoster:
    return TeamRoster(
        team_key=team_key, team_name=name, manager=manager, players=players,
    )


def _rp(player_key: str, name: str, *, season=None, last30=None,
        slot: str = "OF") -> RosterPlayer:
    return RosterPlayer(
        player_key=player_key, name=name, position="OF",
        team_abbr="NYY", selected_position=slot,
        availability_tag="[ACTIVE]",
        season_stats=season or {}, last30_stats=last30 or {},
    )


def test_historical_adds_picks_up_3_and_4_weeks_ago_only() -> None:
    # target_week=8; should look at adds in weeks 4 and 5 only.
    week_dates = {
        4: ("2026-04-21", "2026-04-27"),
        5: ("2026-04-28", "2026-05-04"),
        6: ("2026-05-05", "2026-05-11"),
        7: ("2026-05-12", "2026-05-18"),
    }
    # Week 5 add (3 weeks ago) — 2026-04-30 12:00 UTC
    in_window_3 = _add_tx("p.1", "Player One", "Alpha", 1777881600)
    # Week 4 add (4 weeks ago) — 2026-04-23 12:00 UTC
    in_window_4 = _add_tx("p.2", "Player Two", "Alpha", 1777276800)
    # Week 6 add (only 2 weeks ago) — should NOT match
    too_recent = _add_tx("p.3", "Player Three", "Alpha", 1778486400)
    # Week 2 add (6 weeks ago) — should NOT match
    too_old = _add_tx("p.4", "Player Four", "Alpha", 1776067200)

    t_alpha = _team("t.1", "Alpha", "Ann", {})
    rosters = [_ros("t.1", "Alpha", "Ann", [
        _rp("p.1", "Player One", season={"12": "8"}, last30={"12": "5"}),
        _rp("p.2", "Player Two", season={"12": "12"}, last30={"12": "7"}),
        _rp("p.3", "Player Three"),
        _rp("p.4", "Player Four"),
    ])]

    adds = _historical_adds(
        [in_window_3, in_window_4, too_recent, too_old],
        rosters, [t_alpha], week_dates, target_week=8,
    )

    by_player = {a.player_key: a for a in adds}
    assert set(by_player.keys()) == {"p.1", "p.2"}
    assert by_player["p.1"].weeks_ago == 3
    assert by_player["p.1"].added_week == 5
    assert by_player["p.2"].weeks_ago == 4
    assert by_player["p.2"].added_week == 4
    # Stats joined in from rosters
    assert by_player["p.1"].season_stats == {"12": "8"}
    assert by_player["p.1"].last30_stats == {"12": "5"}


def test_historical_adds_marks_dropped_players() -> None:
    week_dates = {5: ("2026-04-28", "2026-05-04")}
    tx = _add_tx("p.10", "Cut Bait", "Alpha", 1777881600)
    t_alpha = _team("t.1", "Alpha", "Ann", {})
    # Player is NOT on the current roster
    rosters = [_ros("t.1", "Alpha", "Ann", [])]

    adds = _historical_adds([tx], rosters, [t_alpha], week_dates, target_week=8)

    assert len(adds) == 1
    assert adds[0].still_on_roster is False
    assert adds[0].availability_tag == "[DROPPED]"
    assert adds[0].season_stats == {}


def test_historical_adds_uses_to_team_key_when_present() -> None:
    week_dates = {5: ("2026-04-28", "2026-05-04")}
    # Yahoo-newer payload: explicit to_team_key, team-name fallback intentionally bogus
    tx = _add_tx(
        "p.20", "Player Twenty", to_team_name="Beta-by-name",
        timestamp=1777881600, to_team_key="t.42",
    )
    t_real = _team("t.42", "Alpha-canonical", "Ann", {})
    rosters = [_ros("t.42", "Alpha-canonical", "Ann", [
        _rp("p.20", "Player Twenty"),
    ])]

    adds = _historical_adds([tx], rosters, [t_real], week_dates, target_week=8)

    assert len(adds) == 1
    # to_team_key wins over the (mismatched) team name lookup
    assert adds[0].fantasy_team_key == "t.42"
    assert adds[0].fantasy_team_name == "Alpha-canonical"


def test_historical_adds_skips_non_add_actions_and_failed_txns() -> None:
    week_dates = {5: ("2026-04-28", "2026-05-04")}
    add_p = TransactionPlayer(
        player_key="p.30", name="Picked Up", position="OF", team_abbr="NYY",
        action="add", from_team="Free Agents", to_team="Alpha",
    )
    drop_p = TransactionPlayer(
        player_key="p.31", name="Cut Loose", position="OF", team_abbr="NYY",
        action="drop", from_team="Alpha", to_team="Free Agents",
    )
    successful_add = Transaction(
        transaction_key="tx.add", type="add", timestamp=1777881600,
        status="successful", players=[add_p],
    )
    failed_add = Transaction(
        transaction_key="tx.fail", type="add", timestamp=1777881600,
        status="cancelled", players=[add_p],
    )
    drop_only = Transaction(
        transaction_key="tx.drop", type="drop", timestamp=1777881600,
        status="successful", players=[drop_p],
    )

    t_alpha = _team("t.1", "Alpha", "Ann", {})
    rosters = [_ros("t.1", "Alpha", "Ann", [_rp("p.30", "Picked Up")])]

    adds = _historical_adds(
        [successful_add, failed_add, drop_only],
        rosters, [t_alpha], week_dates, target_week=8,
    )

    assert [a.player_key for a in adds] == ["p.30"]


def test_weekly_power_rankings_all_play_from_target_matchups() -> None:
    """Weekly PR is single-week all-play built from the target-week matchup
    stats — the team with the best week beats everyone (3-0), worst goes 0-3.
    """
    from gkl.podcast.datapack import _weekly_power_rankings

    cats = [_cat("12", "HR", higher_better=True)]
    a = _team("t.1", "Best", "Ann", {"12": "40"})
    b = _team("t.2", "Good", "Bob", {"12": "30"})
    c = _team("t.3", "Meh", "Cal", {"12": "20"})
    d = _team("t.4", "Worst", "Dot", {"12": "10"})
    # Two matchups carry all four teams' week stats (pairing is irrelevant to
    # all-play). Season teams supply manager names.
    matchups = [_matchup(11, a, b), _matchup(11, c, d)]
    season = [a, b, c, d]

    pr = _weekly_power_rankings(matchups, season, cats)
    by_name = {p.name: p for p in pr}
    assert (by_name["Best"].hypothetical_wins,
            by_name["Best"].hypothetical_losses) == (3, 0)
    assert (by_name["Worst"].hypothetical_wins,
            by_name["Worst"].hypothetical_losses) == (0, 3)
    # Ranked best-first, with manager names joined from season teams.
    assert pr[0].name == "Best" and pr[0].manager == "Ann"
    assert pr[-1].name == "Worst"


def test_weekly_power_rankings_empty_without_matchups() -> None:
    from gkl.podcast.datapack import _weekly_power_rankings
    assert _weekly_power_rankings([], [], [_cat("12", "HR")]) == []
