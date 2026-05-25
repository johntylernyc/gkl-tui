#!/usr/bin/env python3
"""Generate the reusable podcast asset library for the Weekly Recap segment.

Run once (per segment); the assets are committed to `assets/podcast/` and
reused by every episode. Re-run only to refresh a specific asset. Skips
existing files by default — pass --force to regenerate.

Generates:
- Intro + outro music (via /v1/music)
- Intro + outro stingers, ad-break + returning stingers (via /v1/sound-generation)
- Each ad spot in the library (via /v1/text-to-speech/{voice_id})

Usage:
    export ELEVENLABS_API_KEY=sk_...              # or saved to ~/.config/gkl/elevenlabs.json
    uv run python scripts/generate_podcast_assets.py
    uv run python scripts/generate_podcast_assets.py --force
    uv run python scripts/generate_podcast_assets.py --only music
    uv run python scripts/generate_podcast_assets.py --only sfx
    uv run python scripts/generate_podcast_assets.py --only ads

Each ad spot carries its own voice_id (see gkl/podcast/ads.py::AD_LIBRARY) so
every commercial has a distinct VO talent — no single "announcer" voice.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gkl.podcast.ads import AD_LIBRARY
from gkl.podcast.assets import (
    generate_music_to_file, generate_sfx_to_file, generate_tts_to_file,
)
from gkl.podcast.segments.weekly_recap import (
    MUSIC_ASSETS, SEGMENT_SLUG, SFX_ASSETS, MusicAsset, SfxAsset,
)
from gkl.podcast.voice import load_elevenlabs_key


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = PROJECT_ROOT / "assets"

SEGMENT_ASSET_DIR = ASSETS_ROOT / "podcast" / SEGMENT_SLUG
AD_LIBRARY_DIR = ASSETS_ROOT / "podcast" / "ads" / "library"


def _music_path(asset: MusicAsset) -> Path:
    return SEGMENT_ASSET_DIR / f"{asset.slug}.mp3"


def _sfx_path(asset: SfxAsset) -> Path:
    return SEGMENT_ASSET_DIR / f"{asset.slug}.mp3"


def _ad_path(slug: str) -> Path:
    return AD_LIBRARY_DIR / f"{slug}.mp3"


async def _generate_music(force: bool, api_key: str) -> tuple[int, int]:
    """Generate all music assets. Returns (generated, skipped)."""
    generated = skipped = 0
    for asset in MUSIC_ASSETS:
        path = _music_path(asset)
        if path.exists() and not force:
            print(f"  [skip] music/{asset.slug} (exists)")
            skipped += 1
            continue
        print(f"  [gen]  music/{asset.slug} ({asset.length_ms}ms)...", flush=True)
        await generate_music_to_file(
            asset.prompt, path, length_ms=asset.length_ms, api_key=api_key,
        )
        print(f"         -> {path.relative_to(PROJECT_ROOT)}")
        generated += 1
    return generated, skipped


async def _generate_sfx(force: bool, api_key: str) -> tuple[int, int]:
    generated = skipped = 0
    for asset in SFX_ASSETS:
        path = _sfx_path(asset)
        if path.exists() and not force:
            print(f"  [skip] sfx/{asset.slug} (exists)")
            skipped += 1
            continue
        print(f"  [gen]  sfx/{asset.slug} ({asset.duration_seconds}s)...", flush=True)
        await generate_sfx_to_file(
            asset.prompt, path, duration_seconds=asset.duration_seconds,
            api_key=api_key,
        )
        print(f"         -> {path.relative_to(PROJECT_ROOT)}")
        generated += 1
    return generated, skipped


async def _generate_ads(force: bool, api_key: str) -> tuple[int, int]:
    """Generate ad spots using each spot's own voice_id."""
    generated = skipped = 0
    for ad in AD_LIBRARY:
        path = _ad_path(ad.slug)
        if path.exists() and not force:
            print(f"  [skip] ad/{ad.slug} (exists)")
            skipped += 1
            continue
        print(
            f"  [gen]  ad/{ad.slug} ({ad.char_count()} chars, voice {ad.voice_id})...",
            flush=True,
        )
        await generate_tts_to_file(ad.copy, ad.voice_id, path, api_key=api_key)
        print(f"         -> {path.relative_to(PROJECT_ROOT)}")
        generated += 1
    return generated, skipped


def _check_inputs() -> str:
    """Validate env + return the API key."""
    api_key = load_elevenlabs_key()
    if not api_key:
        sys.exit(
            "error: No ElevenLabs API key. Set ELEVENLABS_API_KEY or save one "
            "via gkl.podcast.voice.save_elevenlabs_key()."
        )
    # Ad voice IDs are per-spot in AD_LIBRARY; fail loud if any are missing.
    missing = [a.slug for a in AD_LIBRARY if not a.voice_id]
    if missing:
        sys.exit(
            "error: ad library has spots without voice_id set: "
            f"{', '.join(missing)}. Edit gkl/podcast/ads.py to assign voices."
        )
    return api_key


async def _run(args: argparse.Namespace) -> None:
    api_key = _check_inputs()
    SEGMENT_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    AD_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    totals: list[tuple[str, int, int]] = []
    if args.only in (None, "music"):
        print("Generating music:")
        g, s = await _generate_music(args.force, api_key)
        totals.append(("music", g, s))
    if args.only in (None, "sfx"):
        print("Generating SFX:")
        g, s = await _generate_sfx(args.force, api_key)
        totals.append(("sfx", g, s))
    if args.only in (None, "ads"):
        print("Generating ads:")
        g, s = await _generate_ads(args.force, api_key)
        totals.append(("ads", g, s))

    print("\nDone.")
    for label, gen, skip in totals:
        print(f"  {label}: {gen} generated, {skip} skipped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate assets even if they already exist.",
    )
    parser.add_argument(
        "--only", choices=("music", "sfx", "ads"), default=None,
        help="Generate only one category.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
