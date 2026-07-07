"""End-to-end episode generation for nextgenpodcast.

Stage graph (weekly):
  datapack v2 → Skipper seed → showrunner rundown (grades ledger) →
  draft → fact-check → punch-up → edit → takeaways (plants ledger) →
  TTS normalize → dialogue render (v3 w/ fallback) → ads → mix → state.

The all-star special runs the same graph over a TeamSeasonPack with the
deep-dive artifact (2 acts, 1 ad break), once per team.

All intermediates are persisted under
`data/podcast/<league_key>/nextgen/<episode_slug>/`.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from gkl.nextgenpodcast.ads import (
    NgAdSpot, active_spots, load_library, rotation_path_for_league,
)
from gkl.nextgenpodcast.datapack import (
    build_team_season_pack, build_weekly_race_datapack, format_playoff_race,
    format_team_season_summary,
)
from gkl.nextgenpodcast.assets import asset_path as nextgen_asset_path
from gkl.nextgenpodcast.dialogue import (
    render_announcer_segments, render_call_in, render_episode_voices,
)
from gkl.nextgenpodcast.factguard import find_scoreline_violations
from gkl.nextgenpodcast.scriptcraft import (
    normalize_script_for_tts, parse_script, run_stage,
)
from gkl.nextgenpodcast.seed import run_seed
from gkl.nextgenpodcast.segments import (
    ALL_STAR_DEEP_DIVE, SegmentSpec, WEEKLY_RECAP_V2,
)
from gkl.nextgenpodcast.showbible import LeagueShowConfig, load_show_bible
from gkl.nextgenpodcast.showrunner import (
    Rundown, caller_voices_block, recent_caller_voices, resolve_caller_voice,
    run_showrunner,
)
from gkl.nextgenpodcast.showstate import (
    EpisodeRecord, Prediction, ShowState, load_show_state, parse_plants,
    save_show_state, state_path_for_league,
)
from gkl.podcast.ads import select_ads_for_episode as v1_select_ads
from gkl.podcast.ads import rotation_path_for_league as v1_rotation_path
from gkl.podcast.mixer import mix_episode
from gkl.podcast.script_writer import build_data_summary
from gkl.yahoo_api import League, StatCategory, YahooFantasyAPI


PRIOR_TAKEAWAYS_WINDOW = 6

_EPISODE_DIR_PAT = re.compile(r"^(\d{4})-w(\d{2})$")


# ---------- Paths ----------

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_data_root() -> Path:
    return _project_root() / "data"


def default_assets_root() -> Path:
    return _project_root() / "assets"


def nextgen_league_dir(data_root: Path, league_key: str) -> Path:
    return data_root / "podcast" / league_key / "nextgen"


# ---------- Prior takeaways (continuity input) ----------

def load_prior_takeaways(
    data_root: Path,
    league_key: str,
    season: str,
    current_target_week: int,
    *,
    speakers: tuple[str, str],
    window: int = PRIOR_TAKEAWAYS_WINDOW,
) -> str:
    """Concatenate recent weekly takeaways, oldest first.

    Reads BOTH the v1 episode dirs (`.../<league>/<season>-wNN/`) and the
    nextgen dirs (`.../<league>/nextgen/<season>-wNN/`), preferring the
    nextgen file when a week exists in both. v1 takeaways attribute lines
    to HOST/GUEST — those are the same two voices the new cast names, so
    they're rewritten to the cast's speaker labels for continuity across
    the migration.
    """
    lead, analyst = speakers
    candidates: dict[int, Path] = {}
    for root, prefer in (
        (data_root / "podcast" / league_key, False),
        (nextgen_league_dir(data_root, league_key), True),
    ):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            m = _EPISODE_DIR_PAT.match(child.name)
            if not m or m.group(1) != season:
                continue
            week_n = int(m.group(2))
            if week_n >= current_target_week:
                continue
            path = child / "takeaways.md"
            if not path.exists() or not path.read_text().strip():
                continue
            if prefer or week_n not in candidates:
                candidates[week_n] = path

    weeks = sorted(candidates)[-window:]
    if not weeks:
        return ""
    chunks: list[str] = []
    for week_n in weeks:
        content = candidates[week_n].read_text().strip()
        content = content.replace("HOST:", f"{lead}:").replace("GUEST:", f"{analyst}:")
        chunks.append(f"--- Episode: Week {week_n} ---\n\n{content}")
    return "\n\n".join(chunks)


# ---------- Ads ----------

def _select_ads(
    data_root: Path, assets_root: Path, league_key: str, n: int,
) -> tuple[list[str], list[Path]]:
    """Prefer the v2 generated library (rendered spots only); fall back to
    the v1 committed library so episodes render before the first v2 batch."""
    v2_lib = [
        s for s in active_spots(load_library())
        if s.asset_path(assets_root).exists()
    ]
    if len(v2_lib) >= n:
        rotation = rotation_path_for_league(data_root, league_key)
        picked: list[NgAdSpot] = v1_select_ads(rotation, n, library=v2_lib)
        return [a.slug for a in picked], [a.asset_path(assets_root) for a in picked]
    picked = v1_select_ads(v1_rotation_path(data_root, league_key), n)
    return [a.slug for a in picked], [a.asset_path(assets_root) for a in picked]


def _slot_paths(
    spec: SegmentSpec,
    *,
    voice_paths_by_act: dict[int, Path],
    ad_paths: list[Path],
    assets_root: Path,
    call_in_path: Path | None = None,
    announcer_paths: dict[str, Path] | None = None,
) -> dict[str, Path]:
    seg = assets_root / "podcast" / spec.asset_slug
    slots: dict[str, Path] = {
        "intro_stinger": seg / "intro-stinger.mp3",
        "intro_music": seg / "intro-music.mp3",
        "outro_music": seg / "outro-music.mp3",
        "outro_stinger": seg / "outro-stinger.mp3",
        "ad_break_stinger": seg / "ad-break-stinger.mp3",
        "returning_stinger": seg / "returning-stinger.mp3",
    }
    if spec.has_call_in:
        if call_in_path is None:
            raise ValueError(f"{spec.slug} requires a call-in track")
        slots["callin_stinger"] = nextgen_asset_path(assets_root, "callin-stinger")
        slots["body_call_in"] = call_in_path
    if spec.has_announcer:
        missing = spec.recipe.kinds & {
            "announcer_intro", "announcer_bumper_1", "announcer_bumper_2",
        } - set(announcer_paths or {})
        if missing:
            raise ValueError(
                f"{spec.slug} announcer slots not rendered: {sorted(missing)}"
            )
        slots.update(announcer_paths or {})
    for act_n, path in voice_paths_by_act.items():
        slots[f"body_act_{act_n}"] = path
    for i, path in enumerate(ad_paths, 1):
        slots[f"ad_{i}"] = path
    return slots


# ---------- Result ----------

@dataclass
class EpisodeResult:
    segment: str
    league_key: str
    season: str
    episode_slug: str
    episode_dir: Path
    final_mp3: Path
    ad_slugs: list[str]
    renderer: str
    char_cost_estimate: int
    llm_stages: int
    generated_at: str
    grades_applied: int = 0
    predictions_planted: int = 0
    caller: str = ""

    def write_manifest(self) -> None:
        payload = asdict(self)
        for k, v in payload.items():
            if isinstance(v, Path):
                payload[k] = str(v)
        (self.episode_dir / "episode.json").write_text(
            json.dumps(payload, indent=2)
        )


# ---------- Shared episode tail (script chain → audio → state) ----------

async def _run_script_chain_and_render(
    *,
    spec: SegmentSpec,
    tokens: dict[str, str],
    episode_dir: Path,
    episode_slug: str,
    week_for_state: int,
    season: str,
    config: LeagueShowConfig,
    state: ShowState,
    state_path: Path,
    data_root: Path,
    assets_root: Path,
    log,
    validate=None,
) -> EpisodeResult:
    speakers = config.cast.speakers()

    # Showrunner — plans the episode, grades due predictions.
    log("[3/8] Showrunner — building the rundown…")
    rundown: Rundown = await run_showrunner(spec.artifact, tokens)
    (episode_dir / "rundown.md").write_text(rundown.text)
    grades = rundown.grades()
    applied = 0
    for pred_id, verdict, reason in grades:
        if state.grade(pred_id, verdict, week_for_state, reason):
            applied += 1
    if applied:
        log(f"       ledger: applied {applied} grade(s)")
    tokens = dict(tokens)
    tokens["rundown"] = rundown.text
    # Post-grade ledger view for the draft/fact-check stages.
    tokens["ledger"] = state.ledger_block(season)

    def _parse(raw: str):
        return parse_script(
            raw, speakers, expected_acts=spec.acts,
            allow_call_in=spec.has_call_in,
            has_announcer=spec.has_announcer,
            expected_bumpers=spec.ad_slots if spec.has_announcer else 0,
            announcer_in_acts=spec.announcer_in_acts,
        )

    log("[4/8] Draft…")
    draft_raw = await run_stage(spec.artifact, "draft", tokens, max_tokens=8192)
    draft = _parse(draft_raw)
    (episode_dir / "draft-script.md").write_text(draft.as_markdown())
    tokens["draft_script"] = draft.as_markdown()

    log("[5/8] Fact check…")
    checked_raw = await run_stage(
        spec.artifact, "fact_check",
        {**tokens, "data_summary": tokens["checker_data_summary"]},
        max_tokens=8192,
    )
    checked = _parse(checked_raw)
    (episode_dir / "fact-checked-script.md").write_text(checked.as_markdown())
    tokens["fact_checked_script"] = checked.as_markdown()

    log("[6/8] Punch-up…")
    punched_raw = await run_stage(spec.artifact, "punch_up", tokens, max_tokens=8192)
    punched = _parse(punched_raw)
    (episode_dir / "punched-up-script.md").write_text(punched.as_markdown())
    tokens["script"] = punched.as_markdown()

    log("[7/8] Edit…")
    final_raw = await run_stage(spec.artifact, "edit", tokens, max_tokens=8192)
    final = _parse(final_raw)

    # Deterministic scoreline backstop: every spoken record tuple in the
    # final script must match an official record in the data pack. On a
    # miss, run one corrective fact-check pass with the specific flags,
    # then fail the run rather than render a wrong number to air.
    if validate is not None:
        problems = validate(final.as_markdown())
        if problems:
            log(
                f"       validator: {len(problems)} scoreline problem(s) — "
                "running corrective fact-check pass"
            )
            flags = (
                "\n\nVALIDATOR FLAGS — these spoken scorelines failed "
                "deterministic verification against the official records. "
                "Correct each to the official matchup/standings record from "
                "the data above; if the line's framing depended on the wrong "
                "score (e.g. calling a blowout a coin-flip), rewrite the "
                "framing to fit the real number:\n"
                + "\n".join(f"- {p}" for p in problems)
            )
            corrected_raw = await run_stage(
                spec.artifact, "fact_check",
                {
                    **tokens,
                    "data_summary": tokens["checker_data_summary"] + flags,
                    "draft_script": final.as_markdown(),
                },
                max_tokens=8192,
            )
            final = _parse(corrected_raw)
            remaining = validate(final.as_markdown())
            if remaining:
                raise RuntimeError(
                    "script failed scoreline validation after the corrective "
                    "pass:\n" + "\n".join(remaining)
                )

    (episode_dir / "script.md").write_text(final.as_markdown())
    log(f"       final: {final.total_turns()} turns, {final.total_words()} words")

    tokens["final_script"] = final.as_markdown()
    takeaways_md = await run_stage(
        spec.artifact, "takeaways", tokens, max_tokens=2048,
    )
    (episode_dir / "takeaways.md").write_text(takeaways_md)

    planted = 0
    for speaker, text, resolves_by in parse_plants(takeaways_md, speakers):
        state.add_prediction(Prediction(
            id=state.next_prediction_id(season, week_for_state, speaker),
            season=season, week_made=week_for_state, speaker=speaker,
            text=text, resolves_by=resolves_by,
        ))
        planted += 1
    if planted:
        log(f"       ledger: planted {planted} prediction(s)")

    # TTS
    tts_script = normalize_script_for_tts(final)
    (episode_dir / "script-tts.md").write_text(tts_script.as_markdown())
    log("[8/8] Rendering voices + mixing…")
    bell_path = (
        nextgen_asset_path(assets_root, "regression-bell")
        if any(t.bell_after for a in tts_script.acts for t in a.turns)
        else None
    )
    voice_results = await render_episode_voices(
        tts_script, config.cast, episode_dir, bell_path=bell_path, log=log,
    )
    renderer = voice_results[0].renderer if voice_results else "none"
    char_cost = sum(r.char_cost for r in voice_results)
    voice_paths = {r.act: r.audio_path for r in voice_results}

    # Studio announcer (Sid Vega): marquee up top + a bumper before each
    # break. Rendered to their own slot clips; empty when the segment has
    # no announcer.
    announcer_paths = await render_announcer_segments(
        tts_script, config.cast, episode_dir,
    )

    # The Lounge Line: caller voice chosen by the showrunner, validated
    # against the pool and recent-caller history; phone filter applied to
    # the caller's turns inside render_call_in.
    call_in_path: Path | None = None
    caller_record = ""
    if spec.has_call_in:
        caller_spec = rundown.caller()
        recent = recent_caller_voices(state.episodes)
        caller_voice = resolve_caller_voice(
            caller_spec.voice_id if caller_spec else None, recent,
        )
        display = caller_spec.display if caller_spec else "a listener"
        persona = caller_spec.persona if caller_spec else ""
        caller_record = f"CALLER: {display} | voice: {caller_voice} | {persona}"
        log(f"       lounge line: {display} (voice {caller_voice})")
        call_in_path = episode_dir / "call_in.mp3"
        char_cost += await render_call_in(
            tts_script.call_in, config.cast, caller_voice, call_in_path,
        )

    ad_slugs, ad_paths = _select_ads(
        data_root, assets_root, state_path.parent.parent.name, spec.ad_slots,
    )
    log(f"       ads: {', '.join(ad_slugs)}")

    final_mp3 = episode_dir / "final.mp3"
    mix_episode(
        spec.recipe,
        _slot_paths(
            spec, voice_paths_by_act=voice_paths, ad_paths=ad_paths,
            assets_root=assets_root, call_in_path=call_in_path,
            announcer_paths=announcer_paths,
        ),
        final_mp3,
    )
    log(f"       -> {final_mp3}")

    # Variety history + persist state (only after a fully successful run).
    state.record_episode(EpisodeRecord(
        slug=episode_slug, segment=spec.slug, week=week_for_state,
        cold_open=rundown.cold_open, sign_off=rundown.sign_off,
        bits=rundown.bits_budget, argument_act=rundown.argument_act,
        caller=caller_record, sid_spots=rundown.sid_spots,
    ))
    save_show_state(state, state_path)

    result = EpisodeResult(
        segment=spec.slug,
        league_key=state_path.parent.parent.name,
        season=season,
        episode_slug=episode_slug,
        episode_dir=episode_dir,
        final_mp3=final_mp3,
        ad_slugs=ad_slugs,
        renderer=renderer,
        char_cost_estimate=char_cost,
        llm_stages=6,  # seed + showrunner + draft + check + punch-up + edit (+takeaways)
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        grades_applied=applied,
        predictions_planted=planted,
        caller=caller_record,
    )
    result.write_manifest()
    return result


# ---------- Weekly episode ----------

async def generate_weekly_episode(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    target_week: int,
    *,
    config: LeagueShowConfig | None = None,
    data_root: Path | None = None,
    assets_root: Path | None = None,
    user_team_key: str | None = None,
    user_team_name: str | None = None,
    verbose: bool = False,
) -> EpisodeResult:
    config = config or LeagueShowConfig()
    data_root = data_root or default_data_root()
    assets_root = assets_root or default_assets_root()
    spec = WEEKLY_RECAP_V2

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    episode_slug = f"{league.season}-w{target_week:02d}"
    episode_dir = nextgen_league_dir(data_root, league.league_key) / episode_slug
    episode_dir.mkdir(parents=True, exist_ok=True)

    log(f"[1/8] Building data pack (with playoff race) for Week {target_week}…")
    pack = await build_weekly_race_datapack(
        api, league, categories, target_week,
        playoff_spots=config.playoff_spots,
    )
    pack.write_to(episode_dir / "datapack.json")

    race_block = (
        "\n\nTHE PLAYOFF RACE (official standings — the Act 3 source of "
        "truth):\n" + format_playoff_race(pack.race)
    )
    draft_summary = build_data_summary(pack.base, include_player_stats=False) + race_block
    checker_summary = build_data_summary(pack.base, include_player_stats=True) + race_block

    log("[2/8] Skipper seed…")
    tokens: dict[str, str] = {
        "league_name": league.name,
        "season": league.season,
        "target_week": str(target_week),
        "week_start": pack.base.meta.week_start,
        "week_end": pack.base.meta.week_end,
        "playoff_spots": str(config.playoff_spots),
    }
    spine = await run_seed(
        api, league, categories, spec.artifact, tokens,
        user_team_key=user_team_key, user_team_name=user_team_name,
    )
    (episode_dir / "suggested-topics.md").write_text(spine)

    state_path = state_path_for_league(data_root, league.league_key)
    state = load_show_state(state_path)
    prior = load_prior_takeaways(
        data_root, league.league_key, league.season, target_week,
        speakers=config.cast.speakers(),
    )
    log(
        f"       continuity: {prior.count('--- Episode: Week')} prior "
        "episode(s) of takeaways" if prior else
        "       continuity: no prior episodes"
    )

    tokens.update({
        "suggested_topics": spine,
        "data_summary": draft_summary,
        "checker_data_summary": checker_summary,
        "prior_takeaways": prior or "(no prior episodes)",
        "show_bible": load_show_bible(config.show_bible_path),
        "episode_history": state.history_block(),
        "ledger": state.ledger_block(league.season),
        "caller_voices": caller_voices_block(),
    })

    pack_dict = json.loads((episode_dir / "datapack.json").read_text())
    scored_n = sum(
        1 for c in pack_dict["categories"] if not c.get("is_only_display")
    )

    def _validate(script_md: str) -> list[str]:
        return find_scoreline_violations(
            script_md, pack_dict,
            scored_categories=scored_n, num_teams=len(pack_dict["teams"]),
        )

    return await _run_script_chain_and_render(
        spec=spec, tokens=tokens, episode_dir=episode_dir,
        episode_slug=episode_slug, week_for_state=target_week,
        season=league.season, config=config, state=state,
        state_path=state_path, data_root=data_root,
        assets_root=assets_root, log=log, validate=_validate,
    )


# ---------- All-star deep dive (one team) ----------

async def generate_deep_dive_episode(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    team_key: str,
    *,
    config: LeagueShowConfig | None = None,
    data_root: Path | None = None,
    assets_root: Path | None = None,
    through_week: int | None = None,
    verbose: bool = False,
) -> EpisodeResult:
    config = config or LeagueShowConfig()
    data_root = data_root or default_data_root()
    assets_root = assets_root or default_assets_root()
    spec = ALL_STAR_DEEP_DIVE
    through = through_week or (league.current_week - 1)

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    team_id = team_key.rsplit(".", 1)[-1]
    episode_slug = f"allstar-w{through:02d}-t{team_id}"
    episode_dir = nextgen_league_dir(data_root, league.league_key) / episode_slug
    episode_dir.mkdir(parents=True, exist_ok=True)

    log(f"[1/8] Building season pack for team {team_key} (through Week {through})…")
    pack = await build_team_season_pack(
        api, league, categories, team_key,
        playoff_spots=config.playoff_spots, through_week=through,
    )
    pack.write_to(episode_dir / "datapack.json")
    summary = format_team_season_summary(pack, categories)

    log("[2/8] Skipper seed…")
    tokens: dict[str, str] = {
        "league_name": league.name,
        "season": league.season,
        "team_name": pack.team_name,
        "manager_name": pack.manager,
        "through_week": str(through),
        "playoff_spots": str(config.playoff_spots),
    }
    spine = await run_seed(api, league, categories, spec.artifact, tokens)
    (episode_dir / "suggested-topics.md").write_text(spine)

    state_path = state_path_for_league(data_root, league.league_key)
    state = load_show_state(state_path)
    prior = load_prior_takeaways(
        data_root, league.league_key, league.season, through + 1,
        speakers=config.cast.speakers(),
    )

    tokens.update({
        "suggested_topics": spine,
        "data_summary": summary,
        "checker_data_summary": summary,  # one table serves both stages here
        "prior_takeaways": prior or "(no prior episodes)",
        "show_bible": load_show_bible(config.show_bible_path),
        "episode_history": state.history_block(),
        "ledger": state.ledger_block(league.season),
    })

    return await _run_script_chain_and_render(
        spec=spec, tokens=tokens, episode_dir=episode_dir,
        episode_slug=episode_slug, week_for_state=through,
        season=league.season, config=config, state=state,
        state_path=state_path, data_root=data_root,
        assets_root=assets_root, log=log,
    )


async def generate_all_star_series(
    api: YahooFantasyAPI,
    league: League,
    categories: list[StatCategory],
    *,
    config: LeagueShowConfig | None = None,
    data_root: Path | None = None,
    assets_root: Path | None = None,
    through_week: int | None = None,
    verbose: bool = False,
) -> list[EpisodeResult]:
    """One deep-dive episode per team, sequentially (shared voices +
    show state make parallel generation self-defeating)."""
    import asyncio
    teams = await asyncio.to_thread(
        api.get_team_season_stats, league.league_key,
    )
    results: list[EpisodeResult] = []
    for team in teams:
        if verbose:
            print(f"\n=== Deep dive: {team.name} ({team.manager}) ===", flush=True)
        results.append(await generate_deep_dive_episode(
            api, league, categories, team.team_key,
            config=config, data_root=data_root, assets_root=assets_root,
            through_week=through_week, verbose=verbose,
        ))
    return results
