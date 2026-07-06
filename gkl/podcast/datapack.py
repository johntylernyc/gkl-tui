"""Raw-datasets half of a podcast data pack.

Assembles the objective, machine-readable view that downstream stages
(Skipper seed, Studio Podcast source builder) analyze. Datasets are the
same ones Skipper's tools wrap, but serialized without editorial framing.

MVP covers the Weekly Recap segment. Additional segments will add their
own builder functions in this module (or a sibling) as they are added.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from gkl.yahoo_api import (
    League, Matchup, PlayerStats, StatCategory, TeamStats, Transaction,
    YahooFantasyAPI,
)
from gkl.stats import (
    compute_power_rankings, compute_roto, official_category_winner,
    simulate_h2h,
)
from gkl.mlb_api import MLBGame, get_mlb_scoreboard
from gkl.skipper import _availability_tag as availability_tag


# How many top free agents to include in the data pack. Sized so the
# script writer's Act 3 (free-agent pickups) has a meaningful pool to
# recommend from AND the fact-checker can verify whichever picks the
# Skipper seed surfaces in the suggested topics.
_FREE_AGENT_POOL_SIZE = 50


# ---------- Output schema ----------

@dataclass
class DataPackMeta:
    league_key: str
    league_name: str
    season: str
    segment: str
    target_week: int
    current_week: int
    week_start: str
    week_end: str
    generated_at: str


@dataclass
class RotoEntry:
    rank: int
    team_key: str
    name: str
    manager: str
    total_points: float
    category_ranks: dict[str, float]
    category_raw: dict[str, str]


@dataclass
class H2HRecord:
    team_key: str
    name: str
    manager: str
    wins: int
    losses: int
    ties: int
    cat_wins: int
    cat_losses: int
    cat_ties: int


@dataclass
class PowerRanking:
    rank: int
    team_key: str
    name: str
    manager: str
    hypothetical_wins: int
    hypothetical_losses: int
    hypothetical_ties: int
    win_pct: float


@dataclass
class CategoryResult:
    display_name: str
    team_a_value: str
    team_b_value: str
    winner: str  # "a", "b", or "t"


@dataclass
class MatchupRecord:
    week: int
    week_start: str
    week_end: str
    status: str
    team_a_key: str
    team_a_name: str
    team_b_key: str
    team_b_name: str
    team_a_cat_wins: int
    team_b_cat_wins: int
    cat_ties: int
    winner_team_key: str
    category_results: list[CategoryResult]


@dataclass
class RosterPlayer:
    player_key: str
    name: str
    position: str
    team_abbr: str
    selected_position: str
    availability_tag: str
    season_stats: dict[str, str]
    last30_stats: dict[str, str]
    # Populated only on `target_week_rosters` entries. The current-roster
    # entries (`rosters`) leave it empty since week-specific lines are
    # only meaningful in the context of a recap.
    week_stats: dict[str, str] = field(default_factory=dict)


@dataclass
class TeamRoster:
    team_key: str
    team_name: str
    manager: str
    players: list[RosterPlayer]


@dataclass
class TransactionPlayerRecord:
    player_key: str
    name: str
    position: str
    team_abbr: str
    action: str
    from_team: str
    to_team: str


@dataclass
class TransactionRecord:
    transaction_key: str
    type: str
    timestamp_iso: str
    status: str
    in_target_week: bool
    players: list[TransactionPlayerRecord]


@dataclass
class MLBGameRecord:
    date: str
    gamePk: str
    status: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int


@dataclass
class StatCategoryRecord:
    stat_id: str
    display_name: str
    sort_order: str
    position_type: str
    is_only_display: bool


@dataclass
class TeamMomentum:
    """Recent-form record over the last N played weeks.

    Distinct from `H2HRecord` (season-cumulative) — momentum measures the
    most recent streak, which Act 2 uses to flag heaters vs slumps in the
    standings tour.
    """
    team_key: str
    name: str
    manager: str
    weeks_covered: list[int]
    wins: int
    losses: int
    ties: int
    cat_wins: int
    cat_losses: int
    cat_ties: int


@dataclass
class HistoricalAdd:
    """A player added 3-4 weeks ago, joined with their stats since.

    Used for Act 3's "look-back" topic — did the add work out? — and as
    fact-checker ground truth for any look-back stat claim.
    """
    player_key: str
    player_name: str
    position: str
    team_abbr: str
    added_week: int
    weeks_ago: int
    fantasy_team_key: str
    fantasy_team_name: str
    manager: str
    still_on_roster: bool
    selected_position: str
    availability_tag: str
    season_stats: dict[str, str]
    last30_stats: dict[str, str]


@dataclass
class DataPack:
    meta: DataPackMeta
    categories: list[StatCategoryRecord]
    teams: list[dict]  # team_key, name, manager
    roto_standings: list[RotoEntry]
    h2h_records: list[H2HRecord]
    power_rankings: list[PowerRanking]  # season-cumulative all-play
    target_week_matchups: list[MatchupRecord]
    rosters: list[TeamRoster]
    # Rosters AS OF the target week, with each player's stats FOR that week.
    # This is the ground truth for verifying any per-player claim the script
    # makes about target-week performance.
    target_week_rosters: list[TeamRoster]
    transactions: list[TransactionRecord]
    mlb_games: list[MLBGameRecord]
    # Top free agents available for pickup, sorted by Yahoo's actual-rank
    # (AR) heuristic. Each entry carries season + last30 stats so the
    # script writer can speak to both year-to-date production and recent
    # form when recommending Act 3 pickups.
    free_agents: list[RosterPlayer] = field(default_factory=list)
    # Per-team record over the last N played weeks. Powers Act 2's
    # momentum framing (teams on a heater vs in a slump).
    team_momentum: list[TeamMomentum] = field(default_factory=list)
    # Adds from 3-4 weeks ago + their stats since. Powers Act 3's
    # rotating "look-back" topic.
    historical_adds: list[HistoricalAdd] = field(default_factory=list)
    # Single-week all-play power rankings for the target week — the "who
    # had the best week" view Act 1 uses. Distinct from `power_rankings`
    # (season-cumulative). Empty for older datapacks built before this
    # field existed.
    weekly_power_rankings: list[PowerRanking] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def write_to(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))


# ---------- Helpers ----------

def _episode_slug(season: str, week: int) -> str:
    return f"{season}-w{week:02d}"


def datapack_dir(output_root: Path, league_key: str, season: str, week: int) -> Path:
    """Per-episode output directory: <root>/<league_key>/<season-wNN>/."""
    return output_root / league_key / _episode_slug(season, week)


def _scored(categories: list[StatCategory]) -> list[StatCategory]:
    return [c for c in categories if not c.is_only_display]


def _team_meta(teams: list[TeamStats]) -> list[dict]:
    return [{"team_key": t.team_key, "name": t.name, "manager": t.manager} for t in teams]


def _roto_entries(
    teams: list[TeamStats], categories: list[StatCategory]
) -> list[RotoEntry]:
    roto = compute_roto(teams, categories)
    scored = _scored(categories)
    entries: list[RotoEntry] = []
    for rank, r in enumerate(roto, 1):
        ranks = {c.stat_id: r.get(c.stat_id, 0.0) for c in scored}
        raws = {c.stat_id: r.get(f"raw_{c.stat_id}", "-") for c in scored}
        entries.append(RotoEntry(
            rank=rank, team_key=r["team_key"], name=r["name"], manager=r["manager"],
            total_points=r["total"], category_ranks=ranks, category_raw=raws,
        ))
    return entries


def _matchup_record(m: Matchup, categories: list[StatCategory]) -> MatchupRecord:
    scored = _scored(categories)
    cat_results: list[CategoryResult] = []
    a_cat_w = b_cat_w = ties = 0
    for c in scored:
        a_val = m.team_a.stats.get(c.stat_id, "0")
        b_val = m.team_b.stats.get(c.stat_id, "0")
        w = _category_winner(m, c, a_val, b_val)
        if w == "a":
            a_cat_w += 1
        elif w == "b":
            b_cat_w += 1
        else:
            ties += 1
        cat_results.append(CategoryResult(
            display_name=c.display_name,
            team_a_value=a_val, team_b_value=b_val, winner=w,
        ))
    return MatchupRecord(
        week=m.week, week_start=m.week_start, week_end=m.week_end,
        status=m.status,
        team_a_key=m.team_a.team_key, team_a_name=m.team_a.name,
        team_b_key=m.team_b.team_key, team_b_name=m.team_b.name,
        team_a_cat_wins=a_cat_w, team_b_cat_wins=b_cat_w, cat_ties=ties,
        winner_team_key=m.winner_team_key, category_results=cat_results,
    )


def _category_winner(
    m: Matchup, cat: StatCategory, a_val: str, b_val: str,
) -> str:
    """Per-category winner — see `gkl.stats.official_category_winner`."""
    return official_category_winner(m, cat)


def _h2h_records(
    all_matchups: list[Matchup],
    teams: list[TeamStats],
    categories: list[StatCategory],
) -> list[H2HRecord]:
    scored = _scored(categories)
    recs: dict[str, H2HRecord] = {
        t.team_key: H2HRecord(
            team_key=t.team_key, name=t.name, manager=t.manager,
            wins=0, losses=0, ties=0, cat_wins=0, cat_losses=0, cat_ties=0,
        )
        for t in teams
    }
    for m in all_matchups:
        if m.status != "postevent":
            continue
        a_cw = b_cw = tw = 0
        for c in scored:
            w = _category_winner(
                m, c,
                m.team_a.stats.get(c.stat_id, "0"),
                m.team_b.stats.get(c.stat_id, "0"),
            )
            if w == "a":
                a_cw += 1
            elif w == "b":
                b_cw += 1
            else:
                tw += 1

        # Trust Yahoo's authoritative matchup outcome (winner_team_key) over
        # our derived a_cw/b_cw comparison. Yahoo's stat_winners + tiebreaker
        # logic occasionally classifies a matchup result differently than a
        # local sum would (e.g. a postevent matchup that Yahoo recorded as a
        # tie even with non-equal category counts).
        if m.is_tied or not m.winner_team_key:
            a_outcome, b_outcome = "t", "t"
        elif m.winner_team_key == m.team_a.team_key:
            a_outcome, b_outcome = "w", "l"
        elif m.winner_team_key == m.team_b.team_key:
            a_outcome, b_outcome = "l", "w"
        else:
            a_outcome, b_outcome = "t", "t"

        for tk, opp_cw, own_cw, own_t, outcome in (
            (m.team_a.team_key, b_cw, a_cw, tw, a_outcome),
            (m.team_b.team_key, a_cw, b_cw, tw, b_outcome),
        ):
            r = recs.get(tk)
            if not r:
                continue
            r.cat_wins += own_cw
            r.cat_losses += opp_cw
            r.cat_ties += own_t
            if outcome == "w":
                r.wins += 1
            elif outcome == "l":
                r.losses += 1
            else:
                r.ties += 1
    return list(recs.values())


# How many recent played weeks team-momentum aggregates over. Sized for
# "the last few weeks" without bleeding into early-season noise. If the
# season has played fewer weeks than this, the window auto-shortens.
_MOMENTUM_WINDOW = 5

# How many weeks back to look for "historical adds" — players added far
# enough ago that there's meaningful data on how they've performed for the
# team that picked them up. Inclusive of both endpoints.
_HISTORICAL_ADD_WEEKS_AGO_MIN = 3
_HISTORICAL_ADD_WEEKS_AGO_MAX = 4


def _team_momentum(
    all_matchups: list[Matchup],
    teams: list[TeamStats],
    categories: list[StatCategory],
    target_week: int,
    *,
    window: int = _MOMENTUM_WINDOW,
) -> list[TeamMomentum]:
    """Aggregate each team's record over the last `window` played weeks.

    Considers postevent matchups in weeks (target_week - window + 1 .. target_week)
    inclusive. Auto-shortens when the season has played fewer weeks. Same
    win/loss attribution logic as `_h2h_records` (Yahoo's `winner_team_key`
    is authoritative over local category-count derivations).
    """
    window_start = max(1, target_week - window + 1)
    weeks_in_window = set(range(window_start, target_week + 1))
    scored = _scored(categories)

    recs: dict[str, TeamMomentum] = {
        t.team_key: TeamMomentum(
            team_key=t.team_key, name=t.name, manager=t.manager,
            weeks_covered=[],
            wins=0, losses=0, ties=0,
            cat_wins=0, cat_losses=0, cat_ties=0,
        )
        for t in teams
    }
    covered: dict[str, set[int]] = {t.team_key: set() for t in teams}

    for m in all_matchups:
        if m.week not in weeks_in_window:
            continue
        if m.status != "postevent":
            continue
        a_cw = b_cw = tw = 0
        for c in scored:
            w = _category_winner(
                m, c,
                m.team_a.stats.get(c.stat_id, "0"),
                m.team_b.stats.get(c.stat_id, "0"),
            )
            if w == "a":
                a_cw += 1
            elif w == "b":
                b_cw += 1
            else:
                tw += 1

        if m.is_tied or not m.winner_team_key:
            a_outcome, b_outcome = "t", "t"
        elif m.winner_team_key == m.team_a.team_key:
            a_outcome, b_outcome = "w", "l"
        elif m.winner_team_key == m.team_b.team_key:
            a_outcome, b_outcome = "l", "w"
        else:
            a_outcome, b_outcome = "t", "t"

        for tk, opp_cw, own_cw, own_t, outcome in (
            (m.team_a.team_key, b_cw, a_cw, tw, a_outcome),
            (m.team_b.team_key, a_cw, b_cw, tw, b_outcome),
        ):
            r = recs.get(tk)
            if not r:
                continue
            r.cat_wins += own_cw
            r.cat_losses += opp_cw
            r.cat_ties += own_t
            if outcome == "w":
                r.wins += 1
            elif outcome == "l":
                r.losses += 1
            else:
                r.ties += 1
            covered[tk].add(m.week)

    for tk, r in recs.items():
        r.weeks_covered = sorted(covered[tk])
    return list(recs.values())


def _week_window_timestamps(week_start: str, week_end: str) -> tuple[int, int]:
    """Return (inclusive start_ts, exclusive end_ts) for a Yahoo week window."""
    start_ts = int(datetime.fromisoformat(week_start).replace(
        tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.fromisoformat(week_end).replace(
        tzinfo=timezone.utc).timestamp()) + 86400
    return start_ts, end_ts


def _historical_adds(
    transactions: list[Transaction],
    rosters: list[TeamRoster],
    teams: list[TeamStats],
    week_dates: dict[int, tuple[str, str]],
    target_week: int,
) -> list[HistoricalAdd]:
    """Find adds from 3-4 weeks ago + join with current roster stats.

    For each successful `add` action whose timestamp falls in week
    (target_week - 4) or (target_week - 3), determine the fantasy team
    that picked them up and check whether they're still on that team's
    roster. Drops are still surfaced (with `still_on_roster=False` and
    empty stats) since "they cut him after two weeks" is itself a story.
    """
    rosters_by_team: dict[str, dict[str, RosterPlayer]] = {
        r.team_key: {p.player_key: p for p in r.players}
        for r in rosters
    }
    team_meta_by_name: dict[str, TeamStats] = {t.name: t for t in teams}

    out: list[HistoricalAdd] = []
    seen: set[tuple[str, str, int]] = set()  # (player_key, team_key, added_week)

    for week_offset in range(_HISTORICAL_ADD_WEEKS_AGO_MIN,
                             _HISTORICAL_ADD_WEEKS_AGO_MAX + 1):
        add_week = target_week - week_offset
        if add_week < 1:
            continue
        window = week_dates.get(add_week)
        if not window:
            continue
        ws, we = window
        if not ws or not we:
            continue
        start_ts, end_ts = _week_window_timestamps(ws, we)

        for tx in transactions:
            if tx.status != "successful":
                continue
            if not (start_ts <= tx.timestamp < end_ts):
                continue
            for p in tx.players:
                if p.action != "add":
                    continue
                # Prefer Yahoo's explicit destination_team_key when present;
                # fall back to team-name lookup for older payloads.
                team: TeamStats | None = None
                if p.to_team_key:
                    team = next(
                        (t for t in teams if t.team_key == p.to_team_key),
                        None,
                    )
                if team is None:
                    team = team_meta_by_name.get(p.to_team)
                if not team:
                    continue
                key = (p.player_key, team.team_key, add_week)
                if key in seen:
                    continue
                seen.add(key)
                roster_player = rosters_by_team.get(
                    team.team_key, {}).get(p.player_key)
                if roster_player is not None:
                    still_on_roster = True
                    selected_position = roster_player.selected_position
                    availability = roster_player.availability_tag
                    season_stats = dict(roster_player.season_stats)
                    last30_stats = dict(roster_player.last30_stats)
                else:
                    still_on_roster = False
                    selected_position = ""
                    availability = "[DROPPED]"
                    season_stats = {}
                    last30_stats = {}

                out.append(HistoricalAdd(
                    player_key=p.player_key,
                    player_name=p.name,
                    position=p.position,
                    team_abbr=p.team_abbr,
                    added_week=add_week,
                    weeks_ago=week_offset,
                    fantasy_team_key=team.team_key,
                    fantasy_team_name=team.name,
                    manager=team.manager,
                    still_on_roster=still_on_roster,
                    selected_position=selected_position,
                    availability_tag=availability,
                    season_stats=season_stats,
                    last30_stats=last30_stats,
                ))
    return out


def _power_rankings(
    teams: list[TeamStats], categories: list[StatCategory],
) -> list[PowerRanking]:
    """Season-aggregate power rankings (hypothetical all-play record)."""
    h2h = simulate_h2h(teams, categories)
    summaries = compute_power_rankings(h2h, teams)
    return [
        PowerRanking(
            rank=rank, team_key=s.team_key, name=s.name, manager=s.manager,
            hypothetical_wins=s.total_wins,
            hypothetical_losses=s.total_losses,
            hypothetical_ties=s.total_ties,
            win_pct=s.win_pct,
        )
        for rank, s in enumerate(summaries, 1)
    ]


def _weekly_power_rankings(
    target_matchups: list[Matchup],
    season_teams: list[TeamStats],
    categories: list[StatCategory],
) -> list[PowerRanking]:
    """Single-week all-play power rankings for the TARGET week only.

    Built from each team's category totals FOR the target week (carried on
    the target-week matchups), not season-cumulative stats. This is the
    "who had the best week" view Act 1 leans on — distinct from
    `_power_rankings`, which is season-long. Early episodes shipped only the
    season view, so the hosts' "best team this week" framing had no
    matching ground truth and drifted (e.g. a team's season 13-4 quoted
    where its weekly 16-1 was meant). Manager names are joined from
    `season_teams` since matchup-side teams may not carry them.
    """
    mgr = {t.team_key: t.manager for t in season_teams}
    week_teams: list[TeamStats] = []
    seen: set[str] = set()
    for m in target_matchups:
        for side in (m.team_a, m.team_b):
            if side.team_key in seen:
                continue
            seen.add(side.team_key)
            week_teams.append(TeamStats(
                team_key=side.team_key, name=side.name,
                manager=mgr.get(side.team_key, side.manager),
                points=0.0, projected_points=0.0,
                stats=dict(side.stats),
            ))
    if not week_teams:
        return []
    h2h = simulate_h2h(week_teams, categories)
    summaries = compute_power_rankings(h2h, week_teams)
    return [
        PowerRanking(
            rank=rank, team_key=s.team_key, name=s.name, manager=s.manager,
            hypothetical_wins=s.total_wins,
            hypothetical_losses=s.total_losses,
            hypothetical_ties=s.total_ties,
            win_pct=s.win_pct,
        )
        for rank, s in enumerate(summaries, 1)
    ]


def _roster_player(
    season_p: PlayerStats, last30_map: dict[str, PlayerStats]
) -> RosterPlayer:
    last30 = last30_map.get(season_p.player_key)
    return RosterPlayer(
        player_key=season_p.player_key,
        name=season_p.name,
        position=season_p.position,
        team_abbr=season_p.team_abbr,
        selected_position=season_p.selected_position,
        availability_tag=availability_tag(season_p),
        season_stats=dict(season_p.stats),
        last30_stats=dict(last30.stats) if last30 else {},
    )


async def _fetch_team_roster(
    api: YahooFantasyAPI, team: TeamStats, week: int,
) -> TeamRoster:
    season_players, last30_players = await asyncio.gather(
        asyncio.to_thread(api.get_roster_stats_season, team.team_key, week),
        asyncio.to_thread(api.get_roster_stats_last30, team.team_key, week),
    )
    last30_by_key = {p.player_key: p for p in last30_players}
    return TeamRoster(
        team_key=team.team_key,
        team_name=team.name,
        manager=team.manager,
        players=[_roster_player(p, last30_by_key) for p in season_players],
    )


async def _fetch_team_target_week_roster(
    api: YahooFantasyAPI, team: TeamStats, target_week: int,
) -> TeamRoster:
    """Fetch the team's roster AS OF the target week, with each player's
    stats FOR that week.

    This is the ground truth for fact-checking per-player claims in the
    weekly recap. Includes players who were on the roster during the
    target week even if they've since been dropped.
    """
    week_players = await asyncio.to_thread(
        api.get_roster_stats, team.team_key, target_week,
    )
    return TeamRoster(
        team_key=team.team_key,
        team_name=team.name,
        manager=team.manager,
        players=[
            RosterPlayer(
                player_key=p.player_key,
                name=p.name,
                position=p.position,
                team_abbr=p.team_abbr,
                selected_position=p.selected_position,
                availability_tag=availability_tag(p),
                season_stats={},
                last30_stats={},
                week_stats=dict(p.stats),
            )
            for p in week_players
        ],
    )


def _transaction_records(
    transactions: list[Transaction], week_start: str, week_end: str,
) -> list[TransactionRecord]:
    if week_start and week_end:
        start_ts = int(datetime.fromisoformat(week_start).replace(
            tzinfo=timezone.utc).timestamp())
        # Inclusive end-of-day: +1 day worth of seconds
        end_ts = int(datetime.fromisoformat(week_end).replace(
            tzinfo=timezone.utc).timestamp()) + 86400
    else:
        start_ts = end_ts = None

    out: list[TransactionRecord] = []
    for tx in transactions:
        in_week = start_ts is not None and start_ts <= tx.timestamp < end_ts
        out.append(TransactionRecord(
            transaction_key=tx.transaction_key,
            type=tx.type,
            timestamp_iso=datetime.fromtimestamp(tx.timestamp, tz=timezone.utc).isoformat(),
            status=tx.status,
            in_target_week=in_week,
            players=[
                TransactionPlayerRecord(
                    player_key=p.player_key, name=p.name, position=p.position,
                    team_abbr=p.team_abbr, action=p.action,
                    from_team=p.from_team, to_team=p.to_team,
                )
                for p in tx.players
            ],
        ))
    return out


def _mlb_game_records(games_by_date: dict[str, list[MLBGame]]) -> list[MLBGameRecord]:
    out: list[MLBGameRecord] = []
    for d, games in games_by_date.items():
        for g in games:
            out.append(MLBGameRecord(
                date=d, gamePk=str(g.gamePk), status=g.status,
                home_team=g.home_team, away_team=g.away_team,
                home_score=g.home_score, away_score=g.away_score,
            ))
    return out


_YAHOO_PAGE_SIZE = 25


async def _fetch_free_agents_paginated(
    api: YahooFantasyAPI, league_key: str, stat_type: str, total: int,
):
    """Paginate Yahoo's free-agent list (25/page max) up to `total` rows."""
    pages = []
    for start in range(0, total, _YAHOO_PAGE_SIZE):
        page_count = min(_YAHOO_PAGE_SIZE, total - start)
        pages.append(asyncio.to_thread(
            api.get_free_agents, league_key,
            stat_type=stat_type, sort="AR", sort_type="season",
            start=start, count=page_count,
        ))
    results = await asyncio.gather(*pages)
    players = []
    for page_players, _ in results:
        players.extend(page_players)
        if len(page_players) < _YAHOO_PAGE_SIZE:
            break  # Yahoo returned fewer than asked — pool exhausted
    return players


