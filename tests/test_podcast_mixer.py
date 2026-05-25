"""Tests for the ffmpeg-backed episode mixer (Phase 6)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gkl.podcast.mixer import (
    MixerError, _resolve_slot_inputs, build_ffmpeg_command,
    concat_audio_files, ffmpeg_available, mix_episode,
)
from gkl.podcast.recipe import Recipe, RecipeSlot


# -- Fixtures ----------------------------------------------------------------

def _simple_recipe() -> Recipe:
    return Recipe(slots=[
        RecipeSlot(kind="a"), RecipeSlot(kind="b"), RecipeSlot(kind="a"),
    ])


@pytest.fixture
def sine_wave_factory(tmp_path: Path):
    """Factory for generating short sine-wave mp3s via ffmpeg.

    Returns a callable `make(name, duration_s, freq)` that writes
    tmp_path/<name>.mp3 and returns the path.
    """
    if not ffmpeg_available():
        pytest.skip("ffmpeg not on PATH")

    def _make(name: str, duration_s: float = 1.0, freq: int = 440) -> Path:
        out = tmp_path / f"{name}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi",
                "-i", f"sine=frequency={freq}:duration={duration_s}",
                "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame",
                "-b:a", "128k", str(out),
            ],
            check=True, capture_output=True,
        )
        return out

    return _make


# -- Input resolution --------------------------------------------------------

def test_resolve_slot_inputs_maps_kinds_to_paths(tmp_path: Path) -> None:
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    slot_paths = {"a": tmp_path / "a.mp3", "b": tmp_path / "b.mp3"}
    inputs = _resolve_slot_inputs(_simple_recipe(), slot_paths)
    # Kind "a" appears twice in the recipe — its path appears twice in inputs
    assert inputs == [
        slot_paths["a"], slot_paths["b"], slot_paths["a"],
    ]


def test_resolve_slot_inputs_raises_on_missing_kind(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match=r"missing kinds: \['b'\]"):
        _resolve_slot_inputs(
            _simple_recipe(), {"a": tmp_path / "a.mp3"},
        )


def test_resolve_slot_inputs_raises_on_missing_file(tmp_path: Path) -> None:
    (tmp_path / "a.mp3").write_bytes(b"x")
    slot_paths = {
        "a": tmp_path / "a.mp3",
        "b": tmp_path / "does-not-exist.mp3",
    }
    with pytest.raises(FileNotFoundError, match="slot 'b'"):
        _resolve_slot_inputs(_simple_recipe(), slot_paths)


# -- Command-string shape ----------------------------------------------------

def test_build_ffmpeg_command_has_one_input_per_slot(tmp_path: Path) -> None:
    inputs = [tmp_path / f"slot{i}.mp3" for i in range(3)]
    cmd = build_ffmpeg_command(inputs, _simple_recipe(), tmp_path / "out.mp3")
    # 3 inputs → 3 "-i" flags
    assert cmd.count("-i") == 3
    assert cmd[0] == "ffmpeg"


def test_build_ffmpeg_command_includes_concat_and_loudnorm(tmp_path: Path) -> None:
    inputs = [tmp_path / "a.mp3", tmp_path / "b.mp3", tmp_path / "a.mp3"]
    recipe = Recipe(
        slots=[RecipeSlot("a"), RecipeSlot("b"), RecipeSlot("a")],
        target_lufs=-14.0,
    )
    cmd = build_ffmpeg_command(inputs, recipe, tmp_path / "out.mp3")
    filter_idx = cmd.index("-filter_complex") + 1
    filter_graph = cmd[filter_idx]
    assert "concat=n=3:v=0:a=1" in filter_graph
    assert "loudnorm=I=-14.0" in filter_graph
    # Per-stream normalization is present for each input
    for i in range(3):
        assert f"[{i}:a]aresample=44100" in filter_graph


def test_build_ffmpeg_command_passes_recipe_bitrate_and_sample_rate(
    tmp_path: Path,
) -> None:
    inputs = [tmp_path / "a.mp3"]
    recipe = Recipe(
        slots=[RecipeSlot("a")], output_bitrate="256k", output_sample_rate=48_000,
    )
    cmd = build_ffmpeg_command(inputs, recipe, tmp_path / "out.mp3")
    assert "-b:a" in cmd
    assert cmd[cmd.index("-b:a") + 1] == "256k"
    assert "-ar" in cmd
    assert cmd[cmd.index("-ar") + 1] == "48000"


def test_build_ffmpeg_command_rejects_zero_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="zero inputs"):
        build_ffmpeg_command([], _simple_recipe(), tmp_path / "out.mp3")


def test_build_ffmpeg_command_injects_fade_for_slots_with_fade_out(
    tmp_path: Path,
) -> None:
    recipe = Recipe(slots=[
        RecipeSlot(kind="a"),
        RecipeSlot(
            kind="b",
            fade_out_start_seconds=20.0,
            fade_out_duration_seconds=2.0,
        ),
        RecipeSlot(kind="a"),
    ])
    inputs = [tmp_path / "a.mp3", tmp_path / "b.mp3", tmp_path / "a.mp3"]
    cmd = build_ffmpeg_command(inputs, recipe, tmp_path / "out.mp3")
    filter_graph = cmd[cmd.index("-filter_complex") + 1]
    # Slot 0 and 2 (no fade) keep just the normalization chain
    assert "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a0]" \
        in filter_graph
    assert "[2:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a2]" \
        in filter_graph
    # Slot 1 (intro_music with fade) gets atrim + afade after normalization
    assert "atrim=end=22.0" in filter_graph
    assert "afade=t=out:st=20.0:d=2.0" in filter_graph


def test_recipe_slot_fade_out_end_seconds() -> None:
    plain = RecipeSlot(kind="x")
    assert plain.fade_out_end_seconds is None
    faded = RecipeSlot(
        kind="x", fade_out_start_seconds=20.0, fade_out_duration_seconds=2.5,
    )
    assert faded.fade_out_end_seconds == 22.5


# -- Mixer error handling ---------------------------------------------------

def test_mix_episode_raises_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gkl.podcast.mixer.ffmpeg_available", lambda: False)
    with pytest.raises(MixerError, match="ffmpeg not found"):
        mix_episode(_simple_recipe(), {}, tmp_path / "out.mp3")


def test_mix_episode_surfaces_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    slots = {"a": tmp_path / "a.mp3", "b": tmp_path / "b.mp3"}

    def _fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr="boom",
        )

    monkeypatch.setattr("gkl.podcast.mixer.subprocess.run", _fake_run)
    with pytest.raises(MixerError, match="exit 1"):
        mix_episode(_simple_recipe(), slots, tmp_path / "out.mp3")


# -- Live smoke test --------------------------------------------------------

def _ffprobe_duration(path: Path) -> float:
    """Return the audio duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def test_live_mix_produces_concatenated_output(
    sine_wave_factory, tmp_path: Path,
) -> None:
    """End-to-end: generate 3 short mp3s, mix them, verify the output exists
    with roughly the summed duration."""
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not on PATH")

    a = sine_wave_factory("a", duration_s=1.0, freq=440)
    b = sine_wave_factory("b", duration_s=0.5, freq=660)
    c = sine_wave_factory("c", duration_s=0.75, freq=880)

    recipe = Recipe(
        slots=[RecipeSlot("intro"), RecipeSlot("body"), RecipeSlot("outro")],
    )
    slot_paths = {"intro": a, "body": b, "outro": c}
    out = tmp_path / "episode.mp3"

    mix_episode(recipe, slot_paths, out)

    assert out.exists()
    assert out.stat().st_size > 0
    duration = _ffprobe_duration(out)
    # Sum ≈ 2.25 s; allow generous tolerance for loudnorm / mp3 padding
    assert 2.0 <= duration <= 3.5, f"unexpected mix duration {duration}s"


