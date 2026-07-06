"""Data packs for nextgenpodcast.

Two additions over the v1 weekly pack (which is reused as-is):

- `PlayoffRacePack` — the official head-to-head standings (category
  record ranked by win percentage, matching the league's real playoff
  qualification and `gkl.skipper._tool_h2h_standings`), seeds, the
  top-N cutline with gaps, and each team's remaining schedule. Computed
  from data the v1 builder already fetches plus future-week scoreboards.
- `TeamSeasonPack` — a single team's season to date, for the all-star
  deep-dive special: week-by-week results, transaction record, roster
  form, and where the team sits in both tables.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gkl.podcast.datapack import (
    DataPack, H2HRecord, MatchupRecord, RotoEntry, TeamRoster,
    TransactionRecord, _fetch_team_roster, _matchup_record, _roto_entries,
    _team_momentum, _transaction_records, build_weekly_recap_datapack,
)
from gkl.yahoo_api import League, Matchup, StatCategory, YahooFantasyAPI


# How many future weeks of scoreboards to pull for remaining-schedule
# context. Bounded so an early-season run doesn't fetch 20 weeks.
REMAINING_SCHEDULE_HORIZON = 8


# ---------- Playoff race ----------

@dataclass
class RaceEntry:
    seed: int
    team_key: str
    name: str
    manager: str
    wins: int
    losses: int
    ties: int
    cat_wins: int
    cat_losses: int
    cat_ties: int
    win_pct: float               # category-record win pct, ties = half
    gap_to_cutline_cat_wins: int  # + = cushion above the line, - = behind
    tier: str                    # "safe" | "bubble" | "field"


@dataclass
class ScheduledMatchup:
    week: int
    team_a_key: str
    team_a_name: str
    team_b_key: str
    team_b_name: str
    bubble_meeting: bool  # both teams in the bubble tier


@dataclass
class PlayoffRacePack:
    playoff_spots: int
    through_week: int
    entries: list[RaceEntry]
    remaining: list[ScheduledMatchup]
    near_ties: list[tuple[str, str]]  # (name, name) adjacent seeds too close to call


def _win_pct(w: int, l: int, t: int) -> float:
    games = w + l + t
    return (w + 0.5 * t) / games if games else 0.0


def compute_playoff_race(
    h2h_records: list[H2HRecord],
    *,
    playoff_spots: int,
    through_week: int,
    remaining: list[ScheduledMatchup] | None = None,
) -> PlayoffRacePack:
    """Official standings: category record ranked by win percentage.

    The bubble is the two seeds on either side of the cutline (e.g. for an
    8-spot league, seeds 7-10); safe is above it, field below.
    """
    ranked = sorted(
        h2h_records, key=lambda r: _win_pct(r.cat_wins, r.cat_losses, r.cat_ties),
        reverse=True,
    )
    cutline_rec = ranked[playoff_spots - 1] if len(ranked) >= playoff_spots else None
    entries: list[RaceEntry] = []
    for seed, r in enumerate(ranked, 1):
        gap = (r.cat_wins - cutline_rec.cat_wins) if cutline_rec else 0
        if seed <= playoff_spots - 2:
            tier = "safe"
        elif seed <= playoff_spots + 2:
            tier = "bubble"
        else:
            tier = "field"
        entries.append(RaceEntry(
            seed=seed, team_key=r.team_key, name=r.name, manager=r.manager,
            wins=r.wins, losses=r.losses, ties=r.ties,
            cat_wins=r.cat_wins, cat_losses=r.cat_losses, cat_ties=r.cat_ties,
            win_pct=round(_win_pct(r.cat_wins, r.cat_losses, r.cat_ties), 4),
            gap_to_cutline_cat_wins=gap, tier=tier,
        ))

    near_ties: list[tuple[str, str]] = []
    for a, b in zip(entries, entries[1:]):
        if abs(a.win_pct - b.win_pct) < 0.005:
            near_ties.append((a.name, b.name))

    rem = remaining or []
    bubble_keys = {e.team_key for e in entries if e.tier == "bubble"}
    for m in rem:
        m.bubble_meeting = (
            m.team_a_key in bubble_keys and m.team_b_key in bubble_keys
        )
    return PlayoffRacePack(
        playoff_spots=playoff_spots, through_week=through_week,
        entries=entries, remaining=rem, near_ties=near_ties,
    )


async def fetch_remaining_schedule(
    api: YahooFantasyAPI,
    league: League,
    *,
    horizon: int = REMAINING_SCHEDULE_HORIZON,
) -> list[ScheduledMatchup]:
    """Scheduled (not-yet-completed) matchups from the current week out.

    Yahoo returns preview-status matchups for future weeks; playoff weeks
    are included if scheduled. Failures on any single week degrade to an
    empty list for that week rather than failing the pack.
    """
    first = league.current_week
    last = min(league.end_week, first + horizon - 1)
    if last < first:
        return []
    tasks = [
        asyncio.to_thread(api.get_scoreboard, league.league_key, w)
        for w in range(first, last + 1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[ScheduledMatchup] = []
    for week, res in zip(range(first, last + 1), results):
        if isinstance(res, BaseException):
            continue
        for m in res:
            if m.status == "postevent":
                continue
            out.append(ScheduledMatchup(
                week=week,
                team_a_key=m.team_a.team_key, team_a_name=m.team_a.name,
                team_b_key=m.team_b.team_key, team_b_name=m.team_b.name,
                bubble_meeting=False,
            ))
    return out


def format_playoff_race(race: PlayoffRacePack) -> str:
    """Prose block for the data summary + fact-checker ground truth."""
    n = race.playoff_spots
    lines = [
        f"Official head-to-head standings through Week {race.through_week} "
        f"(category record, ranked by WIN PERCENTAGE — ties count half). "
        f"The top {n} make the playoffs.",
    ]
    for e in race.entries:
        pct = f"{e.win_pct:.3f}".lstrip("0")
        gap = e.gap_to_cutline_cat_wins
        if e.seed <= n:
            gap_txt = f"cushion above the cutline: {gap} category wins"
        else:
            gap_txt = f"behind the cutline: {abs(gap)} category wins"
        lines.append(
            f"{e.seed}. {e.name} ({e.manager}) [{e.tier.upper()}]: "
            f"category record {e.cat_wins}-{e.cat_losses}-{e.cat_ties} "
            f"(win pct {pct}), matchup record {e.wins}-{e.losses}-{e.ties}; "
            f"{gap_txt}"
        )
        if e.seed == n:
            lines.append(f"----- PLAYOFF CUTLINE (top {n} above this line) -----")
    if race.near_ties:
        pairs = "; ".join(f"{a} and {b}" for a, b in race.near_ties)
        lines.append(
            f"Near-tied seeds (do NOT assert a hard seed order between "
            f"these): {pairs}"
        )
    if race.remaining:
        lines.append("")
        lines.append("Remaining schedule (scheduled matchups, nearest first):")
        for m in race.remaining:
            tag = "  <-- BUBBLE MEETING" if m.bubble_meeting else ""
            lines.append(
                f"Week {m.week}: {m.team_a_name} vs {m.team_b_name}{tag}"
            )
    return "\n".join(lines)


# ---------- Weekly v2 pack (v1 pack + race) ----------

@dataclass
class WeeklyRacePack:
    base: DataPack
    race: PlayoffRacePack

    def write_to(self, path: Path) -> None:
        payload = self.base.to_dict()
        payload["playoff_race"] = asdict(self.race)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))


async def build_weekly_race_datapack(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    target_week: int,
    *,
    playoff_spots: int,
) -> WeeklyRacePack:
    base_task = build_weekly_recap_datapack(api, league, categories, target_week)
    remaining_task = fetch_remaining_schedule(api, league)
    base, remaining = await asyncio.gather(base_task, remaining_task)
    race = compute_playoff_race(
        base.h2h_records, playoff_spots=playoff_spots,
        through_week=target_week, remaining=remaining,
    )
    return WeeklyRacePack(base=base, race=race)


# ---------- Team season pack (all-star deep dive) ----------

@dataclass
class TeamWeekResult:
    week: int
    opponent: str
    result: str        # "W" | "L" | "T"
    cat_score: str     # e.g. "11-6-1" from this team's perspective


@dataclass
class TeamSeasonPack:
    league_key: str
    league_name: str
    season: str
    team_key: str
    team_name: str
    manager: str
    through_week: int
    generated_at: str
    weekly_results: list[TeamWeekResult]
    roto_entry: RotoEntry | None
    roto_rank: int
    race: PlayoffRacePack
    roster: TeamRoster
    transactions: list[TransactionRecord]   # this team's moves only
    momentum_line: str
    matchup_records: list[MatchupRecord]    # this team's matchups, full detail

    def write_to(self, path: Path) -> None:
        payload = asdict(self)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))


def _team_week_result(rec: MatchupRecord, team_key: str) -> TeamWeekResult:
    if rec.team_a_key == team_key:
        mine, theirs, opp = rec.team_a_cat_wins, rec.team_b_cat_wins, rec.team_b_name
    else:
        mine, theirs, opp = rec.team_b_cat_wins, rec.team_a_cat_wins, rec.team_a_name
    if rec.winner_team_key == team_key:
        result = "W"
    elif rec.winner_team_key and rec.winner_team_key != team_key:
        result = "L"
    else:
        result = "T" if mine == theirs else ("W" if mine > theirs else "L")
    return TeamWeekResult(
        week=rec.week, opponent=opp, result=result,
        cat_score=f"{mine}-{theirs}-{rec.cat_ties}",
    )


def _filter_team_transactions(
    transactions: list[TransactionRecord], team_name: str,
) -> list[TransactionRecord]:
    out = []
    for tx in transactions:
        if any(p.to_team == team_name or p.from_team == team_name
               for p in tx.players):
            out.append(tx)
    return out


async def build_team_season_pack(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    team_key: str,
    *,
    playoff_spots: int,
    through_week: int | None = None,
) -> TeamSeasonPack:
    """Season-to-date pack for one team (all-star deep dive)."""
    through = through_week or (league.current_week - 1)
    league_key = league.league_key

    season_teams_task = asyncio.to_thread(api.get_team_season_stats, league_key)
    transactions_task = asyncio.to_thread(api.get_transactions, league_key, 400)
    matchup_tasks = [
        asyncio.to_thread(api.get_scoreboard, league_key, w)
        for w in range(1, through + 1)
    ]
    remaining_task = fetch_remaining_schedule(api, league)
    season_teams, transactions, remaining, *matchup_lists = await asyncio.gather(
        season_teams_task, transactions_task, remaining_task, *matchup_tasks,
    )

    team = next((t for t in season_teams if t.team_key == team_key), None)
    if team is None:
        raise ValueError(f"team_key {team_key!r} not found in league")

    all_matchups: list[Matchup] = [m for lst in matchup_lists for m in lst]
    completed = [m for m in all_matchups if m.status == "postevent"]

    # H2H records over the season → race pack
    from gkl.podcast.datapack import _h2h_records
    h2h = _h2h_records(completed, season_teams, categories)
    race = compute_playoff_race(
        h2h, playoff_spots=playoff_spots, through_week=through,
        remaining=remaining,
    )

    # This team's matchups, week by week
    team_matchups = [
        _matchup_record(m, categories) for m in completed
        if team_key in (m.team_a.team_key, m.team_b.team_key)
    ]
    team_matchups.sort(key=lambda r: r.week)
    weekly_results = [_team_week_result(r, team_key) for r in team_matchups]

    roto = _roto_entries(season_teams, categories)
    roto_entry = next((e for e in roto if e.team_key == team_key), None)

    roster = await _fetch_team_roster(api, team, league.current_week)

    momentum = _team_momentum(completed, season_teams, categories, through + 1)
    mine = next((m for m in momentum if m.team_key == team_key), None)
    momentum_line = ""
    if mine and mine.weeks_covered:
        momentum_line = (
            f"Weeks {mine.weeks_covered[0]}-{mine.weeks_covered[-1]}: "
            f"{mine.wins}-{mine.losses}-{mine.ties} in matchups, "
            f"{mine.cat_wins}-{mine.cat_losses}-{mine.cat_ties} in categories"
        )

    # Week window for transaction in-window flags is irrelevant here; use
    # the season so far.
    tx_records = _transaction_records(transactions, "", "")
    team_tx = _filter_team_transactions(tx_records, team.name)

    return TeamSeasonPack(
        league_key=league_key, league_name=league.name, season=league.season,
        team_key=team_key, team_name=team.name, manager=team.manager,
        through_week=through,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        weekly_results=weekly_results,
        roto_entry=roto_entry,
        roto_rank=roto_entry.rank if roto_entry else 0,
        race=race,
        roster=roster,
        transactions=team_tx,
        momentum_line=momentum_line,
        matchup_records=team_matchups,
    )


# ---------- Deep-dive data summary ----------

def _stat_line(stats: dict[str, str], categories_by_id: dict[str, str]) -> str:
    parts = [
        f"{categories_by_id[sid]} {val}"
        for sid, val in stats.items()
        if sid in categories_by_id and val not in ("", "-")
    ]
    return ", ".join(parts)


def format_team_season_summary(
    pack: TeamSeasonPack, categories: list[StatCategory],
) -> str:
    """Compact natural-language summary of a TeamSeasonPack — ground truth
    for the deep-dive draft writer and fact checker."""
    cats = {c.stat_id: c.display_name for c in categories if not c.is_only_display}
    lines: list[str] = []

    lines.append(
        f"Season results for {pack.team_name} (manager {pack.manager}) "
        f"through Week {pack.through_week}:"
    )
    for r in pack.weekly_results:
        lines.append(
            f"Week {r.week}: {r.result} vs {r.opponent} ({r.cat_score} in categories)"
        )

    if pack.momentum_line:
        lines.append("")
        lines.append(f"Recent form: {pack.momentum_line}")

    lines.append("")
    lines.append(format_playoff_race(pack.race))

    if pack.roto_entry:
        e = pack.roto_entry
        lines.append("")
        lines.append(
            f"Roto standing (context, not the playoff table): rank {e.rank} "
            f"with {e.total_points} points."
        )
        by_pts = sorted(e.category_ranks.items(), key=lambda kv: kv[1], reverse=True)
        best = [f"{cats.get(sid, sid)} ({pts} pts)" for sid, pts in by_pts[:3] if sid in cats]
        worst = [f"{cats.get(sid, sid)} ({pts} pts)" for sid, pts in by_pts[-3:] if sid in cats]
        if best:
            lines.append(f"Best categories by roto points: {', '.join(best)}")
        if worst:
            lines.append(f"Weakest categories by roto points: {', '.join(worst)}")

    lines.append("")
    lines.append(f"Current roster (season line, then last-30 line):")
    for p in pack.roster.players:
        season = _stat_line(p.season_stats, cats)
        last30 = _stat_line(p.last30_stats, cats)
        lines.append(
            f"- {p.name} ({p.position}, {p.team_abbr}) {p.availability_tag}: "
            f"season: {season or 'n/a'} | last 30: {last30 or 'n/a'}"
        )

    lines.append("")
    if pack.transactions:
        lines.append(f"Transaction log for {pack.team_name} (newest first):")
        for tx in pack.transactions:
            moves = "; ".join(
                f"{p.action} {p.name} ({p.position}, {p.team_abbr})"
                for p in tx.players
                if pack.team_name in (p.to_team, p.from_team)
            )
            lines.append(f"- {tx.timestamp_iso[:10]}: {moves}")
    else:
        lines.append("Transaction log: no moves recorded this season.")

    return "\n".join(lines)