async def _fetch_top_free_agents(
    api: YahooFantasyAPI, league_key: str, count: int,
) -> list[RosterPlayer]:
    """Fetch the top `count` free agents with season + last30 stats.

    Sorted by Yahoo's actual-rank ("AR") so the pool skews toward players
    a real fantasy manager would consider adding. Yahoo caps each
    free-agents request at 25 players, so larger pools are paginated.
    Season and last30 stats are fetched in parallel and joined on
    player_key.
    """
    season_task = _fetch_free_agents_paginated(api, league_key, "season", count)
    last30_task = _fetch_free_agents_paginated(api, league_key, "lastmonth", count)
    season_players, last30_players = await asyncio.gather(
        season_task, last30_task,
    )
    last30_by_key = {p.player_key: p for p in last30_players}
    out: list[RosterPlayer] = []
    for p in season_players:
        last30 = last30_by_key.get(p.player_key)
        out.append(RosterPlayer(
            player_key=p.player_key,
            name=p.name,
            position=p.position,
            team_abbr=p.team_abbr,
            selected_position=p.selected_position,
            availability_tag="[FREE AGENT]",
            season_stats=dict(p.stats),
            last30_stats=dict(last30.stats) if last30 else {},
        ))
    return out


async def _fetch_mlb_context(week_start: str, week_end: str) -> dict[str, list[MLBGame]]:
    start = date.fromisoformat(week_start)
    end = date.fromisoformat(week_end)
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    results = await asyncio.gather(*[
        asyncio.to_thread(get_mlb_scoreboard, d) for d in days
    ])
    return {d.isoformat(): games for d, games in zip(days, results)}


