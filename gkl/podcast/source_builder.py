"""Data-formatter utilities for the podcast pipeline.

Used by `script_writer.build_data_summary()` to give the script-writer LLM
a compact natural-language view of the data pack. These helpers used to
back a Studio-Podcast-specific source builder; they're now general-purpose
data formatters that the script writer (and any future segment) can use.
"""

from __future__ import annotations

import re

from gkl.podcast.datapack import (
    DataPack, HistoricalAdd, MatchupRecord, RotoEntry, TeamMomentum,
)


# ---------- Optional splitter (kept for inspection/debugging) ----------

_ACT_HEADING_PAT = re.compile(r"^##\s+Act\s+([123])\b.*$", re.MULTILINE)


def split_suggested_topics(markdown: str) -> dict[int, str]:
    """Split the Phase 2 suggested-topics markdown on `## Act N` headings.

    Returns a dict mapping act number (1, 2, 3) to the body under each
    heading. Not used by the main pipeline anymore (the script writer
    consumes the whole suggested-topics document at once), but handy for
    debugging or segment-specific tooling.
    """
    matches = list(_ACT_HEADING_PAT.finditer(markdown))
    if not matches:
        raise ValueError(
            "suggested-topics markdown has no `## Act N` headings"
        )
    sections: dict[int, str] = {}
    for i, m in enumerate(matches):
        act_n = int(m.group(1))
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        sections[act_n] = markdown[body_start:body_end].strip()
    missing = {1, 2, 3} - set(sections.keys())
    if missing:
        raise ValueError(
            f"suggested-topics markdown is missing act(s): {sorted(missing)}"
        )
    return sections


# ---------- Data-summary formatters ----------

def format_scoreboard(matchups: list[MatchupRecord]) -> str:
    """Natural-language scoreboard for a list of matchups (one per line)."""
    if not matchups:
        return "(no matchups in the target week)"
    lines = []
    for m in matchups:
        if m.team_a_cat_wins > m.team_b_cat_wins:
            winner, loser = m.team_a_name, m.team_b_name
            wc, lc = m.team_a_cat_wins, m.team_b_cat_wins
            desc = f"{winner} defeated {loser}, {wc} categories to {lc}"
        elif m.team_b_cat_wins > m.team_a_cat_wins:
            winner, loser = m.team_b_name, m.team_a_name
            wc, lc = m.team_b_cat_wins, m.team_a_cat_wins
            desc = f"{winner} defeated {loser}, {wc} categories to {lc}"
        else:
            desc = (
                f"{m.team_a_name} and {m.team_b_name} tied at "
                f"{m.team_a_cat_wins} categories each"
            )
        if m.cat_ties:
            desc += f" (tied {m.cat_ties} {'category' if m.cat_ties == 1 else 'categories'})"
        lines.append(f"- {desc}")
    return "\n".join(lines)


_ROTO_NEAR_TIE_THRESHOLD = 2.0


def format_standings(standings: list[RotoEntry], top_n: int = 10) -> str:
    """Compact roto standings as prose lines, with near-tie clusters flagged.

    Roto totals can sit within a fraction of a point of each other, and the
    order across such a gap is fragile — a single late stat correction flips
    it. We surface adjacent teams within `_ROTO_NEAR_TIE_THRESHOLD` points so
    the script avoids asserting hard ordinals ("2nd vs 4th") across a
    near-tie, and the fact-checker can flag it when it does.
    """
    if not standings:
        return "(no standings)"
    lines = []
    for e in standings[:top_n]:
        lines.append(
            f"- {e.rank}. {e.name} ({e.manager}): {e.total_points:.1f} roto points"
        )
    if len(standings) > top_n:
        remaining = standings[top_n:]
        tail = ", ".join(f"{e.rank}. {e.name}" for e in remaining)
        lines.append(f"- Remaining: {tail}")

    clusters: list[str] = []
    for a, b in zip(standings, standings[1:]):
        gap = abs(a.total_points - b.total_points)
        if gap <= _ROTO_NEAR_TIE_THRESHOLD:
            clusters.append(f"{a.name} and {b.name} ({gap:.1f} apart)")
    if clusters:
        lines.append(
            "Near-tied in roto (do NOT assert a hard ordinal like 'second "
            "versus fourth' across these — call it neck-and-neck): "
            + "; ".join(clusters)
        )
    return "\n".join(lines)


