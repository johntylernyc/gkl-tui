"""Data-formatter utilities for the podcast pipeline.

Used by `script_writer.build_data_summary()` to give the script-writer LLM
a compact natural-language view of the data pack. These helpers used to
back a Studio-Podcast-specific source builder; they're now general-purpose
data formatters that the script writer (and any future segment) can use.
"""

from __future__ import annotations

import re

from gkl.podcast.datapack import DataPack, MatchupRecord, RotoEntry


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


def format_standings(standings: list[RotoEntry], top_n: int = 10) -> str:
    """Compact roto standings as prose lines."""
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
