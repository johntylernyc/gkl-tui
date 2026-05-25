"""Phase 2 — run Skipper to produce the suggested-topics narrative.

The segment's Markdown file is the source of truth for the Phase 2 prompt.
`seed_weekly_recap()` parses out the `## Skipper seed` section's two
sub-sections (`### System addendum` and `### User prompt`), substitutes the
episode tokens, and drives a non-interactive `Skipper.run_once()` call with
`SKIPPER_PODCAST_MODEL`. The resulting markdown is written alongside the data
pack as `suggested-topics.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gkl.podcast import SKIPPER_PODCAST_MODEL
from gkl.skipper import Skipper
from gkl.yahoo_api import League, StatCategory, YahooFantasyAPI


# ---------- Prompt extraction ----------

@dataclass
class SegmentPrompt:
    """A parsed Phase 2 prompt pair from a segment artifact."""
    system_addendum: str
    user_prompt: str


def _extract_section(
    markdown: str, parent_heading: str, sub_heading: str,
) -> str:
    """Return the body under `### <sub_heading>` within `## <parent_heading>`.

    Body runs from the line after the sub-heading to (but excluding) the next
    `## ` or `### ` heading. Leading/trailing blank lines are stripped.
    Raises KeyError if either heading is missing.
    """
    lines = markdown.splitlines()

    # Find the parent heading line
    parent_pat = re.compile(rf"^##\s+{re.escape(parent_heading)}\s*$")
    parent_idx = next(
        (i for i, ln in enumerate(lines) if parent_pat.match(ln)), None,
    )
    if parent_idx is None:
        raise KeyError(f"Section '## {parent_heading}' not found")

    # Find the sub-heading line after the parent
    sub_pat = re.compile(rf"^###\s+{re.escape(sub_heading)}\s*$")
    sub_idx: int | None = None
    for i in range(parent_idx + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):  # hit a new top-level section
            break
        if sub_pat.match(lines[i]):
            sub_idx = i
            break
    if sub_idx is None:
        raise KeyError(
            f"Sub-section '### {sub_heading}' not found under '## {parent_heading}'"
        )

    # Collect body until next `## ` or `### ` heading
    body_lines: list[str] = []
    for i in range(sub_idx + 1, len(lines)):
        if re.match(r"^#{2,3}\s+\S", lines[i]):
            break
        body_lines.append(lines[i])

    # Strip leading/trailing blank lines and trailing horizontal rules
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and (
        not body_lines[-1].strip()
        or re.fullmatch(r"[-*_]{3,}", body_lines[-1].strip())
    ):
        body_lines.pop()

    return "\n".join(body_lines)


def load_segment_prompt(segment_artifact: Path) -> SegmentPrompt:
    """Parse `## Skipper seed` from a segment markdown file."""
    md = segment_artifact.read_text()
    return SegmentPrompt(
        system_addendum=_extract_section(md, "Skipper seed (Phase 2)", "System addendum"),
        user_prompt=_extract_section(md, "Skipper seed (Phase 2)", "User prompt"),
    )


# ---------- Token substitution ----------

@dataclass
class EpisodeContext:
    """Values substituted into the segment's user prompt."""
    league_name: str
    season: str
    target_week: int
    week_start: str
    week_end: str

    def as_substitutions(self) -> dict[str, str]:
        return {
            "league_name": self.league_name,
            "season": self.season,
            "target_week": str(self.target_week),
            "week_start": self.week_start,
            "week_end": self.week_end,
        }


_TOKEN_PAT = re.compile(r"\{([a-z_]+)\}")


def _substitute(template: str, values: dict[str, str]) -> str:
    """Replace `{token}` occurrences. Unknown tokens raise KeyError."""
    def _replace(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"Unknown prompt token: {{{key}}}")
        return values[key]

    return _TOKEN_PAT.sub(_replace, template)


# ---------- Public API ----------

DEFAULT_SEGMENT_ARTIFACT = (
    Path(__file__).resolve().parent.parent.parent
    / "docs" / "podcast-segments" / "weekly-recap.md"
)


async def seed_weekly_recap(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    target_week: int,
    week_start: str,
    week_end: str,
    *,
    user_team_key: str | None = None,
    user_team_name: str | None = None,
    segment_artifact: Path | None = None,
    model: str = SKIPPER_PODCAST_MODEL,
) -> str:
    """Run Skipper against the weekly-recap segment prompt.

    Returns the suggested-topics markdown. Callers are responsible for writing
    it to disk (typically alongside the Phase 1 datapack.json).
    """
    artifact_path = segment_artifact or DEFAULT_SEGMENT_ARTIFACT
    prompt = load_segment_prompt(artifact_path)

    ctx = EpisodeContext(
        league_name=league.name,
        season=league.season,
        target_week=target_week,
        week_start=week_start,
        week_end=week_end,
    )
    user_prompt = _substitute(prompt.user_prompt, ctx.as_substitutions())

    skipper = Skipper(
        api=api,
        league=league,
        categories=categories,
        model=model,
        user_team_key=user_team_key,
        user_team_name=user_team_name,
    )
    # The weekly recap spine covers three acts — scoreboard tour across
    # every matchup, standings tour with named players from multiple
    # teams, and three free-agent picks with team-fit reasoning. That
    # output runs past the default 4096-token cap; 16k gives the seed
    # room to finish all three acts without truncating mid-sentence.
    return await skipper.run_once(
        user_prompt,
        system_addendum=prompt.system_addendum,
        max_tokens=16384,
    )
