"""Deterministic scoreline validation for generated scripts.

The LLM stages are told to copy official records verbatim, but a wrong
scoreline (e.g. a matchup recomputed from raw category values as
"ten-seven-one" when Yahoo's official record is 13-4-1) can survive the
fact-check stage — the story spine and the draft corroborate each other.
This module is the code-level backstop: it extracts every spoken record
tuple ("thirteen-four-one", "eleven-seven", "16-0-1") from the final
script and checks it against the datapack's official records. The
pipeline runs one corrective fact-check pass on violations and fails the
run if they persist.

Scope: W-L(-T) record tuples only. Single numbers and spoken decimals
("eight-oh-two", "sixty-nine") are excluded by construction — see the
plausibility guards in `spoken_number_tuples`.
"""

from __future__ import annotations

import re


# ---------- Spoken-number parsing ----------

_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# Words that immediately follow a tuple and mark it as NOT a record:
# prices, rates, and stat readings ("one-fourteen ERA").
_NON_RECORD_FOLLOWERS = {
    "dollar", "dollars", "percent", "era", "whip", "obp", "slg", "avg",
    "average", "slug", "slugging", "ops",
}

_WORD_CHAIN_PAT = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z]+)+\b")
_DIGIT_TUPLE_PAT = re.compile(r"\b(\d{1,2})-(\d{1,2})(?:-(\d{1,2}))?\b")


def _chain_to_numbers(chain: str) -> list[int] | None:
    """Parse a hyphen chain of number words into numbers.

    Returns None when the chain contains a non-number word (so
    "twenty-seven-dollar" and "three-skillet" never look like records).
    "and" is a joiner ("sixteen-and-oh-and-one"); a tens word followed by
    a unit is a single compound number ("sixty-nine" is 69, not (60, 9)).
    """
    parts = [p.lower() for p in chain.split("-") if p.lower() != "and"]
    numbers: list[int] = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in _TENS:
            if i + 1 < len(parts) and parts[i + 1] in _UNITS and _UNITS[parts[i + 1]] < 10:
                numbers.append(_TENS[p] + _UNITS[parts[i + 1]])
                i += 2
            else:
                numbers.append(_TENS[p])
                i += 1
        elif p in _UNITS:
            numbers.append(_UNITS[p])
            i += 1
        else:
            return None
    return numbers


def _plausible_record(nums: list[int], plausible_sums: set[int]) -> bool:
    """Keep only tuples that could be a record in this league.

    3-tuples must sum to a real game length (categories per matchup, or
    opponents in the all-play), which excludes spoken decimals like
    "eight-oh-two" (sums to 10). 2-tuples are a record with the ties
    unsaid, so their sum must not exceed the longest game.
    """
    if len(nums) == 3:
        return sum(nums) in plausible_sums
    if len(nums) == 2:
        return 0 < sum(nums) <= max(plausible_sums, default=0)
    return False


def spoken_number_tuples(
    line: str, plausible_sums: set[int],
) -> list[tuple[int, ...]]:
    """Extract candidate W-L(-T) record tuples from one dialogue line."""
    out: list[tuple[int, ...]] = []

    for m in _WORD_CHAIN_PAT.finditer(line):
        nums = _chain_to_numbers(m.group(0))
        if not nums or not _plausible_record(nums, plausible_sums):
            continue
        follower = re.match(r"\s+([A-Za-z]+)", line[m.end():])
        if follower and follower.group(1).lower() in _NON_RECORD_FOLLOWERS:
            continue
        out.append(tuple(nums))

    for m in _DIGIT_TUPLE_PAT.finditer(line):
        nums = [int(g) for g in m.groups() if g is not None]
        if not _plausible_record(nums, plausible_sums):
            continue
        follower = re.match(r"\s+([A-Za-z]+)", line[m.end():])
        if follower and follower.group(1).lower() in _NON_RECORD_FOLLOWERS:
            continue
        out.append(tuple(nums))

    return out


# ---------- Official records from the datapack ----------

_TRIPLE_KEYS = (
    ("wins", "losses", "ties"),
    ("cat_wins", "cat_losses", "cat_ties"),
    ("hypothetical_wins", "hypothetical_losses", "hypothetical_ties"),
    ("team_a_cat_wins", "team_b_cat_wins", "cat_ties"),
)


def official_record_tuples(pack: dict) -> set[tuple[int, int, int]]:
    """Every official W-L-T record anywhere in the datapack: matchup
    scores, matchup/category season records, all-play power rankings,
    momentum windows, playoff-race entries."""
    found: set[tuple[int, int, int]] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for a, b, c in _TRIPLE_KEYS:
                if a in node and b in node and c in node:
                    try:
                        found.add((int(node[a]), int(node[b]), int(node[c])))
                    except (TypeError, ValueError):
                        pass
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(pack)
    return found


def _matches_official(
    tup: tuple[int, ...], official: set[tuple[int, int, int]],
) -> bool:
    if len(tup) == 3:
        a, b, c = tup
        return (a, b, c) in official or (b, a, c) in official
    a, b = tup
    return any(
        (w, l) in ((a, b), (b, a)) for (w, l, _t) in official
    )


# ---------- Script validation ----------

_STOP_TEAM_WORDS = {
    "the", "of", "is", "my", "me", "can", "do", "4u", "too", "remix",
    "what", "name", "season", "little",
}


def _team_tokens(team_names: list[str]) -> set[str]:
    tokens: set[str] = set()
    for name in team_names:
        for word in re.findall(r"[A-Za-z][A-Za-z'()]+", name):
            w = word.lower().strip("'()")
            if len(w) >= 3 and w not in _STOP_TEAM_WORDS:
                tokens.add(w)
    return tokens


def find_scoreline_violations(
    script_md: str,
    pack: dict,
    *,
    scored_categories: int,
    num_teams: int,
) -> list[str]:
    """Lines whose spoken record tuples match no official record.

    Only lines that also name a team are reported — a record tuple next
    to a team name is almost certainly a matchup score or standings
    record, while tuples elsewhere are too ambiguous to hard-fail on.
    Returns human-readable problem strings (empty list = script passes).
    """
    plausible_sums = {scored_categories, num_teams - 1}
    team_names = [t.get("name", "") for t in pack.get("teams", [])]
    tokens = _team_tokens(team_names)

    problems: list[str] = []
    official = official_record_tuples(pack)
    for raw_line in script_md.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        _speaker, _, text = line.partition(":")
        words = {w.lower().strip("'.,!?—") for w in text.split()}
        if not (words & tokens):
            continue
        for tup in spoken_number_tuples(text, plausible_sums):
            if not _matches_official(tup, official):
                problems.append(
                    f"scoreline {'-'.join(map(str, tup))} matches no official "
                    f"record in the data pack — line: {line!r}"
                )
    return problems