def format_power_rankings(power_rankings, top_n: int = 10) -> str:
    if not power_rankings:
        return "(no power rankings)"
    lines = []
    for p in power_rankings[:top_n]:
        lines.append(
            f"- {p.rank}. {p.name} ({p.manager}): "
            f"{p.hypothetical_wins}-{p.hypothetical_losses}-{p.hypothetical_ties} "
            f"hypothetical record, {p.win_pct:.3f} win%"
        )
    return "\n".join(lines)


def format_weekly_power_rankings(datapack: DataPack, top_n: int = 10) -> str:
    """Single-week all-play power rankings for the target week.

    THE source of truth for any "best team this week" / weekly power-ranking
    claim in Act 1. Distinct from the season-cumulative power rankings — a
    team can crush a single week (16-1) while sitting mid-pack on the season,
    and vice versa. Confusing the two was the cause of early-episode errors.
    """
    pr = getattr(datapack, "weekly_power_rankings", None) or []
    if not pr:
        return "(no weekly power rankings)"
    week = datapack.meta.target_week
    lines = []
    for p in pr[:top_n]:
        lines.append(
            f"- {p.rank}. {p.name} ({p.manager}): "
            f"{p.hypothetical_wins}-{p.hypothetical_losses}-{p.hypothetical_ties} "
            f"for Week {week} ({p.win_pct:.3f} win%)"
        )
    return "\n".join(lines)


def _cat_record_winpct(r) -> float:
    total = r.cat_wins + r.cat_losses + r.cat_ties
    return (r.cat_wins + 0.5 * r.cat_ties) / total if total else 0.0


def format_h2h_records(h2h_records) -> str:
    """Head-to-head records sorted by wins then cat_wins.

    Each line includes both framings of the matchup record so the script
    writer can use either:
    - Formal: `3-1-0` (W-L-T)
    - Narrative: `won 3 of their 4 matchups`

    Plus the categorical record (X-Y-Z in categories) for context on how
    dominant the matchup wins were.
    """
    if not h2h_records:
        return "(no head-to-head records)"
    sorted_recs = sorted(
        h2h_records,
        key=lambda r: (r.wins, r.cat_wins),
        reverse=True,
    )
    lines = []
    for r in sorted_recs:
        total_matchups = r.wins + r.losses + r.ties
        if r.ties:
            narrative = (
                f"won {r.wins} of {total_matchups} matchups, "
                f"with {r.ties} {'tie' if r.ties == 1 else 'ties'}"
            )
        else:
            narrative = f"won {r.wins} of {total_matchups} matchups"
        lines.append(
            f"- {r.name} ({r.manager}): "
            f"{r.wins}-{r.losses}-{r.ties} record "
            f"({narrative}; "
            f"{r.cat_wins}-{r.cat_losses}-{r.cat_ties} in categories)"
        )

    # The category-record LEADER is decided by win percentage, not raw
    # category wins. A team can have the most category wins yet trail on
    # win% because of ties (this exact case caused an early-episode error
    # where "most cat wins" was mistaken for "leads the category record").
    by_winpct = sorted(
        h2h_records, key=lambda r: _cat_record_winpct(r), reverse=True,
    )
    leader_line = ", ".join(
        f"{r.name} ({r.cat_wins}-{r.cat_losses}-{r.cat_ties}, "
        f"{_cat_record_winpct(r):.3f})"
        for r in by_winpct[:3]
    )
    lines.append(
        "Category-record leaders BY WIN PERCENTAGE (this, not raw category "
        f"wins, decides who 'leads the category record'): {leader_line}"
    )
    return "\n".join(lines)


