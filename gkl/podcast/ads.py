"""Phase 5 — ad library + least-recently-aired selector.

Ad spots are fictional, sports-radio-style, PG-13. Each spot is rendered once
via single-voice TTS (a dedicated "announcer" voice) and the resulting mp3
lives in `assets/podcast/ads/library/<slug>.mp3`. Two ads are selected per
episode via LRU rotation persisted to a per-league state file so the same two
don't air two weeks running.

Tone goal (as of the 2026-07-02 refresh): fully over-the-top, GTA-radio-style
satire across the whole library, not just a couple of spots. Sincere,
confident ad-read delivery selling something absurd, predatory, or darkly
funny underneath — testosterone clinics, crypto apps, ambulance-chasers,
payday loans, extended-warranty robocalls. PG-13, obviously fictional, but
every spot commits to the bit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AdSpot:
    """One 15-second fictional ad spot.

    Each spot has its own `voice_id` so the ad library sounds like real
    sports-radio advertising — different advertiser, different voice talent,
    different campaign. The character notes describe the intended vibe so
    the casting decision can be audited and re-cast later without losing
    the reason for each choice.
    """
    slug: str
    title: str
    copy: str
    voice_id: str
    voice_character: str
    tags: list[str] = field(default_factory=list)

    def asset_path(self, assets_root: Path) -> Path:
        """Where the rendered mp3 lives relative to the assets root."""
        return assets_root / "podcast" / "ads" / "library" / f"{self.slug}.mp3"

    def char_count(self) -> int:
        return len(self.copy)


# ---------- The ad library ----------
#
# Refreshed 2026-07-02. The prior 10-spot library (itself only half-
# finished — 2 of a planned 4 GTA-style satire spots) was archived to
# `gkl/podcast/ads_archive.py::ARCHIVED_AD_LIBRARY_2026_07_02` and the
# mp3s moved to `assets/podcast/ads/_archive_2026-07-02/`. This batch is
# entirely new concepts (no brand names or copy carried over) and every
# spot is written fully over-the-top: sincere, confident ad-read delivery
# selling something absurd, predatory, or darkly funny underneath — the
# GTA-radio satire register throughout, not just a couple of spots. Four
# are women-voiced/women-led (prospect-report, legacy-ink, apex-longevity
# — plus the founder framing on several others) to keep the same mix as
# prior batches. Voice IDs were chosen against `GET /v1/voices` on the
# user's account on 2026-05-25 and reused here (no new casting needed).

AD_LIBRARY: list[AdSpot] = [
    AdSpot(
        slug="ironclad-trc",
        title="Ironclad T-R-C Clinic",
        tags=["supplement", "wellness", "satire"],
        voice_id="dbcih6CX6V58wprWOdS8",  # Gym-bro intensity, pumped, aggressive
        voice_character=(
            "GTA-style men's-health-clinic satire. Aggressive, caffeinated, "
            "utterly convinced — sells a six-minute doctor's visit like a "
            "religious awakening."
        ),
        copy=(
            "Forty and tired? That's not aging. That's LOW T. IRONCLAD "
            "T-R-C CLINIC. One blood draw, one prescription, zero follow-"
            "up questions. Our doctor's seen your labs for six minutes "
            "total this year. Testosterone, HGH peptides, a vitamin drip "
            "we invoice as innovative. Insurance won't cover it. "
            "Confidence will. Because feeling like a closer beats seeing "
            "a doctor."
        ),
    ),
    AdSpot(
        slug="skybox-capital",
        title="Skybox Capital",
        tags=["financial", "satire"],
        voice_id="cjVigY5qzO86Huf0OWal",  # Eric — Smooth, Trustworthy
        voice_character=(
            "Smooth, trustworthy fintech-bro satire. Sells reckless "
            "speculation with the calm authority of a real financial "
            "advisor. GTA-style crypto-app satire."
        ),
        copy=(
            "Your 401k made two percent. Embarrassing. SKYBOX CAPITAL "
            "puts your retirement into the same coins our interns trade "
            "on lunch break. No fiduciary duty, no cooling-off period, "
            "no floor. Past performance guarantees nothing, but our "
            "billboards are very convincing. Download the app. Your "
            "grandkids' inheritance was always more of a suggestion."
        ),
    ),
    AdSpot(
        slug="franchise-tag-legal",
        title="Franchise Tag Legal",
        tags=["legal", "satire"],
        voice_id="pNInz6obpgDQGcFmaJgB",  # Adam — Dominant, Firm
        voice_character=(
            "Classic loud personal-injury-lawyer ad energy. Booming, "
            "confident, self-interested. GTA-style ambulance-chaser "
            "satire."
        ),
        copy=(
            "Hurt on the job? Getting divorced? Both? FRANCHISE TAG "
            "LEGAL negotiates you a contract like a bonafide All-Star. "
            "No fee unless we win, and we define winning generously. Our "
            "billboards outnumber our verdicts. Free consultation, "
            "aggressive settlement, occasional court appearance. We get "
            "you paid. We get paid more."
        ),
    ),
    AdSpot(
        slug="prospect-report",
        title="Prospect Report",
        tags=["dating-app", "woman-led", "satire"],
        voice_id="XrExE9yKIg1WjnnlVkGX",  # Matilda — Knowledgable, Professional
        voice_character=(
            "Methodical, data-driven founder voice. Treats dating like "
            "scouting reports. GTA-style dating-app satire, quietly "
            "intense delivery."
        ),
        copy=(
            "Stop swiping blind. PROSPECT REPORT scouts your dates like "
            "a first-round pick. Exit velocity, plate discipline, makeup "
            "grade, all before the first coffee. Built by a woman tired "
            "of scouting reports that were just guys lying in golf "
            "shirts. Nine bucks a month. We can't fix chemistry. We can "
            "flag the ones who still live with their moms."
        ),
    ),
    AdSpot(
        slug="ironhorse-warranty",
        title="Ironhorse Warranty Group",
        tags=["auto", "satire"],
        voice_id="gs0tAILXbY5DNrJrsM6F",  # Jeff — middle-aged American conversational
        voice_character=(
            "Extended-car-warranty robocall energy, but a real person "
            "reading it sincerely. GTA-style scam-satire, folksy and "
            "unbothered."
        ),
        copy=(
            "This is your final notice about your vehicle's extended "
            "warranty. IRONHORSE WARRANTY GROUP has been trying to reach "
            "you since your car was new. Full coverage, low monthly "
            "payments, a claims department that answers roughly never. "
            "We got your number from somewhere. We're not saying where. "
            "Call now. Or don't. We'll call back."
        ),
    ),
    AdSpot(
        slug="legacy-ink",
        title="Legacy Ink Tattoo",
        tags=["service", "woman-led", "satire"],
        voice_id="FGY2WhTYpPnrIDTdsKH5",  # Laura — Enthusiast, Quirky
        voice_character=(
            "Chaotic, quick-witted tattoo-shop owner. Seen everything, "
            "judges everything, still cheerful about it. GTA-style "
            "regret-adjacent satire."
        ),
        copy=(
            "Championship year? Bad breakup? Third bad breakup? LEGACY "
            "INK TATTOO commemorates all of it, permanently, at two a.m. "
            "prices during business hours. Custom lettering, "
            "questionable spelling, a laser-removal punch card we hope "
            "you never need but definitely will. Run by a woman who's "
            "seen your exact tattoo four times this month."
        ),
    ),
    AdSpot(
        slug="gm-mode",
        title="GM Mode",
        tags=["betting-parody", "satire"],
        voice_id="llNlEi50DSCIEuoOIaH7",  # Slick, fast-talking hustler, Vegas-pitchman
        voice_character=(
            "Slick, self-aware Vegas hustler. Fast-talking, winking at "
            "the camera the whole time. GTA-style betting-app satire."
        ),
        copy=(
            "Think you know ball better than the app? Prove it. GM "
            "MODE, the betting platform that turns your gut feeling into "
            "a line item. Same-game parlays, in-play odds, a "
            "notification every time your team blows a lead. Bet "
            "responsibly, or bet like it's Week 14 and you're desperate. "
            "First deposit matched. Terms apply, obviously, to you."
        ),
    ),
    AdSpot(
        slug="bullpen-reserve",
        title="Bullpen Reserve Bourbon",
        tags=["spirits", "satire"],
        voice_id="onwK4e9ZLuTAKqWW03F9",  # Daniel — Steady Broadcaster, British
        voice_character=(
            "Slow, deliberate luxury-spirits voiceover. Every consonant "
            "earned, like the Walk-Off Watches read but for bourbon. "
            "GTA-style premium-goods satire."
        ),
        copy=(
            "Aged twelve years in oak, same as your closer's fastball "
            "has aged out of relevance. BULLPEN RESERVE BOURBON. Small "
            "batch, single barrel, bottled the week a manager finally "
            "admitted the rebuild wasn't working. Notes of caramel, "
            "regret, and a save blown in extras. Drink it neat. Drink it "
            "during extra innings. We won't judge the pace."
        ),
    ),
    AdSpot(
        slug="nightcap-advance",
        title="Nightcap Advance",
        tags=["financial", "satire"],
        voice_id="cgSgspJ2msm6clMCkdW9",  # Jessica — Playful, Bright, Warm
        voice_character=(
            "Bright, cheerful, warm delivery selling a payday loan with "
            "zero irony. GTA-style predatory-fintech satire — the smile "
            "is the whole joke."
        ),
        copy=(
            "Payday's five days out and your waiver claim already went "
            "through. NIGHTCAP ADVANCE fronts you two hundred dollars in "
            "ninety seconds, no credit check, no judgment, modest weekly "
            "fee that compounds like a bad bullpen. Approved instantly. "
            "Repaid eventually. We believe in your next paycheck more "
            "than you do."
        ),
    ),
    AdSpot(
        slug="apex-longevity",
        title="Apex Longevity Lab",
        tags=["wellness", "woman-led", "satire"],
        voice_id="hpp4J3VqNfWAUOO0d1Us",  # Bella — Professional, Bright
        voice_character=(
            "Warm, professional founder-confidence, same register as the "
            "old MVP Mama Wellness spot. Sells biohacking pseudoscience "
            "with total conviction. GTA-style wellness-clinic satire."
        ),
        copy=(
            "I'm a former ER nurse and the founder of APEX LONGEVITY "
            "LAB. IV drips, cryotherapy, a blood panel we grade like "
            "Statcast, barrel rate for your biomarkers. Membership's "
            "four hundred a month. The science is emerging. The "
            "marketing is not. You'll leave feeling optimized. Whether "
            "you are is between you and your actual doctor."
        ),
    ),
]


def find_ad(slug: str, library: list[AdSpot] | None = None) -> AdSpot:
    """Look up an ad by slug. Raises KeyError if not in the library."""
    lib = library if library is not None else AD_LIBRARY
    for ad in lib:
        if ad.slug == slug:
            return ad
    raise KeyError(f"ad slug not found in library: {slug}")


# ---------- LRU rotation ----------

def _load_rotation(path: Path, library: list[AdSpot]) -> list[str]:
    """Load the rotation order from disk, initializing/repairing as needed.

    - If the state file is missing, the rotation starts as the library's
      natural order.
    - If it exists but references ads no longer in the library, those are
      dropped.
    - If the library has new ads not in the state file, they are appended
      to the end (will air last).
    """
    library_slugs = [ad.slug for ad in library]
    library_set = set(library_slugs)
    rotation: list[str] = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
            raw = data.get("rotation", [])
            if isinstance(raw, list):
                rotation = [s for s in raw if isinstance(s, str) and s in library_set]
        except (json.JSONDecodeError, TypeError):
            rotation = []
    # Append any ads newly added to the library
    for slug in library_slugs:
        if slug not in rotation:
            rotation.append(slug)
    return rotation


def _save_rotation(path: Path, rotation: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rotation": rotation}, indent=2))


def select_ads_for_episode(
    rotation_path: Path,
    n: int = 2,
    *,
    library: list[AdSpot] | None = None,
) -> list[AdSpot]:
    """Return `n` ads via LRU rotation, persisting state to `rotation_path`.

    The first `n` slugs in the rotation are selected and moved to the back,
    making them the most-recently-aired. This guarantees:

    - Each episode's pair of ads is unique within the episode.
    - No ad repeats until the entire library has been cycled through.
    - Library edits (adds/removes) are handled gracefully.

    Raises ValueError if the library has fewer than `n` ads.
    """
    lib = library if library is not None else AD_LIBRARY
    if len(lib) < n:
        raise ValueError(
            f"ad library has {len(lib)} spots, need at least {n}"
        )
    rotation = _load_rotation(rotation_path, lib)
    picked_slugs = rotation[:n]
    new_rotation = rotation[n:] + picked_slugs
    _save_rotation(rotation_path, new_rotation)
    return [find_ad(slug, lib) for slug in picked_slugs]


def rotation_path_for_league(data_root: Path, league_key: str) -> Path:
    """Per-league ad rotation state file."""
    return data_root / "podcast" / league_key / "ad-rotation.json"
