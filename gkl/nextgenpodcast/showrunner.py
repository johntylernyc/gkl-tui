"""The showrunner stage: plans each episode (rundown) and keeps the show
from repeating itself, and maintains the Prediction Ledger.

The rundown is markdown with bold section headers (**COLD OPEN**,
**LEDGER GRADES**, **ACT 1..N**, **ARGUMENT ACT**, **NEW LEDGER
ENTRIES**, **BITS BUDGET**, **SIGN-OFF**). This module runs the stage
and parses the sections the pipeline needs: grades to apply to show
state, and the variety-history record.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from gkl.nextgenpodcast import SHOWRUNNER_MODEL
from gkl.nextgenpodcast.scriptcraft import run_stage
from gkl.nextgenpodcast.showstate import parse_grades, parse_plants


_SECTION_PAT = re.compile(r"^\*\*([A-Z][A-Z0-9 /-]+)\*\*\s*$")

# CALLER: <name> from <town> | voice: <voice_id> | <persona>
_CALLER_SPEC_PAT = re.compile(
    r"^\s*(?:[-*]\s*)?CALLER:\s*(.+?)\s*\|\s*voice:\s*(\S+)\s*\|\s*(.+?)\s*$",
    re.IGNORECASE,
)


@dataclass
class CallerSpec:
    display: str    # "Donny from Pittsford"
    voice_id: str
    persona: str


def split_rundown_sections(rundown: str) -> dict[str, str]:
    """Split on `**SECTION NAME**` lines. Keys are upper-cased names."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for ln in rundown.splitlines():
        m = _SECTION_PAT.match(ln.strip())
        if m:
            current = m.group(1).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(ln)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


@dataclass
class Rundown:
    text: str
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def cold_open(self) -> str:
        return self.sections.get("COLD OPEN", "")

    @property
    def sign_off(self) -> str:
        return self.sections.get("SIGN-OFF", "")

    @property
    def bits_budget(self) -> str:
        return self.sections.get("BITS BUDGET", "")

    @property
    def argument_act(self) -> str:
        return self.sections.get("ARGUMENT ACT", "")

    @property
    def call_in_section(self) -> str:
        return self.sections.get("CALL-IN", "")

    def caller(self) -> CallerSpec | None:
        """The structured caller line from the CALL-IN section, if any."""
        for ln in self.call_in_section.splitlines():
            m = _CALLER_SPEC_PAT.match(ln)
            if m:
                return CallerSpec(
                    display=m.group(1).strip(),
                    voice_id=m.group(2).strip(),
                    persona=m.group(3).strip(),
                )
        return None

    def grades(self) -> list[tuple[str, str, str]]:
        """(prediction_id, verdict, reason) from LEDGER GRADES."""
        return parse_grades(self.sections.get("LEDGER GRADES", ""))

    def plants(self, speakers: tuple[str, ...]) -> list[tuple[str, str, str]]:
        """(speaker, text, resolves_by) from NEW LEDGER ENTRIES."""
        return parse_plants(
            self.sections.get("NEW LEDGER ENTRIES", ""), speakers,
        )


# ---------- Caller voice pool ----------

# Callers draw from the same account voices the ad library casts from —
# distinct archetypes, none of them a host voice. A new caller voice
# every week plus the phone filter keeps the Lounge Line fresh. The
# studio announcer's voice is reserved (excluded here) so a caller never
# sounds like Sid Vega introducing them.
from gkl.nextgenpodcast.ads import VOICE_POOL as _AD_VOICE_POOL
from gkl.nextgenpodcast.showbible import ANNOUNCER_VOICE_ID

CALLER_VOICE_POOL = [
    (vid, desc) for vid, desc in _AD_VOICE_POOL if vid != ANNOUNCER_VOICE_ID
]


def caller_voices_block() -> str:
    """Prompt-injectable list of caller voices for the showrunner."""
    return "\n".join(f"- {vid}: {desc}" for vid, desc in CALLER_VOICE_POOL)


def recent_caller_voices(episode_records, n: int = 4) -> list[str]:
    """Voice ids used by the last `n` recorded callers."""
    out: list[str] = []
    for record in reversed(list(episode_records)):
        caller = getattr(record, "caller", "")
        m = _CALLER_SPEC_PAT.match(caller)
        if m:
            out.append(m.group(2).strip())
        if len(out) >= n:
            break
    return out


def resolve_caller_voice(
    preferred: str | None, recent: list[str], *, rng: random.Random | None = None,
) -> str:
    """Validate the showrunner's voice pick; fall back to a random fresh
    voice from the pool when the pick is missing, invalid, or recent."""
    pool_ids = [vid for vid, _ in CALLER_VOICE_POOL]
    if preferred in pool_ids and preferred not in recent:
        return preferred
    fresh = [vid for vid in pool_ids if vid not in recent] or pool_ids
    return (rng or random).choice(fresh)


async def run_showrunner(
    segment_artifact: Path,
    tokens: dict[str, str],
    *,
    model: str = SHOWRUNNER_MODEL,
) -> Rundown:
    text = await run_stage(
        segment_artifact, "showrunner", tokens,
        model=model, max_tokens=4096,
    )
    return Rundown(text=text, sections=split_rundown_sections(text))
