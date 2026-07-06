"""Stage 1 — the Skipper research seed, segment-generic.

Same idea as v1's `seed_weekly_recap`, generalized: any segment artifact
with a `## Skipper seed (stage 1)` section can be seeded. Skipper's
toolkit is a dependency we call into (per the v1 spec), and the seed
runs on the podcast model constant, not interactive-Skipper's default.
"""

from __future__ import annotations

from pathlib import Path

from gkl.nextgenpodcast import SEED_MODEL
from gkl.nextgenpodcast.scriptcraft import load_stage_prompt
from gkl.podcast.skipper_seed import _substitute
from gkl.skipper import Skipper
from gkl.yahoo_api import League, StatCategory, YahooFantasyAPI


async def run_seed(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    segment_artifact: Path,
    tokens: dict[str, str],
    *,
    user_team_key: str | None = None,
    user_team_name: str | None = None,
    model: str = SEED_MODEL,
    max_tokens: int = 16384,
) -> str:
    """Run Skipper against a segment's seed prompt; returns the spine."""
    prompt = load_stage_prompt(segment_artifact, "seed")
    skipper = Skipper(
        api=api, league=league, categories=categories, model=model,
        user_team_key=user_team_key, user_team_name=user_team_name,
    )
    return await skipper.run_once(
        _substitute(prompt.user, tokens),
        system_addendum=_substitute(prompt.system, tokens),
        max_tokens=max_tokens,
    )