def _player_stats_line(
    player, batting_categories, pitching_categories,
) -> str:
    """One-line summary of a player's week stats, using only the categories
    relevant to their position type (batting vs pitching)."""
    is_pitcher = any(
        pos in ("SP", "RP", "P")
        for pos in (player.position or "").split(",")
    )
    cats = pitching_categories if is_pitcher else batting_categories
    parts: list[str] = []
    for c in cats:
        val = player.week_stats.get(c.stat_id, "")
        if val == "" or val == "-":
            continue
        parts.append(f"{c.display_name} {val}")
    if not parts:
        # Player on roster but no week stats (didn't play / no data)
        return (
            f"- {player.name} ({player.position}, {player.team_abbr}) "
            f"{player.availability_tag}: did not record stats"
        )
    return (
        f"- {player.name} ({player.position}, {player.team_abbr}) "
        f"{player.availability_tag}: " + ", ".join(parts)
    )


def format_target_week_player_stats(datapack: DataPack) -> str:
    """Per-player weekly stat lines grouped by fantasy team.

    This is the ground truth for the fact-checker — every per-player claim
    in the script must match what's here. Uses the league's actual scoring
    categories (split by position type) so we surface what the league cares
    about, not arbitrary stats.
    """
    if not datapack.target_week_rosters:
        return "(no target-week rosters in this data pack)"

    scored = [c for c in datapack.categories if not c.is_only_display]
    batting_cats = [c for c in scored if c.position_type == "B"]
    pitching_cats = [c for c in scored if c.position_type == "P"]

    blocks: list[str] = []
    for roster in datapack.target_week_rosters:
        header = f"{roster.team_name} ({roster.manager}):"
        lines = [
            _player_stats_line(p, batting_cats, pitching_cats)
            for p in roster.players
        ]
        blocks.append(header + "\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def _free_agent_stats_line(
    player, scored_cats,
) -> str:
    """Compact season + last30 line for a single free agent."""
    is_pitcher = any(
        pos in ("SP", "RP", "P")
        for pos in (player.position or "").split(",")
    )
    cats = [c for c in scored_cats if c.position_type == ("P" if is_pitcher else "B")]
    season_parts = []
    last30_parts = []
    for c in cats:
        s_val = player.season_stats.get(c.stat_id, "")
        if s_val not in ("", "-"):
            season_parts.append(f"{c.display_name} {s_val}")
        l_val = player.last30_stats.get(c.stat_id, "")
        if l_val not in ("", "-"):
            last30_parts.append(f"{c.display_name} {l_val}")
    season_str = ", ".join(season_parts) if season_parts else "(no season data)"
    last30_str = ", ".join(last30_parts) if last30_parts else "(no last30 data)"
    return (
        f"- {player.name} ({player.position}, {player.team_abbr}): "
        f"season — {season_str}; last 30 — {last30_str}"
    )


def format_free_agents(datapack: DataPack, *, top_n: int | None = None) -> str:
    """Top free agents grouped by position type, with season + last30 stats.

    Used by the script writer for Act 3 (free-agent pickups) and by the
    fact-checker to verify whichever players the script recommends.
    `top_n=None` includes every free agent in the data pack.
    """
    fas = datapack.free_agents
    if top_n is not None:
        fas = fas[:top_n]
    if not fas:
        return "(no free agents in the data pack)"

    scored = [c for c in datapack.categories if not c.is_only_display]

    def _is_pitcher(player) -> bool:
        return any(
            pos in ("SP", "RP", "P")
            for pos in (player.position or "").split(",")
        )

    hitters = [p for p in fas if not _is_pitcher(p)]
    pitchers = [p for p in fas if _is_pitcher(p)]

    blocks: list[str] = []
    if hitters:
        blocks.append(
            "Top free-agent hitters:\n"
            + "\n".join(_free_agent_stats_line(p, scored) for p in hitters)
        )
    if pitchers:
        blocks.append(
            "Top free-agent pitchers:\n"
            + "\n".join(_free_agent_stats_line(p, scored) for p in pitchers)
        )
    return "\n\n".join(blocks)


