"""Tests for the music/SFX/TTS asset generation clients (Phase 5)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from gkl.podcast.assets import (
    generate_music, generate_music_to_file, generate_sfx, generate_sfx_to_file,
    generate_tts, generate_tts_to_file,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)


# -- Music -------------------------------------------------------------------

@pytest.mark.anyio
async def test_generate_music_posts_prompt_and_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(
            200, content=b"fake-mp3", headers={"content-type": "audio/mpeg"},
        )

    _patch_httpx(monkeypatch, handler)

    data = await generate_music(
        "upbeat sports bumper", length_ms=15_000, api_key="k",
    )
    assert data == b"fake-mp3"
    assert captured["url"].endswith("/v1/music")
    import json
    body = json.loads(captured["body"])
    assert body["prompt"] == "upbeat sports bumper"
    assert body["music_length_ms"] == 15_000
    assert body["force_instrumental"] is True


@pytest.mark.anyio
async def test_generate_music_rejects_out_of_range_length() -> None:
    with pytest.raises(ValueError, match="between 3000 and 600000"):
        await generate_music("x", length_ms=2_000, api_key="k")
    with pytest.raises(ValueError, match="between 3000 and 600000"):
        await generate_music("x", length_ms=700_000, api_key="k")


@pytest.mark.anyio
async def test_generate_music_to_file_writes_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"music-bytes")

    _patch_httpx(monkeypatch, handler)
    out = tmp_path / "intro.mp3"
    await generate_music_to_file("prompt", out, api_key="k")
    assert out.read_bytes() == b"music-bytes"


# -- SFX ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_generate_sfx_posts_text_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, content=b"sfx")

    _patch_httpx(monkeypatch, handler)

    data = await generate_sfx(
        "ball hitting bat, crowd cheer", duration_seconds=2.0, api_key="k",
    )
    assert data == b"sfx"
    assert captured["url"].endswith("/v1/sound-generation")
    import json
    body = json.loads(captured["body"])
    assert body["text"] == "ball hitting bat, crowd cheer"
    assert body["duration_seconds"] == 2.0
    assert body["loop"] is False


@pytest.mark.anyio
async def test_generate_sfx_omits_duration_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, content=b"sfx")

    _patch_httpx(monkeypatch, handler)
    await generate_sfx("x", duration_seconds=None, api_key="k")
    import json
    body = json.loads(captured["body"])
    assert "duration_seconds" not in body


@pytest.mark.anyio
async def test_generate_sfx_rejects_bad_duration() -> None:
    with pytest.raises(ValueError, match="0.5 and 30"):
        await generate_sfx("x", duration_seconds=0.1, api_key="k")
    with pytest.raises(ValueError, match="0.5 and 30"):
        await generate_sfx("x", duration_seconds=45, api_key="k")


@pytest.mark.anyio
async def test_generate_sfx_rejects_bad_prompt_influence() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        await generate_sfx("x", prompt_influence=1.5, api_key="k")


@pytest.mark.anyio
async def test_generate_sfx_to_file_writes_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"sting")

    _patch_httpx(monkeypatch, handler)
    out = tmp_path / "stinger.mp3"
    await generate_sfx_to_file("short sting", out, duration_seconds=1.5, api_key="k")
    assert out.read_bytes() == b"sting"


# -- TTS ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_generate_tts_posts_to_voice_specific_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, content=b"tts")

    _patch_httpx(monkeypatch, handler)
    data = await generate_tts("ad copy here", voice_id="voice-123", api_key="k")
    assert data == b"tts"
    assert "/v1/text-to-speech/voice-123" in captured["url"]


@pytest.mark.anyio
async def test_generate_tts_includes_default_voice_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without explicit voice_settings, fall back to the podcast-tuned
    DEFAULT_TTS_VOICE_SETTINGS so per-turn audio doesn't drift."""
    import json
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, content=b"tts")

    _patch_httpx(monkeypatch, handler)
    await generate_tts("hello", voice_id="v", api_key="k")
    body = json.loads(captured["body"])
    assert "voice_settings" in body
    # The defaults: high stability + similarity_boost for consistency
    assert body["voice_settings"]["stability"] == 0.65
    assert body["voice_settings"]["similarity_boost"] == 0.85
    assert body["voice_settings"]["use_speaker_boost"] is True


