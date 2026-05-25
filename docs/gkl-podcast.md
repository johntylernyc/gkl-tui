# GKL Podcast

Overview: 
The goal of this feature is to use the available data and insights we've been able to create in our application, and generate a podcast that discusses the league. 

Capabilities:
- Use the data capabilities of our application to retrieve the relevant datasets from the various APIs we use.
- Prepare and pre-process this data in a way that it can be provided to an endpoint in a clear and well documented manner. 
- Leverage the Google Podcast API to send this data to and generate the audio podcast. 
- Update our application to create a "News" page in our application, navigated to from the homepage like any of the other features in our appplication, where users can select a link to stream the podcast online in their browser.

Requirements:

We think this will expand over time to have all sorts of different versions of the podcast, we can think of each of these versions as "Segments". Each segment will have a general theme and cadence at which it runs. For example: 

- Weekly recap: a segment that runs on Mondays that recaps the matchups from the week prior. The podcast quickly summarizes each matchup's results, and then jumps into the big stories from that week. Which teams surged or tanked, standout performances from individual teams or players, key transactions, and a brief commentary on the week ahead and what to expect. Available once weekly on Monday 7am est, 8-10 minutes in length. 
- Daily dive: a daily episode that goes over yesterday's team performances and each of their matchups in that week of the fantasy season. Available daily at 8am est, 4-6 minutes in length.
- League standings: a zoomed out view of the league, and each team's roto, power rankings, and official h2h standings. How things have changed week-over-week. A discussion of specific manager's and their team's needs or strengths. And, from week 15 forward, commentary on the emerging playoff picture for that league. Available once weekly on Tuesday at 7am est, 8-10 minutes in length.
- The wire: a discussion of available free agents and potential rosters they could add value. Available once weekly on Sunday night at 5pm est, 4-6 minutes in length. 

For the initial version, we just want to get one variant of the podcast working and thoroughly refine. We'll add to the publishing schedule afterward. We will begin with the Weekly recap.

We want each segment to have distinct host personalities that are consistent episode over episode. The hosts should have names and characteristics that persist. We are a bit indifferent to the specifics here provided the requirement is met. The podcasts described above will target a league-wide audience for now. The hosts should take the role of traditional sports analysts and news media personalities. The personalities can be both complimentary and critical of individual teams and decisions in the league. They should mostly remain professional (but not cold, we want them to be engaging). 

We will use Google Podcast API, or a suitable alternative. The general idea is that we wil prepare data packs using the calls we make in our application elsewhere (e.g., h2h sim, standings, etc) and that these will become data packs for the Podcast API. We think it might be beneficial if we define the types of questions or analyses we want to be a recurring part of each segment so the Podcast API can produce something that feels consistent over episodes. Of course, like any broadcast, there should be some variation to keep things feeling fresh. 

Pre-requisites: 

In addition to the holistic data packs we want to provide the podcast API, we want to re-use some of the functionality in ask-skipper.py to get some insights about the league and more interesting datasets than the base data that is being returned when we make API calls. This will also ensure some consistency between the podcast content and the analysis provided by our application llm. Thus, before we can begin work on this feature, we would like to revisit our current ask-skipper.py functionality, and specifically we need to update the skiills, tools, and scripts to reflect our current application and recent improvements: 

1) we've recently added a trade analyzer with 3 trade modes that should be used to improve our analyze trade capabilities in ask-skipper,
2) we've recently incorporated learnings from our trade analyzer into our "compare player" functionality, and in cases where free agents are being evaluated against a team's current roster this analytical view should be taken into consideration
3) we've expanded the capabilities of our mlb game feature and so questions about MLB game outcomes as they relate to fantasy team performance and otherwise should be able to leverage these
4) we generally want to review the work on ask-skipper.py to date to see where we can improve the agent's ability to retrieve data and answer user questions. 

Note: We don't want to overly constrain the podcast API to the ask-skipper capabilities, as we generally believe an API like Google's NotebookLM will out-perform our agent's naive capabilities. The goal here is to incrementally improve ask-skipper.py while doing this work to create some alignment in the narrative and analyses being shown to users, while generally leveraging the 3rd party podcast api as fully as possible to get the best outcomes. 

Skipper refactor complete — takeaways from v0.6.2:

The skipper refactor shipped as v0.6.2 and lays the groundwork for podcast seeding. Tools Skipper can now call: `get_league_standings`, `get_h2h_standings`, `analyze_strength_of_schedule`, `get_matchup_scoreboard`, `get_weekly_recap`, `get_team_roster`, `find_trade_targets`, `analyze_trade`, `discover_trade_scenarios`, `compare_add_drop`, `get_mlb_scoreboard`, `get_mlb_boxscore`, `get_statcast_profile`, `get_free_agents`. These are the same tools that should back the "suggested topics" half of each podcast data pack.

Hardening learnings worth preserving when we build the podcast pipeline:

- Player availability must be tagged explicitly. Every player listed by Skipper tools now carries one of `[ACTIVE]`, `[BENCH — active]`, `[BENCH — healthy; SPs rotate through bench on rest days]`, `[INJURED/IL]`, `[NOT-ACTIVE …]`, or `[FREE AGENT]`. The podcast data packs should carry the same tags so the podcast API doesn't speculate about injuries or mistake a bench SP on a rest day for a drop candidate.
- NA players don't count against max roster size. This is easy to miss; Skipper had to be taught it explicitly. Podcast hosts commenting on roster moves should inherit the same rule.
- Every named current-season claim has to be grounded in data just pulled by a tool call — no characterizing a player from memory. The podcast pipeline should pass the actual current-year line, not rely on the model's prior.
- Statcast (xBA, xSLG, xERA, Barrel%, HardHit%) is required context before endorsing a pickup or trade target. Podcast segments that discuss "standout performances" or "who to watch" should include Statcast regression signals in the data pack so the hosts can distinguish sustainable performance from luck.
- Prompt formatting rules (no markdown tables, no heavy `**bold**` / `###` / `---`, no ΔRoto-style shorthand): these were tuned for TUI consumption. For podcasts, the analog is "the hosts should speak in flowing analyst language," and the data pack should avoid shipping pre-formatted prose that the hosts will awkwardly read verbatim.

Skipper will keep improving independently of the podcast — we expect more tools and better prompts over time. The podcast implementation should treat Skipper's toolkit as a dependency we can call into, not a fixed API.

Data pack structure:

Each podcast data pack (one per episode) has two halves:

1. Raw datasets — the large, objective views the podcast API can analyze directly. These are the outputs of the same tools Skipper uses, serialized without editorial commentary:
   - League roto standings (all teams, all categories, points and ranks)
   - H2H records and power rankings
   - Strength-of-schedule table (actual record vs. power-ranking record vs. luck factor)
   - Weekly matchup scoreboards for the segment's time window
   - Full rosters for all teams with availability tags, season stats, and trailing-window stats (last7/last30)
   - Transactions log (trades, adds, drops) for the window
   - Statcast profiles for players the data pack highlights (not every player — just the ones the segment calls out)
   - MLB game context where relevant (who won/lost, key player lines)
   The podcast API consumes these datasets and does its own pattern-finding and analysis.

2. Suggested topics — a shorter file produced by running Skipper against the segment's prompt template. This gives the podcast API a narrative spine to lean on: which stories stood out, which teams surged or tanked, which transactions mattered, which matchups are worth highlighting. The suggested-topics output grounds the podcast in the same analytical framing users see in Ask Skipper, so the narrative feels consistent with the app.

Model policy for Skipper-seeded podcast generation:

