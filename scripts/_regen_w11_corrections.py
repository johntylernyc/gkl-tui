"""One-off: re-render only the changed turns of the wk11 episode and
re-stitch with the SAME two ads. Surgical correction pass — see the
2026-06-08 stat-correction edits to script-tts.md.
"""
import asyncio
from pathlib import Path

from gkl.podcast.ads import find_ad
from gkl.podcast.mixer import mix_episode
from gkl.podcast.pipeline import (
    _slot_paths_for_weekly_recap, default_assets_root,
)
from gkl.podcast.script_writer import parse_script
from gkl.podcast.segments.weekly_recap import (
    GUEST_VOICE_ID, HOST_VOICE_ID, WEEKLY_RECAP_RECIPE,
)
from gkl.podcast.voice import render_episode_voices

EP = Path("data/podcast/469.l.6252/2026-w11")
AD_SLUGS = ["rally-cap-coffee", "bullpen-brews"]  # same as original episode.json


async def main() -> None:
    script = parse_script((EP / "script-tts.md").read_text())
    print(f"Rendering voice tracks ({sum(len(a.turns) for a in script.acts)} "
          f"turns; cached turns skip TTS)…")
    results = await render_episode_voices(
        script, HOST_VOICE_ID, GUEST_VOICE_ID, EP,
    )
    for r in results:
        print(f"  act {r.act}: {r.turn_count} turns -> {r.audio_path.name}")

    assets_root = default_assets_root()
    ads = [find_ad(s) for s in AD_SLUGS]
    slot_paths = _slot_paths_for_weekly_recap(
        voice_paths_by_act={r.act: r.audio_path for r in results},
        ad_paths=[a.asset_path(assets_root) for a in ads],
        assets_root=assets_root,
    )
    final_mp3 = EP / "final.mp3"
    mix_episode(WEEKLY_RECAP_RECIPE, slot_paths, final_mp3)
    print(f"Re-stitched -> {final_mp3}  ({final_mp3.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
