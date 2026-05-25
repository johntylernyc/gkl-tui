"""Phase 4 — Per-turn TTS voice-track renderer.

For each Act in the script, this module iterates the dialogue turns, hits
`/v1/text-to-speech/{voice_id}` with the matching host voice, and
concatenates the per-turn mp3s into a single act track. All three acts
render in parallel.

The previous Studio Podcast implementation was removed when ElevenLabs
gated that endpoint behind "contact sales" on the Creator tier. Per-turn
TTS uses an endpoint that's available on Creator today.

Also hosts the ElevenLabs API key loading utilities (env / web / disk),
including hardening against bracketed-paste terminal artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from gkl.podcast.mixer import concat_audio_files
from gkl.podcast.script_writer import Act, DialogueTurn, Script


ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
ELEVENLABS_KEY_PATH = Path.home() / ".config" / "gkl" / "elevenlabs.json"


# ---------- Result type ----------

@dataclass
class ActRenderResult:
    """One act's rendered voice track."""
    act: int
    audio_path: Path
    turn_count: int
    char_cost: int  # sum of characters rendered via TTS


# ---------- API key loading ----------

# Terminal bracketed-paste markers: when pasting into a terminal with
# bracketed-paste mode on, the shell wraps the pasted text with the escape
# sequences \e[200~ … \e[201~. If these leak into the saved key (or an env
# var) the resulting HTTP header has control chars and is rejected by the
# gateway with an opaque Google 400 rather than an ElevenLabs error —
# silently stripping them here saves a very confusing debugging session.
_BRACKETED_PASTE_RE = re.compile(r"\x1b\[20[01]~")


def _clean_key(raw: str) -> str:
    """Strip whitespace, bracketed-paste escape sequences, and control chars.

    Also strips leading/trailing `~` which can appear as orphaned tails when
    the escape prefix of a paste-marker (\\x1b[201) gets eaten upstream but
    the terminator `~` survives. ElevenLabs keys are `sk_` + hex, so `~` is
    never a legitimate boundary character.
    """
    cleaned = _BRACKETED_PASTE_RE.sub("", raw).strip()
    # Drop any remaining C0 control characters (invalid in HTTP headers).
    cleaned = "".join(c for c in cleaned if c == "\t" or c >= " ")
    # Orphaned paste-terminator tails — e.g. leading "200~" or trailing "~"
    # left behind when the \x1b prefix was stripped by another layer.
    cleaned = cleaned.lstrip("~").rstrip("~")
    if cleaned.startswith("200~"):
        cleaned = cleaned[4:]
    if cleaned.endswith("201"):
        cleaned = cleaned[:-3]
    return cleaned


def load_elevenlabs_key() -> str | None:
    """Load the ElevenLabs API key from env var, per-user file, or disk.

    Mirrors the Anthropic key loading pattern in `gkl.skipper`. Supports:
    - ELEVENLABS_API_KEY / GKL_ELEVENLABS_KEY env var
    - Per-user file in web mode ($GKL_DB_PATH/../elevenlabs_keys/<user>.json)
    - Local config at ~/.config/gkl/elevenlabs.json

    All loaded values are run through `_clean_key` so bracketed-paste
    artifacts or stray whitespace don't corrupt the HTTP header.
    """
    env_key = (
        os.environ.get("GKL_ELEVENLABS_KEY")
        or os.environ.get("ELEVENLABS_API_KEY")
    )
    if env_key:
        cleaned = _clean_key(env_key)
        if cleaned:
            return cleaned

    user_id = os.environ.get("GKL_USER_ID")
    db_dir = os.environ.get("GKL_DB_PATH")
    if user_id and db_dir:
        web_path = Path(db_dir).parent / "elevenlabs_keys" / f"{user_id}.json"
        if web_path.exists():
            try:
                data = json.loads(web_path.read_text())
                key = _clean_key(data.get("api_key", ""))
                if key:
                    return key
            except (json.JSONDecodeError, KeyError):
                pass

    if ELEVENLABS_KEY_PATH.exists():
        try:
            data = json.loads(ELEVENLABS_KEY_PATH.read_text())
            key = _clean_key(data.get("api_key", ""))
            if key:
                return key
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def save_elevenlabs_key(key: str) -> None:
    """Persist the ElevenLabs API key locally. Strips paste artifacts."""
    cleaned = _clean_key(key)
    if not cleaned:
        raise ValueError("key is empty after cleaning")
    ELEVENLABS_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ELEVENLABS_KEY_PATH.write_text(json.dumps({"api_key": cleaned}))


