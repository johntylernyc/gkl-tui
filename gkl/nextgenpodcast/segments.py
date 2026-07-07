"""Segment registry.

A segment is a prompt artifact + an episode shape (acts, recipe, word
budget). Specials are additive: register a new SegmentSpec and give it an
artifact; the pipeline machinery is shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gkl.podcast.recipe import Recipe, RecipeSlot


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SEGMENTS_DIR = _PROJECT_ROOT / "docs" / "nextgenpodcast" / "segments"


# Weekly flow with the studio announcer (Sid Vega) and the Lounge Line.
# Sid reads the marquee after the intro music, teases each break with a
# bumper, and introduces the caller inside the call-in block (which is
# its own audio block, announced by its own sting, between Act 2 and the
# second break). The hosts — not Sid — sign off at the very end.
WEEKLY_V2_RECIPE: Recipe = Recipe(
    slots=[
        RecipeSlot(kind="intro_stinger"),
        RecipeSlot(
            kind="intro_music",
            fade_out_start_seconds=20.0,
            fade_out_duration_seconds=2.0,
        ),
        RecipeSlot(kind="announcer_intro"),
        RecipeSlot(kind="body_act_1"),
        RecipeSlot(kind="announcer_bumper_1"),
        RecipeSlot(kind="ad_break_stinger"),
        RecipeSlot(kind="ad_1"),
        RecipeSlot(kind="returning_stinger"),
        RecipeSlot(kind="body_act_2"),
        RecipeSlot(kind="callin_stinger"),
        RecipeSlot(kind="body_call_in"),
        RecipeSlot(kind="announcer_bumper_2"),
        RecipeSlot(kind="ad_break_stinger"),
        RecipeSlot(kind="ad_2"),
        RecipeSlot(kind="returning_stinger"),
        RecipeSlot(kind="body_act_3"),
        RecipeSlot(kind="outro_music"),
        RecipeSlot(kind="outro_stinger"),
    ],
)


# Two-act special: one ad break. Reuses the weekly music/stinger assets.
DEEP_DIVE_RECIPE: Recipe = Recipe(
    slots=[
        RecipeSlot(kind="intro_stinger"),
        RecipeSlot(
            kind="intro_music",
            fade_out_start_seconds=20.0,
            fade_out_duration_seconds=2.0,
        ),
        RecipeSlot(kind="body_act_1"),
        RecipeSlot(kind="ad_break_stinger"),
        RecipeSlot(kind="ad_1"),
        RecipeSlot(kind="returning_stinger"),
        RecipeSlot(kind="body_act_2"),
        RecipeSlot(kind="outro_music"),
        RecipeSlot(kind="outro_stinger"),
    ],
)


@dataclass(frozen=True)
class SegmentSpec:
    slug: str
    artifact: Path
    acts: int
    ad_slots: int
    recipe: Recipe
    asset_slug: str  # which committed asset dir the stingers/music come from
    word_budget: int
    has_call_in: bool = False
    # The studio announcer (Sid Vega) reads the marquee up top and teases
    # each break; when set, the script carries an INTRO block plus one
    # BUMPER per ad break.
    has_announcer: bool = False
    # Allow the announcer to speak INSIDE acts for rundown-scripted spots
    # (host-initiated stat checks, the look-back bit). Requires
    # has_announcer; every act still ends on a host.
    announcer_in_acts: bool = False


WEEKLY_RECAP_V2 = SegmentSpec(
    slug="weekly-recap-v2",
    artifact=_SEGMENTS_DIR / "weekly-recap.md",
    acts=3,
    ad_slots=2,
    recipe=WEEKLY_V2_RECIPE,
    asset_slug="weekly-recap",
    word_budget=1780,
    has_call_in=True,
    has_announcer=True,
    announcer_in_acts=True,
)

ALL_STAR_DEEP_DIVE = SegmentSpec(
    slug="all-star-deep-dive",
    artifact=_SEGMENTS_DIR / "all-star-deep-dive.md",
    acts=2,
    ad_slots=1,
    recipe=DEEP_DIVE_RECIPE,
    asset_slug="weekly-recap",
    word_budget=1090,
)


SEGMENTS: dict[str, SegmentSpec] = {
    s.slug: s for s in (WEEKLY_RECAP_V2, ALL_STAR_DEEP_DIVE)
}
