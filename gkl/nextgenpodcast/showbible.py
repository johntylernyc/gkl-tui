"""Show bible loader + cast definition.

The show bible (docs/nextgenpodcast/show-bible.md) is the source of truth
for who the hosts are and how episodes vary. This module loads it and
exposes the pieces the prompts need. A league can override the bible file
wholesale (multi-tenant future); the default cast ships here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from gkl.podcast.assets import DEFAULT_TTS_VOICE_SETTINGS
# Reuse the committed host voices from the v1 segment config. v1 is
# imported, never modified.
from gkl.podcast.segments.weekly_recap import GUEST_VOICE_ID, HOST_VOICE_ID


# Sid Vega, the Lounge's booth announcer. A distinct account voice —
# smooth, calm authority — reserved for the studio-announcer role and
# kept out of the caller/ad pools so it never doubles as someone else.
ANNOUNCER_VOICE_ID = "cjVigY5qzO86Huf0OWal"

# Every voice that belongs to a recurring on-air character. These are
# UNIQUE to the cast: no ad spot and no Lounge Line caller may ever use
# one — a listener hearing Bat Boy pitch gold coins or Hawk sell injury
# law breaks the room. Ads and callers cast from the remaining pool.
CAST_VOICE_IDS = frozenset({HOST_VOICE_ID, GUEST_VOICE_ID, ANNOUNCER_VOICE_ID})


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_SHOW_BIBLE = _PROJECT_ROOT / "docs" / "nextgenpodcast" / "show-bible.md"


@dataclass(frozen=True)
class CastMember:
    speaker: str      # script label, e.g. "HAWK"
    full_name: str
    voice_id: str
    # Per-voice playback speed for the per-turn TTS render (ElevenLabs
    # `voice_settings.speed`, 0.7–1.2; the v2 model honors it). 1.0 is
    # normal; Webb sits a hair faster for a crisper delivery.
    speed: float = 1.0
    # Optional per-voice stability override (0.0–1.0). Higher = steadier,
    # less volume/emotion swing between takes. None uses the podcast
    # default. Hawk runs higher: his voice kept tipping excitement into
    # outright yelling at the default setting.
    stability: float | None = None


@dataclass(frozen=True)
class Cast:
    """The show cast: script speaker labels mapped to voices. Two hosts
    plus the studio announcer (Sid Vega), who reads the marquee, teases
    the breaks, and works the phones — but never signs off."""
    lead: CastMember
    analyst: CastMember
    announcer: CastMember

    def speakers(self) -> tuple[str, str]:
        """The two HOSTS. The announcer is deliberately excluded — host
        speakers drive act parsing, balance, and continuity; the
        announcer is a structural voice, not a debating host."""
        return (self.lead.speaker, self.analyst.speaker)

    def _member(self, speaker: str) -> CastMember:
        for m in (self.lead, self.analyst, self.announcer):
            if speaker == m.speaker:
                return m
        raise ValueError(f"unknown speaker: {speaker!r}")

    def voice_for(self, speaker: str) -> str:
        return self._member(speaker).voice_id

    def voice_settings_for(self, speaker: str) -> dict:
        """Per-turn TTS voice settings for this speaker: the podcast
        defaults plus the member's per-voice speed and any stability
        override."""
        m = self._member(speaker)
        settings = {**DEFAULT_TTS_VOICE_SETTINGS, "speed": m.speed}
        if m.stability is not None:
            settings["stability"] = m.stability
        return settings


DEFAULT_CAST = Cast(
    lead=CastMember(speaker="HAWK", full_name='Dale "Hawk" Hawkins',
                    voice_id=HOST_VOICE_ID, stability=0.75),
    analyst=CastMember(speaker="WEBB", full_name='Marcus "The Professor" Webb',
                       voice_id=GUEST_VOICE_ID, speed=1.05),
    announcer=CastMember(speaker="ANNOUNCER", full_name="Sid Vega",
                         voice_id=ANNOUNCER_VOICE_ID),
)


@dataclass(frozen=True)
class LeagueShowConfig:
    """Per-league knobs. Defaults match the GKL; a future multi-tenant
    service constructs one of these per league."""
    playoff_spots: int = 8
    show_bible_path: Path = DEFAULT_SHOW_BIBLE
    cast: Cast = field(default=DEFAULT_CAST)


def extract_bible_section(markdown: str, heading: str) -> str:
    """Return the body under `## <heading>` up to the next `## `.

    H3 subsections are included in the body. Raises KeyError if missing.
    """
    lines = markdown.splitlines()
    pat = re.compile(rf"^##\s+{re.escape(heading)}\s*$")
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        raise KeyError(f"Section '## {heading}' not found in show bible")
    body: list[str] = []
    for ln in lines[start + 1:]:
        if re.match(r"^##\s+\S", ln):
            break
        body.append(ln)
    while body and not body[0].strip():
        body.pop(0)
    while body and (not body[-1].strip() or re.fullmatch(r"[-*_]{3,}", body[-1].strip())):
        body.pop()
    return "\n".join(body)


def load_show_bible(path: Path | None = None) -> str:
    """The full prompt-injectable bible: identity + hosts + sound +
    playbook + editorial rules, concatenated in reading order."""
    md = (path or DEFAULT_SHOW_BIBLE).read_text()
    sections = [
        ("Show identity", extract_bible_section(md, "Show identity")),
        ("Hosts", extract_bible_section(md, "Hosts")),
        ("Sound and delivery", extract_bible_section(md, "Sound and delivery")),
        ("Variety playbook", extract_bible_section(md, "Variety playbook")),
        ("Editorial rules (always on)",
         extract_bible_section(md, "Editorial rules (always on)")),
    ]
    return "\n\n".join(f"**{title}**\n\n{body}" for title, body in sections)
