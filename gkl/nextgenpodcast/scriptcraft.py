"""Script chain machinery: parser, prompt loading, and the staged
Claude calls (draft → fact-check → punch-up → edit → takeaways).

Prompts live in the segment artifacts under docs/nextgenpodcast/segments/
and are extracted with the same section conventions as v1 (`## Stage` /
`### System prompt` / `### User prompt`; no `##`/`###` inside bodies).

The parser is cast-aware (speaker labels come from the Cast, not
hardcoded) and audio-tag-aware: a whitelist of expressive tags is kept
for the v3 dialogue renderer, everything else in brackets is stripped so
a fallback TTS render never speaks bracket junk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from gkl.nextgenpodcast import SCRIPT_MODEL
from gkl.podcast.script_writer import normalize_line_for_tts
from gkl.podcast.skipper_seed import _extract_section, _substitute
from gkl.skipper import load_anthropic_key


# ---------- Audio tags ----------

ALLOWED_TAGS = (
    "laughs", "chuckles", "sighs", "exhales", "gasps",
    "clears throat", "whispers",
)

# The Regression Bell cue. Webb ends his bell line with `[bell]`; the
# parser strips it from the spoken text and flags the turn so the
# renderer dings a real desk bell right after it. Not an ElevenLabs audio
# tag — it never reaches TTS.
BELL_CUE = "bell"

_TAG_PAT = re.compile(r"\[([^\[\]]{1,30})\]")


def _is_bell(token: str) -> bool:
    return token.strip().lower() == BELL_CUE


def has_bell_cue(line: str) -> bool:
    """True if the line carries the `[bell]` Regression Bell cue."""
    return any(_is_bell(m.group(1)) for m in _TAG_PAT.finditer(line))


def sanitize_tags(line: str) -> str:
    """Keep whitelisted audio tags; drop the bell cue and any other
    bracketed token. The bell cue is handled separately (see
    `has_bell_cue`) before this runs, so here it is simply removed."""
    def _keep(m: re.Match[str]) -> str:
        return m.group(0) if m.group(1).strip().lower() in ALLOWED_TAGS else ""
    out = _TAG_PAT.sub(_keep, line)
    return re.sub(r"  +", " ", out).strip()


def strip_tags(line: str) -> str:
    """Remove ALL bracketed tags (for non-expressive per-turn TTS)."""
    out = _TAG_PAT.sub("", line)
    return re.sub(r"  +", " ", out).strip()


# ---------- Script model ----------

# Speaker label for the Lounge Line's fictional listener. Not part of the
# host cast; only valid inside the CALL-IN block.
CALLER = "CALLER"

# Speaker label for the studio announcer (Sid Vega). Not a host: valid
# only in the INTRO, BUMPER, and CALL-IN blocks, never inside an act and
# never in the sign-off.
ANNOUNCER = "ANNOUNCER"


@dataclass(frozen=True)
class DialogueTurn:
    speaker: str
    line: str
    # True on Webb's Regression Bell turn — the renderer dings a bell
    # right after this clip. Set by the parser from the `[bell]` cue.
    bell_after: bool = False


@dataclass
class Act:
    number: int
    turns: list[DialogueTurn]


@dataclass
class Script:
    acts: list[Act]
    speakers: tuple[str, ...]
    # Announcer-only marquee that opens the episode (empty when the
    # segment has no announcer).
    intro: list[DialogueTurn] = field(default_factory=list)
    # Announcer-only "after the break" teases, one per ad break, in order.
    bumpers: list[list[DialogueTurn]] = field(default_factory=list)
    # The Lounge Line call-in block (empty when the segment has none).
    # Emitted between act `call_in_after` and the next act.
    call_in: list[DialogueTurn] = field(default_factory=list)
    call_in_after: int = 2

    def _all_turns(self) -> list[DialogueTurn]:
        turns = list(self.intro)
        for a in self.acts:
            turns.extend(a.turns)
        for b in self.bumpers:
            turns.extend(b)
        turns.extend(self.call_in)
        return turns

    def total_turns(self) -> int:
        return len(self._all_turns())

    def total_words(self) -> int:
        return sum(len(t.line.split()) for t in self._all_turns())

    @staticmethod
    def _fmt(t: DialogueTurn) -> str:
        # Re-emit the [bell] cue so the round-trip is lossless and every
        # downstream stage still sees where the bell rings.
        suffix = " [bell]" if t.bell_after else ""
        return f"{t.speaker}: {t.line}{suffix}"

    def as_markdown(self) -> str:
        parts: list[str] = []
        if self.intro:
            parts.append("INTRO")
            parts.extend(self._fmt(t) for t in self.intro)
            parts.append("")
        for act in self.acts:
            parts.append(f"ACT {act.number}")
            parts.extend(self._fmt(t) for t in act.turns)
            parts.append("")
            if self.call_in and act.number == self.call_in_after:
                parts.append("CALL-IN")
                parts.extend(self._fmt(t) for t in self.call_in)
                parts.append("")
            # A bumper precedes each ad break; breaks follow every act but
            # the last, after that act's call-in (if any).
            bumper_i = act.number - 1
            if bumper_i < len(self.bumpers):
                parts.append(f"BUMPER {act.number}")
                parts.extend(self._fmt(t) for t in self.bumpers[bumper_i])
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def map_lines(self, fn) -> "Script":
        def _map(turns: list[DialogueTurn]) -> list[DialogueTurn]:
            return [
                DialogueTurn(speaker=t.speaker, line=fn(t.line),
                             bell_after=t.bell_after)
                for t in turns
            ]
        return Script(
            acts=[Act(number=a.number, turns=_map(a.turns)) for a in self.acts],
            speakers=self.speakers,
            intro=_map(self.intro),
            bumpers=[_map(b) for b in self.bumpers],
            call_in=_map(self.call_in),
            call_in_after=self.call_in_after,
        )


_ACT_HEADER_PAT = re.compile(r"^ACT\s+(\d+)\s*$", re.IGNORECASE)
_CALL_IN_HEADER_PAT = re.compile(r"^CALL[- ]IN\s*$", re.IGNORECASE)
_INTRO_HEADER_PAT = re.compile(r"^INTRO\s*$", re.IGNORECASE)
_BUMPER_HEADER_PAT = re.compile(r"^BUMPER\s+(\d+)\s*$", re.IGNORECASE)


def parse_script(
    raw: str,
    speakers: tuple[str, ...],
    *,
    expected_acts: int = 3,
    allow_call_in: bool = False,
    has_announcer: bool = False,
    expected_bumpers: int = 0,
    announcer_in_acts: bool = False,
) -> Script:
    """Parse `INTRO` / `ACT N` / `BUMPER N` / `CALL-IN` + `<SPEAKER>:`
    lines into a Script.

    Tolerates preamble junk before the first block. Sanitizes audio tags
    on every line and lifts the `[bell]` Regression Bell cue onto the
    turn. Fails loudly on missing/misordered acts, unknown or
    out-of-place speakers, empty lines, or dialogue outside a block.

    With `allow_call_in`, a single CALL-IN block is REQUIRED (the segment
    promises listeners a caller), with at least one CALLER turn and one
    host turn; CALLER lines may not appear elsewhere.

    With `has_announcer`, an INTRO block (announcer-only) and exactly
    `expected_bumpers` `BUMPER N` blocks (announcer-only) are REQUIRED,
    the announcer may also speak inside CALL-IN (introducing the caller),
    and ANNOUNCER lines may not appear inside an act. Without it, the
    announcer speaker is rejected everywhere.

    With `announcer_in_acts` (requires `has_announcer`), ANNOUNCER turns
    are additionally allowed inside acts — the rundown-scripted stat
    checks and look-back spots. Every act must still END on a host: the
    announcer never carries an act out to a break or the sign-off.
    """
    host_speakers = set(speakers)
    valid_speakers = set(speakers) | {CALLER}
    if has_announcer:
        valid_speakers.add(ANNOUNCER)
    turn_pat = re.compile(
        rf"^({'|'.join(re.escape(s) for s in sorted(valid_speakers))})"
        rf"\s*:\s*(.+)$"
    )

    acts: list[Act] = []
    intro: list[DialogueTurn] = []
    bumpers: dict[int, list[DialogueTurn]] = {}
    call_in: list[DialogueTurn] = []
    call_in_after = 0
    current: list[DialogueTurn] | None = None
    current_kind = ""          # "intro" | "act" | "bumper" | "call_in"
    in_script = False
    bell_count = 0

    for ln in (l.rstrip() for l in raw.splitlines()):
        if not ln.strip():
            continue
        if has_announcer and _INTRO_HEADER_PAT.match(ln):
            if intro:
                raise ValueError("multiple INTRO blocks")
            if acts:
                raise ValueError("INTRO must come before ACT 1")
            in_script, current_kind, current = True, "intro", intro
            continue
        header = _ACT_HEADER_PAT.match(ln)
        if header:
            act = Act(number=int(header.group(1)), turns=[])
            acts.append(act)
            in_script, current_kind, current = True, "act", act.turns
            continue
        bumper = _BUMPER_HEADER_PAT.match(ln) if has_announcer else None
        if bumper:
            n = int(bumper.group(1))
            if n in bumpers:
                raise ValueError(f"multiple BUMPER {n} blocks")
            bumpers[n] = []
            in_script, current_kind, current = True, "bumper", bumpers[n]
            continue
        if allow_call_in and _CALL_IN_HEADER_PAT.match(ln):
            if not acts:
                raise ValueError("CALL-IN before any ACT header")
            if call_in:
                raise ValueError("multiple CALL-IN blocks")
            call_in_after = acts[-1].number
            in_script, current_kind, current = True, "call_in", call_in
            continue
        if not in_script:
            continue
        m = turn_pat.match(ln)
        if not m:
            raise ValueError(
                f"script line is not one of {sorted(valid_speakers)} — "
                f"got: {ln!r}"
            )
        speaker, text = m.group(1), m.group(2).strip()
        # Speaker/block placement rules.
        if speaker == CALLER and current_kind != "call_in":
            raise ValueError("CALLER line outside the CALL-IN block")
        announcer_kinds = {"intro", "bumper", "call_in"}
        if announcer_in_acts:
            announcer_kinds.add("act")
        if speaker == ANNOUNCER and current_kind not in announcer_kinds:
            raise ValueError("ANNOUNCER line outside INTRO/BUMPER/CALL-IN")
        if current_kind in ("intro", "bumper") and speaker != ANNOUNCER:
            raise ValueError(
                f"{current_kind.upper()} block is announcer-only — got {speaker}"
            )
        act_speakers = host_speakers | ({ANNOUNCER} if announcer_in_acts else set())
        if current_kind == "act" and speaker not in act_speakers:
            raise ValueError(f"act line must be a host — got {speaker}")
        # The bell cue is only meaningful on a host turn inside an act.
        bell = has_bell_cue(text)
        if bell:
            if current_kind != "act" or speaker not in host_speakers:
                raise ValueError("[bell] cue only allowed on a host act turn")
            bell_count += 1
        line = sanitize_tags(text)
        if not line:
            raise ValueError(f"empty dialogue line after {speaker}:")
        if current is None:
            raise ValueError("dialogue before any block header")
        current.append(DialogueTurn(speaker=speaker, line=line, bell_after=bell))

    if len(acts) != expected_acts:
        raise ValueError(
            f"expected {expected_acts} acts, got {len(acts)}: "
            f"{[a.number for a in acts]}"
        )
    if [a.number for a in acts] != list(range(1, expected_acts + 1)):
        raise ValueError(
            f"acts must be 1..{expected_acts} in order — got "
            f"{[a.number for a in acts]}"
        )
    for a in acts:
        if not a.turns:
            raise ValueError(f"act {a.number} has no dialogue turns")
    if bell_count > 1:
        raise ValueError(f"at most one [bell] cue per episode — got {bell_count}")
    # The episode signs off on the hosts: the last act must end on a host
    # turn (announcer/caller can't appear in an act, so this holds — but
    # assert it so a future format change can't silently regress it).
    if acts[-1].turns[-1].speaker not in host_speakers:
        raise ValueError("the final act must end on a host sign-off")
    # With announcer-in-acts, EVERY act must still hand out on a host —
    # an act that ends on Sid would cut straight to Sid's own bumper.
    if announcer_in_acts:
        for a in acts:
            if a.turns[-1].speaker not in host_speakers:
                raise ValueError(
                    f"act {a.number} must end on a host turn, not the announcer"
                )

    bumper_list: list[list[DialogueTurn]] = []
    if has_announcer:
        if not intro:
            raise ValueError("segment requires an INTRO block; none found")
        if sorted(bumpers) != list(range(1, expected_bumpers + 1)):
            raise ValueError(
                f"expected BUMPER 1..{expected_bumpers}, got "
                f"{sorted(bumpers)}"
            )
        for n in range(1, expected_bumpers + 1):
            if not bumpers[n]:
                raise ValueError(f"BUMPER {n} has no announcer turns")
        bumper_list = [bumpers[n] for n in range(1, expected_bumpers + 1)]

    if allow_call_in:
        if not call_in:
            raise ValueError("segment requires a CALL-IN block; none found")
        if not any(t.speaker == CALLER for t in call_in):
            raise ValueError("CALL-IN block has no CALLER turn")
        if not any(t.speaker in host_speakers for t in call_in):
            raise ValueError("CALL-IN block has no host turn")
        if has_announcer and not any(t.speaker == ANNOUNCER for t in call_in):
            raise ValueError("CALL-IN block has no ANNOUNCER caller intro")

    return Script(
        acts=acts, speakers=speakers,
        intro=intro, bumpers=bumper_list,
        call_in=call_in, call_in_after=call_in_after or 2,
    )


_STACKED_BANG_PAT = re.compile(r"!{2,}")


def _tame_exclamations(line: str) -> str:
    """Collapse stacked exclamation marks — "!!" reads as screaming to the
    TTS voice, and one bang carries the excitement fine."""
    return _STACKED_BANG_PAT.sub("!", line)


def normalize_script_for_tts(script: Script) -> Script:
    """v1's deterministic pronunciation safety net, applied per line.
    Audio tags contain no stat abbreviations, so they pass through."""
    return script.map_lines(
        lambda line: _tame_exclamations(normalize_line_for_tts(line))
    )


# ---------- Prompt loading + the Claude call ----------

@dataclass
class StagePrompt:
    system: str
    user: str


# (parent heading, sub headings) per stage — shared across segments.
STAGE_HEADINGS = {
    "seed": ("Skipper seed (stage 1)", "System addendum", "User prompt"),
    "showrunner": ("Showrunner (stage 2)", "System prompt", "User prompt"),
    "draft": ("Script draft (stage 3a)", "System prompt", "User prompt"),
    "fact_check": ("Fact checker (stage 3b)", "System prompt", "User prompt"),
    "punch_up": ("Punch-up (stage 3c)", "System prompt", "User prompt"),
    "edit": ("Production editor (stage 3d)", "System prompt", "User prompt"),
    "takeaways": ("Takeaways generator (stage 3e)", "System prompt", "User prompt"),
}


def load_stage_prompt(segment_artifact: Path, stage: str) -> StagePrompt:
    parent, sys_h, user_h = STAGE_HEADINGS[stage]
    md = segment_artifact.read_text()
    return StagePrompt(
        system=_extract_section(md, parent, sys_h),
        user=_extract_section(md, parent, user_h),
    )


async def call_claude(
    system: str, user: str, *, model: str = SCRIPT_MODEL,
    max_tokens: int = 8192,
) -> str:
    """Single-shot Claude call; returns concatenated text."""
    api_key = load_anthropic_key()
    if not api_key:
        raise ValueError("No Anthropic API key configured")
    # Generous retries: the pipeline burst-sends several large calls and
    # needs to ride out per-minute token windows (same rationale as v1).
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=8)
    response = await client.messages.create(
        model=model, max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in response.content if b.type == "text"]
    if not parts:
        raise RuntimeError("model returned no text content")
    return "\n".join(parts).strip()


async def run_stage(
    segment_artifact: Path,
    stage: str,
    tokens: dict[str, str],
    *,
    model: str = SCRIPT_MODEL,
    max_tokens: int = 8192,
) -> str:
    """Load a stage's prompts, substitute tokens into BOTH system and
    user prompts, and run the call. Unknown `{token}`s raise KeyError —
    fail at generation time, not on air."""
    prompt = load_stage_prompt(segment_artifact, stage)
    return await call_claude(
        _substitute(prompt.system, tokens),
        _substitute(prompt.user, tokens),
        model=model, max_tokens=max_tokens,
    )