def format_team_momentum(datapack: DataPack) -> str:
    """Last-N-week record per team — for Act 2 momentum framing.

    Sorted hottest first (wins desc, cat_wins desc). Lines include the window
    (e.g. "weeks 3-7") so the script can be specific about the run. Teams
    with no postevent matchups in the window are reported as "no recent data"
    rather than skipped — keeps the list complete for the standings tour.
    """
    momentum: list[TeamMomentum] = list(datapack.team_momentum)
    if not momentum:
        return "(no momentum data)"
    momentum.sort(key=lambda r: (r.wins, r.cat_wins), reverse=True)

    lines: list[str] = []
    for r in momentum:
        if not r.weeks_covered:
            lines.append(
                f"- {r.name} ({r.manager}): no recent matchup data"
            )
            continue
        if len(r.weeks_covered) == 1:
            window = f"week {r.weeks_covered[0]}"
        else:
            window = (
                f"weeks {r.weeks_covered[0]}-{r.weeks_covered[-1]} "
                f"({len(r.weeks_covered)} matchups)"
            )
        lines.append(
            f"- {r.name} ({r.manager}): "
            f"{r.wins}-{r.losses}-{r.ties} over {window}, "
            f"{r.cat_wins}-{r.cat_losses}-{r.cat_ties} in categories"
        )
    return "\n".join(lines)


def _historical_add_stats_line(
    add: HistoricalAdd, scored_cats,
) -> str:
    """One-line summary of the player's stats since the add."""
    if not add.still_on_roster:
        return (
            f"- {add.player_name} ({add.position}, {add.team_abbr}): "
            f"dropped after pickup — no longer on roster"
        )
    is_pitcher = any(
        pos in ("SP", "RP", "P")
        for pos in (add.position or "").split(",")
    )
    cats = [
        c for c in scored_cats
        if c.position_type == ("P" if is_pitcher else "B")
    ]
    last30_parts: list[str] = []
    season_parts: list[str] = []
    for c in cats:
        s_val = add.season_stats.get(c.stat_id, "")
        if s_val not in ("", "-"):
            season_parts.append(f"{c.display_name} {s_val}")
        l_val = add.last30_stats.get(c.stat_id, "")
        if l_val not in ("", "-"):
            last30_parts.append(f"{c.display_name} {l_val}")
    season_str = ", ".join(season_parts) if season_parts else "(no season data)"
    last30_str = ", ".join(last30_parts) if last30_parts else "(no last30 data)"
    slot = add.selected_position or "—"
    return (
        f"- {add.player_name} ({add.position}, {add.team_abbr}) "
        f"{add.availability_tag} [slot: {slot}]: "
        f"last 30 — {last30_str}; season — {season_str}"
    )


def format_historical_adds(datapack: DataPack) -> str:
    """Players added 3-4 weeks ago, grouped by the team that added them.

    Used for Act 3's "look-back" topic and as fact-checker ground truth for
    look-back stat claims. Drops are surfaced too — "they cut him after two
    weeks" is itself a story.
    """
    adds = datapack.historical_adds
    if not adds:
        return "(no qualifying adds from 3-4 weeks ago)"

    scored = [c for c in datapack.categories if not c.is_only_display]
    by_team: dict[str, list[HistoricalAdd]] = {}
    team_label: dict[str, str] = {}
    for a in adds:
        by_team.setdefault(a.fantasy_team_key, []).append(a)
        team_label[a.fantasy_team_key] = f"{a.fantasy_team_name} ({a.manager})"

    blocks: list[str] = []
    for team_key, team_adds in by_team.items():
        team_adds.sort(key=lambda x: (x.added_week, x.player_name))
        header = f"{team_label[team_key]}:"
        lines = []
        for a in team_adds:
            lines.append(
                f"- Added Week {a.added_week} ({a.weeks_ago} weeks ago): "
                f"{a.player_name}"
            )
            lines.append(
                "  " + _historical_add_stats_line(a, scored).lstrip("- ")
            )
        blocks.append(header + "\n" + "\n".join(lines))
    return "\n\n".join(blocks)