# ---------- Dialogue rendering ----------

def _voice_for_speaker(
    speaker: str, host_voice_id: str, guest_voice_id: str,
) -> str:
    if speaker == "HOST":
        return host_voice_id
    if speaker == "GUEST":
        return guest_voice_id
    raise ValueError(f"unknown speaker: {speaker!r}")


def _turn_cache_path(
    work_dir: Path, turn: DialogueTurn, voice_id: str,
) -> Path:
    """Content-addressed per-turn mp3 path.

    Hashes the voice_id + line text into the filename so:
    - Re-running the pipeline after a network timeout reuses already-
      rendered turns (the file already exists → skip TTS).
    - If the script changes (Opus 4.6 isn't deterministic), the hash
      changes and the new content gets rendered fresh. Stale orphans
      accumulate under the work_dir but are harmless.
    - Two turns with identical text + voice share a single mp3.
    """
    h = hashlib.sha256(f"{voice_id}|{turn.line}".encode("utf-8")).hexdigest()[:16]
    return work_dir / f"turn_{turn.speaker.lower()}_{h}.mp3"


async def render_dialogue_to_act_track(
    act: Act,
    host_voice_id: str,
    guest_voice_id: str,
    out_path: Path,
    *,
    api_key: str,
    work_dir: Path | None = None,
    turn_gap_seconds: float = 0.25,
) -> int:
    """Render one Act's dialogue to a single mp3. Returns char count.

    Per-turn mp3s are content-addressed under `work_dir`. If a matching
    file already exists (e.g. from a prior run that failed mid-episode),
    the TTS call is skipped and the cached audio is reused. The returned
    char count still includes skipped turns — it reflects the script's
    character total, not the incremental API usage this run.
    """
    # Import locally to avoid a circular module import at load time (assets
    # depends on voice for the key-loading helpers).
    from gkl.podcast.assets import generate_tts_to_file

    work_dir = work_dir or out_path.parent / f"_turns_act_{act.number}"
    work_dir.mkdir(parents=True, exist_ok=True)

    turn_paths: list[Path] = []
    char_total = 0
    for turn in act.turns:
        voice_id = _voice_for_speaker(
            turn.speaker, host_voice_id, guest_voice_id,
        )
        turn_path = _turn_cache_path(work_dir, turn, voice_id)
        if not turn_path.exists() or turn_path.stat().st_size == 0:
            await generate_tts_to_file(
                turn.line, voice_id, turn_path, api_key=api_key,
            )
        turn_paths.append(turn_path)
        char_total += len(turn.line)

    concat_audio_files(
        turn_paths, out_path, gap_seconds=turn_gap_seconds,
    )
    return char_total


async def render_episode_voices(
    script: Script,
    host_voice_id: str,
    guest_voice_id: str,
    output_dir: Path,
    *,
    api_key: str | None = None,
) -> list[ActRenderResult]:
    """Render all three act voice tracks sequentially.

    Writes per-act mp3s to `output_dir/act_<n>.mp3` and returns metadata.
    Per-turn intermediate mp3s are kept under `output_dir/_turns_act_<n>/`
    for debugging + re-concatenation without re-charging TTS.

    Acts render sequentially rather than in parallel because ElevenLabs
    rejects concurrent TTS calls against the same voice_id with a 409
    (`already_running`). Since all three acts use the same two voices,
    parallelism across acts would predictably collide. Sequential keeps
    the total wall time bounded at roughly (total_turns × per-turn latency)
    which for a typical ~48-turn episode is 2-3 minutes — acceptable for a
    weekly-generated artifact.
    """
    key = api_key or load_elevenlabs_key()
    if not key:
        raise ValueError(
            "No ElevenLabs API key configured. Set ELEVENLABS_API_KEY or "
            f"write one to {ELEVENLABS_KEY_PATH}."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ActRenderResult] = []
    for act in script.acts:
        out = output_dir / f"act_{act.number}.mp3"
        chars = await render_dialogue_to_act_track(
            act, host_voice_id, guest_voice_id, out, api_key=key,
        )
        results.append(ActRenderResult(
            act=act.number, audio_path=out,
            turn_count=len(act.turns), char_cost=chars,
        ))
    return results
