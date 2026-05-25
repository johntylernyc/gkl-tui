"""Weekly Recap segment config.

Source of truth for the one-time-generated assets (music, stingers) and
segment-wide settings (Studio Podcast duration_scale, etc.). The segment's
markdown artifact at docs/podcast-segments/weekly-recap.md mirrors this
config in prose for human review; this module is what scripts and the
pipeline actually load.
"""

from __future__ import annotations

from dataclasses import dataclass

from gkl.podcast.recipe import Recipe, RecipeSlot


SEGMENT_SLUG = "weekly-recap"


# ---------- Asset definitions ----------

@dataclass(frozen=True)
class MusicAsset:
    """A music bed generated via the Eleven Music API once and reused."""
    slug: str
    prompt: str
    length_ms: int


@dataclass(frozen=True)
class SfxAsset:
    """A sound-effect stinger generated via the SFX API once and reused."""
    slug: str
    prompt: str
    duration_seconds: float


INTRO_MUSIC = MusicAsset(
    slug="intro-music",
    prompt=(
        "Upbeat sports-talk-radio bumper. Energetic brass stabs over a driving "
        "drum loop. 120 BPM. Bright and confident, sets the tone for a weekly "
        "sports recap show. Ends on a clear downbeat so a voice can come in on "
        "the next bar. Instrumental."
    ),
    length_ms=12_000,
)


OUTRO_MUSIC = MusicAsset(
    slug="outro-music",
    prompt=(
        "Outro bed for a sports-talk-radio show. Same energy family as the "
        "intro but slightly more laid-back — the listener is being sent off. "
        "Resolving chord progression with a clear ending. 110 BPM. "
        "Instrumental."
    ),
    length_ms=10_000,
)


INTRO_STINGER = SfxAsset(
    slug="intro-stinger",
    prompt=(
        "A short, bright radio-station-ID sting. Brass hit with a tiny reverb "
        "tail. Feels like the station logo hitting the screen. No voice."
    ),
    duration_seconds=1.5,
)


OUTRO_STINGER = SfxAsset(
    slug="outro-stinger",
    prompt=(
        "A closing-button sting for a radio show. Descending tonal hit that "
        "tells the listener 'that's all folks.' Short, crisp, no voice."
    ),
    duration_seconds=1.5,
)


AD_BREAK_STINGER = SfxAsset(
    slug="ad-break-stinger",
    prompt=(
        "Commercial-break transition sting. A soft whoosh into a short "
        "impact hit — signals 'we're going to a break.' Two seconds. No "
        "voice."
    ),
    duration_seconds=2.0,
)


RETURNING_STINGER = SfxAsset(
    slug="returning-stinger",
    prompt=(
        "A 'welcome back from commercial' sting. Upbeat whoosh with a brass "
        "hit at the end. Energetic, signals the show is resuming. Two "
        "seconds. No voice."
    ),
    duration_seconds=2.0,
)


# All music + SFX assets in the order the generation script processes them
MUSIC_ASSETS: list[MusicAsset] = [INTRO_MUSIC, OUTRO_MUSIC]
SFX_ASSETS: list[SfxAsset] = [
    INTRO_STINGER, OUTRO_STINGER, AD_BREAK_STINGER, RETURNING_STINGER,
]


# ---------- Studio Podcast config ----------

# Each of the three acts targets 2-3 minutes, so `short` (<3 min) is the right
# duration bucket. The weekly recap adds up to 8-10 minutes total including
# stingers and ads. Promote to `default` if a listen shows acts feel rushed.
STUDIO_DURATION_SCALE = "short"

# Host voices for the two-host conversation. Swap the two values if, on first
# listen, the host/guest roles should be reversed — the Studio Podcast
# `host_voice_id` tends to drive more of the narrative while `guest_voice_id`
# reacts, so the distinction matters less for a peer-to-peer analyst show but
# can still be worth tuning.
HOST_VOICE_ID = "d5xU2Rwln0n15oHMmaTU"
GUEST_VOICE_ID = "NOpBlnGInO9m6vDvFkFC"


# ---------- Recipe ----------

# Slot kinds used below. The pipeline (Phase 7) maps these to file paths:
#   intro_stinger, intro_music, outro_music, outro_stinger — asset library
#   ad_break_stinger, returning_stinger                    — asset library (play twice)
#   body_act_1, body_act_2, body_act_3                     — per-episode voice tracks
#   ad_1, ad_2                                              — per-episode ads from LRU
WEEKLY_RECAP_RECIPE: Recipe = Recipe(
    slots=[
        RecipeSlot(kind="intro_stinger"),
        # Intro music plays for 20s, then fades out over 2s — the host
        # comes in over the tail of the fade. Source mp3 may be longer
        # (ElevenLabs sometimes returns audio longer than length_ms);
        # this caps + fades it deterministically.
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
        RecipeSlot(kind="ad_break_stinger"),
        RecipeSlot(kind="ad_2"),
        RecipeSlot(kind="returning_stinger"),
        RecipeSlot(kind="body_act_3"),
        RecipeSlot(kind="outro_music"),
        RecipeSlot(kind="outro_stinger"),
    ],
)
