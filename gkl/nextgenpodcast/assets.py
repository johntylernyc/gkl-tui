"""v2-specific generated assets.

The weekly music/stingers are reused from the committed v1 library
(`assets/podcast/weekly-recap/`). v2 adds its own assets under
`assets/podcast/nextgen/` — currently just the Lounge Line sting.
Rendered once via `gkl-nextgenpodcast assets render`; idempotent (skips
files that exist).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gkl.podcast.assets import generate_sfx_to_file


NEXTGEN_ASSET_DIR = ("podcast", "nextgen")


@dataclass(frozen=True)
class SfxAssetDef:
    slug: str
    prompt: str
    duration_seconds: float


CALLIN_STINGER = SfxAssetDef(
    slug="callin-stinger",
    prompt=(
        "Going to the phones on a call-in radio show: two coins drop into "
        "an old payphone coin slot with a metallic clatter, then an "
        "old-fashioned rotary telephone rings twice, then the handset is "
        "picked up with a click and the line opens. Nostalgic, analog, "
        "clean. About three seconds. No voice, no music."
    ),
    duration_seconds=3.0,
)

# The Regression Bell — a real desk bell Webb dings when he flags a
# player whose surface stats have outrun their Statcast. Spliced in right
# after his cue line by the per-turn renderer.
REGRESSION_BELL = SfxAssetDef(
    slug="regression-bell",
    prompt=(
        "A single clean hotel-desk service bell 'ding' — one bright, "
        "resonant strike that rings out and decays naturally. Crisp, "
        "close-mic'd, no reverb tail cut short. About one and a half "
        "seconds. No voice, no music."
    ),
    duration_seconds=1.5,
)

SEGMENT_ASSETS: list[SfxAssetDef] = [CALLIN_STINGER, REGRESSION_BELL]


def asset_path(assets_root: Path, slug: str) -> Path:
    return assets_root.joinpath(*NEXTGEN_ASSET_DIR) / f"{slug}.mp3"


async def render_missing_segment_assets(
    assets_root: Path, *, force: bool = False, log=None,
) -> list[Path]:
    """Generate any missing v2 SFX assets via the ElevenLabs SFX API."""
    rendered: list[Path] = []
    for asset in SEGMENT_ASSETS:
        out = asset_path(assets_root, asset.slug)
        if out.exists() and not force:
            continue
        if log:
            log(f"  rendering {asset.slug} ({asset.duration_seconds}s)…")
        await generate_sfx_to_file(
            asset.prompt, out, duration_seconds=asset.duration_seconds,
        )
        rendered.append(out)
    return rendered
