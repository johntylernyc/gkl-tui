# Ad Writing — Style Guide (nextgenpodcast)

The target register is the in-game radio advertisement from Grand Theft
Auto V and its predecessors: a fictional product sold with total
sincerity, where something is deeply wrong underneath — and the ad
itself never notices. The listener does the math; the announcer never
does. Short, confident, specific, and funnier on the second listen than
the first.

This document is loaded by `gkl/nextgenpodcast/ads.py` and injected into
the ad-writer and ad-critic prompts. Edit here; the next `ads generate`
run picks it up.

## The prime directive: the ad never knows it's the joke

The single biggest failure mode is being **on the nose** — copy that
winks, confesses, or labels its own scam. A GTA ad is written by someone
who believes in the product. Damning facts are allowed — encouraged —
but they must be delivered as *benefits, reassurances, or points of
pride*, never as self-aware admissions.

Bad → good, same joke, different altitude:

| On the nose (confession) | Implied (pride) |
|---|---|
| "a claims department that answers roughly never" | "Claims are processed in the order they deserve." |
| "no fiduciary duty, no cooling-off period, no floor" | "Our advisors are free to act on instinct." |
| "the science is emerging, the marketing is not" | "Data-driven wellness, whatever the data says." |
| "we define winning generously" | "We've recovered millions in verdicts, settlements, and gift cards." |
| "zero follow-up questions" | "Our physicians prescribe with confidence, speed, and a personal best of ninety seconds." |

If a line explains why the product is bad, cut it and replace it with a
proud, specific detail that lets the listener reach the same conclusion
one beat later. The laugh should arrive slightly delayed — that delay is
the craft.

## Anatomy of a spot

**45-75 words. Hard ceiling 80.** Roughly 20-30 seconds read aloud —
these are quick hits between segments, not features. Five beats, and
every word earns its seat:

1. **The hook** — a relatable pain or desire, one sentence.
2. **The pitch** — brand + product, proud and almost legitimate.
3. **The escalation** — two (at most three) claims, each slightly more
   wrong than the last, all delivered as selling points. Escalate by
   IMPLICATION, not volume: the claims get quieter and more specific,
   not louder and more absurd.
4. **The turn** — the darkest or strangest fact in the spot, thrown away
   casually. Understatement beats a crescendo. ("Pause anytime after
   your sixth shipment.")
5. **The tag** — a short slogan or sign-off that recontextualizes
   everything before it. ("The Foul Pole. You could do worse. You have.")

If beats 3a and 3b could swap order without anyone noticing, the ladder
isn't built. If any beat runs two sentences, it's too long.

## Rules

- **Commit to the bit.** The announcer believes every word. No irony
  markers, no "just kidding" energy. Sincerity IS the joke.
- **Specificity is the engine.** "Board-certified in at least one
  state." "Pasture-raised on land, by ranchers." "One working restroom
  we're very proud of." A number, a credential, or a qualifier doing
  quiet damage beats any amount of shouting.
- **Subtlety over shock.** The best line in the spot should be the one a
  listener could miss the first time. Trust the audience.
- **A victim is implied, never mocked.** Satirize industries — wellness
  grift, predatory finance, injury law, youth-sports hustle, collector
  mania — not personal misfortune. **No divorce or breakup jokes**, no
  punching at grief, addiction, or illness. The target is always the
  company, never the caller-in-pain it preys on.
- **Vary the skeleton.** Not every spot opens with a second-person
  question. Alternate frames: founder monologue, testimonial read
  cheerfully, reverent product poetry, fake bulletin, folksy local read.
  The critic rejects a batch where more than half share an opening frame.
- **Baseball-adjacent, not league-specific.** Sports-radio products keep
  the world coherent — but NEVER real league members, real fantasy
  teams, real brands, or real people.
- **Recurring advertisers are encouraged.** A brand may return with a
  sequel (a recall notice, a "we've heard your concerns" spot). Sequels
  inherit the same subtlety bar.
- **PG-13.** Innuendo yes, profanity no, nothing hateful.
- **Written for the ear.** Numbers in spoken form, short sentences, no
  abbreviations TTS will mangle. The tag can be one breathless run-on.
- **Voice casting note required.** One line per spot on how the read
  should sound; contrast between warm delivery and cold content is part
  of the joke.

## Reference spot (the bar)

> You used to take the stairs two at a time. SUMMIT VITALITY CLINICS
> runs one simple blood test and finds exactly what we always find. Our
> physicians prescribe with confidence, speed, and a personal best of
> ninety seconds. Walk-ins welcome. Walk-outs feel incredible, for a
> while. Summit. Ask your doctor if a different doctor is right for you.

Why it works: 58 words; nothing is confessed ("finds exactly what we
always find" is pride, not a wink); the escalation is quiet
(test → prescribe → ninety seconds); the turn is three words ("for a
while"); the tag re-frames the whole spot. Every laugh is one beat
delayed.

## Library management

- Target library size: 12-16 active spots; refresh 4-6 every ~6 weeks;
  archive the weakest.
- Every generated batch goes through the critic pass; spots failing the
  anatomy, length, or subtlety checks are rewritten or dropped before
  rendering.
- Rendered mp3s are immutable once committed; re-rendering requires
  deleting the mp3 (same contract as v1).
