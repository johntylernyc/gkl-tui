# nextgenpodcast — the next-generation GKL podcast pipeline

Successor to the v1 pipeline (`gkl/podcast/`, spec: `docs/gkl-podcast.md`).
The v1 code is **preserved untouched** and remains runnable via
`gkl-podcast`; this package (`gkl/nextgenpodcast/`, CLI
`gkl-nextgenpodcast`) is a parallel build that reuses v1's proven
infrastructure (mixer, TTS client, asset library, Skipper toolkit) while
replacing the creative pipeline end to end.

## Why (current-state review, 2026-07-03)

A full review of the v1 code, prompts, and the 11 generated episodes
(Weeks 4-14) found the engineering strong — staged pipeline, persisted
intermediates, battle-tested fact-checking, LRU ads, tests — and the
show itself stalling. Findings, with evidence:

1. **No characters.** The hosts are literally `HOST`/`GUEST` — the show
   bible section of the v1 segment artifact still says "TBD — Phase 8"
   eleven weeks in. No names, no personal texture, >90% of turns are pure
   stat delivery, and the only signature device ("my guy") calcified into
   an identical opening clause six weeks running.
2. **A frozen template.** Same greeting, same act openers/closers ("And
   we're back" 10/10 episodes), same standings thesis (the "pitching
   depth" conclusion appeared 7 consecutive weeks), same fall/rise/co-sign
   ritual. A listener can predict the next sentence's shape from the act
   number.
3. **The edit chain flattens the draft.** Diffing Week 13's draft →
   fact-checked → final shows the fact-checker and editor deleting
   callbacks ("We called that decline structural back in Week 9"), color,
   and character beats. The best version of each episode was the draft.
4. **The two liveliest devices are underpowered.** The only two genuine
   disagreements in 11 weeks (the w12 Davis Martin argument, the w14
   split pick) were the best content in the run — and nothing in the
   pipeline asks for them. Continuity exists but is delivered via a
   mechanical "since Week X" tic recycling five storylines.
5. **Ads: right register, no ladder.** The 2026-07-02 refresh got the
   GTA-satire tone, but 8 of 10 spots share one skeleton
   (hook-question → brand → flat claim list → single punchline) with no
   in-spot escalation, and the library is hand-written — no generation or
   review pipeline.
6. **No playoff-race treatment.** The league's playoffs are the top 8 of
   the official H2H standings (category record by win %), but the show's
   "top 8" framing was roto-based — an editorial misalignment with how
   the league is actually won. No cutline math, no seeds, no remaining
   schedule.
7. **Single hard-coded segment.** Pipeline, CLI, datapack, and prompts
   are weekly-recap-specific; no special editions possible.
8. **TTS is flat.** Per-turn `eleven_multilingual_v2` with a fixed 0.25s
   gap — no emotional direction, no reactions, robotic pacing.

## What nextgenpodcast changes

| Area | v1 | v2 |
|---|---|---|
| Hosts | anonymous HOST/GUEST | named cast with personas, running bits, a scored Prediction Ledger (`docs/nextgenpodcast/show-bible.md`) |
| Variation | fixed template | showrunner stage plans each episode against recorded history (cold opens, textures, sign-offs rotate; banned-crutch list) |
| Script chain | draft → fact-check → edit (flattens) | rundown → draft → fact-check → **punch-up** → edit, with continuity claims *verified* (against prior takeaways + ledger) instead of deleted, and an explicit protected-content list for the editor |
| Standings | roto-first | **playoff-race-first**: official H2H standings, seeds, cutline gaps, momentum, remaining schedule (`PlayoffRacePack`) |
| Segments | 1, hard-coded | segment registry; weekly-recap v2 + all-star per-team deep dives; specials are additive |
| Ads | hand-written static library | style-guide-driven generation + critic pass (5-beat escalation anatomy), library JSON + render command (`docs/nextgenpodcast/ads.md`) |
| TTS | per-turn multilingual v2 | ElevenLabs v3 dialogue with audio tags, automatic fallback to v1-style per-turn TTS (tags stripped) |
| Memory | takeaways only | takeaways + show state (ledger with per-host records, bits/cold-open history) |
| Models | claude-opus-4-6 | claude-opus-4-8 (constants per stage) |

## Architecture

```
gkl/nextgenpodcast/
  __init__.py     — model constants
  showbible.py    — show-bible loader/sections; Cast (speaker→voice map)
  showstate.py    — per-league persistent state: Prediction Ledger
                    (open/graded, per-host records), episode history
                    (cold opens, sign-offs, textures, bits)
  datapack.py     — PlayoffRacePack (official H2H standings by cat-record
                    win%, seeds, cutline gaps, momentum, remaining
                    schedule) layered on the v1 weekly datapack;
                    TeamSeasonPack for deep dives
  seed.py         — segment-generic Skipper seed runner
  showrunner.py   — rundown stage; parses LEDGER GRADES / NEW LEDGER
                    ENTRIES back into show state
  scriptcraft.py  — draft → fact-check → punch-up → edit → takeaways;
                    tag-aware script parser (cast-defined speakers);
                    TTS normalization (reused from v1)
  dialogue.py     — v3 text-to-dialogue renderer + per-turn fallback
  ads.py          — ad generation (writer + critic vs style guide),
                    library JSON, render, LRU rotation (reuses v1 helpers)
  segments.py     — SegmentSpec registry (weekly-recap-v2, all-star-deep-dive)
  pipeline.py     — generic orchestrator (per-segment stage graph)
  cli.py          — `gkl-nextgenpodcast weekly | all-star | ads ...`

docs/nextgenpodcast/
  show-bible.md               — cast, playbook, editorial rules (code-loaded)
  segments/weekly-recap.md    — 7 stage prompts (code-loaded)
  segments/all-star-deep-dive.md — special-edition prompts (code-loaded)
  ads.md                      — GTA-ad anatomy + rules (code-loaded)
```

Reused from v1 (imported, not modified): `gkl.podcast.mixer`,
`gkl.podcast.recipe`, `gkl.podcast.assets` (TTS/music/SFX clients),
`gkl.podcast.voice` (key loading), `gkl.podcast.datapack` (weekly pack
builder + dataclasses), `gkl.podcast.source_builder` (formatters),
`gkl.skipper` (`Skipper.run_once`), and the committed music/stinger
assets under `assets/podcast/weekly-recap/`.

Outputs: `data/podcast/<league_key>/nextgen/<episode_slug>/…` with all
intermediates (datapack, spine, rundown, draft, fact-checked, punched-up,
final, tts, takeaways, mp3s, manifest). Show state:
`data/podcast/<league_key>/nextgen/show-state.json`.

## The Prediction Ledger (mechanics)

- Predictions are planted by the showrunner (`PLANT: <speaker> | …`) and
  confirmed by the takeaways stage from the final script; the pipeline
  writes them into show state with ids, week, speaker.
- Grades are proposed by the showrunner (`GRADE: <id> | correct|wrong |
  reason`) only when the week's data settles them; the pipeline applies
  them and updates per-host W-L records.
- The ledger (open predictions + records) is injected into the
  showrunner, draft, and fact-check prompts — so on-air record claims are
  verifiable facts, not vibes.

## Multi-tenant readiness (future service — design constraints honored now)

- No hardcoded league shape: team count comes from the league object;
  playoff spots default to 8 but are a `LeagueShowConfig` field.
- All per-league state (episodes, show state, ad rotation) is keyed under
  `data/podcast/<league_key>/`; nothing global mutates per episode.
- The show bible loader takes an override path — a future per-league bible
  (different show name, cast, bits) is a file swap, no code change.
- Prompts reference the league only via tokens; ads are league-agnostic
  by rule.
- Costs logged per episode in the manifest (LLM call count + TTS chars).

## Decision log

- **2026-07-03 — package created.** v1 preserved as-is; v2 is a parallel
  package importing v1 infrastructure. Rationale: user explicitly asked to
  preserve current capability while building the next generation.
- **Models: `claude-opus-4-8`** for all creative/verification stages
  (seed, showrunner, draft, fact-check, punch-up, edit, takeaways, ads).
  Current recommended Opus; per-episode LLM spend remains trivial next to
  TTS. Constants in `gkl/nextgenpodcast/__init__.py`.
- **Punch-up before editor, fact-check before punch-up.** Punch-up may
  not touch numbers (so it can't introduce stat errors after the check);
  the editor gets an explicit protected list because the w13 diff proved
  the polish stages were deleting exactly the beats the show needs.
- **Fact-checker now receives prior takeaways + ledger** and is
  instructed to *verify* continuity claims rather than strip them — the
  root cause of the flattening was continuity claims being unverifiable
  against the data pack alone.
- **Playoff race = official H2H standings** (category record ranked by
  win %, matching `gkl.skipper._tool_h2h_standings`), computed in-process
  from season matchups already fetched — no new Yahoo calls. Remaining
  schedule fetched from future-week scoreboards (preview matchups).
- **Speaker labels HAWK/WEBB** (cast-defined, parser takes them from the
  Cast) — names in the script artifacts make persona drift visible in
  review.
- **v3 dialogue TTS with fallback.** `eleven_v3` text-to-dialogue gives
  emotional delivery via audio tags; availability varies by plan, so the
  renderer probes once and falls back to the v1 per-turn path with tags
  stripped. Tag whitelist enforced at parse time so a fallback render
  never speaks bracket junk.
- **Ads are generated, then criticized, then rendered.** The style guide
  is the contract; the critic pass rejects spots missing the escalation
  ladder or reusing an opening frame. Library lives in
  `assets/podcast/ads/nextgen/library.json` + mp3s; rotation reuses v1's
  LRU helpers with a v2 state file.
- **Specials plant one ledger entry each** (final-standing call) —
  gradeable at season end; weekly grades are capped at 3/episode to keep
  the device scarce.
- **2026-07-04 — "My Guy" is canon (user feedback).** Listeners grew
  attached to the greeting, so it stays as the show's required cold-open
  handshake and becomes Webb's on-air nickname; only the worn-out full
  clause "my guy alongside me as always" stays banned, and the wrapping
  sentence must vary weekly. Punch-up ADDS the greeting if a draft lacks
  it.
- **2026-07-04 — The Lounge Line (user feedback).** Every weekly episode
  carries one listener call between Act 2 and the second ad break: its
  own sting (`assets/podcast/nextgen/callin-stinger.mp3`, rendered via
  `gkl-nextgenpodcast assets`), a NEW fictional caller each week
  (showrunner invents name/town/persona from the seed's "Lounge Line
  fodder"; voice picked from the 10-voice account pool, validated
  against recent-caller history, random fresh fallback), a question or
  hot take about a manager's roster/waiver decisions, and a phone-line
  EQ (300-3400 Hz + compression) on the caller's turns only — so the
  call-in always renders per-turn while the acts can use v3 dialogue.
  The caller may be confidently wrong ON AIR only if a host corrects the
  record (fact-checker rule 11). Script format gains a `CALL-IN` block
  (`CALLER:` speaker) between ACT 2 and ACT 3; the parser requires it
  for the weekly segment. Callers are recorded in show state so
  names/personas/voices don't repeat within a season.

- **2026-07-04 — ad refinement (user feedback on the first generated
  batch).** The 2026-07-03 batch ran long (100-115 words), confessed its
  own jokes ("a number we made up but stand behind fiercely"), and leaned
  on divorce gags. New bar: 45-75 words (hard ceiling 80, code-enforced),
  "the ad never knows it's the joke" — damning facts delivered as pride,
  never as winks (style guide now carries a bad→good rewrite table) —
  and no divorce/breakup or personal-misfortune humor (deterministic
  banned-terms backstop in `generate_ad_batch`, applied after the critic).
  The old batch is archived (mp3s in `ads/nextgen/_archive_2026-07-04/`)
  and a hand-written nine-spot batch at the new bar seeds the library;
  render with `gkl-nextgenpodcast ads render`.

## Status

| # | Work item | Status |
|---|---|---|
| 1 | Current-state review (code + prompts + 11 episodes) | ✅ Done |
| 2 | Show bible, ad style guide, weekly v2 + deep-dive prompt artifacts | ✅ Done |
| 3 | showbible/showstate loaders + tests | ✅ Done |
| 4 | datapack v2 (PlayoffRacePack, TeamSeasonPack) + tests | ✅ Done |
| 5 | seed/showrunner/scriptcraft chain + tests | ✅ Done |
| 6 | dialogue renderer (v3 + fallback) + tests | ✅ Done |
| 7 | ads v2 generation pipeline + tests | ✅ Done |
| 8 | segments registry, pipeline, CLI, entry point | ✅ Done |
| 9 | "My Guy" canon + Lounge Line call-in (bible, prompts, parser, phone-filter renderer, recipe, state, CLI, tests) | ✅ Done |
| 10 | Render the Lounge Line sting | ⬜ Ready — `gkl-nextgenpodcast assets` (one-time, before the first weekly run) |
| 11 | Live end-to-end weekly episode | ⬜ Ready — `gkl-nextgenpodcast weekly` |
| 12 | Live all-star series run | ⬜ Ready — `gkl-nextgenpodcast all-star --all` |
| 13 | Generate + render first v2 ad batch | ⬜ Ready — `gkl-nextgenpodcast ads generate` then `ads render` |
