"""Ads v2: style-guide-driven generation, a critic pass, and a JSON
library.

v1 shipped a hand-written Python list of spots. v2 makes ads a content
pipeline: `ads generate` has Claude write a batch against the style guide
(docs/nextgenpodcast/ads.md), a critic pass rejects or rewrites spots
that miss the escalation-ladder anatomy, and survivors land in a JSON
library (`assets/podcast/ads/nextgen/library.json`). `ads render` TTS-
renders any active spot missing its mp3. Episode selection reuses v1's
LRU rotation against a v2 state file.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gkl.nextgenpodcast import AD_WRITER_MODEL
from gkl.nextgenpodcast.scriptcraft import call_claude
from gkl.podcast.ads import select_ads_for_episode  # LRU reused (duck-typed)
from gkl.podcast.assets import generate_tts_to_file


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STYLE_GUIDE = _PROJECT_ROOT / "docs" / "nextgenpodcast" / "ads.md"
DEFAULT_LIBRARY_PATH = (
    _PROJECT_ROOT / "assets" / "podcast" / "ads" / "nextgen" / "library.json"
)

# Ad reads want more expressiveness than host dialogue.
AD_VOICE_SETTINGS = {
    "stability": 0.45,
    "similarity_boost": 0.8,
    "style": 0.35,
    "use_speaker_boost": True,
}

# Casting pool: voice IDs already used on this ElevenLabs account (from
# the v1 ad library casting session, 2026-05-25) with the archetype each
# reads well. The writer picks a voice_id per spot from this pool.
VOICE_POOL: list[tuple[str, str]] = [
    ("dbcih6CX6V58wprWOdS8", "Gym-bro intensity: pumped, caffeinated, aggressive"),
    ("cjVigY5qzO86Huf0OWal", "Smooth, trustworthy advisor; calm authority"),
    ("pNInz6obpgDQGcFmaJgB", "Booming, dominant, personal-injury-lawyer energy"),
    ("XrExE9yKIg1WjnnlVkGX", "Knowledgeable professional woman; methodical"),
    ("gs0tAILXbY5DNrJrsM6F", "Folksy middle-aged American; conversational"),
    ("FGY2WhTYpPnrIDTdsKH5", "Quirky, chaotic, quick-witted woman"),
    ("llNlEi50DSCIEuoOIaH7", "Slick fast-talking Vegas pitchman"),
    ("onwK4e9ZLuTAKqWW03F9", "Slow, reverent British luxury voiceover"),
    ("cgSgspJ2msm6clMCkdW9", "Bright, playful, warm woman; cheerful"),
    ("hpp4J3VqNfWAUOO0d1Us", "Professional founder-confidence woman"),
]


@dataclass
class NgAdSpot:
    slug: str
    title: str
    copy: str
    voice_id: str
    voice_character: str
    tags: list[str] = field(default_factory=list)
    batch: str = ""          # e.g. "2026-07-03"
    status: str = "active"   # active | archived
    sequel_of: str = ""      # slug of a prior spot this one continues

    def asset_path(self, assets_root: Path) -> Path:
        return assets_root / "podcast" / "ads" / "nextgen" / f"{self.slug}.mp3"


# ---------- Library ----------

def load_library(path: Path = DEFAULT_LIBRARY_PATH) -> list[NgAdSpot]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [NgAdSpot(**spot) for spot in raw.get("spots", [])]


def save_library(spots: list[NgAdSpot], path: Path = DEFAULT_LIBRARY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"spots": [asdict(s) for s in spots]}, indent=2))


def active_spots(library: list[NgAdSpot]) -> list[NgAdSpot]:
    return [s for s in library if s.status == "active"]


def select_episode_ads(
    rotation_path: Path, n: int = 2, *, library_path: Path = DEFAULT_LIBRARY_PATH,
) -> list[NgAdSpot]:
    """LRU-select n active spots (reuses the v1 rotation machinery)."""
    lib = active_spots(load_library(library_path))
    return select_ads_for_episode(rotation_path, n, library=lib)


def rotation_path_for_league(data_root: Path, league_key: str) -> Path:
    return data_root / "podcast" / league_key / "nextgen" / "ad-rotation.json"


# ---------- Generation ----------

_WRITER_SYSTEM = """\
You write fictional radio advertisements for a fantasy-baseball podcast.
The complete style guide is provided in the user prompt — it is the
contract. The prime directive: THE AD NEVER KNOWS IT'S THE JOKE. No
winking, no confessing, no line that labels its own scam — damning
facts are delivered as pride, benefits, or reassurance, and the
listener does the math one beat later. Understatement beats shouting;
the best line should be missable on first listen.