When Skipper is invoked to produce the suggested-topics half of a data pack, it must use `claude-opus-4-6`, not the default Sonnet. Podcast generation runs infrequently (one segment per schedule slot) and is worth the stronger reasoning. The default Skipper model in the interactive "Ask Skipper" feature remains `claude-sonnet-4-6` — this rule only applies to the podcast seeding code path. Expose this as a constant (e.g. `SKIPPER_PODCAST_MODEL = "claude-opus-4-6"`) so it's easy to audit and swap later.

Open questions: 

This application runs both locally and is hosted on the web via railway.com; We're not yet sure the best way to have these generated and served to users. For the initial version, we're ok with not having these episodes generated on a schedule but instead triggered on-demand. I think the long-term version is a scheduled series of programs where past podcasts act as input to future ones, but right now we just want to be able to programmatically generate the podcast and prove the concept. We'll need options to consider how best to incrementally build this. 

Confirm access to Google's NotebookLM API to create engaging podcasts programmatically. If this isn't available, discovery to find a suitable alternative. 

The data pack formats that are provided to the podcast api should be informed by the service we use and it's recommendations for best practices in providing data to use.

How best to get each of the segments to maintain a consistent theme/structure while not being overly formulaic. The implementation plan will need to take on a producer role to decide the format for each segment and give named recurring segments and some guardrails without overly constraining the llm generation the podcast. The segments, structures, personalities of the hosts, and other guardrails should be defined in an artifact in our project so that we can come back to and refine these over-time. We should maintain seperate files for each segment.

How to store the generated mp3s for historic retrieval and to surface a broadcast library.

How much will this cost? We'll want to monitor cost during development as well.

Assumptions:

We can build this in a way that works for both the terminal application running locally as well as the deployed version on gklbaseball.com using railway.com as the infrastructure provisioning provider (as is currently the case). When we get to serving this through the publicly hosted site, the podcasts should require a login/league auth to listen and a user should only be able to listen to episodes related to their league.

MVP:

A single example of the weekly recap using data provided by the application that can be used to refine and iterate the podcast generation process before moving onto figuring out how to do this in a repeatable way.

Housekeeping:

