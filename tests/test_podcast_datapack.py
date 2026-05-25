"""Tests for the podcast data pack builder (Phase 1)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from gkl.podcast.datapack import (
    DataPack, DataPackMeta, StatCategoryRecord,
    _h2h_records, _matchup_record, _roto_entries, _transaction_records,
    datapack_dir,
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