Keep every spot 45-75 words (hard ceiling 80). Follow the five-beat
anatomy, vary the opening frames across the batch, PG-13,
league-agnostic, written for the ear (spoken-form numbers, no
abbreviations). Satirize industries, never personal misfortune — no
divorce or breakup jokes, nothing that punches at grief or illness.

Output STRICT JSON only — a single array, no markdown fences, no prose:
[
  {
    "slug": "kebab-case-brand-slug",
    "title": "Brand Name",
    "copy": "the full spot text",
    "voice_id": "one voice_id chosen from the casting pool provided",
    "voice_character": "one line: how this read should sound and why the contrast is funny",
    "tags": ["category", "satire"],
    "sequel_of": ""
  }
]
If existing-brand summaries are provided, you may write AT MOST one
sequel spot continuing one of them (set sequel_of to that slug)."""

_CRITIC_SYSTEM = """\
You are the comedy editor for a batch of fictional radio ads. The style
guide in the user prompt is the contract. For each spot, check:
1. All five beats present (hook / pitch / escalation / turn / tag)?
2. Does the escalation actually LADDER — each claim slightly more wrong
   than the last, by implication not volume? (If the middle claims could
   swap order without anyone noticing = rewrite.)
3. THE SUBTLETY CHECK — the most important one. Does any line confess,
   wink, or label its own scam ("we barely check", "the science is
   shaky", "we're not really insured")? On-the-nose lines get the spot a
   "rewrite": convert every confession into a proud, specific detail
   that implies the same thing. The laugh must arrive one beat delayed.
4. Is the turn understated — the darkest fact thrown away casually —
   rather than a shouted crescendo?
5. Specificity: at least one number, credential, or qualifier doing
   quiet damage?
6. 45-75 words (hard ceiling 80 — over is an automatic rewrite,
   trimming is part of the fix), PG-13, league-agnostic, written for
   the ear?
7. Sensitive-target check: any divorce/breakup joke, or humor at
   personal misfortune (grief, addiction, illness) = rewrite it out or
   fail the spot. Industries are targets; suffering people are not.
8. Across the BATCH: do more than half the spots share an opening frame?
   If so, fail the weakest duplicates.

Output STRICT JSON only — a single array, one entry per input spot:
[
  {
    "slug": "...",
    "verdict": "pass" | "rewrite" | "fail",
    "notes": "one or two sentences",
    "fixed_copy": "full rewritten copy (ONLY when verdict is rewrite; keep the concept, fix the craft)"
  }
]"""


# Deterministic backstops applied AFTER the critic pass — a spot the
# critic waves through still gets dropped if it breaks a hard rule.
MAX_SPOT_WORDS = 80
# Personal-misfortune humor is off the table (user feedback 2026-07-04:
# "dial down the divorce jabs"). Industries are targets; suffering isn't.
BANNED_TOPIC_TERMS = (
    "divorce", "divorced", "breakup", "broke up", "ex-wife", "ex-husband",
    "wife left", "husband left", "custody",
)


def violates_hard_rules(copy: str) -> str | None:
    """Return a reason string if the copy breaks a non-negotiable rule."""
    if len(copy.split()) > MAX_SPOT_WORDS:
        return f"over {MAX_SPOT_WORDS} words"
    lowered = copy.lower()
    for term in BANNED_TOPIC_TERMS:
        if term in lowered:
            return f"banned topic: {term!r}"
    return None


def _parse_json_array(raw: str) -> list[dict]:
    """Parse a JSON array from model output, tolerating stray fences."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON array found in model output: {raw[:200]!r}")
    return json.loads(text[start:end + 1])


