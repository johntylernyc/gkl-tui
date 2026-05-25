"""Phase 3 — three-step dialogue generation (Opus 4.6).

The script for each episode runs through three sequential Opus 4.6 passes:

    3a. draft      — opinion-show-style dialogue seeded from Phase 2 topics
    3b. fact check — verify every stat claim against the data pack, correct
                     wrong values, strip unverifiable claims
    3c. edit       — narrative flow, kill cross-act repetition, break up
                     monologues, sharpen weak takes

Each step's output is a complete `Script` in the same HOST/GUEST format.
Intermediate artifacts (`draft-script.md`, `fact-checked-script.md`,
`script.md`) are kept on disk by the pipeline for debugging + prompt tuning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import anthropic

from gkl.podcast.datapack import DataPack
from gkl.podcast.skipper_seed import (
    DEFAULT_SEGMENT_ARTIFACT, _extract_section, _substitute,
)
from gkl.podcast.source_builder import (
    format_free_agents, format_h2h_records, format_power_rankings,
    format_scoreboard, format_standings, format_target_week_player_stats,
    format_target_week_transactions,
)
from gkl.skipper import load_anthropic_key


SCRIPT_WRITER_MODEL = "claude-opus-4-6"


# ---------- Parsed-script types ----------

@dataclass(frozen=True)
class DialogueTurn:
    speaker: str  # "HOST" or "GUEST"
    line: str


@dataclass
class Act:
    number: int  # 1, 2, or 3
    turns: list[DialogueTurn]


@dataclass
class Script:
    acts: list[Act]

    def total_turns(self) -> int:
        return sum(len(a.turns) for a in self.acts)

    def as_markdown(self) -> str:
        """Render the script in the same format the LLM produced."""
        parts: list[str] = []
        for act in self.acts:
            parts.append(f"ACT {act.number}")
            for turn in act.turns:
                parts.append(f"{turn.speaker}: {turn.line}")
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"


@dataclass
class ScriptVersions:
    """The three intermediate outputs of Phase 3."""
    draft: Script
    fact_checked: Script
    final: Script


# ---------- Parser ----------

_ACT_HEADER_PAT = re.compile(r"^ACT\s+([123])\s*$", re.IGNORECASE)
_TURN_PAT = re.compile(r"^(HOST|GUEST)\s*:\s*(.+)$")
_VALID_SPEAKERS = {"HOST", "GUEST"}


def parse_script(raw: str) -> Script:
    """Parse `ACT N` + `HOST:` / `GUEST:` lines into a Script.

    Strips leading/trailing blank lines and any preamble before the first
    `ACT 1`. Raises ValueError if fewer than three acts are found or if the
    acts aren't 1-2-3 in order.
    """
    lines = [ln.rstrip() for ln in raw.splitlines()]
    acts: list[Act] = []
    current: Act | None = None
    in_script = False

    for ln in lines:
        if not ln.strip():
            continue
        header = _ACT_HEADER_PAT.match(ln)
        if header:
            in_script = True
            act_num = int(header.group(1))
            current = Act(number=act_num, turns=[])
            acts.append(current)
            continue
        if not in_script:
            # Tolerate junk before the first ACT header
            continue
        turn = _TURN_PAT.match(ln)
        if not turn:
            raise ValueError(
                f"script line is not `HOST:` or `GUEST:` — got: {ln!r}"
            )
        speaker = turn.group(1).upper()
        line = turn.group(2).strip()
        if speaker not in _VALID_SPEAKERS:
            raise ValueError(f"unknown speaker {speaker!r}")
        if not line:
            raise ValueError(f"empty dialogue line after {speaker}:")
        if current is None:
            raise ValueError(
                "dialogue line appeared before any `ACT N` header"
            )
        current.turns.append(DialogueTurn(speaker=speaker, line=line))

    if len(acts) != 3:
        raise ValueError(
            f"expected 3 acts, got {len(acts)} — act numbers: "
            f"{[a.number for a in acts]}"
        )
    if [a.number for a in acts] != [1, 2, 3]:
        raise ValueError(
            f"acts must appear in order 1, 2, 3 — got "
            f"{[a.number for a in acts]}"
        )
    for a in acts:
        if not a.turns:
            raise ValueError(f"act {a.number} has no dialogue turns")
    return Script(acts=acts)


# ---------- Data summary (used across all three steps) ----------

def build_data_summary(
    datapack: DataPack, *, include_player_stats: bool = False,
) -> str:
    """Compact natural-language summary of the data pack for the LLM.

    `include_player_stats=True` appends the comprehensive per-player
    week-by-week stat table — required ground truth for the fact-checker,
    but very large (one line per rostered player × 18 teams ≈ 12k+ tokens).
    The draft writer omits it to keep its prompt under the per-minute
    Opus rate limit and grounds player claims via the suggested-topics
    narrative instead. Hallucinations the draft writer introduces are
    caught one step downstream by the fact-checker, which DOES carry the
    full table.
    """
    week = datapack.meta.target_week
    base = (
        f"Scoreboard for Week {week}:\n"
        f"{format_scoreboard(datapack.target_week_matchups)}\n\n"
        f"Current roto standings:\n"
        f"{format_standings(datapack.roto_standings)}\n\n"
        f"Head-to-head records through Week {week}:\n"
        f"{format_h2h_records(datapack.h2h_records)}\n\n"
        f"Power rankings (hypothetical all-play record):\n"
        f"{format_power_rankings(datapack.power_rankings)}\n\n"
        f"Transactions during Week {week}:\n"
        f"{format_target_week_transactions(datapack)}\n\n"
        "Top free agents available right now "
        "(verify any FA pickup recommendation against this list):\n"
        f"{format_free_agents(datapack)}"
    )
    if include_player_stats:
        base += (
            f"\n\nPer-player performance for Week {week} "
            "(USE THIS to verify any individual player-stat claim — every "
            "number cited about a player MUST match what's here):\n"
            f"{format_target_week_player_stats(datapack)}"
        )
    return base


# ---------- Prompt loading ----------

@dataclass
class StepPrompt:
    system: str
    user: str


def _load_step_prompt(
    segment_artifact: Path, parent_heading: str,
) -> StepPrompt:
    md = segment_artifact.read_text()
    return StepPrompt(
        system=_extract_section(md, parent_heading, "System prompt"),
        user=_extract_section(md, parent_heading, "User prompt"),
    )


def load_draft_prompt(segment_artifact: Path) -> StepPrompt:
    return _load_step_prompt(segment_artifact, "Script draft (Phase 3a)")


def load_fact_check_prompt(segment_artifact: Path) -> StepPrompt:
    return _load_step_prompt(segment_artifact, "Fact checker (Phase 3b)")


def load_editor_prompt(segment_artifact: Path) -> StepPrompt:
    return _load_step_prompt(segment_artifact, "Production editor (Phase 3c)")


# ---------- Shared Claude call ----------

async def _call_opus(
    system: str, user: str, *, model: str, max_tokens: int = 8192,
) -> str:
    """Single-shot Claude call; returns the concatenated text response."""
    api_key = load_anthropic_key()
    if not api_key:
        raise ValueError("No Anthropic API key configured")
    # max_retries=8 lets the SDK back off through the org's per-minute token
    # window if the pipeline burst-sends multiple Opus calls in succession.
    # Default of 2 exhausts in ~6s — not nearly enough for a 60s window.
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=8)
    response = await client.messages.create(
        model=model, max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text_parts = [b.text for b in response.content if b.type == "text"]
    if not text_parts:
        raise RuntimeError("Opus returned no text content")
    return "\n".join(text_parts).strip()


# ---------- Step 3a: draft ----------

async def write_draft_script(
    datapack: DataPack,
    suggested_topics_md: str,
    *,
    segment_artifact: Path | None = None,
    model: str = SCRIPT_WRITER_MODEL,
) -> Script:
    """Phase 3a — produce the first-draft op-ed dialogue."""
    prompt = load_draft_prompt(segment_artifact or DEFAULT_SEGMENT_ARTIFACT)
    meta = datapack.meta
    user_prompt = _substitute(prompt.user, {
        "league_name": meta.league_name,
        "season": meta.season,
        "target_week": str(meta.target_week),
        "week_start": meta.week_start,
        "week_end": meta.week_end,
        "suggested_topics": suggested_topics_md,
        # Draft writer skips the per-player table — it's huge, and the
        # fact-checker downstream catches any per-player hallucinations.
        "data_summary": build_data_summary(datapack, include_player_stats=False),
    })
    raw = await _call_opus(prompt.system, user_prompt, model=model)
    return parse_script(raw)


# ---------- Step 3b: fact check ----------

async def fact_check_script(
    draft: Script,
    datapack: DataPack,
    *,
    segment_artifact: Path | None = None,
    model: str = SCRIPT_WRITER_MODEL,
) -> Script:
    """Phase 3b — validate every stat claim; correct or strip where wrong.

    Receives the comprehensive per-player weekly stat table — every
    individual player claim in the draft is verified against it.
    """
    prompt = load_fact_check_prompt(segment_artifact or DEFAULT_SEGMENT_ARTIFACT)
    meta = datapack.meta
    user_prompt = _substitute(prompt.user, {
        "league_name": meta.league_name,
        "target_week": str(meta.target_week),
        "data_summary": build_data_summary(datapack, include_player_stats=True),
        "draft_script": draft.as_markdown(),
    })
    raw = await _call_opus(prompt.system, user_prompt, model=model)
    return parse_script(raw)


# ---------- Step 3c: edit ----------

async def edit_script(
    fact_checked: Script,
    datapack: DataPack,
    *,
    segment_artifact: Path | None = None,
    model: str = SCRIPT_WRITER_MODEL,
) -> Script:
    """Phase 3c — polish narrative flow, reduce repetition, sharpen takes."""
    prompt = load_editor_prompt(segment_artifact or DEFAULT_SEGMENT_ARTIFACT)
    meta = datapack.meta
    user_prompt = _substitute(prompt.user, {
        "league_name": meta.league_name,
        "target_week": str(meta.target_week),
        "fact_checked_script": fact_checked.as_markdown(),
    })
    raw = await _call_opus(prompt.system, user_prompt, model=model)
    return parse_script(raw)


# ---------- Number-to-spoken-form helpers (baseball broadcast style) ----------

_DIGIT_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}
_TEEN_WORDS = {
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
    18: "eighteen", 19: "nineteen",
}
_TENS_WORDS = {
    2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
    6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety",
}


def _spell_two_digit(n: int) -> str:
    """0-99 → spoken English."""
    if n < 10:
        return _DIGIT_WORDS[str(n)]
    if n < 20:
        return _TEEN_WORDS[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _TENS_WORDS[tens]
    return f"{_TENS_WORDS[tens]}-{_DIGIT_WORDS[str(ones)]}"


def _spell_baseball_three_digit(n: int) -> str:
    """Baseball-broadcast spoken form for a 3-digit batting-average style number.

    Examples (think AVG/OBP/SLG):
    .000 → "zero"
    .023 → "twenty-three"           (drops leading zero)
    .100 → "one hundred"
    .105 → "one oh five"
    .150 → "one fifty"
    .250 → "two fifty"
    .316 → "three sixteen"
    .563 → "five sixty-three"
    .500 → "five hundred"
    .999 → "nine ninety-nine"
    """
    if n == 0:
        return "zero"
    if n < 100:
        return _spell_two_digit(n)
    first, rest = divmod(n, 100)
    first_word = _DIGIT_WORDS[str(first)]
    if rest == 0:
        return f"{first_word} hundred"
    if rest < 10:
        return f"{first_word} oh {_DIGIT_WORDS[str(rest)]}"
    return f"{first_word} {_spell_two_digit(rest)}"


def _spell_rate_stat(integer: int, decimal_2: int) -> str:
    """X.XX rate stat (ERA, WHIP) in baseball-broadcast spoken form.

    2.85 → "two eighty-five"
    1.21 → "one twenty-one"
    1.00 → "one flat"
    3.00 → "three flat"
    0.95 → "zero ninety-five"
    """
    int_word = _DIGIT_WORDS[str(integer)] if 0 <= integer <= 9 else str(integer)
    if decimal_2 == 0:
        return f"{int_word} flat"
    return f"{int_word} {_spell_two_digit(decimal_2)}"


# ---------- TTS-readability normalization ----------

# Regex → replacement pairs. Each pattern uses `\b` word boundaries so we
# only match standalone abbreviations, not substrings of longer words.
# Order matters for overlapping patterns (longer/more-specific first).
#
# We deliberately DO NOT expand: ERA, RBI, MLB, OPS, AVG, HR, SB, SP, RP
# — these are commonly said letter-by-letter (or as a word) by real
# broadcasters and ElevenLabs handles them naturally. Left here as a
# breadcrumb so future additions don't accidentally over-normalize.
_TTS_NORMALIZATIONS: list[tuple[str, str]] = [
    # Expected / advanced stats (less common → must spell out for listeners)
    (r"\bxwOBA\b", "expected weighted on base average"),
    (r"\bxBA\b", "expected batting average"),
    (r"\bxSLG\b", "expected slugging percentage"),
    (r"\bxERA\b", "expected E R A"),
    (r"\bxFIP\b", "expected F I P"),
    (r"\bwRC\+", "weighted runs created plus"),
    (r"\bwOBA\b", "weighted on base average"),
    (r"\bSIERA\b", "siera"),
    (r"\bBABIP\b", "babip"),
    (r"\bFIP\b", "F I P"),
    (r"\bISO\b", "isolated power"),
    # Rate stats with slashes/percents. Trailing `\b` is omitted on patterns
    # that end in non-word characters (%, /, +) because `\b` requires a
    # transition between word and non-word, which can't happen with two
    # non-word chars adjacent (e.g. "BB%" followed by a space).
    (r"\bHR/9\b", "home runs per nine"),
    (r"\bK/9\b", "strikeouts per nine"),
    (r"\bBB/9\b", "walks per nine"),
    (r"\bH/9\b", "hits per nine"),
    (r"\bHR/FB\b", "home run to fly ball rate"),
    (r"\bK%", "strikeout rate"),
    (r"\bBB%", "walk rate"),
    # Trailing-window shorthand
    (r"\bL30\b", "last thirty days"),
    (r"\bL14\b", "last fourteen days"),
    (r"\bL7\b", "last seven days"),
    # Roster slots + availability tags
    (r"\bBN\b", "bench"),
    (r"\bIL\b", "injured list"),
    (r"\bNA\b", "not active"),
    # Positions — prompt asks LLM to spell these out; normalizer catches stragglers
    (r"\bSP\b", "starting pitcher"),
    (r"\bRP\b", "relief pitcher"),
    # Stat terms that benefit from spelling out
    (r"\bOBP\b", "on base percentage"),
    (r"\bSLG\b", "slugging percentage"),
    # H2H is case-insensitive — the LLM occasionally writes 'h2h' lowercase
    (r"\b[Hh]2[Hh]\b", "head to head"),
    (r"\bYTD\b", "year to date"),
    (r"\bPA\b", "plate appearances"),
    (r"\bIP\b", "innings pitched"),
]


def _spell_decimal_stats(line: str) -> str:
    """Convert baseball decimal stats to spoken-form before TTS.

    `.316` and `0.316` → "three sixteen". `2.85` (ERA/WHIP) → "two eighty-five".
    The `.XXX` pattern is processed first so a 3-decimal value isn't
    misclassified as a rate stat. Negative lookbehind/ahead prevents
    matches inside larger numbers (e.g. "1.316" stays untouched, "12345"
    isn't carved up).
    """
    # .XXX or 0.XXX (batting AVG / OBP / SLG)
    line = re.sub(
        r"(?<![\d.])0?\.(\d{3})(?!\d)",
        lambda m: _spell_baseball_three_digit(int(m.group(1))),
        line,
    )
    # X.XX (rate stats: ERA, WHIP). Run AFTER .XXX so a hit on .X... wins first.
    line = re.sub(
        r"(?<![\d.])(\d{1,2})\.(\d{2})(?!\d)",
        lambda m: _spell_rate_stat(int(m.group(1)), int(m.group(2))),
        line,
    )
    return line


def normalize_line_for_tts(line: str) -> str:
    """Apply all TTS normalizations to a single dialogue line."""
    line = _spell_decimal_stats(line)
    for pattern, replacement in _TTS_NORMALIZATIONS:
        line = re.sub(pattern, replacement, line)
    return line


def normalize_script_for_tts(script: Script) -> Script:
    """Return a new Script with every turn's line run through the normalizer.

    Deterministic safety net for the pronunciation prompt. If Opus slips and
    leaves `xBA` or `OBP` in the final script, these get expanded before
    reaching ElevenLabs. Does not touch turn speakers or act structure.
    """
    return Script(acts=[
        Act(
            number=a.number,
            turns=[
                DialogueTurn(
                    speaker=t.speaker,
                    line=normalize_line_for_tts(t.line),
                )
                for t in a.turns
            ],
        )
        for a in script.acts
    ])


# ---------- Orchestrator ----------

async def write_script(
    datapack: DataPack,
    suggested_topics_md: str,
    *,
    segment_artifact: Path | None = None,
    model: str = SCRIPT_WRITER_MODEL,
) -> ScriptVersions:
    """Run all three Phase 3 steps and return every intermediate version.

    Callers (e.g. the pipeline) typically care about `.final`, but we return
    all three so intermediate artifacts can be persisted for debugging.
    """
    draft = await write_draft_script(
        datapack, suggested_topics_md,
        segment_artifact=segment_artifact, model=model,
    )
    fact_checked = await fact_check_script(
        draft, datapack,
        segment_artifact=segment_artifact, model=model,
    )
    final = await edit_script(
        fact_checked, datapack,
        segment_artifact=segment_artifact, model=model,
    )
    return ScriptVersions(draft=draft, fact_checked=fact_checked, final=final)
