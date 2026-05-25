"""Phase 5 — ad library + least-recently-aired selector.

Ad spots are fictional, sports-radio-style, PG-13. Each spot is rendered once
via single-voice TTS (a dedicated "announcer" voice) and the resulting mp3
lives in `assets/podcast/ads/library/<slug>.mp3`. Two ads are selected per
episode via LRU rotation persisted to a per-league state file so the same two
don't air two weeks running.

Tone goal: convincing-enough to sound like a real sponsor read, absurd enough
to be obviously fictional. Nutritional supplements, local auto dealers, meat
subscriptions, tax services, parody betting apps — the normal sports radio
menu.
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

AD_LIBRARY: list[AdSpot] = [
    AdSpot(
        slug="victory-serum",
        title="Victory Serum",
        tags=["supplement", "cheeky"],
        voice_id="dbcih6CX6V58wprWOdS8",
        voice_character="Gym-bro intensity. Pumped, caffeinated, slightly aggressive.",
        copy=(
            "Game on the line and you're dragging in the seventh? "
            "VICTORY SERUM. Thirty grams of whey, forty milligrams of caffeine, "
            "and one thousand milligrams of pure competitive spite. Drink it "
            "before the first pitch. Order online at victoryserum dot com. "
            "Warning: may cause yelling at fantasy teams."
        ),
    ),
    AdSpot(
        slug="memorial-mattress",
        title="Memorial Mattress",
        tags=["mattress", "sports-radio-classic"],
        voice_id="qSeXEcewz7tA0Q0qk9fH",
        voice_character="Warm, empathetic, trust-me-I've-been-there. Classic mattress-ad sincerity.",
        copy=(
            "Can't sleep after your closer blew a three-run lead? "
            "MEMORIAL MATTRESS feels your pain. Our patented Ace Foam absorbs "
            "disappointment, bad takes, and the crushing weight of a losing "
            "week. Zero interest financing. Free delivery. Your bullpen may be "
            "soft. Your mattress shouldn't be."
        ),
    ),
    AdSpot(
        slug="honest-hanks-trucks",
        title="Honest Hank's Pre-Owned Trucks",
        tags=["auto", "local"],
        voice_id="WWr4C8ld745zI3BiA8n7",
        voice_character="Folksy Southern used-car huckster. Loud, endearing, slightly dishonest.",
        copy=(
            "You ever meet a guy named Honest Hank who wasn't? You have now. "
            "HONEST HANK'S PRE-OWNED TRUCKS. If it's on the lot, it runs. "
            "Probably. Bring your trade-in, bring your hopes, bring a "
            "co-signer. Honest Hank's. We accept cash, check, and excuses."
        ),
    ),
    AdSpot(
        slug="daddys-tools",
        title="Daddy's Tools",
        tags=["home-improvement"],
        voice_id="Mpo86HxDypWmsME2FSjf",
        voice_character="Gruff but friendly blue-collar dad. Sawdust and cold beer.",
        copy=(
            "The deck isn't going to build itself, pal. Unless you call "
            "DADDY'S TOOLS. One call, one truck, one weekend. We do the "
            "measuring, sawing, cursing, and the other cursing. You do the "
            "beer drinking. Daddy's Tools. Now in three states. Not liable "
            "for marriages."
        ),
    ),
    AdSpot(
        slug="meatstone",
        title="Meatstone Meat of the Month",
        tags=["food", "subscription"],
        voice_id="4QLC5fepxZkYmdD2IGRU",
        voice_character="Deep, reverent, carnivore-poet. Thinks ribeye is a religious experience.",
        copy=(
            "Tired of grilling the same sad burger while your team loses? "
            "Upgrade. MEATSTONE MEAT OF THE MONTH ships two pounds of "
            "ribeye, brisket, or mystery meat to your door every thirty days. "
            "No lineups, no hidden fees, just protein. Order now and get a "
            "free pack of questionable sausages."
        ),
    ),
    AdSpot(
        slug="grand-slam-wagers",
        title="Grand Slam Wagers",
        tags=["betting-parody", "cheeky"],
        voice_id="llNlEi50DSCIEuoOIaH7",
        voice_character="Slick, fast-talking, self-aware hustler. Vegas-pitchman energy.",
        copy=(
            "Think your uncle knows ball? So do we. GRAND SLAM WAGERS. The "
            "only betting app endorsed by four out of five divorce attorneys. "
            "Parlay responsibly. Or don't. Who are we, your mother? First "
            "bet up to one hundred dollars matched. Terms and conditions "
            "apply, obviously."
        ),
    ),
    AdSpot(
        slug="diamond-capital",
        title="Diamond Capital Advisors",
        tags=["financial"],
        voice_id="jHprmvvyQreWpRuutdmV",
        voice_character="Smooth, authoritative trusted-advisor. Wealth-manager sincerity.",
        copy=(
            "Crypto crashed. Your IRA hasn't moved since 2019. Your fantasy "
            "team's worth more than your portfolio. DIAMOND CAPITAL ADVISORS. "
            "We manage your money like you manage your bullpen. With "
            "confidence, regret, and a strong opinion. First consultation "
            "is free."
        ),
    ),
    AdSpot(
        slug="pennant-apparel",
        title="Pennant Apparel",
        tags=["apparel"],
        voice_id="PB6BdkFkZLbI39GHdnbQ",
        voice_character="Bright, enthusiastic, slightly preppy. Golf-sweater guy.",
        copy=(
            "Still wearing cotton tees to the ballpark? Embarrassing. "
            "PENNANT APPAREL. Moisture-wicking, team-branded, game-ready "
            "gear for guys who sweat through box scores. Fifteen percent "
            "off your first order. Look like you played D-1. Even if you "
            "peaked in rec league."
        ),
    ),
    AdSpot(
        slug="big-league-tax",
        title="Big League Tax",
        tags=["tax", "service"],
        voice_id="DwI0NZuZgKu8SNwnpa1x",
        voice_character="No-nonsense, Brooklyn-accent, just-get-it-done energy.",
        copy=(
            "April fifteenth, pal. It's here. BIG LEAGUE TAX. Our agents "
            "file faster than your closer blows a save. No appointment, no "
            "attitude, no judgment about your W-9 situation. Walk in. Walk "
            "out. We handle the rest. Now accepting crypto losses."
        ),
    ),
    AdSpot(
        slug="peak-performance-max",
        title="Peak Performance Max",
        tags=["supplement", "wellness", "cheeky"],
        voice_id="V0cljQmo7wpx8LTdbqfJ",
        voice_character="Urgent late-night infomercial. Act-now! energy.",
        copy=(
            "Feeling tired? Sluggish? Getting out-lapped by guys half your "
            "age? PEAK PERFORMANCE MAX. A daily blend of zinc, magnesium, "
            "and three herbs we can't pronounce. Results in thirty days or "
            "your money back. Ask your doctor. Or don't. We're not your "
            "doctor."
        ),
    ),
    AdSpot(
        slug="rookie-zzzs",
        title="Rookie ZZZs Sleep Spray",
        tags=["sleep"],
        voice_id="j05EIz3iI3JmBTWC3CsA",
        voice_character="Calm, soothing, nearly ASMR. Intentional contrast for comedy.",
        copy=(
            "Tossing and turning after another bullpen meltdown? ROOKIE "
            "ZZZs. Pillow spray infused with lavender, chamomile, and the "
            "sweet scent of not watching the highlights. Spritz it. Sleep "
            "it off. Wake up ready to lose again tomorrow. Non-habit "
            "forming. We hope."
        ),
    ),
    AdSpot(
        slug="dugout-eats",
        title="Dugout Eats",
        tags=["food", "delivery"],
        voice_id="dlGxemPxFMTY7iXagmOj",
        voice_character="Chipper, cheerful ad-read. Like a food-truck jingle.",
        copy=(
            "Game's on. You're starving. Takeout's cold. DUGOUT EATS "
            "delivers stadium-quality hot dogs, nachos, and suspicious "
            "pretzels to your couch in twenty minutes. No tip, no chat, no "
            "judgment about ordering four dogs. Get the app. Eat like you "
            "earned it."
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
