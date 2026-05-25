"""Generic podcast recipe types.

A `Recipe` declares the ordered timeline of an episode — the slots that play
back-to-back, the final loudness target, and the output bitrate. Each slot
has a `kind` that the caller maps to a specific file path at mix time. The
same kind may appear multiple times in a recipe (e.g., `ad_break_stinger`
plays twice in the Weekly Recap), which simply means that asset plays twice.

Segment-specific recipes live next to the segment config — see
`gkl/podcast/segments/weekly_recap.py::WEEKLY_RECAP_RECIPE`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecipeSlot:
    """One position in the episode timeline.

    `kind` names the asset the slot references — at mix time the caller
    supplies a `{kind: Path}` mapping. Multiple slots may share a kind when
    the same asset plays more than once.

    Optional per-slot fade-out: if `fade_out_start_seconds` is set, the slot's
    audio is trimmed to `fade_out_start_seconds + fade_out_duration_seconds`
    and a linear fade is applied across that final window. Useful for music
    beds that are longer than we want them to play before a host comes in.
    """
    kind: str
    fade_out_start_seconds: float | None = None
    fade_out_duration_seconds: float = 2.0

    @property
    def fade_out_end_seconds(self) -> float | None:
        if self.fade_out_start_seconds is None:
            return None
        return self.fade_out_start_seconds + self.fade_out_duration_seconds


@dataclass(frozen=True)
class Recipe:
    """Ordered list of slots plus mix-wide output parameters."""
    slots: list[RecipeSlot]
    target_lufs: float = -16.0
    true_peak_db: float = -1.5
    loudness_range: float = 11.0
    output_bitrate: str = "192k"
    output_sample_rate: int = 44100

    @property
    def kinds(self) -> set[str]:
        """Distinct slot kinds referenced by the recipe."""
        return {s.kind for s in self.slots}