This .md file will act as a place to store all decisions made in the course of developing this capability, as well as a project tracker. The implementation plan should be captured at the start in this file and this file should be regularly updated throughout development. trade-analyzer.md is a good example of what "good" looks like for using the markdown to update progress throughout development. At the end of development, we want to capture any future opportunities or work that was not completed as issues in our remote repository (similar to how we did issues #10 an #11 in our remote repo after work on trade-analyzer.md wrapped).

---

## Implementation Log

### Plan (approved 2026-04-24)

**MVP scope:** On-demand generation of a single Weekly Recap episode end-to-end, produced locally. Web surfacing and scheduling are post-MVP.

**Audio service decision:** ElevenLabs self-serve (Creator tier) using individual APIs rather than the gated Studio Projects orchestration API. We own the mixing so we aren't blocked on a sales conversation.

**Episode shape (three-act body with two ad breaks):**

```
intro_stinger → intro_music
body_act_1  (Studio Podcast call 1 of 3)
ad_break_stinger → ad_1 → returning_stinger
body_act_2  (Studio Podcast call 2 of 3)
ad_break_stinger → ad_2 → returning_stinger
body_act_3  (Studio Podcast call 3 of 3)
outro_music → outro_stinger
```

Body is split into three acts because the Studio Podcast API returns a single mp3 without timestamps — the only way to cleanly insert ad breaks is to fire three separate calls and stitch them. Each act uses `instructions_prompt` to shape the hosts' hand-offs into/out of commercial breaks. Total character count across the three acts ≈ one monolithic call, so cost is unchanged.

**Locked decisions:**

1. **Asset vs per-episode split.** Music beds, stingers, and ad spots are generated once via ElevenLabs APIs, committed under `assets/podcast/`, and reused every episode. Only the voice track (three Studio Podcast calls) is generated per episode. Keeps per-episode spend effectively flat.
2. **Ad library.** 10–15 fictional sports-radio-style spots (supplements, "legitimate" products, cheeky PG-13 tone). Rendered via single-voice TTS (`POST /v1/text-to-speech`) with a dedicated announcer voice — cheaper and more deterministic than Studio Podcast for a 15-second spot. Ad selector picks 2 non-repeating ads per episode via an LRU state file so the same two don't air two weeks in a row.
3. **Mixing engine.** ffmpeg wrapped in `gkl/podcast/mixer.py`. A Python recipe declares slot order + mix directives; mixer translates it into one `-filter_complex` invocation per episode with `afade` for transitions and `loudnorm` to -16 LUFS podcast standard.
4. **Recipe format.** Python dataclasses in `gkl/podcast/recipe.py` for MVP. `docs/podcast-segments/weekly-recap.md` documents hosts, asset prompts, topic partitioning — reviewable but not loaded by code initially. Promote to YAML-front-matter-driven recipes if we find ourselves re-tuning them frequently.
5. **Skipper seeding model.** `SKIPPER_PODCAST_MODEL = "claude-opus-4-6"` in the podcast pipeline only. Interactive "Ask Skipper" stays on Sonnet 4.6 default.
6. **MVP body-music policy.** Intro/outro music only; the body is voice-only (no bed under dialogue). Revisit if episodes feel bare after first listen — adding a ducked bed is an isolated mixer change.
7. **Storage.** Per-episode artifacts under `data/podcast/<league_key>/<episode_slug>/`. Web storage + episode library UI are post-MVP.

### Planned phases

| # | Phase | Status |
|---|-------|--------|
| 1 | Data pack builder — raw datasets half | ✅ Done |
| 2 | Skipper seed → suggested topics (Opus 4.6) | ✅ Done |
| 3 | Source document builder (three-act partitioning + Studio Podcast source text) | ✅ Done |
| 4 | Voice track generation (Studio Podcast client, poll/webhook) | ✅ Done |
| 5 | Asset generation (music, stingers, ads, ad selector) | ✅ Done |
| 6 | Mixer (ffmpeg engine + recipes) | ✅ Done |
| 7 | End-to-end pipeline + CLI entry point | ✅ Done |
| 8 | Segment artifact: `docs/podcast-segments/weekly-recap.md` | ✅ Done (rolled into Phases 2, 5, 6) |
| 9 | Web "News" page | ⬜ Post-MVP |

### Open items to resolve during build

- Host names + personalities (drafted in segment artifact, Phase 8)
- Specific ElevenLabs voice IDs for the two hosts and the ad announcer
- Provision ElevenLabs account + API key before Phase 4
- Per-episode cost tracking (log character counts + API calls to a running ledger)

### Phase 1 — Data pack builder (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`.

**Key files:**
- `gkl/podcast/__init__.py` (new; exposes `SKIPPER_PODCAST_MODEL`)
- `gkl/podcast/datapack.py` (new; `build_weekly_recap_datapack` + dataclasses)
- `tests/test_podcast_datapack.py` (new; 6 unit tests)

**Decisions:**

1. **Datapack is a pure data assembly, not narrative.** The module calls the same underlying Yahoo/MLB/stats primitives Skipper's tools wrap, but returns dataclasses serialized to JSON — no editorial framing. Narrative (suggested topics) is produced separately in Phase 2. This keeps the raw-data half testable in isolation and lets us swap narrative engines without rewriting the data layer.
2. **Concurrent fetches with `asyncio.gather`.** Season team stats, per-week scoreboards (1..current-1 for H2H records), target-week scoreboard, transactions, and weekly-dates are fetched in parallel. Rosters (per-team, season + last30) and MLB context (per-day of the target week) are fetched in a second round once the week window is known. Total wall time for a mid-season 18-team league is bounded by ~2 round-trips of concurrent Yahoo calls plus MLB.
3. **Availability tag reused from Skipper verbatim.** Imported `_availability_tag` from `gkl.skipper` rather than duplicating the logic — the spec explicitly calls out that podcast data packs should carry the same tags as Skipper tools. Leading underscore is convention only; any future change to the tag format needs to stay in one place.
4. **H2H records filter on `status == "postevent"`.** In-progress or preview matchups are excluded — avoids counting current-week partial tallies. Weekly recap is always about a completed week, but including the filter keeps the data pack correct if the pipeline ever fires mid-week.
5. **Target-week transaction flagging.** Each transaction carries an `in_target_week` boolean rather than pre-filtering the list — downstream stages can show "week's moves" as the primary cut while still having the full 200-transaction window available for trend context ("Smith has been dropped three times this month").
6. **Statcast profiles deferred to Phase 2.** Highlights depend on which players the narrative calls out — fetching a profile for every rostered player would be wasteful. Phase 2 will decide the highlight set and fetch just those.
7. **Strength-of-schedule deferred.** The full SOS computation in `skipper._tool_strength_of_schedule` is substantial; the raw ingredients (per-week team stats, per-week matchups, season roto) are sufficient for Phase 2 to derive SOS if the suggested-topics prompt asks for it. Extracting SOS into `gkl/stats.py` as a pure function is a follow-up if we find we need it server-side.

**Output structure:** `data/podcast/<league_key>/<season>-w<NN>/datapack.json`.

### Tasks

| # | Task | Status |
|---|------|--------|
| 1 | Create `gkl/podcast/__init__.py` with `SKIPPER_PODCAST_MODEL` | ✅ Done |
| 2 | Define `DataPack` dataclass schema (meta, teams, roto, H2H, power, matchups, rosters, transactions, MLB games) | ✅ Done |
| 3 | Implement `build_weekly_recap_datapack` with concurrent fetches | ✅ Done |
| 4 | Wire computed derivations (roto entries, H2H records, power rankings) | ✅ Done |
| 5 | Implement `DataPack.write_to(path)` with JSON serialization | ✅ Done |
| 6 | Unit tests for helpers + roundtrip | ✅ Done |
| 7 | Integration test against a live Yahoo session | ⬜ Deferred to Phase 7 (CLI smoke test) |

### Phase 2 — Skipper seed for suggested topics (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`.

**Key files:**
- `docs/podcast-segments/weekly-recap.md` (new; segment config + prompt template)
- `gkl/podcast/skipper_seed.py` (new; prompt parser + runner)
- `gkl/skipper.py` (added `Skipper.run_once()` method)
- `tests/test_podcast_skipper_seed.py` (new; 9 unit tests for parser + substitution)

**Decisions:**

1. **Segment Markdown is the source of truth for prompts.** The Phase 2 prompt template lives in `docs/podcast-segments/weekly-recap.md` under `## Skipper seed (Phase 2)`, split into `### System addendum` and `### User prompt` sub-sections. Non-engineers can edit prompts without touching Python. Rationale: as more segments come online (daily dive, wire, standings), each needs its own distinct voice and prompt — keeping prompts with the segment config avoids drift and makes segments self-contained units.
2. **Prompt parser over frontmatter.** Used a small regex-based section extractor (no YAML dep) that pulls the body under named `### ` headings. Strips leading/trailing blank lines and trailing `---` horizontal rules so the extracted text is clean prompt content. Raises on missing sections so we fail loud if the segment artifact structure drifts.
3. **Token substitution at call time.** Prompt templates use `{league_name}`, `{season}`, `{target_week}`, `{week_start}`, `{week_end}` tokens. Unknown tokens raise `KeyError` — better to crash during seed than to ship a broken episode with a literal `{target_week}` in the source document.
4. **`Skipper.run_once()` is a sibling of `chat()`, not a refactor.** Added a new non-interactive entry point on the existing Skipper class rather than refactoring `chat()` into shared helpers. Reasoning: the interactive loop and the podcast seed have different needs (history tracking, max_tokens, max_iterations) and sharing code risks destabilizing the interactive Skipper users rely on. Duplication here is ~30 lines; the code paths can diverge further if one needs to.
5. **`run_once()` defaults: 4096 max_tokens, 25 max_iterations.** Seeds need longer output than chat replies (full three-act narrative) and more tool calls (standings + H2H + matchups + multiple rosters + multiple Statcast profiles). Interactive chat stays at 2048/10 for responsiveness.
6. **Skipper state is isolated per seed run.** `run_once()` builds a fresh `messages` list rather than appending to `self.history` — each podcast generation is self-contained and can't be polluted by a stale interactive session on the same Skipper instance. The Skipper constructor is also called fresh per episode in `seed_weekly_recap()`.
7. **Prompt shape enforces structure.** The system addendum explicitly asks for `## Act 1` / `## Act 2` / `## Act 3` headers with `### Story Title` subsections and forbids preambles. This gives Phase 3's source-document builder a deterministic shape to partition on.
8. **Statcast grounding is non-negotiable.** The prompt requires `get_statcast_profile` calls before any player endorsement — mirroring the same rule established during the Skipper v0.6.2 refactor. Podcast hosts commenting on "standout performances" must distinguish sustainable from lucky or the episode sounds like it's reciting a stat line.

**Usage shape** (to be wired into Phase 7 pipeline):

```python
from gkl.podcast.skipper_seed import seed_weekly_recap

suggested_topics_md = await seed_weekly_recap(
    api=yahoo_api, league=league, categories=categories,
    target_week=4, week_start="2026-04-14", week_end="2026-04-20",
)
(episode_dir / "suggested-topics.md").write_text(suggested_topics_md)
```

### Tasks

| # | Task | Status |
|---|------|--------|
| 8 | Create `docs/podcast-segments/` directory + `weekly-recap.md` skeleton | ✅ Done |
| 9 | Draft Phase 2 prompt template (system addendum + user prompt) | ✅ Done |
| 10 | Implement prompt-section extractor + token substitution | ✅ Done |
| 11 | Add `Skipper.run_once()` non-interactive entry point | ✅ Done |
| 12 | Implement `seed_weekly_recap()` public API | ✅ Done |
| 13 | Unit tests for parser, substitution, shipped artifact | ✅ Done |
| 14 | Integration test against live Skipper (requires API key) | ⬜ Deferred to Phase 7 (CLI smoke test) |

### Phase 3 — Source document builder (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`.

**Key files:**
- `gkl/podcast/source_builder.py` (new; act splitter + data formatters + EpisodeSource assembly)
- `tests/test_podcast_source_builder.py` (new; 13 unit tests)

**Decisions:**

1. **Split on `## Act N` headers, fail loudly if any act is missing.** The Phase 2 prompt explicitly asks for three `## Act 1/2/3` headers, so downstream parsing can rely on them. If Skipper returns a malformed output (missing act, no headers), `split_suggested_topics()` raises `ValueError` rather than silently producing a two-act episode.
2. **Narrative beats drive act-specific data payloads.** Act 1 gets scoreboard + standings + power rankings (needed for recap framing). Act 2 gets transactions + H2H records + full standings (for momentum framing). Act 3 is narrative-only — the Phase 2 Skipper pass already baked Statcast numbers into the highlights, so there's no value in re-shipping raw stats. Keeping each act's source doc focused reduces Studio Podcast's token count and sharpens what the hosts talk about.
3. **Prose data summaries, not tables.** Per the Skipper refactor takeaway, hosts trip over pre-formatted tables when reading naturally. Scoreboard lines read like "Alpha defeated Beta, 12 categories to 6"; standings like "1. Alpha (Ann): 180.5 roto points" — one fact per line, no columns.
4. **Ad breaks are shaped in `instructions_prompt`, not `source_text`.** Each act's instructions tell the Studio Podcast hosts whether to cold-open, welcome listeners back, or sign off. The source text stays focused on what to discuss; the instructions control the shape of the act.
5. **Acts 2 and 3 explicitly forbid re-introduction.** Instructions use "Do NOT re-introduce yourselves or the show" and prescribe a "welcome-back" opener. Without this, Studio Podcast defaults to generating complete mini-podcasts with fresh intros, which would make the stitched episode sound like three separate shows.
6. **Instructions share a base host-persona string.** Every act starts with the same "two hosts of the GKL Fantasy Baseball Weekly Recap, sports analysts, PG-13, flowing language" framing so tone stays consistent across acts. Only the act-specific directives (cold-open vs welcome-back vs sign-off) differ.

### Tasks

| # | Task | Status |
|---|------|--------|
| 15 | Implement `split_suggested_topics()` act splitter | ✅ Done |
| 16 | Implement per-dataset prose formatters (scoreboard, standings, H2H, transactions) | ✅ Done |
| 17 | Implement `_data_summary_act_N()` for each act | ✅ Done |
| 18 | Implement `_build_instructions()` per-act shaper | ✅ Done |
| 19 | Implement `build_episode_sources()` public API | ✅ Done |
| 20 | Unit tests covering parsing, formatters, full assembly | ✅ Done |

### Phase 4 — Voice track generation (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`. **Integration still blocked on ElevenLabs API key provisioning.**

**Key files:**
- `gkl/podcast/voice.py` (new; Studio Podcast client + orchestration)
- `tests/test_podcast_voice.py` (new; 15 unit + mocked-HTTP tests)

**Decisions:**

1. **Thin async client, not a full SDK wrapper.** `StudioPodcastClient` only wraps the four endpoints we actually need (create, get project, list snapshots, stream audio). Anything else would be speculative. If later phases need more endpoints we can add them.
2. **Poll rather than webhook for MVP.** The Create Podcast API supports `callback_url` webhooks but that requires a public endpoint. For local on-demand generation, polling is simpler and zero-infra. Default poll interval 5s, max wait 900s (15 min). Webhook mode can be added when we deploy to Railway.
3. **Three acts render in parallel via `asyncio.gather`.** ElevenLabs rendering is the long pole of episode generation (likely 60-120s per act). Firing all three sequentially would take 3–6 minutes; parallel brings it down to the slowest act's render time plus a bit. If ElevenLabs rate-limits concurrent requests for conversation mode, we'll learn that on first integration run.
4. **Snapshot discovery: list-latest pattern.** After the project finishes rendering, list all snapshots and take the one with the highest `created_at_unix`. More robust than trying to pluck `current_snapshot_id` out of a specific sub-object in the project response (docs are ambiguous about where that field lives).
5. **`convert_to_mpeg=true` on audio download.** The stream endpoint returns `text/event-stream` by default; with `convert_to_mpeg=true` we get raw mp3 bytes suitable for direct write to disk. Simpler than parsing SSE.
6. **Flexible project-id extraction.** `extract_project_id()` handles both `{"project": {"project_id": "..."}}` and `{"project_id": "..."}` shapes — ElevenLabs doc revisions have shown both patterns. Falling back rather than failing avoids a brittle integration.
7. **API key loading mirrors the Anthropic pattern.** Env var (`ELEVENLABS_API_KEY` or `GKL_ELEVENLABS_KEY`) → per-user web-mode file → local config at `~/.config/gkl/elevenlabs.json`. `save_elevenlabs_key()` exposed for a config command (to be wired in Phase 7 if needed).
8. **Widened timeout on audio download.** Default `httpx` timeouts are too short for a multi-minute streaming download. Download client uses 300s; everything else uses 60s.
9. **Config surface is the voice/model/duration fields, not transport settings.** `StudioPodcastConfig` only exposes `host_voice_id`, `guest_voice_id`, `model_id`, `quality_preset`, `duration_scale`, and optional `language`. Poll interval and max-wait are arguments to `render_episode_voices` so production tuning lives at the call site.

**Open items unblocking this phase's integration test:**
- Provision an ElevenLabs account (Creator tier, per the cost analysis).
- Decide on two host voice IDs + one ad-announcer voice ID. Document them in `docs/podcast-segments/weekly-recap.md` under `## Voices`.
- Verify that `POST /v1/studio/podcasts` is self-serve on Creator tier. If gated behind "contact sales," we may need to escalate or fall back to composing the episode via `/v1/text-to-speech` per-speaker lines (bigger lift but unblocked).

### Tasks

| # | Task | Status |
|---|------|--------|
| 21 | Implement `StudioPodcastClient` (create, get, list-snapshots, stream) | ✅ Done |
| 22 | Implement `render_episode_voices` parallel orchestrator | ✅ Done |
| 23 | API key loading (env / web / disk), `save_elevenlabs_key()` | ✅ Done |
| 24 | Unit tests: payload shape, response parsing, polling, timeouts | ✅ Done |
| 25 | HTTP mock tests: create, poll, download | ✅ Done |
| 26 | **Live integration test against ElevenLabs** | ⬜ Blocked on API key + voice-ID decisions |

### Phase 5 — Asset generation (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`. ElevenLabs API key is provisioned (`~/.config/gkl/elevenlabs.json`). Ad-announcer + host voice IDs still need to be picked before running the one-time generation script.

**Key files:**
- `gkl/podcast/assets.py` (new; music/SFX/TTS API clients)
- `gkl/podcast/ads.py` (new; 12-spot ad library + LRU selector)
- `gkl/podcast/segments/__init__.py` (new)
- `gkl/podcast/segments/weekly_recap.py` (new; music + stinger asset definitions + `STUDIO_DURATION_SCALE`)
- `scripts/generate_podcast_assets.py` (new; one-time CLI to render everything)
- `tests/test_podcast_ads.py` (new; 13 tests)
- `tests/test_podcast_assets.py` (new; 12 tests)
- `docs/podcast-segments/weekly-recap.md` (updated; mirror of asset prompts for human review)

**Decisions:**

1. **Three APIs consolidated into one module (`assets.py`).** Music, SFX, and TTS share the same base URL, auth pattern, and httpx flow — the only differences are payload fields and URL suffix. Keeping them together avoids three near-identical files. Studio Podcast stays in its own `voice.py` module because it has a multi-step async flow (create → poll → download) that's meaningfully different.
2. **Ad copy as Python module, not external files.** The 12 spots live in `AD_LIBRARY: list[AdSpot]` in `ads.py` — typed, grep-able, diffable. A per-ad `.txt` + `.json` sidecar would add filesystem I/O without buying flexibility. Rendered mp3s are the artifact that gets committed; the copy is source.
3. **12 ads seeded initially.** At 2 ads/episode with LRU rotation, 12 spots means each ad airs once every 6 weeks — enough variety that listeners don't notice repetition, small enough to hand-write and maintain. Can grow the library as we add more segments or want more variety.
4. **PG-13 sports-radio mix (supplements, mattresses, local auto, meat, betting parody, sleep, tax, financial, apparel, food delivery).** Targets the aesthetic the user called out — "things you'd hear on sports radio." Clearly fictional brands, absurdity-adjacent copy, no real product trademarks. Tone notes saved in a project memory so future episodes/segments stay consistent.
5. **LRU rotation state is per-league.** State file at `data/podcast/<league_key>/ad-rotation.json`. Users running multiple leagues each get their own rotation, so ads don't leak across leagues.
6. **Rotation is resilient to library edits.** `_load_rotation` drops slugs that no longer exist in the library and appends newly-added slugs to the tail. We can add/remove ads without resetting the rotation manually.
7. **Music + SFX prompts live in `segments/weekly_recap.py`, not the markdown artifact.** Considered parsing them out of the markdown (like the Phase 2 Skipper prompt) but asset prompts are generate-once-and-forget — parsing overhead isn't worth it. The segment markdown mirrors them in prose for review, but the code is the source of truth.
8. **Music is `force_instrumental=True` by default.** No lyrics to fight the hosts' voices when the bed is ducked under dialogue. Matters less for intro/outro where music isn't layered with voice, but still the right default.
9. **Generation script is idempotent.** Skips assets that already exist on disk unless `--force` is passed. Means you can partially regenerate (change one prompt, delete one file, re-run the script) without burning credits on everything. `--only music/sfx/ads` lets you target a single category.
10. **Voice IDs are env-var input, not committed.** `GKL_AD_ANNOUNCER_VOICE_ID` is required to render the ad library. Voice preference is personal, depends on the user's ElevenLabs library/clones, and shouldn't be hardcoded. Phase 7 will wire up a `gkl config` flow to save voice IDs locally.
11. **STUDIO_DURATION_SCALE = "short".** Each of the three acts targets 2–3 minutes. "short" (<3 min) is the correct duration bucket — "default" (3–7 min) would produce 9–21 minute episodes. This is the fix for the mismatch flagged during the ElevenLabs pricing review.

### Tasks

| # | Task | Status |
|---|------|--------|
| 27 | Implement music, SFX, and TTS API wrappers (`assets.py`) | ✅ Done |
| 28 | Draft 12-spot ad library in `ads.py::AD_LIBRARY` | ✅ Done |
| 29 | Implement LRU ad rotation with per-league state file | ✅ Done |
| 30 | Define `weekly_recap.py` segment config (music + SFX assets) | ✅ Done |
| 31 | Build `scripts/generate_podcast_assets.py` CLI | ✅ Done |
| 32 | Update segment markdown with asset prompts + voice config | ✅ Done |
| 33 | Unit tests: ad library invariants, rotation behavior, API payloads | ✅ Done |
| 34 | **One-time asset generation against live ElevenLabs** | ⬜ Ready — all voice IDs committed, awaiting user run |

### Phase 6 — Mixer (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`. Live ffmpeg smoke tests passing.

**Key files:**
- `gkl/podcast/recipe.py` (new; `Recipe` + `RecipeSlot` generic dataclasses)
- `gkl/podcast/mixer.py` (new; ffmpeg wrapper + `mix_episode` entry point)
- `gkl/podcast/segments/weekly_recap.py` (added `WEEKLY_RECAP_RECIPE` — 13-slot timeline)
- `tests/test_podcast_mixer.py` (new; 11 tests including live ffmpeg smoke tests)

**Decisions:**

1. **Recipe shape: `slots: list[RecipeSlot]` where `kind` may repeat.** The weekly recap has `ad_break_stinger` and `returning_stinger` playing twice each — modeling these as distinct kinds (`ad_break_stinger_1`, `ad_break_stinger_2`) would have cluttered the mapping and made the pipeline do pointless path-duplication. Slot kind is a reference to an asset; the recipe controls sequencing.
2. **One ffmpeg invocation per episode.** No intermediate files, no subprocess pipelining. Single `-filter_complex` command generates the final mp3 in one pass. Easier to audit, easier to reproduce, no cleanup of temp files.
3. **Per-stream `aresample` + `aformat` before concat.** ElevenLabs mp3s are nominally 44.1 kHz stereo, but Studio Podcast / Music / SFX / TTS outputs could drift in sample rate or channel layout. Normalizing each input stream before the concat filter prevents mismatched-input errors that would fail the whole mix.
4. **MVP has no per-slot fades.** Considered supporting `fade_in_ms` / `fade_out_ms` on `RecipeSlot`, but implementing fade-out requires knowing the clip duration, which means either probing with ffprobe or threading duration through the data model — both add complexity before we've heard whether it's needed. ElevenLabs output typically has clean starts/ends. If the first listen reveals abrupt transitions, adding `afade` filters per slot is a localized change.
5. **Loudness target: -16 LUFS.** Podcast platform standard (Apple Podcasts, Spotify). True peak -1.5 dB, LRA 11. Configurable via `Recipe` fields if we ever target a different distribution.
6. **Output bitrate default 192 kbps libmp3lame.** Good perceptual quality for spoken-word content without blowing file sizes. `Recipe` field so we can knob it.
7. **Explicit prerequisite check.** `mix_episode` checks `ffmpeg_available()` before attempting the mix and raises `MixerError` with install guidance if missing. Saves a confusing FileNotFoundError on subprocess.run.
8. **`MixerError` distinct exception type.** Downstream callers (Phase 7 pipeline) can catch it and surface as a user-actionable error without swallowing unrelated `RuntimeError`s.
9. **Live tests use ffmpeg-generated sine waves as fixtures.** The `sine_wave_factory` fixture calls ffmpeg to produce small test mp3s on demand. Tests can verify end-to-end behavior (file exists, duration matches sum of inputs) without committing binary audio fixtures to the repo. Tests auto-skip if ffmpeg isn't on PATH.

### Tasks

| # | Task | Status |
|---|------|--------|
| 35 | `Recipe` / `RecipeSlot` dataclasses in `recipe.py` | ✅ Done |
| 36 | `build_ffmpeg_command` — deterministic filter graph + concat + loudnorm | ✅ Done |
| 37 | `_resolve_slot_inputs` with missing-kind / missing-file error paths | ✅ Done |
| 38 | `mix_episode` public entry point with `MixerError` surfacing | ✅ Done |
| 39 | `WEEKLY_RECAP_RECIPE` 13-slot timeline in segment config | ✅ Done |
| 40 | Unit tests: command shape, input resolution, error handling | ✅ Done |
| 41 | Live ffmpeg smoke tests with synthetic sine-wave fixtures | ✅ Done |

### Phase 7 — End-to-end pipeline + CLI (completed 2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`. End-to-end integration test (live Yahoo + ElevenLabs) still pending — only unblocked once the one-time asset generation runs successfully.

**Key files:**
- `gkl/podcast/pipeline.py` (new; `generate_weekly_recap_episode()` orchestrator + `EpisodeResult` manifest)
- `gkl/podcast/cli.py` (new; argparse-based CLI with `weekly-recap` subcommand)
- `pyproject.toml` (added `gkl-podcast = "gkl.podcast.cli:main"` entry point)
- `tests/test_podcast_pipeline.py` (new; 4 tests including full mocked end-to-end)

**Decisions:**

1. **Sequential phase execution, not parallel.** Phase 1 (datapack) and Phase 2 (Skipper seed) both need week dates — running them in parallel would mean duplicate work or threading dates in as a pre-step. Sequential adds ~5-15s wall time at the low end and keeps the orchestrator readable. Revisit only if generation latency becomes user-visible pain.
2. **Phase 2 reuses dates from Phase 1's output.** `datapack.meta.week_start` / `week_end` are threaded into `seed_weekly_recap()` so the Skipper seed prompt reflects the exact window the datapack summarizes. One source of truth for the episode window.
3. **All intermediate artifacts are kept.** The episode directory ends up with `datapack.json`, `suggested-topics.md`, three `act_N_source.txt` + `act_N_instructions.txt` files, three `act_N.mp3` files, and the final `episode.json` manifest alongside `final.mp3`. All useful for debugging "why did the hosts say X?" and for iterating on prompts without regenerating upstream stages.
4. **`EpisodeResult.write_manifest()` serializes with `Path → str`.** dataclass `asdict()` preserves Path objects which aren't JSON-serializable; the manifest writer walks and stringifies. Simpler than adding a custom encoder.
5. **Cheap char-cost estimate.** The manifest records the sum of the three source texts — a rough proxy for ElevenLabs character usage this episode. Doesn't count music/SFX/ads (those are library assets, zero incremental cost) and doesn't include Studio Podcast's internal script-generation characters (ElevenLabs currently covers that per the pricing page). Good enough for spot-checking cost drift over time without a full billing integration.
6. **CLI is a new entry point (`gkl-podcast`), not a subcommand of `gkl`.** The main `gkl` script launches the Textual TUI; adding argparse subcommands to it would fight the TUI startup. Separate entry point is cleaner and mirrors `gkl-web` which is already established.
7. **League resolution mirrors the TUI's pattern.** `load_credentials()` → `YahooAuth` → `get_user_leagues()` path is identical to `gkl/app.py::main`. `--league <key>` selects explicitly when multiple leagues exist. Single-league accounts auto-pick.
8. **Default target week = current_week - 1.** Weekly Recap recaps the most recently completed week; defaulting to `current_week - 1` makes `gkl-podcast weekly-recap` (no args) produce the "most recent episode" that users would expect. Explicit `--week N` still overrides for backfill / testing.
9. **`--data-root` and `--assets-root` flags are present but optional.** Defaults point to the project-root `data/` and `assets/` directories. Flags allow testing against alternate locations without polluting the real assets.
10. **`_rel()` helper falls back to absolute path outside the project root.** The verbose log prints try to show paths relative to the project root for readability, but tests (and power-users with custom `--data-root`) can live outside it. Safer than letting `relative_to` raise mid-pipeline.

**End-to-end flow:**

```
$ uv run gkl-podcast weekly-recap --week 4
Generating Weekly Recap for GKL (season 2026), Week 4…
[1/6] Building data pack for Week 4…
       -> data/podcast/mlb.l.XXXXX/2026-w04/datapack.json
[2/6] Running Skipper seed (Opus 4.6) for suggested topics…
       -> data/podcast/mlb.l.XXXXX/2026-w04/suggested-topics.md
[3/6] Building three-act source documents…
[4/6] Rendering voice tracks via ElevenLabs Studio Podcast (3 acts in parallel)…
       act 1 -> data/podcast/mlb.l.XXXXX/2026-w04/act_1.mp3
       act 2 -> data/podcast/mlb.l.XXXXX/2026-w04/act_2.mp3
       act 3 -> data/podcast/mlb.l.XXXXX/2026-w04/act_3.mp3
[5/6] Selecting 2 ads via LRU rotation…
       picked: victory-serum, memorial-mattress
[6/6] Mixing episode with ffmpeg…
       -> data/podcast/mlb.l.XXXXX/2026-w04/final.mp3

Episode ready: data/podcast/mlb.l.XXXXX/2026-w04/final.mp3
Manifest: data/podcast/mlb.l.XXXXX/2026-w04/episode.json  (~3,500 chars of ElevenLabs usage)
```

### Tasks

| # | Task | Status |
|---|------|--------|
| 42 | `generate_weekly_recap_episode()` orchestrator | ✅ Done |
| 43 | `EpisodeResult` manifest + JSON serialization | ✅ Done |
| 44 | `_slot_paths_for_weekly_recap()` path resolution | ✅ Done |
| 45 | `gkl-podcast` CLI entry point in `cli.py` | ✅ Done |
| 46 | Register `gkl-podcast` script in `pyproject.toml` | ✅ Done |
| 47 | Mocked end-to-end pipeline tests | ✅ Done |
| 48 | **Live end-to-end run against Yahoo + ElevenLabs** | ⬜ Ready — awaiting asset generation to complete first |

### Pivot: Studio Podcast → TTS-per-turn (2026-04-24)

**Status:** Pivot implemented on `feature/gkl-podcast`. 95 tests passing.

**What happened:** The first live run of `gkl-podcast weekly-recap --week 4` surfaced two latent issues that between them swallowed the Studio Podcast phase:

1. The saved ElevenLabs API key had terminal bracketed-paste escape artifacts (`\x1b[200~` and orphan `~` tail) left over from the paste into `save_elevenlabs_key`. The resulting HTTP headers were malformed and the request bounced at the Google edge with an opaque 400 (not an ElevenLabs error). Fix: hardened `_clean_key()` in `voice.py` to strip both full `\x1b[20[01]~` sequences AND orphaned paste-terminator tails, plus three regression tests.
2. Once the key was clean, `POST /v1/studio/podcasts` returned **403 Forbidden** with `{"detail":{"status":"invalid_subscription","message":"Access to the Studio API requires your account to be explicitly whitelisted to use it. Please contact our sales team."}}`. The Studio API is sales-gated on Creator tier.

Contacting sales would unblock Studio but on an unknown timeline and likely at enterprise pricing. The faster, equally-capable path — and the one we picked — is to replace Phase 4 with **per-turn TTS rendering** using `/v1/text-to-speech/{voice_id}`, the same endpoint that already successfully rendered the 12-ad library on the user's Creator key.

**What changed:**

- **New Phase 3: script writer (Opus 4.6).** `gkl/podcast/script_writer.py` adds a dedicated Claude Opus 4.6 call (via `SCRIPT_WRITER_MODEL = "claude-opus-4-6"`, no tool use) that takes the Phase 2 suggested-topics + a compact data summary and produces an explicit HOST/GUEST dialogue script. Output is parsed into `Script` / `Act` / `DialogueTurn` objects. The segment markdown now has a `## Script writer (Phase 3)` section with `### System prompt` / `### User prompt` sub-sections, parallel to the Phase 2 prompt structure.
- **Rewrote Phase 4: `render_episode_voices`.** Now takes a `Script` plus host + guest voice IDs, iterates each act's turns, calls `generate_tts_to_file()` per line with the matching host voice, and concatenates the per-turn mp3s into per-act tracks. Three acts run in parallel; turns within an act run sequentially to avoid hammering the API.
- **New mixer helper: `concat_audio_files()`.** Simple ffmpeg concat (no loudness normalization — that still happens once in Phase 6 on the full episode) with inter-turn silence gaps. Covered by live ffmpeg smoke tests.
- **Trimmed `source_builder.py`.** The `EpisodeSource` / `build_episode_sources` / `_build_instructions` machinery (Studio-Podcast-specific) is gone. Data-summary formatters (`format_scoreboard`, `format_standings`, etc.) stayed — they're now used by `script_writer.build_data_summary()`.
- **Deleted `StudioPodcastConfig` + `StudioPodcastClient` + all polling/download machinery** from `voice.py`. If we ever get whitelisted, git is the revert path. The file now hosts only the TTS-per-turn renderer + API key loading helpers.
- **Pipeline updated.** `pipeline.py` now calls `write_script()` between the Skipper seed and voice rendering; writes `script.md` to the episode dir in place of the old per-act source/instructions txt files. Char-cost estimate now reflects sum of TTS characters across acts.
- **Segment artifact updated.** In-prompt headings switched from `## Heading` to `**Heading**` so the section extractor doesn't truncate the prompt body at intermediate `##`s (small pitfall worth noting: our markdown-based prompt loader treats `##` / `###` as section boundaries — prompt authors should use bold or h4+ for formatting inside a prompt).

**Decisions recorded for the pivot:**

1. **Opus 4.6 for script writing**, not Sonnet. This is the most creative single LLM call in the pipeline and runs once per episode — the stronger model is cheap per-episode and noticeably better at natural dialogue. Exposed as `SCRIPT_WRITER_MODEL` constant so it's easy to tune.
2. **Turns render sequentially within an act**, parallel across acts. 10-16 turns per act concurrent would risk API rate-limit errors; three acts in parallel is the happy middle.
3. **Per-turn mp3s kept on disk for debugging.** `output_dir/_turns_act_<n>/turn_<NNN>_<speaker>.mp3` retains every individual TTS rendering. Great for spot-checking a specific line without re-charging TTS, or re-running the concat step after a prompt tweak.
4. **No loudness normalization per act.** `concat_audio_files()` deliberately omits `loudnorm` — that's Phase 6's job on the full episode. Running it twice alters the audio.
5. **Parser is strict on structure, permissive on preamble.** The output parser accepts a preamble before `ACT 1` (tolerating a model that can't resist a "Here's the script:" lead-in), but fails loudly on missing acts, out-of-order acts, unknown speakers, or dialogue lines outside an act.

### Tasks

| # | Task | Status |
|---|------|--------|
| 49 | Add bracketed-paste hardening to ElevenLabs key loader + regression tests | ✅ Done |
| 50 | `Script` / `Act` / `DialogueTurn` dataclasses + `parse_script()` | ✅ Done |
| 51 | `gkl/podcast/script_writer.py` with `write_script()` (Opus 4.6) | ✅ Done |
| 52 | Script-writer prompt in segment artifact (System + User sub-sections) | ✅ Done |
| 53 | `concat_audio_files()` helper in `mixer.py` (+ live tests) | ✅ Done |
| 54 | Rewrite `render_episode_voices` for per-turn TTS + parallel acts | ✅ Done |
| 55 | Trim `source_builder.py` to data formatters; delete Studio-specific code | ✅ Done |
| 56 | Update `pipeline.py` to use `write_script` → new voice renderer | ✅ Done |
| 57 | Rewrite voice tests; add script-writer tests; refresh pipeline tests | ✅ Done |
| 58 | **Live end-to-end run against Yahoo + ElevenLabs (with pivot)** | ⬜ Ready — retry `gkl-podcast weekly-recap --week 4` |

### Phase 3 iteration: draft → fact-check → edit (2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`. 105 tests passing. First live test produced a script with stat errors and felt stat-sheet-like with cross-act repetition; this refactor addresses both directly.

**What changed:**

Phase 3 is now three sequential Opus 4.6 passes instead of one, plus a substantially revised draft-writer prompt emphasizing opinion-show dynamics.

- **3a — Draft writer (`write_draft_script`)**. Revised system prompt frames the hosts as an op-ed duo (ESPN Around-the-Horn / The Herd energy) rather than news-readers. Core shift: "Every stat supports a TAKE." Lead with the opinion, back it with the number — not the reverse. Requires 2–3 points of genuine friction per act (real differences in read, not manufactured). Explicitly bans paragraph-long monologues. Bumps target turns-per-act from 8–16 to 10–18.
- **3b — Fact checker (`fact_check_script`)**. New Opus 4.6 pass. Takes the draft + the data summary, validates every stat/rank/record claim, and produces a corrected script. Three correction modes: replace wrong values with correct ones (preserving dialogue voice), rewrite lines with unverifiable claims to remove the specific claim (preserving the surrounding argument), trim turns whose entire premise rests on false data. Explicitly forbidden from inventing new stats or changing act structure.
- **3c — Production editor (`edit_script`)**. New Opus 4.6 pass. Takes the fact-checked script and polishes for narrative flow. Specifically targets: repetition across acts (hosts rehashing the same team/topic in two different segments), monologues (turns running 4+ sentences), weak/vague takes, flat handoffs, missing conversational cues ("Right?" / "Come on." / "Hold on."). Critically, it does NOT get the data summary — only the already-validated script — so it cannot introduce new stat claims.
- **Orchestrator (`write_script`)** runs all three in sequence and returns a `ScriptVersions` dataclass with `draft`, `fact_checked`, and `final` Scripts.
- **Pipeline persists all three.** `data/podcast/.../draft-script.md`, `.../fact-checked-script.md`, and `.../script.md` (final, fed to TTS). Debugging a prompt-tuning iteration is easy: diff the three files to see what each pass did.

**Decisions:**

1. **Three separate Opus calls, not a single multi-step prompt.** Each step has a focused job with a dedicated system prompt. Easier to iterate on any one step's prompt without regressing the others; intermediate artifacts are concrete and reviewable. Per-episode Anthropic cost is ~3x a single call, which is still negligible compared to TTS.
2. **Fact checker runs BEFORE editor.** Editor gets a clean script and only reshapes narrative; it doesn't need to worry about introducing new stat errors. This ordering also means the fact checker doesn't have to care about narrative flow — one job per step.
3. **Editor is denied the data pack.** The editor's user prompt intentionally excludes `{data_summary}` so the model can't be tempted to add new stat claims during polishing. If it wants to sharpen a weak take, it has to use facts already in the script.
4. **All three steps use `SCRIPT_WRITER_MODEL` (`claude-opus-4-6`).** Opus for the draft is creative work. Opus for fact-checking means it can reason about multi-step stat derivations (e.g. "this team's roto rank implies standings above X teams"). Opus for editing is for nuanced narrative judgment. One model constant keeps swaps easy if we want to experiment (e.g., Sonnet 4.6 for the fact-check pass, which could be a cost win).
5. **Section headings in the artifact use in-prompt bold instead of `##`.** The markdown section extractor treats any `##` or `###` as a section boundary. Prompt authors must use `**bold**` for structural hints inside a prompt body, not `## headings`. This is a subtle pitfall; documented inline now via the existing extractor comments.

**Expected behavior change on next live run:**

- Script should lead with opinions, use stats as evidence for takes rather than as the main content.
- Cross-act repetition should be visibly reduced — if Team X came up in Act 1, Act 2 should reference that rather than re-litigate.
- Stat errors in the initial draft should get caught and corrected before reaching TTS.
- Per-episode Anthropic cost up ~3× (still cheap). Per-episode wall time up — three Opus calls add roughly 30–60 seconds total. TTS remains the long pole.

### Tasks

| # | Task | Status |
|---|------|--------|
| 59 | Add `ScriptVersions` dataclass + orchestrator signature | ✅ Done |
| 60 | Rewrite draft-writer system prompt for op-ed / debate energy | ✅ Done |
| 61 | Add fact-checker prompt (System + User) to segment artifact | ✅ Done |
| 62 | Add production-editor prompt (System + User) to segment artifact | ✅ Done |
| 63 | Implement `write_draft_script`, `fact_check_script`, `edit_script` | ✅ Done |
| 64 | Update pipeline.py to persist three intermediate scripts | ✅ Done |
| 65 | Update tests for three-step script generation | ✅ Done |
| 66 | **Live run with three-step Phase 3** | ⬜ Ready — retry `gkl-podcast weekly-recap --week 4` |

### TTS-readability normalization (2026-04-24)

**Status:** Implemented on `feature/gkl-podcast`. 130 tests passing.

**Problem:** The first live-generated script contained stat abbreviations the TTS read letter-by-letter ("oh-bee-pee" for OBP, "ex-bee-ay" for xBA). Real broadcasters say some abbreviations as letters (ERA, RBI, MLB) because those are universally understood, but less-common ones sound wrong and interrupt the flow.

**Two-part fix:**

1. **Prompt guidance in all three Phase 3 steps.** A new "Pronunciation — writing for the ear" section in the draft prompt explicitly tells Opus to spell out technical abbreviations (xBA → expected batting average, OBP → on-base percentage, L30 → last thirty days, IL → injured list, SP → starting pitcher, etc.) and to leave naturally-pronounced ones alone (ERA, RBI, MLB, OPS, AVG, HR, SB, WHIP). Fact-checker and editor prompts also gained a "preserve spelled-out forms" rule so they don't contract back during their passes.
2. **`normalize_script_for_tts()` safety net** in `script_writer.py`. Runs after Phase 3c, before Phase 4 TTS. Applies a dictionary of regex-based substitutions for the abbreviations the prompt asks Opus to avoid — deterministic coverage for anything the model missed. Dictionary is parametrized and easy to extend as we notice new failures.

**Pipeline artifacts:**

- `script.md` — the editor's literal output (may contain abbreviations — debug reference)
- `script-tts.md` — normalized version fed to TTS (what listeners hear)

Diffing the two tells us whether the prompt worked or the normalizer saved us. If `script-tts.md` has substitutions that `script.md` doesn't, the prompt needs tightening on that abbreviation. If both have a new abbreviation that shouldn't be there, add it to the dictionary.

**Decisions:**

1. **Conservative dictionary — only spell out what genuinely sounds wrong letter-by-letter.** Left ERA/RBI/MLB/OPS/AVG/HR/SB/WHIP as-is because broadcasters actually say them that way. Expanding every acronym would make the dialogue stilted.
2. **Word-boundary regex (`\b`).** Prevents accidental substring matches — "pivotal" doesn't become "pivotinjured list". Tests cover this edge case.
3. **Trailing `\b` omitted on patterns ending in non-word chars (%, /, +).** Python's `\b` requires a transition between word and non-word, which doesn't hold when the pattern ends in a non-word character already. Caught by test. Documented inline in the dictionary.
4. **Immutable-friendly — returns a new Script.** `normalize_script_for_tts` never mutates; creates fresh `DialogueTurn` dataclasses. The un-normalized `final` stays preserved for debug/inspection.

### Tasks

| # | Task | Status |
|---|------|--------|
| 67 | Add "Pronunciation" section to draft prompt | ✅ Done |
| 68 | Add "preserve spelled-out forms" rule to fact-checker + editor | ✅ Done |
| 69 | Implement `normalize_line_for_tts` + `normalize_script_for_tts` with dictionary | ✅ Done |
| 70 | Pipeline writes `script-tts.md` + feeds normalized script to TTS | ✅ Done |
| 71 | Unit tests (expansions, preserved abbreviations, word-boundary safety) | ✅ Done |

### Weekly Recap redesign — league-wide balance + standings tour + free agency (2026-05-18)

**Status:** Implemented on `feature/gkl-podcast`. 168 tests passing.

**Problem:** The Week 8 episode (first end-to-end run) over-indexed on a
single team (Mary's Little Lambs) — they were the lead story in Act 1,
came back through transactions in Act 2, and most of the standout
performances in Act 3 were players on their roster. The episode felt
like a Mary's Little Lambs fan podcast rather than a league recap. The
existing format also offered no recurring "stake your read" segments
the hosts could disagree on, and no league-wide treatment of the
waiver wire.

**What changed:**

- **Act layout redesigned.** Act 1 is now an explicit balanced
  scoreboard tour (every matchup mentioned, no team more than two
  beats), Act 2 is a standings tour (top 8 vs bottom 10 composition
  with two host-pick predictions: one team to FALL out of the top 8,
  one bottom-10 team with the best shot to RISE), Act 3 is the
  league-wide free-agent wire (three pickups with the best natural
  team fit for each) + a brief week-ahead.
- **Free agents added to the data pack.** New `_fetch_top_free_agents`
  in `datapack.py` pulls the top 50 free agents by AR sort with both
  season and last-30-days stats, joined on player_key. New
  `DataPack.free_agents` field carries the result.
- **Free-agent formatter in source_builder.** New `format_free_agents`
  groups picks by position type (hitters vs pitchers), shows
  season-and-last-30 lines, and is wired into `build_data_summary` so
  both the draft writer and the fact-checker see the FA pool. The
  fact-checker now has explicit rules for verifying Act 3 pickup
  recommendations against the FA list.
- **Balance rule baked into the draft prompt.** New "Balance —
  league-wide coverage is non-negotiable" section caps team mentions
  per act and per episode. The production editor (Phase 3c) got a
  matching "League-wide balance" audit rule so any leftover
  team-heavy framing gets trimmed at the polish step.
- **Skipper seed prompt re-pointed.** The Phase 2 prompt now explicitly
  asks Skipper to pull rosters across the top-8 / bottom-10 divide and
  call `get_free_agents` for the Act 3 pool. Statcast grounding still
  required for any endorsed player.

**Decisions:**

1. **Permanent format change, not a one-off override for Week 8.** The
   redesign lives in the segment artifact (`weekly-recap.md`) so every
   future episode follows it. Re-running Week 8 is just the validation
   case.
2. **Free agents in the data pack, not just in the Skipper seed.** The
   fact-checker (Phase 3b) needs the FA pool in the data summary to
   verify Act 3 pickups. Skipper still calls `get_free_agents` during
   the seed, but the data summary is the single source of truth for
   per-player claims downstream.
3. **Top 50 free agents by AR sort.** AR (actual rank) skews toward
   "players a real manager would consider adding," which is the right
   pool for "three pickup picks." 50 gives enough breadth that the
   Skipper seed's recommendations almost always land in the pool, so
   the fact-checker can verify them rather than strip them.
4. **Position-split FA formatting.** Hitters and pitchers grouped
   separately in the data summary because the Act 3 framing pairs
   each pickup with a team's positional need. Splitting upfront
   matches how the hosts think about it.
5. **Balance rule lives in BOTH draft and editor prompts.** Draft asks
   the model to cap team mentions while writing; editor audits the
   finished script and trims if the cap was breached. Belt-and-braces
   so a single-team-focused draft can still get rescued.

### Tasks

| # | Task | Status |
|---|------|--------|
| 72 | Add `free_agents` field + `_fetch_top_free_agents` to `datapack.py` | ✅ Done |
| 73 | Implement `format_free_agents` in `source_builder.py` | ✅ Done |
| 74 | Wire FA section into `build_data_summary` | ✅ Done |
| 75 | Rewrite three-act structure section of `weekly-recap.md` | ✅ Done |
| 76 | Update Skipper seed prompts (standings tour + FA pull) | ✅ Done |
| 77 | Update draft prompt (new act guidance + balance rule) | ✅ Done |
| 78 | Update fact-checker prompt (FA + standings-tour verification) | ✅ Done |
| 79 | Update production editor prompt (balance audit) | ✅ Done |
| 80 | Unit tests for FA formatter + data summary | ✅ Done |
| 81 | **Live regeneration of Week 8 with the new format** | ⬜ Ready — delete `data/podcast/<league>/2026-w08` and re-run `gkl-podcast weekly-recap --week 8` |
