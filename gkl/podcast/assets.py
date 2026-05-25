"""Phase 5 — ElevenLabs API clients for music, SFX, and single-voice TTS.

These three capabilities generate the reusable asset library (intro/outro music,
stingers, ad spots). They're consolidated here because they share the same auth,
base URL, and httpx patterns — the differences are purely payload shape.

Endpoints:
- POST /v1/music — Eleven Music (intro/outro beds)
- POST /v1/sound-generation — SFX (stingers, commercial-break stings)
- POST /v1/text-to-speech/{voice_id} — single-voice TTS (ad spots)

All return raw audio bytes. Helpers write them to disk.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from gkl.podcast.voice import ELEVENLABS_BASE_URL, load_elevenlabs_key


# Retry transient network errors and upstream hiccups. A 50-turn episode
# crossing the internet will occasionally hit a TCP connect timeout or a
# gateway 5xx — retrying a few times with backoff makes the pipeline
# resilient to those without requiring a full re-run.
_RETRY_EXCEPTIONS = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_RETRIES = 4
_INITIAL_BACKOFF_SECONDS = 1.0


DEFAULT_TTS_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_MUSIC_MODEL_ID = "music_v1"
DEFAULT_SFX_MODEL_ID = "eleven_text_to_sound_v2"

# Voice settings tuned for podcast consistency over expressiveness. ElevenLabs
# defaults vary per voice and can produce noticeable drift between turns —
# louder/quieter takes, different room sound. Higher `stability` damps that
# expressive variation; higher `similarity_boost` keeps each render close to
# the cloned voice's reference. `style=0` avoids exaggeration that can make
# successive turns feel different. `use_speaker_boost` further stabilizes
# cloned voices.
DEFAULT_TTS_VOICE_SETTINGS: dict = {
    "stability": 0.65,
    "similarity_boost": 0.85,
    "style": 0.0,
    "use_speaker_boost": True,
}


# ---------- Shared ----------

def _headers(api_key: str) -> dict[str, str]:
    return {"xi-api-key": api_key}


def _require_key(api_key: str | None) -> str:
    key = api_key or load_elevenlabs_key()
    if not key:
        raise ValueError(
            "No ElevenLabs API key configured. Set ELEVENLABS_API_KEY or "
            "save one via gkl.podcast.voice.save_elevenlabs_key()."
        )
    return key


async def _post_audio(
    url: str, json_body: dict, api_key: str, *,
    timeout: float = 120.0,
) -> bytes:
    """POST JSON to an endpoint that returns raw audio bytes.

    Retries on transient network errors (connect/read timeouts, connection
    resets) and retryable HTTP statuses (429, 5xx) with exponential backoff.
    Non-retryable 4xx errors raise immediately with the response body
    included — the default `raise_for_status()` drops that body, which is
    where ElevenLabs puts actionable error detail.
    """
    last_error: str | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    url, headers=_headers(api_key), json=json_body,
                )
                if resp.status_code in _RETRYABLE_STATUS:
                    last_error = (
                        f"{resp.status_code} (retryable): {resp.text[:500]}"
                    )
                elif resp.status_code >= 400:
                    # Non-retryable client error — fail loud with full body.
                    raise RuntimeError(
                        f"ElevenLabs {resp.status_code} on {url}: {resp.text}"
                    )
                else:
                    return resp.content
        except _RETRY_EXCEPTIONS as e:
            last_error = f"{type(e).__name__}: {e}"

        if attempt < _MAX_RETRIES - 1:
            backoff = _INITIAL_BACKOFF_SECONDS * (2 ** attempt)
            await asyncio.sleep(backoff)

    raise RuntimeError(
        f"ElevenLabs request to {url} failed after {_MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---------- Music ----------

async def generate_music(
    prompt: str,
    *,
    length_ms: int = 30_000,
    force_instrumental: bool = True,
    model_id: str = DEFAULT_MUSIC_MODEL_ID,
    api_key: str | None = None,
    base_url: str = ELEVENLABS_BASE_URL,
) -> bytes:
    """Generate music from a text prompt. Returns raw mp3 bytes.

    `length_ms` must be 3000–600000 (3 s to 10 min). For intro/outro beds,
    20–30 s is typical. Instrumental is on by default so there aren't any
    lyrics fighting the hosts' voices when ducked under dialogue.
    """
    if not 3_000 <= length_ms <= 600_000:
        raise ValueError(
            f"length_ms must be between 3000 and 600000, got {length_ms}"
        )
    key = _require_key(api_key)
    body: dict = {
        "prompt": prompt,
        "music_length_ms": length_ms,
        "model_id": model_id,
        "force_instrumental": force_instrumental,
    }
    return await _post_audio(f"{base_url}/v1/music", body, key)


async def generate_music_to_file(
    prompt: str, out_path: Path,
    *, length_ms: int = 30_000, force_instrumental: bool = True,
    model_id: str = DEFAULT_MUSIC_MODEL_ID,
    api_key: str | None = None,
    base_url: str = ELEVENLABS_BASE_URL,
) -> None:
    data = await generate_music(
        prompt, length_ms=length_ms, force_instrumental=force_instrumental,
        model_id=model_id, api_key=api_key, base_url=base_url,
    )
    _write_bytes(out_path, data)


# ---------- Sound effects ----------

async def generate_sfx(
    prompt: str,
    *,
    duration_seconds: float | None = None,
    prompt_influence: float = 0.3,
    loop: bool = False,
    model_id: str = DEFAULT_SFX_MODEL_ID,
    api_key: str | None = None,
    base_url: str = ELEVENLABS_BASE_URL,
) -> bytes:
    """Generate a sound effect. Returns raw mp3 bytes.

    `duration_seconds` must be 0.5–30 or None (auto). For commercial-break
    stingers, 1–3 s is typical. `loop=True` makes the model produce a sample
    that loops cleanly — useful for a music bed, less so for one-shot stings.
    """
    if duration_seconds is not None and not 0.5 <= duration_seconds <= 30:
        raise ValueError(
            f"duration_seconds must be between 0.5 and 30, got {duration_seconds}"
        )
    if not 0.0 <= prompt_influence <= 1.0:
        raise ValueError(
            f"prompt_influence must be between 0 and 1, got {prompt_influence}"
        )
    key = _require_key(api_key)
    body: dict = {
        "text": prompt,
        "model_id": model_id,
        "prompt_influence": prompt_influence,
        "loop": loop,
    }
    if duration_seconds is not None:
        body["duration_seconds"] = duration_seconds
    return await _post_audio(f"{base_url}/v1/sound-generation", body, key)


async def generate_sfx_to_file(
    prompt: str, out_path: Path,
    *, duration_seconds: float | None = None,
    prompt_influence: float = 0.3, loop: bool = False,
    model_id: str = DEFAULT_SFX_MODEL_ID,
    api_key: str | None = None,
    base_url: str = ELEVENLABS_BASE_URL,
) -> None:
    data = await generate_sfx(
        prompt, duration_seconds=duration_seconds,
        prompt_influence=prompt_influence, loop=loop,
        model_id=model_id, api_key=api_key, base_url=base_url,
    )
    _write_bytes(out_path, data)


# ---------- Single-voice TTS (for ad spots) ----------

async def generate_tts(
    text: str,
    voice_id: str,
    *,
    model_id: str = DEFAULT_TTS_MODEL_ID,
    voice_settings: dict | None = None,
    api_key: str | None = None,
    base_url: str = ELEVENLABS_BASE_URL,
) -> bytes:
    """Render a single-voice TTS line. Returns raw mp3 bytes.

    `voice_settings` defaults to `DEFAULT_TTS_VOICE_SETTINGS` (high
    stability + similarity_boost) for podcast turn-to-turn consistency.
    Pass an explicit dict to override per-call (e.g. ad reads might want
    more expressiveness).
    """
    if not text.strip():
        raise ValueError("text must not be empty")
    key = _require_key(api_key)
    body = {
        "text": text,
        "model_id": model_id,
        "voice_settings": voice_settings or DEFAULT_TTS_VOICE_SETTINGS,
    }
    return await _post_audio(
        f"{base_url}/v1/text-to-speech/{voice_id}", body, key,
    )


async def generate_tts_to_file(
    text: str, voice_id: str, out_path: Path,
    *, model_id: str = DEFAULT_TTS_MODEL_ID,
    voice_settings: dict | None = None,
    api_key: str | None = None,
    base_url: str = ELEVENLABS_BASE_URL,
) -> None:
    data = await generate_tts(
        text, voice_id, model_id=model_id, voice_settings=voice_settings,
        api_key=api_key, base_url=base_url,
    )
    _write_bytes(out_path, data)