# ---------- Public API ----------

async def build_weekly_recap_datapack(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    target_week: int,
) -> DataPack:
    """Build the raw-datasets half of a Weekly Recap data pack.

    The target_week is the week being recapped (usually the most recently
    completed week). Rosters are fetched at the current_week snapshot —
    which is what the hosts would talk about "going into next week."
    """
    if target_week < 1 or target_week >= league.current_week:
        raise ValueError(
            f"target_week must be a completed week (1..{league.current_week - 1}); "
            f"got {target_week}"
        )

    league_key = league.league_key

    # Base fetches that everything else depends on
    season_teams_task = asyncio.to_thread(api.get_team_season_stats, league_key)
    week_dates_task = asyncio.to_thread(api.get_week_dates, league_key)
    target_matchups_task = asyncio.to_thread(api.get_scoreboard, league_key, target_week)
    transactions_task = asyncio.to_thread(api.get_transactions, league_key, 200)

    # Pull all-season matchups (1..current-1) for H2H records
    season_matchup_tasks = [
        asyncio.to_thread(api.get_scoreboard, league_key, w)
        for w in range(1, league.current_week)
    ]

    (season_teams, week_dates, target_matchups, transactions, *season_matchups_lists) = \
        await asyncio.gather(
            season_teams_task, week_dates_task, target_matchups_task,
            transactions_task, *season_matchup_tasks,
        )

    all_season_matchups: list[Matchup] = []
    for lst in season_matchups_lists:
        all_season_matchups.extend(lst)

    week_start, week_end = week_dates.get(target_week, ("", ""))
    if not week_start:
        # Fall back to the matchup's own dates (always present on the Matchup)
        if target_matchups:
            week_start = target_matchups[0].week_start
            week_end = target_matchups[0].week_end

    # Rosters + MLB context can start once we know the week window. We
    # fetch BOTH the current-week rosters (for season + last30 trend
    # context) AND the target-week rosters (for fact-checking per-player
    # weekly claims). All concurrent.
    roster_tasks = [
        _fetch_team_roster(api, t, league.current_week) for t in season_teams
    ]
    target_week_roster_tasks = [
        _fetch_team_target_week_roster(api, t, target_week) for t in season_teams
    ]
    mlb_task = _fetch_mlb_context(week_start, week_end)
    free_agents_task = _fetch_top_free_agents(
        api, league_key, _FREE_AGENT_POOL_SIZE,
    )
    rosters, target_week_rosters, mlb_games_by_date, free_agents = \
        await asyncio.gather(
            asyncio.gather(*roster_tasks),
            asyncio.gather(*target_week_roster_tasks),
            mlb_task,
            free_agents_task,
        )

    meta = DataPackMeta(
        league_key=league_key,
        league_name=league.name,
        season=league.season,
        segment="weekly-recap",
        target_week=target_week,
        current_week=league.current_week,
        week_start=week_start,
        week_end=week_end,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    rosters_list = list(rosters)
    return DataPack(
        meta=meta,
        categories=[
            StatCategoryRecord(
                stat_id=c.stat_id, display_name=c.display_name,
                sort_order=c.sort_order, position_type=c.position_type,
                is_only_display=c.is_only_display,
            )
            for c in categories
        ],
        teams=_team_meta(season_teams),
        roto_standings=_roto_entries(season_teams, categories),
        h2h_records=_h2h_records(all_season_matchups, season_teams, categories),
        power_rankings=_power_rankings(season_teams, categories),
        weekly_power_rankings=_weekly_power_rankings(
            target_matchups, season_teams, categories,
        ),
        target_week_matchups=[_matchup_record(m, categories) for m in target_matchups],
        rosters=rosters_list,
        target_week_rosters=list(target_week_rosters),
        transactions=_transaction_records(transactions, week_start, week_end),
        mlb_games=_mlb_game_records(mlb_games_by_date),
        free_agents=free_agents,
        team_momentum=_team_momentum(
            all_season_matchups, season_teams, categories, target_week,
        ),
        historical_adds=_historical_adds(
            transactions, rosters_list, season_teams, week_dates, target_week,
        ),
    )
