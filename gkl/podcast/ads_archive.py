"""Archived ad libraries.

Each archived list is a complete `AD_LIBRARY` snapshot retired on the date
in its name. The rendered mp3s for an archive live alongside the code at
`assets/podcast/ads/_archive_<date>/`. Nothing in this module is imported
by the active runtime — it's history for reference and possible
restoration if a retired spot is missed enough to bring back.
"""

from __future__ import annotations

from gkl.podcast.ads import AdSpot


# Original 12-spot library shipped with the podcast feature. Archived on
# 2026-05-25 in favor of a fresh 10-spot batch tailored to the favorites
# the user named (Honest Hank's, Daddy's Tools, Diamond Capital, and two
# women-led brands). Mp3s moved to
# `assets/podcast/ads/_archive_2026-05-25/`.
ARCHIVED_AD_LIBRARY_2026_05_25: list[AdSpot] = [
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


# Second-generation 10-spot library (the 2026-05-25 refresh above). Retired
# on 2026-07-02 — never fully finished (only 2 of the planned 4 GTA-style
# satire spots were rewritten before this batch itself was replaced) and
# superseded wholesale by an all-new, fully-satirical 10-spot library so
# none of these concepts carry forward. Mp3s moved to
# `assets/podcast/ads/_archive_2026-07-02/`.
ARCHIVED_AD_LIBRARY_2026_07_02: list[AdSpot] = [
    AdSpot(
        slug="slugger-tees",
        title="Slugger Tees",
        tags=["apparel", "woman-led", "satire"],
        voice_id="cgSgspJ2msm6clMCkdW9",  # Jessica — Playful, Bright, Warm
        voice_character=(
            "GTA-style girlboss-empowerment satire. Bright, cheerful, "
            "sincere — sells the cynicism underneath with a warm smile."
        ),
        copy=(
            "Tired of team merch your dad's worn since 2007? SLUGGER TEES. "
            "Founded by two women who quit finance and kept the "
            "spreadsheets. Hand-distressed by Brooklyn interns paying us "
            "in equity. Sixty-eight dollars, sourced from a country we "
            "won't name. Three percent of profits go to a cause we'll "
            "pick after the IPO. Code GIRLBOSS for fifteen off. You wear "
            "the empowerment. We'll bank the rest."
        ),
    ),
    AdSpot(
        slug="mvp-mama-wellness",
        title="MVP Mama Wellness",
        tags=["supplement", "wellness", "woman-led", "satire"],
        voice_id="hpp4J3VqNfWAUOO0d1Us",  # Bella — Professional, Bright
        voice_character=(
            "GTA-style wellness-supplement satire. Warm, professional, "
            "mom-confidence — sells a quietly suspect daily multi with "
            "absolute conviction."
        ),
        copy=(
            "I'm a mom of three, a former registered nurse, and the "
            "founder of MVP MAMA WELLNESS. Our daily multi has iron, "
            "magnesium, B-complex, and a proprietary blend our legal "
            "team asked us not to specify. The FDA hasn't evaluated it. "
            "They rarely do. Twenty bucks a month. Cancel anytime by "
            "mailing a notarized affidavit. We're not selling youth. "
            "We're selling Tuesday. Side effects may include Wednesday."
        ),
    ),
    AdSpot(
        slug="lawn-bombers",
        title="Lawn Bombers Lawn Care",
        tags=["home-service", "local"],
        voice_id="d5xU2Rwln0n15oHMmaTU",  # Sheps Rocky — Middle-aged American
        voice_character="Suburban dad who'd rather be watching the game. Lawn guy you actually trust.",
        copy=(
            "It's Sunday. The game's at one. Your lawn looks like Triple-A "
            "in the rain. Call LAWN BOMBERS. We mow, we edge, we leave. "
            "Twenty-five bucks flat for a quarter acre. We bring our own "
            "beer. We don't talk to your wife. Lawn Bombers. Like a closer, "
            "but for grass."
        ),
    ),
    AdSpot(
        slug="fairway-finance",
        title="Fairway Finance",
        tags=["financial", "satire"],
        voice_id="cjVigY5qzO86Huf0OWal",  # Eric — Smooth, Trustworthy
        voice_character=(
            "Smooth grandfatherly wealth-broker with predatory undertones. "
            "The advisor who absolutely will steal your inheritance, "
            "smiling the whole time. GTA-style elder-finance satire."
        ),
        copy=(
            "Sixty-five and retired? Congratulations — we've been waiting. "
            "FAIRWAY FINANCE. Advisors for seniors with paid-off homes and "
            "trusting natures. The Fairway Eagle turns your nest egg into "
            "surprising fees. Tuesday seminars at the nineteenth hole. "
            "Brunch included, deed required. First session free, last one "
            "binding. Fairway Finance. We treat you like family, leave "
            "your inheritance with us."
        ),
    ),
    AdSpot(
        slug="rally-cap-coffee",
        title="Rally Cap Coffee Roasters",
        tags=["food", "subscription", "woman-led"],
        voice_id="FGY2WhTYpPnrIDTdsKH5",  # Laura — Enthusiast, Quirky
        voice_character="Bright modern woman-owned coffee shop. Slightly chaotic. Caffeinated.",
        copy=(
            "Game's at ten p.m. West Coast. You're not making it through "
            "the seventh inning. RALLY CAP COFFEE. Roasted by a woman who "
            "pulls her own all-nighters watching pitching prospects. Our "
            "Bullpen Blend is dark, single-origin, and possibly illegal in "
            "three states. Subscribe, twelve bucks a bag, ships every two "
            "weeks. Sleep is for non-contenders."
        ),
    ),
    AdSpot(
        slug="bullpen-brews",
        title="Bullpen Brews",
        tags=["food", "local"],
        voice_id="NOpBlnGInO9m6vDvFkFC",  # Spuds Oxley — Wise, Approachable, old
        voice_character="Old-timer local brewpub owner. Friendly, story-laden, possibly two beers in.",
        copy=(
            "Twenty-two years I've been brewing beer behind this bar. "
            "BULLPEN BREWS. Game days we open at noon, close when the last "
            "manager gets ejected. House lager, two IPAs, a stout we call "
            "The Long Reliever. First pint's on me if you came in wearing a "
            "jersey. Two pints if you came in with a fresh divorce. Bullpen "
            "Brews. Step inside."
        ),
    ),
    AdSpot(
        slug="hot-corner-sauces",
        title="Hot Corner Hot Sauces",
        tags=["food", "small-batch", "woman-led"],
        voice_id="XrExE9yKIg1WjnnlVkGX",  # Matilda — Knowledgable, Professional
        voice_character="Methodical food-scientist mom. Notes pH levels. Quietly intense.",
        copy=(
            "I built our flagship sauce in my garage during the 2024 "
            "playoffs. HOT CORNER HOT SAUCES. Real ingredients, real heat, "
            "no high-fructose anything. The Diving Catch is mild. The "
            "Brushback will make you reconsider your life choices. Small-"
            "batch, woman-owned, hand-bottled in Cleveland. Six bucks a "
            "bottle. Lab-tested for capsaicin and emotional damage."
        ),
    ),
    AdSpot(
        slug="slidepiece-storage",
        title="Slidepiece Storage",
        tags=["service", "local"],
        voice_id="gs0tAILXbY5DNrJrsM6F",  # Jeff — middle-aged American conversational
        voice_character="Friendly midwestern storage-unit guy. Has seen things. Won't judge.",
        copy=(
            "Things change. Marriages end. The wife wants the records, the "
            "dog, AND the man cave. SLIDEPIECE STORAGE. Climate-controlled "
            "units from a hundred bucks a month. Twenty-four-seven access "
            "for those three a.m. emotional reorganizing sessions. We take "
            "everything. Vinyl, weight benches, your dad's golf clubs, "
            "your dignity. No questions. Coffee in the lobby."
        ),
    ),
    AdSpot(
        slug="curveball-carpets",
        title="Curveball Carpets",
        tags=["home-improvement", "local"],
        voice_id="pNInz6obpgDQGcFmaJgB",  # Adam — Dominant, Firm
        voice_character="Classic loud-flooring-ad guy. Yelling about square footage. Used-car energy for rugs.",
        copy=(
            "Wife says your carpet looks like a Triple-A clubhouse after a "
            "no-hitter. She's right. CURVEBALL CARPETS. Two hundred styles, "
            "every fiber known to man, financing for veterans, first "
            "responders, and divorced guys. Free measurement. Free "
            "installation. Free pizza on Tuesdays. Curveball Carpets. We "
            "don't miss the corners."
        ),
    ),
    AdSpot(
        slug="walk-off-watches",
        title="Walk-Off Watches",
        tags=["luxury", "parody"],
        voice_id="onwK4e9ZLuTAKqWW03F9",  # Daniel — Steady Broadcaster, British
        voice_character="Luxury-watch voiceover. Slow, deliberate, every consonant earned.",
        copy=(
            "A man's wrist tells the world how he keeps time. WALK-OFF "
            "WATCHES. Swiss movement. Sapphire crystal. Leather strap from "
            "cows raised in the Alps. Each piece engraved with the words "
            "Bottom of the Ninth. Twelve hundred dollars, financing "
            "available, free engraving with your closer's number. A Rolex "
            "is for closers. This is for fans."
        ),
    ),
]
