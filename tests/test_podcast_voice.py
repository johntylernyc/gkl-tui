"""Tests for the per-turn TTS voice renderer and the key-loading utilities."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gkl.podcast.script_writer import Act, DialogueTurn, Script
from gkl.podcast.voice import (
    ELEVENLABS_KEY_PATH, _clean_key, _voice_for_speaker,
    load_elevenlabs_key, render_episode_voices, save_elevenlabs_key,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# -- Key loader hygiene ------------------------------------------------------

def test_load_elevenlabs_key_strips_bracketed_paste_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminals paste-wrap text with \\x1b[200~ … \\x1b[201~ when bracketed-
    paste mode is on; those escape sequences are invalid in HTTP headers and
    cause opaque 400s from the ElevenLabs gateway. The loader must strip them.
    """
    monkeypatch.setenv(
        "ELEVENLABS_API_KEY", "\x1b[200~sk_cleanme_42\x1b[201~",
    )
    key = load_elevenlabs_key()
    assert key == "sk_cleanme_42"
    assert "\x1b" not in key


def test_save_elevenlabs_key_strips_paste_markers_on_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "gkl.podcast.voice.ELEVENLABS_KEY_PATH", tmp_path / "key.json",
    )
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("GKL_ELEVENLABS_KEY", raising=False)
    save_elevenlabs_key("\x1b[200~sk_pasted_key\x1b[201~")
    assert load_elevenlabs_key() == "sk_pasted_key"


def test_save_elevenlabs_key_rejects_empty_after_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "gkl.podcast.voice.ELEVENLABS_KEY_PATH", tmp_path / "key.json",
    )
    with pytest.raises(ValueError, match="empty after cleaning"):
        save_elevenlabs_key("\x1b[200~\x1b[201~")


def test_clean_key_strips_orphan_paste_marker_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the \\x1b prefix of a paste marker was stripped upstream, the
    orphaned tail (trailing `~` or `201`, leading `200~`) must still be
    removed."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_cafebabe~")
    assert load_elevenlabs_key() == "sk_cafebabe"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "200~sk_cafebabe")
    assert load_elevenlabs_key() == "sk_cafebabe"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_cafebabe201")
    assert load_elevenlabs_key() == "sk_cafebabe"


# -- Speaker → voice mapping -------------------------------------------------

def test_voice_for_speaker_picks_host_and_guest() -> None:
    assert _voice_for_speaker("HOST", "vh", "vg") == "vh"
    assert _voice_for_speaker("GUEST", "vh", "vg") == "vg"


def test_voice_for_speaker_raises_on_unknown() -> None:
    with pytest.raises(ValueError, match="unknown speaker"):
        _voice_for_speaker("NARRATOR", "vh", "vg")


# -- Episode rendering (mocked TTS + mocked concat) --------------------------

def _simple_script() -> Script:
    return Script(acts=[
        Act(number=n, turns=[
            DialogueTurn(speaker="HOST", line=f"act {n} line 1"),
            DialogueTurn(speaker="GUEST", line=f"act {n} line 2"),
        ])
        for n in (1, 2, 3)
    ])


@pytest.mark.anyio
async def test_render_episode_voices_writes_per_act_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts_calls: list[tuple[str, str]] = []
    concat_calls: list[tuple[int, Path]] = []

    async def fake_tts(
        text: str, voice_id: str, out_path: Path, *, api_key=None, **kw,
    ) -> None:
        tts_calls.append((text, voice_id))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake-turn-mp3")

    def fake_concat(inputs, output, **kw) -> None:
        concat_calls.append((len(inputs), output))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-act-mp3")

    monkeypatch.setattr(
        "gkl.podcast.assets.generate_tts_to_file", fake_tts,
    )
    monkeypatch.setattr(
        "gkl.podcast.voice.concat_audio_files", fake_concat,
    )

    script = _simple_script()
    results = await render_episode_voices(
        script, host_voice_id="vh", guest_voice_id="vg",
        output_dir=tmp_path, api_key="test-key",
    )

    # Three acts rendered with HOST/GUEST voices as appropriate
    assert [r.act for r in results] == [1, 2, 3]
    assert [r.turn_count for r in results] == [2, 2, 2]
    # Each act contributed its line lengths to char_cost
    assert all(r.char_cost > 0 for r in results)

    # 6 TTS calls (2 turns × 3 acts), alternating voices
    assert len(tts_calls) == 6
    assert tts_calls[0][1] == "vh"  # first turn of act 1 is HOST
    assert tts_calls[1][1] == "vg"  # second turn of act 1 is GUEST

    # 3 concat calls, each with 2 inputs (the two turns)
    assert len(concat_calls) == 3
    assert all(n == 2 for n, _ in concat_calls)
    assert [p for _, p in concat_calls] == [
        tmp_path / "act_1.mp3",
        tmp_path / "act_2.mp3",
        tmp_path / "act_3.mp3",
    ]


