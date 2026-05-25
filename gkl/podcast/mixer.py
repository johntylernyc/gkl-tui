"""Phase 6 — ffmpeg-backed episode mixer.

Takes a `Recipe` + a `{kind: Path}` slot mapping and produces a single mp3.
All mixing happens in one `ffmpeg` invocation — concatenate the slots in
order, normalize each input stream's sample rate / channel layout, loudness-
normalize the final output, and encode to mp3 at the recipe's bitrate.

Design notes:
- One subprocess call, no intermediate files. Deterministic and easy to audit.
- Per-stream `aresample` + `aformat` before concat so inputs with different
  sample rates (ElevenLabs mp3s can be 44.1 kHz, locally-generated test
  fixtures might be 48 kHz) still stitch cleanly.
- Per-slot fades are NOT applied in MVP — ElevenLabs output typically has
  clean starts/ends. If listen-testing reveals abrupt transitions, extending
  the filter graph per-slot is a localized change.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gkl.podcast.recipe import Recipe


class MixerError(RuntimeError):
    """Raised when ffmpeg fails or prerequisites are missing."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _resolve_slot_inputs(
    recipe: Recipe, slot_paths: dict[str, Path],
) -> list[Path]:
    """Map each slot in the recipe's timeline to a concrete file path.

    Raises KeyError if a slot kind has no mapping and FileNotFoundError if
    the referenced file does not exist on disk.
    """
    inputs: list[Path] = []
    missing_kinds = recipe.kinds - set(slot_paths.keys())
    if missing_kinds:
        raise KeyError(
            f"slot_paths is missing kinds: {sorted(missing_kinds)}"
        )
    for slot in recipe.slots:
        path = slot_paths[slot.kind]
        if not path.exists():
            raise FileNotFoundError(
                f"slot '{slot.kind}' path does not exist: {path}"
            )
        inputs.append(path)
    return inputs


def build_ffmpeg_command(
    inputs: list[Path], recipe: Recipe, output_path: Path,
) -> list[str]:
    """Build the argv for a single ffmpeg invocation that mixes the episode."""
    if not inputs:
        raise ValueError("cannot build ffmpeg command with zero inputs")

    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for path in inputs:
        cmd.extend(["-i", str(path)])

    # Per-stream normalization: force consistent sample rate + stereo float
    # planar so concat doesn't reject mismatched inputs. Also apply per-slot
    # fade-out + length trim if the recipe slot configures it.
    normalize_parts: list[str] = []
    for i, slot in enumerate(recipe.slots):
        chain = (
            f"[{i}:a]aresample={recipe.output_sample_rate},"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo"
        )
        if slot.fade_out_start_seconds is not None:
            end = slot.fade_out_end_seconds  # start + duration
            chain += f",atrim=end={end},asetpts=PTS-STARTPTS"
            chain += (
                f",afade=t=out:"
                f"st={slot.fade_out_start_seconds}:"
                f"d={slot.fade_out_duration_seconds}"
            )
        normalize_parts.append(f"{chain}[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(len(inputs)))
    concat_part = f"{labels}concat=n={len(inputs)}:v=0:a=1[concat]"
    loudnorm_part = (
        f"[concat]loudnorm="
        f"I={recipe.target_lufs}:"
        f"TP={recipe.true_peak_db}:"
        f"LRA={recipe.loudness_range}[out]"
    )
    filter_graph = ";".join(normalize_parts + [concat_part, loudnorm_part])

    cmd.extend([
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-b:a", recipe.output_bitrate,
        "-ar", str(recipe.output_sample_rate),
        str(output_path),
    ])
    return cmd


def concat_audio_files(
    inputs: list[Path],
    output: Path,
    *,
    gap_seconds: float = 0.25,
    sample_rate: int = 44100,
    bitrate: str = "192k",
) -> None:
    """Concatenate N audio files into one mp3 with optional silence gaps.

    Used by Phase 4's per-turn TTS renderer to stitch dialogue turns into a
    single act track. Does NOT apply loudness normalization — that's Phase 6's
    job on the full-episode mix. Running `loudnorm` twice alters the audio.

    Between each pair of inputs a short silence (default 250 ms) is padded
    onto the trailing end of all inputs except the last, which makes turns
    feel natural rather than glued together.
    """
    if not inputs:
        raise ValueError("cannot concat zero inputs")
    if not ffmpeg_available():
        raise MixerError(
            "ffmpeg not found on PATH. Install it before rendering "
            "per-act audio."
        )

    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in inputs:
        cmd.extend(["-i", str(p)])

    filter_parts: list[str] = []
    n = len(inputs)
    for i in range(n):
        base = (
            f"[{i}:a]aresample={sample_rate},"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo"
        )
        if i < n - 1 and gap_seconds > 0:
            base += f",apad=pad_dur={gap_seconds}"
        filter_parts.append(f"{base}[t{i}]")
    labels = "".join(f"[t{i}]" for i in range(n))
    filter_parts.append(f"{labels}concat=n={n}:v=0:a=1[out]")
    filter_graph = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        "-ar", str(sample_rate),
        str(output),
    ])

    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MixerError(
            f"ffmpeg concat failed (exit {result.returncode}):\n{result.stderr}"
        )


def mix_episode(
    recipe: Recipe,
    slot_paths: dict[str, Path],
    output_path: Path,
) -> None:
    """Produce the episode mp3 at `output_path`.

    Raises MixerError if ffmpeg is missing or the mix fails.
    """
    if not ffmpeg_available():
        raise MixerError(
            "ffmpeg not found on PATH. Install it before generating an "
            "episode (e.g. `brew install ffmpeg` or your distro's package)."
        )
    inputs = _resolve_slot_inputs(recipe, slot_paths)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_command(inputs, recipe, output_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MixerError(
            f"ffmpeg mix failed (exit {result.returncode}):\n{result.stderr}"
        )