# ---------- Category Kings + weekly standouts + roster form ----------

# Rate (per-rate) stats — excluded from weekly-standout *selection* because a
# one-week sample makes them noisy (a reliever with one inning can "lead" ERA).
# They still appear in the bundled stat lines; they just don't crown standouts.
_RATE_STAT_NAMES = {
    "AVG", "OBP", "SLG", "OPS", "ERA", "WHIP", "K/BB", "K/9", "BB%", "BABIP",
}


def _is_rate_stat(cat) -> bool:
    return (cat.display_name or "").upper() in _RATE_STAT_NAMES


def _to_number(val) -> float | None:
    """Parse a Yahoo stat string to a float, or None if not numeric."""
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def format_category_leaders(datapack: DataPack, *, top_n: int = 3) -> str:
    """Per-category season-long leaders from the roto table.

    `category_ranks` holds each team's roto POINTS in a category (worst team
    gets 1, the leader gets N) — so higher is better regardless of whether the
    underlying stat sorts high or low. Teams are listed best-first; the head
    of each line is the category leader. Ground truth for the Act 2 "Category
    Kings" topic AND for any "manager is Nth in <category> on the season"
    color layered elsewhere in the episode.
    """
    standings = datapack.roto_standings
    scored = [c for c in datapack.categories if not c.is_only_display]
    if not standings or not scored:
        return "(no category standings)"

    lead_counts: dict[str, int] = {}
    lines: list[str] = []
    for c in scored:
        # Highest roto points = the category leader. Ties get averaged points,
        # so the max value is the leader (possibly shared).
        ranked = sorted(
            standings,
            key=lambda e, sid=c.stat_id: e.category_ranks.get(sid, -1.0),
            reverse=True,
        )
        best_points = ranked[0].category_ranks.get(c.stat_id)
        # Count every team sharing the best (highest) points as a co-leader.
        for e in ranked:
            if e.category_ranks.get(c.stat_id) == best_points:
                lead_counts[e.name] = lead_counts.get(e.name, 0) + 1
            else:
                break
        parts = [
            f"{e.name} ({e.category_raw.get(c.stat_id, '-')})"
            for e in ranked[:top_n]
        ]
        lines.append(f"- {c.display_name}: " + " > ".join(parts))

    body = "\n".join(lines)
    leaders_summary = ", ".join(
        f"{name} ({cnt})"
        for name, cnt in sorted(
            lead_counts.items(), key=lambda kv: kv[1], reverse=True,
        )
    )
    if leaders_summary:
        body += f"\n\nMost categories led: {leaders_summary}"
    return body