async def generate_ad_batch(
    n_spots: int = 6,
    *,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE,
    library_path: Path = DEFAULT_LIBRARY_PATH,
    batch_label: str = "",
    model: str = AD_WRITER_MODEL,
) -> tuple[list[NgAdSpot], list[dict]]:
    """Write + criticize a batch. Returns (accepted spots, critic report).

    Accepted spots are appended to the library (existing slugs are never
    overwritten). Rendering is a separate step.
    """
    guide = style_guide_path.read_text()
    library = load_library(library_path)
    existing = {s.slug for s in library}

    pool_lines = "\n".join(f"- {vid}: {desc}" for vid, desc in VOICE_POOL)
    brand_lines = "\n".join(
        f"- {s.slug}: {s.title} — {s.copy[:120]}..." for s in active_spots(library)
    ) or "(none yet)"

    writer_user = (
        f"Style guide:\n\n{guide}\n\n"
        f"Casting pool (pick voice_id per spot):\n{pool_lines}\n\n"
        f"Existing active brands (for optional sequels, and to avoid "
        f"duplicating concepts):\n{brand_lines}\n\n"
        f"Write {n_spots} new spots now. Output the JSON array only."
    )
    raw_spots = _parse_json_array(
        await call_claude(_WRITER_SYSTEM, writer_user, model=model, max_tokens=8192)
    )

    critic_user = (
        f"Style guide:\n\n{guide}\n\n"
        f"Batch to review:\n\n{json.dumps(raw_spots, indent=2)}\n\n"
        f"Output the JSON verdict array only."
    )
    verdicts = _parse_json_array(
        await call_claude(_CRITIC_SYSTEM, critic_user, model=model, max_tokens=8192)
    )
    verdict_by_slug = {v.get("slug"): v for v in verdicts}

    valid_voice_ids = {vid for vid, _ in VOICE_POOL}
    accepted: list[NgAdSpot] = []
    for raw in raw_spots:
        slug = raw.get("slug", "")
        if not slug or slug in existing:
            continue
        v = verdict_by_slug.get(slug, {"verdict": "pass", "notes": ""})
        if v.get("verdict") == "fail":
            continue
        copy = raw.get("copy", "")
        if v.get("verdict") == "rewrite" and v.get("fixed_copy"):
            copy = v["fixed_copy"]
        if not copy.strip():
            continue
        reason = violates_hard_rules(copy)
        if reason:
            verdicts.append({
                "slug": slug, "verdict": "fail",
                "notes": f"hard-rule backstop: {reason}",
            })
            continue
        voice_id = raw.get("voice_id", "")
        if voice_id not in valid_voice_ids:
            voice_id = VOICE_POOL[len(accepted) % len(VOICE_POOL)][0]
        accepted.append(NgAdSpot(
            slug=slug,
            title=raw.get("title", slug),
            copy=copy.strip(),
            voice_id=voice_id,
            voice_character=raw.get("voice_character", ""),
            tags=list(raw.get("tags", [])),
            batch=batch_label,
            sequel_of=raw.get("sequel_of", "") or "",
        ))
        existing.add(slug)

    save_library(library + accepted, library_path)
    return accepted, verdicts


# ---------- Rendering ----------

async def render_missing_ads(
    assets_root: Path,
    *,
    library_path: Path = DEFAULT_LIBRARY_PATH,
    force: bool = False,
    log=None,
) -> list[Path]:
    """TTS-render every active spot whose mp3 is missing (or all, with
    force). Returns the rendered paths."""
    rendered: list[Path] = []
    for spot in active_spots(load_library(library_path)):
        out = spot.asset_path(assets_root)
        if out.exists() and not force:
            continue
        if log:
            log(f"  rendering {spot.slug} ({len(spot.copy)} chars)…")
        await generate_tts_to_file(
            spot.copy, spot.voice_id, out, voice_settings=AD_VOICE_SETTINGS,
        )
        rendered.append(out)
    return rendered
