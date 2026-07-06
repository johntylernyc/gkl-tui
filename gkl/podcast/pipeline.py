"""Phase 7 — end-to-end episode generation.

Orchestrates Phases 1-6 for a single segment + episode (currently just the
Weekly Recap). Writes all intermediate artifacts + the final mp3 under
`data/podcast/<league_key>/<season>-w<NN>/`.

Intermediate artifacts (kept for debugging + refinement):
- `datapack.json` (Phase 1)
- `suggested-topics.md` (Phase 2)
- `draft-script.md`, `fact-checked-script.md`, `script.md` (Phase 3a/b/c)
- `script-tts.md` (TTS-normalized final)
- `act_{n}.mp3` (Phase 4)
- `final.mp3` (Phase 6)
- `takeaways.md` (Phase 3d — feeds future episodes' continuity)
- `episode.json` (this module; metadata summary)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gkl.podcast.ads import (
    rotation_path_for_league, select_ads_for_episode,
)
from gkl.podcast.datapack import (
    build_weekly_recap_datapack, datapack_dir,
)
from gkl.podcast.mixer import mix_episode
from gkl.podcast.script_writer import (
    normalize_script_for_tts, write_script, write_takeaways,
)
from gkl.podcast.segments.weekly_recap import (
    GUEST_VOICE_ID, HOST_VOICE_ID, SEGMENT_SLUG, WEEKLY_RECAP_RECIPE,
)
from gkl.podcast.skipper_seed import seed_weekly_recap
from gkl.podcast.voice import render_episode_voices
from gkl.yahoo_api import League, StatCategory, YahooFantasyAPI


# How many recent episodes' takeaways to thread into the draft writer for
# continuity. Matches the spec ("last 4-6 weeks").
PRIOR_TAKEAWAYS_WINDOW = 6


_EPISODE_DIR_PAT = re.compile(r"^(\d{4})-w(\d{2})$")


def load_prior_takeaways(
    league_data_dir: Path,
    season: str,
    current_target_week: int,
    *,
    window: int = PRIOR_TAKEAWAYS_WINDOW,
) -> str:
    """Read the previous `window` episodes' `takeaways.md` for continuity.

    Scans `league_data_dir` for episode subdirectories matching
    `<season>-wNN`, takes the up-to-`window` most recent that have a
    non-empty `takeaways.md`, and returns their content concatenated with
    week-N labels (oldest first, so the model reads a chronological
    record). Excludes the current target week (allows safe re-runs).

    Returns an empty string when nothing is found — the caller is expected
    to translate that into the draft prompt's "(no prior episodes)"
    sentinel via the script writer's helper.
    """
    if not league_data_dir.is_dir():
        return ""

    candidates: list[tuple[int, Path]] = []
    for child in league_data_dir.iterdir():
        if not child.is_dir():
            continue
        m = _EPISODE_DIR_PAT.match(child.name)
        if not m:
            continue
        if m.group(1) != season:
            continue
        week_n = int(m.group(2))
        if week_n >= current_target_week:
            continue
        takeaways_path = child / "takeaways.md"
        if not takeaways_path.exists():
            continue
        content = takeaways_path.read_text().strip()
        if not content:
            continue
        candidates.append((week_n, takeaways_path))

    candidates.sort(key=lambda x: x[0])  # oldest first
    if not candidates:
        return ""
    selected = candidates[-window:]  # keep the most-recent N, oldest first

    chunks: list[str] = []
    for week_n, path in selected:
        chunks.append(
            f"--- Episode: Week {week_n} ---\n\n{path.read_text().strip()}"
        )
    return "\n\n".join(chunks)


# ---------- Result schema ----------

@dataclass
class EpisodeResult:
    """Metadata summary for a generated episode."""
    segment: str
    league_key: str
    season: str
    target_week: int
    episode_dir: Path
    final_mp3: Path
    datapack_path: Path
    suggested_topics_path: Path
    act_voice_paths: list[Path]
    ad_slugs: list[str]
    generated_at: str
    char_cost_estimate: int = 0  # rough count of chars sent to ElevenLabs
    takeaways_path: Path | None = None
    prior_episodes_used: int = 0

    def write_manifest(self) -> None:
        """Persist a summary of this episode as `episode.json`."""
        payload = asdict(self)
        # Path objects aren't JSON-serializable; stringify.
        for k, v in payload.items():
            if isinstance(v, Path):
                payload[k] = str(v)
            elif isinstance(v, list) and v and isinstance(v[0], Path):
                payload[k] = [str(p) for p in v]
        (self.episode_dir / "episode.json").write_text(
            json.dumps(payload, indent=2)
        )


# ---------- Path helpers ----------

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_assets_root() -> Path:
    return _project_root() / "assets"


def default_data_root() -> Path:
    return _project_root() / "data"


def _segment_asset_dir(assets_root: Path) -> Path:
    return assets_root / "podcast" / SEGMENT_SLUG


def _slot_paths_for_weekly_recap(
    *,
    voice_paths_by_act: dict[int, Path],
    ad_paths: list[Path],
    assets_root: Path,
) -> dict[str, Path]:
    """Build the `{kind: Path}` mapping the mixer expects."""
    seg = _segment_asset_dir(assets_root)
    return {
        "intro_stinger": seg / "intro-stinger.mp3",
        "intro_music": seg / "intro-music.mp3",
        "outro_music": seg / "outro-music.mp3",
        "outro_stinger": seg / "outro-stinger.mp3",
        "ad_break_stinger": seg / "ad-break-stinger.mp3",
        "returning_stinger": seg / "returning-stinger.mp3",
        "body_act_1": voice_paths_by_act[1],
        "body_act_2": voice_paths_by_act[2],
        "body_act_3": voice_paths_by_act[3],
        "ad_1": ad_paths[0],
        "ad_2": ad_paths[1],
    }


# ---------- Public API ----------

async def generate_weekly_recap_episode(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    target_week: int,
    *,
    data_root: Path | None = None,
    assets_root: Path | None = None,
    user_team_key: str | None = None,
    user_team_name: str | None = None,
    verbose: bool = False,
) -> EpisodeResult:
    """Generate a Weekly Recap episode end-to-end.

    Runs Phase 1 → Phase 6 sequentially, writing all intermediate artifacts
    to the episode directory. Returns a manifest summarizing what was made.
    """
    data_root = data_root or default_data_root()
    assets_root = assets_root or default_assets_root()

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    def _rel(path: Path) -> str:
        """Relative to project root when possible; otherwise the full path."""
        try:
            return str(path.relative_to(_project_root()))
        except ValueError:
            return str(path)

    episode_dir = datapack_dir(
        data_root / "podcast", league.league_key, league.season, target_week,
    )
    episode_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1 — data pack
    log(f"[1/6] Building data pack for Week {target_week}…")
    datapack = await build_weekly_recap_datapack(
        api, league, categories, target_week,
    )
    datapack_path = episode_dir / "datapack.json"
    datapack.write_to(datapack_path)
    log(f"       -> {_rel(datapack_path)}")

    # Phase 2 — Skipper seed
    log("[2/6] Running Skipper seed (Opus 4.6) for suggested topics…")
    suggested_topics = await seed_weekly_recap(
        api, league, categories, target_week,
        week_start=datapack.meta.week_start,
        week_end=datapack.meta.week_end,
        user_team_key=user_team_key,
        user_team_name=user_team_name,
    )
    suggested_topics_path = episode_dir / "suggested-topics.md"
    suggested_topics_path.write_text(suggested_topics)
    log(f"       -> {_rel(suggested_topics_path)}")

    # Load prior episodes' takeaways so the draft writer can call back to
    # past topics / position changes. Empty string when there's nothing yet.
    league_data_dir = data_root / "podcast" / league.league_key
    prior_takeaways = load_prior_takeaways(
        league_data_dir, league.season, target_week,
    )
    if prior_takeaways:
        prior_count = prior_takeaways.count("--- Episode: Week")
        log(
            f"       continuity: loaded {prior_count} prior episode(s) "
            "of takeaways"
        )
    else:
        log("       continuity: no prior episodes (skipping callbacks)")

    # Phase 3 — three Opus 4.6 passes: draft → fact-check → edit
    log("[3/6] Writing dialogue script (Opus 4.6, three passes)…")
    log("       3a — drafting op-ed dialogue…")
    scripts = await write_script(
        datapack, suggested_topics, prior_takeaways=prior_takeaways,
    )
    (episode_dir / "draft-script.md").write_text(scripts.draft.as_markdown())
    log(
        f"       draft -> {_rel(episode_dir / 'draft-script.md')}  "
        f"({scripts.draft.total_turns()} turns)"
    )
    (episode_dir / "fact-checked-script.md").write_text(
        scripts.fact_checked.as_markdown()
    )
    log(
        f"       fact-checked -> {_rel(episode_dir / 'fact-checked-script.md')}  "
        f"({scripts.fact_checked.total_turns()} turns)"
    )
    script = scripts.final
    script_path = episode_dir / "script.md"
    script_path.write_text(script.as_markdown())
    log(
        f"       final -> {_rel(script_path)}  "
        f"({script.total_turns()} turns across 3 acts)"
    )

    # Phase 3d — takeaways for the NEXT episode's continuity. Runs against
    # the final (un-normalized) script. Persist alongside the other artifacts
    # so the future-episode loader can pick it up.
    log("       3d — distilling takeaways for next-episode continuity…")
    takeaways_md = await write_takeaways(script, datapack)
    takeaways_path = episode_dir / "takeaways.md"
    takeaways_path.write_text(takeaways_md)
    log(f"       takeaways -> {_rel(takeaways_path)}")

    # Normalize for TTS: expand abbreviations (OBP → on-base percentage,
    # xBA → expected batting average, etc.) so the hosts don't spell out
    # technical stats letter-by-letter. Un-normalized final is already on
    # disk above; the normalized version is what Phase 4 renders.
    tts_script = normalize_script_for_tts(script)
    (episode_dir / "script-tts.md").write_text(tts_script.as_markdown())

    # Phase 4 — voice tracks (per-turn TTS, concat per act, sequential acts)
    log("[4/6] Rendering voice tracks via ElevenLabs TTS (per-turn, acts sequential)…")
    voice_results = await render_episode_voices(
        tts_script, HOST_VOICE_ID, GUEST_VOICE_ID, episode_dir,
    )
    voice_paths_by_act = {r.act: r.audio_path for r in voice_results}
    for r in voice_results:
        log(
            f"       act {r.act} -> {_rel(r.audio_path)}  "
            f"({r.turn_count} turns, {r.char_cost:,} chars)"
        )

    # Phase 5 — ad selection (LRU against the per-league rotation state)
    log("[5/6] Selecting 2 ads via LRU rotation…")
    rotation_path = rotation_path_for_league(data_root, league.league_key)
    ads = select_ads_for_episode(rotation_path, n=2)
    ad_paths = [ad.asset_path(assets_root) for ad in ads]
    log(f"       picked: {', '.join(ad.slug for ad in ads)}")

    # Phase 6 — mix
    log("[6/6] Mixing episode with ffmpeg…")
    slot_paths = _slot_paths_for_weekly_recap(
        voice_paths_by_act=voice_paths_by_act,
        ad_paths=ad_paths,
        assets_root=assets_root,
    )
    final_mp3 = episode_dir / "final.mp3"
    mix_episode(WEEKLY_RECAP_RECIPE, slot_paths, final_mp3)
    log(f"       -> {_rel(final_mp3)}")

    # Rough ElevenLabs char-cost estimate: sum of characters fed to TTS
    # across all three acts. Music/SFX/Ads are asset-library (zero
    # incremental cost per episode).
    char_cost = sum(r.char_cost for r in voice_results)

    prior_count = (
        prior_takeaways.count("--- Episode: Week") if prior_takeaways else 0
    )
    result = EpisodeResult(
        segment=SEGMENT_SLUG,
        league_key=league.league_key,
        season=league.season,
        target_week=target_week,
        episode_dir=episode_dir,
        final_mp3=final_mp3,
        datapack_path=datapack_path,
        suggested_topics_path=suggested_topics_path,
        act_voice_paths=[voice_paths_by_act[n] for n in (1, 2, 3)],
        ad_slugs=[ad.slug for ad in ads],
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        char_cost_estimate=char_cost,
        takeaways_path=takeaways_path,
        prior_episodes_used=prior_count,
    )
    result.write_manifest()
    return result