def format_weekly_standouts(
    datapack: DataPack, *, per_category: int = 2, max_players: int = 12,
) -> str:
    """Top individual weekly performances, bundled with last30 + season form.

    Selection is generic: for each counting category (rate stats excluded to
    avoid small-sample noise), the top `per_category` rostered players by
    target-week value become standout candidates. The union is deduped,
    ordered by how many categories a player topped, and capped at
    `max_players`. Each line bundles the week line + last-30-day + season line
    so the script can *conditionally* layer trend/season context onto a weekly
    performance (the "beyond the headline" enrichment). Powers Act 2's
    "Weekly Awards" topic.
    """
    if not datapack.target_week_rosters:
        return "(no target-week rosters in this data pack)"
    scored = [c for c in datapack.categories if not c.is_only_display]
    counting = [c for c in scored if not _is_rate_stat(c)]

    # season/last30 form, joined by player_key from the current-week rosters
    form_by_key: dict[str, object] = {
        p.player_key: p for r in datapack.rosters for p in r.players
    }
    week_players: dict[str, object] = {}
    team_by_player: dict[str, str] = {}
    for r in datapack.target_week_rosters:
        for p in r.players:
            week_players[p.player_key] = p
            team_by_player[p.player_key] = r.team_name

    topped: dict[str, set[str]] = {}  # player_key -> categories topped
    for c in counting:
        higher_better = c.sort_order != "0"
        rated = [
            (_to_number(p.week_stats.get(c.stat_id, "")), pk)
            for pk, p in week_players.items()
        ]
        rated = [(v, pk) for v, pk in rated if v is not None]
        if not rated:
            continue
        rated.sort(reverse=higher_better)
        for v, pk in rated[:per_category]:
            if v == 0:
                continue  # a zero in a counting cat isn't a standout
            topped.setdefault(pk, set()).add(c.display_name)

    if not topped:
        return "(no standout weekly performances)"

    ordered = sorted(
        topped.items(), key=lambda kv: len(kv[1]), reverse=True,
    )[:max_players]

    lines: list[str] = []
    for pk, cats in ordered:
        wp = week_players[pk]
        is_pitcher = any(
            pos in ("SP", "RP", "P") for pos in (wp.position or "").split(",")
        )
        rel = [
            c for c in scored
            if c.position_type == ("P" if is_pitcher else "B")
        ]
        week_parts = [
            f"{c.display_name} {wp.week_stats[c.stat_id]}"
            for c in rel
            if wp.week_stats.get(c.stat_id, "") not in ("", "-")
        ]
        form = form_by_key.get(pk)
        season_parts: list[str] = []
        last30_parts: list[str] = []
        if form is not None:
            for c in rel:
                s = form.season_stats.get(c.stat_id, "")
                if s not in ("", "-"):
                    season_parts.append(f"{c.display_name} {s}")
                l = form.last30_stats.get(c.stat_id, "")
                if l not in ("", "-"):
                    last30_parts.append(f"{c.display_name} {l}")
        line = (
            f"- {wp.name} ({wp.position}, {wp.team_abbr}) on "
            f"{team_by_player.get(pk, '')} {wp.availability_tag}: week — "
            + (", ".join(week_parts) if week_parts else "did not record stats")
        )
        if last30_parts:
            line += "; last 30 — " + ", ".join(last30_parts)
        if season_parts:
            line += "; season — " + ", ".join(season_parts)
        line += f"  [topped this week: {', '.join(sorted(cats))}]"
        lines.append(line)
    return "\n".join(lines)


def format_roster_form(datapack: DataPack) -> str:
    """Season + last-30-day lines for every current rostered player, by team.

    Fact-checker ground truth for any trend/season claim the script layers on
    top of a weekly performance ("he's slugging six-twenty over the last
    thirty"). The per-week table (`format_target_week_player_stats`) verifies
    the headline weekly number; this verifies the context around it.
    """
    if not datapack.rosters:
        return "(no current rosters in this data pack)"
    scored = [c for c in datapack.categories if not c.is_only_display]
    blocks: list[str] = []
    for r in datapack.rosters:
        header = f"{r.team_name} ({r.manager}):"
        lines = [_free_agent_stats_line(p, scored) for p in r.players]
        blocks.append(header + "\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def format_target_week_transactions(datapack: DataPack) -> str:
    txns = [t for t in datapack.transactions if t.in_target_week]
    if not txns:
        return "(no transactions during the target week)"
    lines = []
    for t in txns:
        tx_type = t.type or "transaction"
        player_parts = []
        for p in t.players:
            action = p.action or "moved"
            if p.from_team and p.to_team and p.from_team != p.to_team:
                player_parts.append(
                    f"{p.name} ({p.position}, {p.team_abbr}): {action} "
                    f"from {p.from_team} to {p.to_team}"
                )
            else:
                player_parts.append(f"{p.name} ({p.position}, {p.team_abbr}): {action}")
        lines.append(f"- {tx_type.title()}: " + "; ".join(player_parts))
    return "\n".join(lines)