def test_live_mix_handles_repeated_kind(
    sine_wave_factory, tmp_path: Path,
) -> None:
    """A single asset used twice in the recipe plays twice in the output."""
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not on PATH")

    sting = sine_wave_factory("sting", duration_s=0.5, freq=880)
    body = sine_wave_factory("body", duration_s=1.0, freq=440)

    recipe = Recipe(slots=[
        RecipeSlot("sting"), RecipeSlot("body"), RecipeSlot("sting"),
    ])
    out = tmp_path / "episode.mp3"
    mix_episode(recipe, {"sting": sting, "body": body}, out)

    duration = _ffprobe_duration(out)
    # 0.5 + 1.0 + 0.5 = 2.0s; tolerance as above
    assert 1.75 <= duration <= 2.75


def test_live_mix_applies_fade_out_and_truncates(
    sine_wave_factory, tmp_path: Path,
) -> None:
    """A slot configured with fade_out trims the source down to the fade end.

    Source: 5-second sine wave. Slot: fade out starting at 2s, 1s duration.
    Expected: slot contributes 3 seconds (2s normal + 1s fading) to the mix.
    """
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not on PATH")

    a = sine_wave_factory("a", duration_s=5.0, freq=440)
    b = sine_wave_factory("b", duration_s=0.5, freq=660)

    recipe = Recipe(slots=[
        RecipeSlot(
            kind="a",
            fade_out_start_seconds=2.0,
            fade_out_duration_seconds=1.0,
        ),
        RecipeSlot(kind="b"),
    ])
    out = tmp_path / "faded.mp3"
    mix_episode(recipe, {"a": a, "b": b}, out)

    duration = _ffprobe_duration(out)
    # 3.0s (faded a) + 0.5s (b) = 3.5s, generous tolerance for codec padding
    assert 3.2 <= duration <= 4.0, f"unexpected duration {duration}"


