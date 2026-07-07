"""Per-league persistent show state: the Prediction Ledger and the
episode-variety history.

Stored at `data/podcast/<league_key>/nextgen/show-state.json`. Everything
the show "remembers" that isn't derivable from a single episode's
artifacts lives here: open predictions with per-host running records, and
which cold opens / sign-offs / bits ran recently (so the showrunner can
avoid repeating them).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Prediction:
    id: str                # e.g. "2026-w14-HAWK-1"
    season: str
    week_made: int
    speaker: str           # cast speaker label
    text: str
    resolves_by: str = ""
    status: str = "open"   # open | correct | wrong | expired
    week_graded: int | None = None
    reason: str = ""


@dataclass
class EpisodeRecord:
    """What an episode did, for the showrunner's variety history."""
    slug: str              # e.g. "2026-w14" or "allstar-<teamkey>"
    segment: str
    week: int
    cold_open: str = ""    # raw COLD OPEN section text from the rundown
    sign_off: str = ""
    bits: str = ""         # raw BITS BUDGET text
    argument_act: str = ""
    caller: str = ""       # Lounge Line caller spec line (name/voice/persona)
    sid_spots: str = ""    # raw SID SPOTS text (stat checks + look-back)


@dataclass
class ShowState:
    predictions: list[Prediction] = field(default_factory=list)
    episodes: list[EpisodeRecord] = field(default_factory=list)

    # ---------- ledger views ----------

    def open_predictions(self, season: str) -> list[Prediction]:
        return [p for p in self.predictions
                if p.status == "open" and p.season == season]

    def records(self, season: str) -> dict[str, tuple[int, int]]:
        """speaker -> (correct, wrong) for the season."""
        out: dict[str, list[int]] = {}
        for p in self.predictions:
            if p.season != season or p.status not in ("correct", "wrong"):
                continue
            wl = out.setdefault(p.speaker, [0, 0])
            wl[0 if p.status == "correct" else 1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}

    def ledger_block(self, season: str) -> str:
        """Prompt-injectable ledger: records + open predictions."""
        lines: list[str] = []
        recs = self.records(season)
        if recs:
            lines.append("Running records (correct-wrong):")
            for speaker, (w, l) in sorted(recs.items()):
                lines.append(f"- {speaker}: {w}-{l}")
        else:
            lines.append("Running records: none yet this season.")
        opens = self.open_predictions(season)
        if opens:
            lines.append("")
            lines.append("Open predictions:")
            for p in opens:
                tail = f" (resolves by: {p.resolves_by})" if p.resolves_by else ""
                lines.append(
                    f"- [{p.id}] Week {p.week_made}, {p.speaker}: {p.text}{tail}"
                )
        else:
            lines.append("")
            lines.append("Open predictions: none.")
        return "\n".join(lines)

    # ---------- variety history ----------

    def history_block(self, n: int = 6) -> str:
        """Prompt-injectable recent-episode history, newest last."""
        recent = self.episodes[-n:]
        if not recent:
            return "(no prior episodes)"
        chunks: list[str] = []
        for e in recent:
            parts = [f"--- {e.slug} ({e.segment}) ---"]
            if e.cold_open:
                parts.append(f"Cold open: {e.cold_open}")
            if e.argument_act:
                parts.append(f"Argument act: {e.argument_act}")
            if e.bits:
                parts.append(f"Bits: {e.bits}")
            if e.sid_spots:
                parts.append(f"Sid spots: {e.sid_spots}")
            if e.caller:
                parts.append(f"Lounge Line caller: {e.caller}")
            if e.sign_off:
                parts.append(f"Sign-off: {e.sign_off}")
            chunks.append("\n".join(parts))
        return "\n\n".join(chunks)

    # ---------- mutation ----------

    def next_prediction_id(self, season: str, week: int, speaker: str) -> str:
        base = f"{season}-w{week:02d}-{speaker}"
        n = 1 + sum(1 for p in self.predictions if p.id.startswith(base))
        return f"{base}-{n}"

    def add_prediction(self, pred: Prediction) -> None:
        self.predictions.append(pred)

    def grade(self, pred_id: str, verdict: str, week: int, reason: str) -> bool:
        """Apply a grade. Returns False if the id isn't an open prediction."""
        if verdict not in ("correct", "wrong"):
            raise ValueError(f"verdict must be correct|wrong, got {verdict!r}")
        for p in self.predictions:
            if p.id == pred_id and p.status == "open":
                p.status = verdict
                p.week_graded = week
                p.reason = reason
                return True
        return False

    def record_episode(self, record: EpisodeRecord) -> None:
        # Re-runs replace the previous record for the same slug.
        self.episodes = [e for e in self.episodes if e.slug != record.slug]
        self.episodes.append(record)


# ---------- persistence ----------

def state_path_for_league(data_root: Path, league_key: str) -> Path:
    return data_root / "podcast" / league_key / "nextgen" / "show-state.json"


def load_show_state(path: Path) -> ShowState:
    if not path.exists():
        return ShowState()
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return ShowState()
    return ShowState(
        predictions=[Prediction(**p) for p in raw.get("predictions", [])],
        episodes=[EpisodeRecord(**e) for e in raw.get("episodes", [])],
    )


def save_show_state(state: ShowState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))


# ---------- structured-line parsing (rundown + takeaways) ----------

# GRADE: <id> | <correct|wrong> | <reason>        (rundown — ids known)
_GRADE_ID_PAT = re.compile(
    r"^\s*(?:[-*]\s*)?GRADE:\s*([^|]+?)\s*\|\s*(correct|wrong)\s*\|\s*(.+?)\s*$",
    re.IGNORECASE,
)
# PLANT: <SPEAKER> | <text> [| resolves-by: <when>]   (rundown + takeaways)
_PLANT_PAT = re.compile(
    r"^\s*(?:[-*]\s*)?PLANT:\s*([A-Z]+)\s*\|\s*(.+?)"
    r"(?:\s*\|\s*resolves-by:\s*(.+?))?\s*$",
    re.IGNORECASE,
)


def parse_grades(text: str) -> list[tuple[str, str, str]]:
    """Extract (prediction_id, verdict, reason) GRADE lines. Lines whose
    id field is 'none' are skipped."""
    out: list[tuple[str, str, str]] = []
    for ln in text.splitlines():
        m = _GRADE_ID_PAT.match(ln)
        if not m:
            continue
        pred_id = m.group(1).strip()
        if pred_id.lower() == "none":
            continue
        out.append((pred_id, m.group(2).lower(), m.group(3).strip()))
    return out


def parse_plants(text: str, valid_speakers: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """Extract (speaker, prediction_text, resolves_by) PLANT lines.
    Unknown speakers are dropped rather than corrupting the ledger."""
    out: list[tuple[str, str, str]] = []
    for ln in text.splitlines():
        m = _PLANT_PAT.match(ln)
        if not m:
            continue
        speaker = m.group(1).upper()
        if speaker not in valid_speakers:
            continue
        out.append((speaker, m.group(2).strip(), (m.group(3) or "").strip()))
    return out