@pytest.mark.anyio
async def test_render_episode_voices_raises_without_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("GKL_ELEVENLABS_KEY", raising=False)
    monkeypatch.setattr(
        "gkl.podcast.voice.ELEVENLABS_KEY_PATH", tmp_path / "nope.json",
    )
    with pytest.raises(ValueError, match="No ElevenLabs API key"):
        await render_episode_voices(
            _simple_script(), "vh", "vg", tmp_path,
        )


# -- Per-turn content-addressed caching -------------------------------------

@pytest.mark.anyio
async def test_render_skips_tts_when_cached_turn_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn whose hashed mp3 already exists must not trigger a TTS call."""
    from gkl.podcast.voice import _turn_cache_path

    tts_calls: list[str] = []
    concat_calls: list[int] = []

    async def fake_tts(
        text: str, voice_id: str, out_path: Path, *, api_key=None, **kw,
    ) -> None:
        tts_calls.append(text)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"new-turn")

    def fake_concat(inputs, output, **kw) -> None:
        concat_calls.append(len(inputs))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"act-track")

    monkeypatch.setattr(
        "gkl.podcast.assets.generate_tts_to_file", fake_tts,
    )
    monkeypatch.setattr(
        "gkl.podcast.voice.concat_audio_files", fake_concat,
    )

    # Prime the cache for the first turn only
    turn_1 = DialogueTurn(speaker="HOST", line="Already cached line.")
    turn_2 = DialogueTurn(speaker="GUEST", line="Needs to render.")
    script = Script(acts=[
        Act(number=1, turns=[turn_1, turn_2]),
        Act(number=2, turns=[]),
        Act(number=3, turns=[]),
    ])
    # Prefill act 2 and 3 with a single turn each so the script is well-formed
    for a in script.acts[1:]:
        a.turns.append(DialogueTurn(speaker="HOST", line=f"Act {a.number} only"))

    work_dir = tmp_path / "_turns_act_1"
    work_dir.mkdir()
    cache_hit_path = _turn_cache_path(work_dir, turn_1, "vh")
    cache_hit_path.write_bytes(b"previously-rendered")

    await render_episode_voices(
        script, host_voice_id="vh", guest_voice_id="vg",
        output_dir=tmp_path, api_key="k",
    )

    # Turn 1 (primed cache) should NOT have been re-rendered.
    # Turns 2, act 2's, and act 3's turns are fresh renders.
    assert "Already cached line." not in tts_calls
    assert "Needs to render." in tts_calls
    # Primed file's contents are preserved (proving we didn't overwrite it)
    assert cache_hit_path.read_bytes() == b"previously-rendered"


def test_turn_cache_path_changes_when_voice_changes(tmp_path: Path) -> None:
    from gkl.podcast.voice import _turn_cache_path
    turn = DialogueTurn(speaker="HOST", line="Same line.")
    p1 = _turn_cache_path(tmp_path, turn, "voice-A")
    p2 = _turn_cache_path(tmp_path, turn, "voice-B")
    assert p1 != p2


def test_turn_cache_path_stable_for_same_inputs(tmp_path: Path) -> None:
    from gkl.podcast.voice import _turn_cache_path
    turn = DialogueTurn(speaker="HOST", line="Same line.")
    assert (
        _turn_cache_path(tmp_path, turn, "v")
        == _turn_cache_path(tmp_path, turn, "v")
    )