# -- concat_audio_files ------------------------------------------------------

def test_concat_audio_files_rejects_zero_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="zero inputs"):
        concat_audio_files([], tmp_path / "out.mp3")


def test_concat_audio_files_raises_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gkl.podcast.mixer.ffmpeg_available", lambda: False)
    with pytest.raises(MixerError, match="ffmpeg not found"):
        concat_audio_files(
            [tmp_path / "a.mp3"], tmp_path / "out.mp3",
        )


def test_live_concat_produces_summed_duration(
    sine_wave_factory, tmp_path: Path,
) -> None:
    """End-to-end: concat 3 short mp3s with 100ms gaps, verify duration ≈ sum
    of clips + 2×gap."""
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not on PATH")

    a = sine_wave_factory("a", duration_s=0.5, freq=440)
    b = sine_wave_factory("b", duration_s=0.5, freq=660)
    c = sine_wave_factory("c", duration_s=0.5, freq=880)

    out = tmp_path / "concatenated.mp3"
    concat_audio_files([a, b, c], out, gap_seconds=0.1)

    assert out.exists()
    duration = _ffprobe_duration(out)
    # 3 × 0.5 + 2 × 0.1 = 1.7s, with generous mp3/encoder tolerance
    assert 1.4 <= duration <= 2.1


def test_live_concat_with_zero_gap(
    sine_wave_factory, tmp_path: Path,
) -> None:
    """`gap_seconds=0` produces a clean butt-join with no padding."""
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not on PATH")

    a = sine_wave_factory("a", duration_s=0.5, freq=440)
    b = sine_wave_factory("b", duration_s=0.5, freq=660)

    out = tmp_path / "butt_joined.mp3"
    concat_audio_files([a, b], out, gap_seconds=0)

    duration = _ffprobe_duration(out)
    assert 0.8 <= duration <= 1.3