@pytest.mark.anyio
async def test_generate_tts_respects_explicit_voice_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-call override (e.g. ad reads with more expressiveness)."""
    import json
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, content=b"tts")

    _patch_httpx(monkeypatch, handler)
    await generate_tts(
        "hello", voice_id="v", api_key="k",
        voice_settings={"stability": 0.3, "similarity_boost": 0.5},
    )
    body = json.loads(captured["body"])
    assert body["voice_settings"]["stability"] == 0.3
    assert body["voice_settings"]["similarity_boost"] == 0.5


@pytest.mark.anyio
async def test_generate_tts_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await generate_tts("   ", voice_id="v", api_key="k")


@pytest.mark.anyio
async def test_generate_tts_to_file_writes_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tts-mp3")

    _patch_httpx(monkeypatch, handler)
    out = tmp_path / "ads" / "victory.mp3"
    await generate_tts_to_file("ad copy", "voice-1", out, api_key="k")
    assert out.read_bytes() == b"tts-mp3"


# -- API key guard-rail -----------------------------------------------------

# -- Retry behavior ---------------------------------------------------------

@pytest.mark.anyio
async def test_post_audio_retries_on_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient connection timeouts should be retried with backoff, not fail
    the whole pipeline on the first blip."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return httpx.Response(200, content=b"mp3-bytes")

    _patch_httpx(monkeypatch, handler)
    # Skip actual sleeps to keep the test fast
    monkeypatch.setattr("gkl.podcast.assets.asyncio.sleep", _instant_sleep)

    data = await generate_tts("ok", voice_id="v", api_key="k")
    assert data == b"mp3-bytes"
    assert attempts["n"] == 3


@pytest.mark.anyio
async def test_post_audio_retries_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(503, text="upstream overloaded")
        return httpx.Response(200, content=b"ok")

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr("gkl.podcast.assets.asyncio.sleep", _instant_sleep)

    data = await generate_tts("ok", voice_id="v", api_key="k")
    assert data == b"ok"
    assert attempts["n"] == 2


@pytest.mark.anyio
async def test_post_audio_fails_loud_on_non_retryable_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4xx responses other than 408/429 should raise immediately with body."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(403, text='{"detail":"forbidden"}')

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr("gkl.podcast.assets.asyncio.sleep", _instant_sleep)

    with pytest.raises(RuntimeError, match="403.*forbidden"):
        await generate_tts("ok", voice_id="v", api_key="k")
    # No retries on non-retryable 4xx
    assert attempts["n"] == 1


@pytest.mark.anyio
async def test_post_audio_raises_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("never recovers")

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr("gkl.podcast.assets.asyncio.sleep", _instant_sleep)

    with pytest.raises(RuntimeError, match="failed after 4 attempts"):
        await generate_tts("ok", voice_id="v", api_key="k")


async def _instant_sleep(_seconds: float) -> None:
    return None


@pytest.mark.anyio
async def test_missing_api_key_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("GKL_ELEVENLABS_KEY", raising=False)
    monkeypatch.setattr(
        "gkl.podcast.voice.ELEVENLABS_KEY_PATH", tmp_path / "none.json",
    )
    with pytest.raises(ValueError, match="No ElevenLabs API key"):
        await generate_music("x", api_key=None)
    with pytest.raises(ValueError, match="No ElevenLabs API key"):
        await generate_sfx("x", api_key=None)
    with pytest.raises(ValueError, match="No ElevenLabs API key"):
        await generate_tts("x", voice_id="v", api_key=None)
