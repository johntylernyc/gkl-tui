"""Voice rendering for nextgenpodcast: expressive multi-speaker dialogue
with a deterministic fallback.

Primary path: ElevenLabs Text-to-Dialogue (`POST /v1/text-to-dialogue`,
model `eleven_v3`) — the whole act renders in one call, speakers
alternate naturally, and bracketed audio tags ([laughs], [sighs], ...)
become actual delivery instead of read-aloud junk.

Fallback path: the availability of the v3 dialogue endpoint varies by
plan. On a 401/403/404 from the endpoint the renderer downgrades — once,
process-wide — to the v1-style per-turn TTS (`gkl.podcast.assets`
`generate_tts_to_file`) with audio tags stripped, per-turn caching, and
ffmpeg concat. An episode always renders.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

from gkl.nextgenpodcast.scriptcraft import (
    ANNOUNCER, CALLER, Act, DialogueTurn, Script, strip_tags,
)
from gkl.nextgenpodcast.showbible import Cast
from gkl.podcast.assets import (
    _post_audio, _require_key, generate_tts_to_file,
)
from gkl.podcast.mixer import MixerError, concat_audio_files
from gkl.podcast.voice import ELEVENLABS_BASE_URL


DIALOGUE_MODEL_ID = "eleven_v3"

# The ElevenLabs UI exposes stability as three named presets ("Creative" ~0.3,
# "Natural" ~0.5, "Robust" ~0.8), but the API itself only accepts a float.
# 0.5 ("Natural") balances expressiveness against voice drift for a weekly show.
DIALOGUE_STABILITY = 0.5


@dataclass
class ActRenderResult:
    act: int
    audio_path: Path
    turn_count: int
    char_cost: int
    renderer: str  # "dialogue-v3" | "per-turn-fallback"


class DialogueUnavailable(Exception):
    """The v3 dialogue endpoint is not available on this account."""


async def render_act_dialogue_v3(
    act: Act,
    cast: Cast,
    out_path: Path,
    *,
    api_key: str,
    base_url: str = ELEVENLABS_BASE_URL,
) -> int:
    """Render one act in a single text-to-dialogue call. Returns chars.

    Raises DialogueUnavailable on 401/403/404 so the caller can fall
    back; other errors propagate (they're transient or real bugs).
    """
    inputs = [
        {"text": t.line, "voice_id": cast.voice_for(t.speaker)}
        for t in act.turns
    ]
    body = {
        "inputs": inputs,
        "model_id": DIALOGUE_MODEL_ID,
        "settings": {"stability": DIALOGUE_STABILITY},
    }
    try:
        data = await _post_audio(
            f"{base_url}/v1/text-to-dialogue", body, api_key, timeout=600.0,
        )
    except RuntimeError as e:
        msg = str(e)
        if any(f"ElevenLabs {code}" in msg for code in (401, 403, 404)):
            raise DialogueUnavailable(msg) from e
        raise
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return sum(len(t.line) for t in act.turns)


async def _render_turn_clip(
    turn: DialogueTurn, cast: Cast, work_dir: Path, *, api_key: str,
) -> tuple[Path, int]:
    """Render one studio-clean turn to a content-addressed cache file.

    Returns (clip_path, char_count). The cache key includes the voice's
    settings (speed) so a pacing change re-renders rather than serving a
    stale clip. Callers review episodes and re-render single lines, so
    only changed turns pay the TTS cost."""
    line = strip_tags(turn.line)
    voice_id = cast.voice_for(turn.speaker)
    settings = cast.voice_settings_for(turn.speaker)
    key = f"{voice_id}|{settings.get('speed', 1.0)}|{line}"
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    clip = work_dir / f"turn_{turn.speaker.lower()}_{h}.mp3"
    if not clip.exists() or clip.stat().st_size == 0:
        await generate_tts_to_file(
            line, voice_id, clip, api_key=api_key, voice_settings=settings,
        )
    return clip, len(line)


async def _render_turns_to_file(
    turns: list[DialogueTurn],
    cast: Cast,
    out_path: Path,
    *,
    api_key: str,
    work_dir: Path,
    turn_gap_seconds: float = 0.25,
    bell_path: Path | None = None,
) -> int:
    """Render a run of studio-clean turns to a single mp3 and return the
    character count. Turns flagged `bell_after` get the Regression Bell
    (`bell_path`) spliced in right after them."""
    work_dir.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []
    chars = 0
    for turn in turns:
        if not strip_tags(turn.line):
            continue
        clip, n = await _render_turn_clip(turn, cast, work_dir, api_key=api_key)
        clip_paths.append(clip)
        chars += n
        if turn.bell_after and bell_path is not None:
            clip_paths.append(bell_path)
    concat_audio_files(clip_paths, out_path, gap_seconds=turn_gap_seconds)
    return chars


async def _render_act_per_turn(
    act: Act,
    cast: Cast,
    out_path: Path,
    *,
    api_key: str,
    turn_gap_seconds: float = 0.25,
    bell_path: Path | None = None,
) -> int:
    """Per-turn TTS for one act (tags stripped), content-addressed turn
    cache, ffmpeg concat, with the Regression Bell spliced in on the
    flagged turn."""
    return await _render_turns_to_file(
        act.turns, cast, out_path, api_key=api_key,
        work_dir=out_path.parent / f"_turns_act_{act.number}",
        turn_gap_seconds=turn_gap_seconds, bell_path=bell_path,
    )


async def render_announcer_segments(
    script: Script,
    cast: Cast,
    output_dir: Path,
    *,
    api_key: str | None = None,
) -> dict[str, Path]:
    """Render Sid Vega's marquee + break bumpers to their own clips.

    Returns a {slot_kind: path} map for the mixer: `announcer_intro`,
    `announcer_bumper_1`, `announcer_bumper_2`, … Only slots that have
    content are included."""
    key = _require_key(api_key)
    output_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    if script.intro:
        path = output_dir / "announcer_intro.mp3"
        await _render_turns_to_file(
            script.intro, cast, path, api_key=key,
            work_dir=output_dir / "_turns_announcer_intro",
        )
        out["announcer_intro"] = path
    for i, bumper in enumerate(script.bumpers, 1):
        path = output_dir / f"announcer_bumper_{i}.mp3"
        await _render_turns_to_file(
            bumper, cast, path, api_key=key,
            work_dir=output_dir / f"_turns_announcer_bumper_{i}",
        )
        out[f"announcer_bumper_{i}"] = path
    return out


# ---------- The Lounge Line (call-in) ----------

# Telephone-bandwidth EQ so the caller sounds like they're on the line.
# Classic POTS passband (300-3400 Hz) + light compression + a nudge of
# gain to sit right against the studio-clean host voices.
_PHONE_FILTER = (
    "highpass=f=300,lowpass=f=3400,"
    "acompressor=threshold=-18dB:ratio=3:attack=10:release=120,"
    "volume=1.4"
)


def _apply_phone_filter(src: Path, dst: Path) -> None:
    """Re-encode a clip through the phone-line EQ chain."""
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-af", _PHONE_FILTER,
            "-codec:a", "libmp3lame", "-b:a", "192k",
            str(dst),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise MixerError(
            f"phone-filter ffmpeg pass failed on {src.name}: "
            f"{result.stderr[-500:]}"
        )


async def render_call_in(
    turns: list[DialogueTurn],
    cast: Cast,
    caller_voice_id: str,
    out_path: Path,
    *,
    api_key: str | None = None,
    turn_gap_seconds: float = 0.3,
) -> int:
    """Render the Lounge Line block to a single mp3. Returns chars.

    Always per-turn (never the v3 dialogue endpoint): the caller's turns
    get the phone-line filter and everyone else — hosts and the studio
    announcer who introduces the caller — stays studio-clean, which
    requires rendering them as separate clips. Caller turns render with
    `caller_voice_id` — a different voice every episode, picked by the
    showrunner.
    """
    api_key = _require_key(api_key)
    work_dir = out_path.parent / "_turns_call_in"
    work_dir.mkdir(parents=True, exist_ok=True)
    turn_paths: list[Path] = []
    chars = 0
    for turn in turns:
        line = strip_tags(turn.line)
        if not line:
            continue
        if turn.speaker == CALLER:
            # Caller isn't in the cast: its own voice, default settings,
            # then the phone-line EQ.
            h = hashlib.sha256(f"{caller_voice_id}|{line}".encode()).hexdigest()[:16]
            clean = work_dir / f"turn_caller_{h}.mp3"
            if not clean.exists() or clean.stat().st_size == 0:
                await generate_tts_to_file(
                    line, caller_voice_id, clean, api_key=api_key,
                )
            phoned = work_dir / f"turn_caller_{h}_phone.mp3"
            if not phoned.exists() or phoned.stat().st_size == 0:
                _apply_phone_filter(clean, phoned)
            turn_paths.append(phoned)
        else:
            clip, _ = await _render_turn_clip(turn, cast, work_dir, api_key=api_key)
            turn_paths.append(clip)
        chars += len(line)
    concat_audio_files(turn_paths, out_path, gap_seconds=turn_gap_seconds)
    return chars


async def render_episode_voices(
    script: Script,
    cast: Cast,
    output_dir: Path,
    *,
    api_key: str | None = None,
    prefer_dialogue: bool = False,
    bell_path: Path | None = None,
    log=None,
) -> list[ActRenderResult]:
    """Render every act. The default path is per-turn TTS: each turn is
    its own content-addressed clip, which gives per-voice pacing, a
    reviewer the ability to re-render a single line, and a trivial splice
    point for the Regression Bell (`bell_path`). Pass
    `prefer_dialogue=True` to opt into the single-call v3 text-to-dialogue
    renderer instead (more natural interplay + audio tags, but no per-voice
    speed, no per-line edits, and no mid-act bell); it downgrades to
    per-turn for the REST of the episode on the first DialogueUnavailable.

    Acts render sequentially: both paths hit the same voices, and
    ElevenLabs rejects concurrent renders against one voice.
    """
    key = _require_key(api_key)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if log:
            log(msg)

    use_dialogue = prefer_dialogue
    results: list[ActRenderResult] = []
    for act in script.acts:
        out = output_dir / f"act_{act.number}.mp3"
        if use_dialogue:
            try:
                chars = await render_act_dialogue_v3(act, cast, out, api_key=key)
                results.append(ActRenderResult(
                    act=act.number, audio_path=out,
                    turn_count=len(act.turns), char_cost=chars,
                    renderer="dialogue-v3",
                ))
                continue
            except DialogueUnavailable as e:
                use_dialogue = False
                _log(
                    "       text-to-dialogue unavailable on this account "
                    f"({e}); falling back to per-turn TTS"
                )
        chars = await _render_act_per_turn(
            act, cast, out, api_key=key, bell_path=bell_path,
        )
        results.append(ActRenderResult(
            act=act.number, audio_path=out,
            turn_count=len(act.turns), char_cost=chars,
            renderer="per-turn",
        ))
    return results
