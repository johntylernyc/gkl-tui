"""Tests for the nextgenpodcast package (v2 pipeline)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from gkl.nextgenpodcast import scriptcraft
from gkl.nextgenpodcast.ads import (
    NgAdSpot, _parse_json_array, active_spots, load_library, save_library,
    select_episode_ads,
)
from gkl.nextgenpodcast.datapack import (
    RaceEntry, ScheduledMatchup, compute_playoff_race, format_playoff_race,
    _team_week_result,
)
from gkl.nextgenpodcast.scriptcraft import (
    STAGE_HEADINGS, load_stage_prompt, parse_script, sanitize_tags,
    strip_tags,
)
from gkl.nextgenpodcast.segments import ALL_STAR_DEEP_DIVE, WEEKLY_RECAP_V2
from gkl.nextgenpodcast.showbible import (
    DEFAULT_CAST, DEFAULT_SHOW_BIBLE, extract_bible_section, load_show_bible,
)
from gkl.nextgenpodcast.showrunner import Rundown, split_rundown_sections
from gkl.nextgenpodcast.showstate import (
    EpisodeRecord, Prediction, ShowState, load_show_state, parse_grades,
    parse_plants, save_show_state,
)
from gkl.podcast.datapack import H2HRecord, MatchupRecord


SPEAKERS = ("HAWK", "WEBB")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------- show bible ----------

class TestShowBible:
    def test_bible_exists_and_loads(self):
        bible = load_show_bible()
        assert "Hawk" in bible and "Webb" in bible
        assert "Variety playbook" in bible
        assert "Prediction Ledger" in bible

    def test_extract_section_raises_on_missing(self):
        with pytest.raises(KeyError):
            extract_bible_section("# T\n\n## A\nbody\n", "Nope")

    def test_cast_voice_mapping(self):
        assert DEFAULT_CAST.voice_for("HAWK") == DEFAULT_CAST.lead.voice_id
        assert DEFAULT_CAST.voice_for("WEBB") == DEFAULT_CAST.analyst.voice_id
        assert DEFAULT_CAST.voice_for("ANNOUNCER") == DEFAULT_CAST.announcer.voice_id
        with pytest.raises(ValueError):
            DEFAULT_CAST.voice_for("HOST")

    def test_cast_announcer_excluded_from_hosts(self):
        # Host speakers drive act parsing/balance; the announcer is not one.
        assert DEFAULT_CAST.speakers() == ("HAWK", "WEBB")
        assert DEFAULT_CAST.announcer.speaker == "ANNOUNCER"

    def test_webb_reads_faster_than_hawk(self):
        # "My Guy" gets the small pacing bump; settings carry per-voice speed.
        assert DEFAULT_CAST.voice_settings_for("WEBB")["speed"] > \
            DEFAULT_CAST.voice_settings_for("HAWK")["speed"]
        assert DEFAULT_CAST.voice_settings_for("HAWK")["speed"] == 1.0
        # Defaults are carried through alongside the speed override.
        assert "similarity_boost" in DEFAULT_CAST.voice_settings_for("WEBB")

    def test_announcer_voice_reserved_from_caller_pool(self):
        from gkl.nextgenpodcast.showbible import ANNOUNCER_VOICE_ID
        from gkl.nextgenpodcast.showrunner import CALLER_VOICE_POOL
        assert ANNOUNCER_VOICE_ID not in {vid for vid, _ in CALLER_VOICE_POOL}

    def test_banned_crutches_documented(self):
        md = DEFAULT_SHOW_BIBLE.read_text()
        for phrase in ("my guy alongside me as always", "I'll co-sign",
                       "elite pitching infrastructure"):
            assert phrase in md


# ---------- show state ----------

class TestShowState:
    def test_roundtrip(self, tmp_path):
        state = ShowState()
        state.add_prediction(Prediction(
            id="2026-w14-HAWK-1", season="2026", week_made=14,
            speaker="HAWK", text="ShapeShifters win Week 17",
        ))
        state.record_episode(EpisodeRecord(
            slug="2026-w14", segment="weekly-recap-v2", week=14,
            cold_open="The grade", sign_off="ballgame",
        ))
        path = tmp_path / "show-state.json"
        save_show_state(state, path)
        loaded = load_show_state(path)
        assert loaded.predictions[0].id == "2026-w14-HAWK-1"
        assert loaded.episodes[0].cold_open == "The grade"

    def test_load_missing_or_corrupt(self, tmp_path):
        assert load_show_state(tmp_path / "nope.json").predictions == []
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        assert load_show_state(bad).predictions == []

    def test_records_and_grading(self):
        state = ShowState()
        for i, verdict in enumerate(("correct", "wrong", "correct")):
            pid = f"2026-w10-HAWK-{i+1}"
            state.add_prediction(Prediction(
                id=pid, season="2026", week_made=10, speaker="HAWK", text="t",
            ))
            assert state.grade(pid, verdict, 11, "because")
        assert state.records("2026") == {"HAWK": (2, 1)}
        # unknown / already-graded ids return False
        assert not state.grade("2026-w10-HAWK-1", "correct", 12, "again")
        assert not state.grade("missing", "correct", 12, "x")

    def test_ledger_block_lists_open_predictions(self):
        state = ShowState()
        state.add_prediction(Prediction(
            id="2026-w14-WEBB-1", season="2026", week_made=14,
            speaker="WEBB", text="Braun falls out of the top eight",
            resolves_by="Week 16",
        ))
        block = state.ledger_block("2026")
        assert "[2026-w14-WEBB-1]" in block
        assert "Braun falls" in block
        assert "resolves by: Week 16" in block

    def test_next_prediction_id_increments(self):
        state = ShowState()
        first = state.next_prediction_id("2026", 14, "HAWK")
        state.add_prediction(Prediction(
            id=first, season="2026", week_made=14, speaker="HAWK", text="a",
        ))
        assert state.next_prediction_id("2026", 14, "HAWK") == "2026-w14-HAWK-2"

    def test_record_episode_replaces_on_rerun(self):
        state = ShowState()
        state.record_episode(EpisodeRecord(slug="2026-w14", segment="s", week=14,
                                           cold_open="a"))
        state.record_episode(EpisodeRecord(slug="2026-w14", segment="s", week=14,
                                           cold_open="b"))
        assert len(state.episodes) == 1
        assert state.episodes[0].cold_open == "b"

    def test_history_block_empty(self):
        assert ShowState().history_block() == "(no prior episodes)"

    def test_parse_grades(self):
        text = (
            "- GRADE: 2026-w13-HAWK-1 | correct | ShapeShifters swept\n"
            "GRADE: none\n"
            "- GRADE: 2026-w13-WEBB-2 | WRONG | Braun held on\n"
            "irrelevant line\n"
        )
        grades = parse_grades(text)
        assert grades == [
            ("2026-w13-HAWK-1", "correct", "ShapeShifters swept"),
            ("2026-w13-WEBB-2", "wrong", "Braun held on"),
        ]

    def test_parse_plants(self):
        text = (
            "- PLANT: HAWK | Holy Toledo makes the top eight | resolves-by: Week 17\n"
            "- PLANT: WEBB | The average comes down\n"
            "- PLANT: NARRATOR | not a real speaker\n"
        )
        plants = parse_plants(text, SPEAKERS)
        assert plants == [
            ("HAWK", "Holy Toledo makes the top eight", "Week 17"),
            ("WEBB", "The average comes down", ""),
        ]


# ---------- scriptcraft ----------

class TestScriptParsing:
    def test_parse_three_acts(self):
        raw = (
            "ACT 1\nHAWK: Welcome in. [laughs] Big week.\nWEBB: Numbers say otherwise.\n\n"
            "ACT 2\nHAWK: Awards time.\nWEBB: Ring it.\n\n"
            "ACT 3\nHAWK: The race.\nWEBB: The water finds its level.\n"
        )
        script = parse_script(raw, SPEAKERS)
        assert script.total_turns() == 6
        assert script.acts[0].turns[0].line == "Welcome in. [laughs] Big week."

    def test_parse_tolerates_preamble(self):
        raw = "Here's the script:\nACT 1\nHAWK: Hi.\nACT 2\nWEBB: Hello.\nACT 3\nHAWK: Bye.\n"
        assert parse_script(raw, SPEAKERS).total_turns() == 3

    def test_parse_two_act_special(self):
        raw = "ACT 1\nWEBB: The file.\nACT 2\nHAWK: The verdict.\n"
        script = parse_script(raw, SPEAKERS, expected_acts=2)
        assert len(script.acts) == 2

    def test_unknown_speaker_fails(self):
        raw = "ACT 1\nHOST: Hi.\nACT 2\nHAWK: Hi.\nACT 3\nWEBB: Hi.\n"
        with pytest.raises(ValueError):
            parse_script(raw, SPEAKERS)

    def test_missing_act_fails(self):
        raw = "ACT 1\nHAWK: Hi.\nACT 2\nWEBB: Hi.\n"
        with pytest.raises(ValueError):
            parse_script(raw, SPEAKERS)

    def test_unknown_tag_stripped_known_kept(self):
        raw = (
            "ACT 1\nHAWK: [laughs] Sure. [smirks] Fine.\n"
            "ACT 2\nWEBB: [sighs] Espresso.\nACT 3\nHAWK: Done.\n"
        )
        script = parse_script(raw, SPEAKERS)
        line = script.acts[0].turns[0].line
        assert "[laughs]" in line and "[smirks]" not in line

    def test_sanitize_and_strip(self):
        assert sanitize_tags("[laughs] ok [robot noise]") == "[laughs] ok"
        assert strip_tags("[laughs] ok [clears throat] go") == "ok go"

    def test_word_count(self):
        raw = "ACT 1\nHAWK: one two three.\nACT 2\nWEBB: four five.\nACT 3\nHAWK: six.\n"
        assert parse_script(raw, SPEAKERS).total_words() == 6

    def test_as_markdown_roundtrip(self):
        raw = "ACT 1\nHAWK: A.\nACT 2\nWEBB: B.\nACT 3\nHAWK: C.\n"
        script = parse_script(raw, SPEAKERS)
        assert parse_script(script.as_markdown(), SPEAKERS).total_turns() == 3


_CALL_IN_RAW = (
    "ACT 1\nHAWK: My guy, tell me you saw Tuesday.\nWEBB: I saw the spreadsheet.\n"
    "ACT 2\nHAWK: Awards.\nWEBB: Ring it.\n"
    "CALL-IN\n"
    "HAWK: Let's go to the Lounge Line. Who've we got?\n"
    "CALLER: Donny from Pittsford, first time caller. Tell My Guy he's wrong about Riley.\n"
    "WEBB: [sighs] Donny, the expected slugging says otherwise.\n"
    "ACT 3\nWEBB: The race.\nHAWK: Take us home.\n"
)


class TestCallInParsing:
    def test_call_in_parsed(self):
        script = parse_script(_CALL_IN_RAW, SPEAKERS, allow_call_in=True)
        assert len(script.call_in) == 3
        assert script.call_in_after == 2
        assert script.call_in[1].speaker == "CALLER"
        assert script.total_turns() == 9

    def test_call_in_required_when_allowed(self):
        raw = "ACT 1\nHAWK: A.\nACT 2\nWEBB: B.\nACT 3\nHAWK: C.\n"
        with pytest.raises(ValueError, match="CALL-IN"):
            parse_script(raw, SPEAKERS, allow_call_in=True)

    def test_caller_outside_block_fails(self):
        raw = (
            "ACT 1\nCALLER: hello?\nACT 2\nHAWK: B.\n"
            "CALL-IN\nCALLER: hi.\nWEBB: hi.\nACT 3\nHAWK: C.\n"
        )
        with pytest.raises(ValueError, match="outside"):
            parse_script(raw, SPEAKERS, allow_call_in=True)

    def test_caller_not_allowed_without_flag(self):
        with pytest.raises(ValueError):
            parse_script(_CALL_IN_RAW, SPEAKERS)  # allow_call_in=False

    def test_call_in_needs_caller_and_host(self):
        raw = (
            "ACT 1\nHAWK: A.\nACT 2\nWEBB: B.\n"
            "CALL-IN\nHAWK: nobody called.\n"
            "ACT 3\nHAWK: C.\n"
        )
        with pytest.raises(ValueError, match="no CALLER turn"):
            parse_script(raw, SPEAKERS, allow_call_in=True)

    def test_as_markdown_roundtrips_call_in(self):
        script = parse_script(_CALL_IN_RAW, SPEAKERS, allow_call_in=True)
        md = script.as_markdown()
        assert "CALL-IN" in md
        again = parse_script(md, SPEAKERS, allow_call_in=True)
        assert len(again.call_in) == 3
        # block stays anchored after act 2
        assert md.index("ACT 2") < md.index("CALL-IN") < md.index("ACT 3")

    def test_map_lines_covers_call_in(self):
        script = parse_script(_CALL_IN_RAW, SPEAKERS, allow_call_in=True)
        upper = script.map_lines(str.upper)
        assert upper.call_in[1].line.startswith("DONNY FROM PITTSFORD")


_ANNOUNCER_RAW = (
    "INTRO\nANNOUNCER: Tonight in the Lounge: the bubble tightens.\n"
    "ACT 1\nHAWK: My guy, big week.\nWEBB: The numbers agree.\n"
    "BUMPER 1\nANNOUNCER: After the break, the awards.\n"
    "ACT 2\nHAWK: Awards.\nWEBB: Suzuki's a mirage. Ring it. [bell]\n"
    "CALL-IN\n"
    "ANNOUNCER: We've got Donny from Pittsford. What's on your mind?\n"
    "CALLER: Tell My Guy he's wrong about Riley.\n"
    "WEBB: The expected slugging says otherwise.\n"
    "HAWK: Thanks Donny.\n"
    "BUMPER 2\nANNOUNCER: Next: who's safe and who's sweating.\n"
    "ACT 3\nWEBB: The race.\nHAWK: That's a ballgame, folks.\n"
)

_ANN_KW = dict(expected_acts=3, allow_call_in=True, has_announcer=True,
               expected_bumpers=2)


class TestAnnouncerAndBell:
    def test_full_parse(self):
        s = parse_script(_ANNOUNCER_RAW, SPEAKERS, **_ANN_KW)
        assert [t.speaker for t in s.intro] == ["ANNOUNCER"]
        assert len(s.bumpers) == 2
        assert all(t.speaker == "ANNOUNCER" for b in s.bumpers for t in b)
        assert s.call_in[0].speaker == "ANNOUNCER"

    def test_bell_cue_lifted_and_stripped(self):
        s = parse_script(_ANNOUNCER_RAW, SPEAKERS, **_ANN_KW)
        bell_turns = [t for a in s.acts for t in a.turns if t.bell_after]
        assert len(bell_turns) == 1
        assert bell_turns[0].speaker == "WEBB"
        assert "[bell]" not in bell_turns[0].line  # stripped from spoken text
        assert bell_turns[0].line.endswith("Ring it.")

    def test_roundtrip_preserves_blocks_and_bell(self):
        s = parse_script(_ANNOUNCER_RAW, SPEAKERS, **_ANN_KW)
        md = s.as_markdown()
        # on-air order: INTRO, ACT1, BUMPER1, ACT2, CALL-IN, BUMPER2, ACT3
        order = [md.index(h) for h in
                 ("INTRO", "ACT 1", "BUMPER 1", "ACT 2", "CALL-IN", "BUMPER 2", "ACT 3")]
        assert order == sorted(order)
        again = parse_script(md, SPEAKERS, **_ANN_KW)
        assert sum(t.bell_after for a in again.acts for t in a.turns) == 1

    def test_announcer_in_act_rejected(self):
        raw = _ANNOUNCER_RAW.replace(
            "ACT 1\nHAWK: My guy, big week.",
            "ACT 1\nANNOUNCER: I don't belong here.\nHAWK: My guy, big week.",
        )
        with pytest.raises(ValueError, match="ANNOUNCER"):
            parse_script(raw, SPEAKERS, **_ANN_KW)

    def test_missing_intro_rejected(self):
        raw = _ANNOUNCER_RAW.replace(
            "INTRO\nANNOUNCER: Tonight in the Lounge: the bubble tightens.\n", "",
        )
        with pytest.raises(ValueError, match="INTRO"):
            parse_script(raw, SPEAKERS, **_ANN_KW)

    def test_wrong_bumper_count_rejected(self):
        raw = _ANNOUNCER_RAW.replace(
            "BUMPER 2\nANNOUNCER: Next: who's safe and who's sweating.\n", "",
        )
        with pytest.raises(ValueError, match="BUMPER"):
            parse_script(raw, SPEAKERS, **_ANN_KW)

    def test_two_bells_rejected(self):
        raw = _ANNOUNCER_RAW.replace(
            "HAWK: My guy, big week.", "HAWK: My guy, big week. [bell]",
        )
        with pytest.raises(ValueError, match="one \\[bell\\]"):
            parse_script(raw, SPEAKERS, **_ANN_KW)

    def test_bell_outside_act_rejected(self):
        raw = _ANNOUNCER_RAW.replace(
            "ANNOUNCER: After the break, the awards.",
            "ANNOUNCER: After the break, the awards. [bell]",
        )
        with pytest.raises(ValueError, match="bell"):
            parse_script(raw, SPEAKERS, **_ANN_KW)

    def test_call_in_needs_announcer_intro(self):
        raw = _ANNOUNCER_RAW.replace(
            "ANNOUNCER: We've got Donny from Pittsford. What's on your mind?\n", "",
        )
        with pytest.raises(ValueError, match="ANNOUNCER caller intro"):
            parse_script(raw, SPEAKERS, **_ANN_KW)

    def test_announcer_rejected_without_flag(self):
        # Same script parsed as a no-announcer segment must fail.
        with pytest.raises(ValueError):
            parse_script(_ANNOUNCER_RAW, SPEAKERS, expected_acts=3, allow_call_in=True)


# Tokens the pipeline provides per segment. Prompt-invariant tests below
# assert every {token} used in an artifact's prompts is in this set —
# a drifted artifact fails here instead of crashing mid-generation.
_WEEKLY_TOKENS = {
    "league_name", "season", "target_week", "week_start", "week_end",
    "playoff_spots", "show_bible", "rundown", "suggested_topics",
    "data_summary", "checker_data_summary", "prior_takeaways", "ledger",
    "episode_history", "draft_script", "fact_checked_script", "script",
    "final_script", "caller_voices",
}
_DEEP_DIVE_TOKENS = (_WEEKLY_TOKENS - {"week_start", "week_end"}) | {
    "team_name", "manager_name", "through_week",
}

_TOKEN_RE = re.compile(r"\{([a-z_]+)\}")


class TestPromptArtifacts:
    @pytest.mark.parametrize("stage", list(STAGE_HEADINGS))
    def test_weekly_stages_extract(self, stage):
        prompt = load_stage_prompt(WEEKLY_RECAP_V2.artifact, stage)
        assert prompt.system.strip() and prompt.user.strip()

    @pytest.mark.parametrize("stage", list(STAGE_HEADINGS))
    def test_deep_dive_stages_extract(self, stage):
        prompt = load_stage_prompt(ALL_STAR_DEEP_DIVE.artifact, stage)
        assert prompt.system.strip() and prompt.user.strip()

    @pytest.mark.parametrize("stage", list(STAGE_HEADINGS))
    def test_weekly_tokens_known(self, stage):
        prompt = load_stage_prompt(WEEKLY_RECAP_V2.artifact, stage)
        used = set(_TOKEN_RE.findall(prompt.system + prompt.user))
        assert used <= _WEEKLY_TOKENS, f"unknown tokens in {stage}: {used - _WEEKLY_TOKENS}"

    @pytest.mark.parametrize("stage", list(STAGE_HEADINGS))
    def test_deep_dive_tokens_known(self, stage):
        prompt = load_stage_prompt(ALL_STAR_DEEP_DIVE.artifact, stage)
        used = set(_TOKEN_RE.findall(prompt.system + prompt.user))
        assert used <= _DEEP_DIVE_TOKENS, f"unknown tokens in {stage}: {used - _DEEP_DIVE_TOKENS}"

    def test_weekly_draft_has_character_guidance(self):
        prompt = load_stage_prompt(WEEKLY_RECAP_V2.artifact, "draft")
        assert "HAWK" in prompt.system and "WEBB" in prompt.system
        assert "my guy alongside me as always" in prompt.system  # banned list

    def test_fact_checker_protects_continuity(self):
        prompt = load_stage_prompt(WEEKLY_RECAP_V2.artifact, "fact_check")
        assert "verify" in prompt.system.lower()
        assert "PRIOR TAKEAWAYS" in prompt.system
        assert "byte-identical" in prompt.system

    def test_editor_has_protected_list(self):
        prompt = load_stage_prompt(WEEKLY_RECAP_V2.artifact, "edit")
        assert "PROTECTED" in prompt.system

    def test_weekly_race_framing(self):
        prompt = load_stage_prompt(WEEKLY_RECAP_V2.artifact, "seed")
        assert "playoff" in prompt.system.lower()
        assert "get_h2h_standings" in prompt.system + prompt.user


# ---------- showrunner ----------

_RUNDOWN = """\
**COLD OPEN**
Style: The grade. Open on Hawk's Week 13 pick.

**LEDGER GRADES**
GRADE: 2026-w13-HAWK-1 | correct | ShapeShifters swept the week
Lands in the cold open.

**ACT 1**
Hawk fronts. Whip-around scoreboard.

**ACT 2**
Webb fronts. Category Kings, Regression Watch.

**ACT 3**
Webb fronts. The race, bubble first.

**ARGUMENT ACT**
Act 3. Hawk says Holy Toledo climbs; Webb says the schedule kills it.

**CALL-IN**
CALLER: Donny from Pittsford | voice: gs0tAILXbY5DNrJrsM6F | granddad who has had the same take since 1987
He thinks Dan should have sold the closers in May. He's right. Hawk takes his side; Webb defends the saves stash.

**NEW LEDGER ENTRIES**
PLANT: HAWK | Holy Toledo makes the top eight | resolves-by: Week 17
PLANT: WEBB | Sho Me The Money falls out

**BITS BUDGET**
Regression Bell in Act 2 for Crow-Armstrong. One espresso tease.

**SIGN-OFF**
Webb reads next week's ledger stakes.
"""


class TestShowrunner:
    def test_split_sections(self):
        sections = split_rundown_sections(_RUNDOWN)
        assert "COLD OPEN" in sections
        assert sections["SIGN-OFF"].startswith("Webb reads")

    def test_rundown_grades_and_plants(self):
        r = Rundown(text=_RUNDOWN, sections=split_rundown_sections(_RUNDOWN))
        assert r.grades() == [
            ("2026-w13-HAWK-1", "correct", "ShapeShifters swept the week"),
        ]
        plants = r.plants(SPEAKERS)
        assert len(plants) == 2
        assert plants[0][0] == "HAWK"
        assert r.cold_open.startswith("Style: The grade")
        assert "Regression Bell" in r.bits_budget

    def test_rundown_caller_spec(self):
        r = Rundown(text=_RUNDOWN, sections=split_rundown_sections(_RUNDOWN))
        caller = r.caller()
        assert caller is not None
        assert caller.display == "Donny from Pittsford"
        assert caller.voice_id == "gs0tAILXbY5DNrJrsM6F"
        assert "1987" in caller.persona

    def test_rundown_caller_missing(self):
        text = "**COLD OPEN**\nhi\n\n**SIGN-OFF**\nbye\n"
        r = Rundown(text=text, sections=split_rundown_sections(text))
        assert r.caller() is None


class TestCallerVoices:
    def test_resolve_prefers_valid_fresh_pick(self):
        from gkl.nextgenpodcast.showrunner import (
            CALLER_VOICE_POOL, resolve_caller_voice,
        )
        pick = CALLER_VOICE_POOL[0][0]
        assert resolve_caller_voice(pick, recent=[]) == pick

    def test_resolve_rejects_recent_and_invalid(self):
        import random
        from gkl.nextgenpodcast.showrunner import (
            CALLER_VOICE_POOL, resolve_caller_voice,
        )
        rng = random.Random(7)
        recent = [CALLER_VOICE_POOL[0][0]]
        out = resolve_caller_voice(CALLER_VOICE_POOL[0][0], recent, rng=rng)
        assert out != CALLER_VOICE_POOL[0][0]
        out2 = resolve_caller_voice("not-a-voice", [], rng=rng)
        assert out2 in {vid for vid, _ in CALLER_VOICE_POOL}

    def test_recent_caller_voices_from_history(self):
        from gkl.nextgenpodcast.showrunner import recent_caller_voices
        records = [
            EpisodeRecord(slug="2026-w12", segment="s", week=12,
                          caller="CALLER: Al from Nyack | voice: v-old | grump"),
            EpisodeRecord(slug="2026-w13", segment="s", week=13,
                          caller="CALLER: Bo from Rye | voice: v-new | kid"),
            EpisodeRecord(slug="2026-w14", segment="s", week=14),  # no caller
        ]
        assert recent_caller_voices(records) == ["v-new", "v-old"]


# ---------- datapack (playoff race) ----------

def _rec(name, cw, cl, ct, w=0, l=0, t=0):
    return H2HRecord(
        team_key=f"k.{name}", name=name, manager=f"m-{name}",
        wins=w, losses=l, ties=t, cat_wins=cw, cat_losses=cl, cat_ties=ct,
    )


class TestPlayoffRace:
    def test_seeding_by_win_pct_not_raw_wins(self):
        # B has more raw wins but worse win% (many ties for A).
        recs = [
            _rec("B", 113, 80, 2),
            _rec("A", 112, 64, 22),  # (112+11)/198 = .621 > B's .585
        ]
        race = compute_playoff_race(recs, playoff_spots=1, through_week=10)
        assert race.entries[0].name == "A"
        assert race.entries[0].seed == 1

    def test_cutline_gap_and_tiers(self):
        recs = [_rec(f"T{i}", 100 - i * 5, 50, 0) for i in range(12)]
        race = compute_playoff_race(recs, playoff_spots=8, through_week=10)
        cut = race.entries[7]
        assert cut.gap_to_cutline_cat_wins == 0
        assert race.entries[0].tier == "safe"
        assert race.entries[6].tier == "bubble"
        assert race.entries[9].tier == "bubble"
        assert race.entries[11].tier == "field"
        # gap signs: above cutline positive, below negative
        assert race.entries[0].gap_to_cutline_cat_wins > 0
        assert race.entries[9].gap_to_cutline_cat_wins < 0

    def test_near_ties_flagged(self):
        recs = [_rec("A", 100, 50, 0), _rec("B", 100, 50, 1), _rec("C", 10, 100, 0)]
        race = compute_playoff_race(recs, playoff_spots=2, through_week=10)
        assert ("A", "B") in race.near_ties or ("B", "A") in race.near_ties

    def test_bubble_meetings_marked(self):
        recs = [_rec(f"T{i}", 100 - i * 5, 50, 0) for i in range(12)]
        rem = [ScheduledMatchup(
            week=15, team_a_key="k.T7", team_a_name="T7",
            team_b_key="k.T9", team_b_name="T9", bubble_meeting=False,
        ), ScheduledMatchup(
            week=15, team_a_key="k.T0", team_a_name="T0",
            team_b_key="k.T11", team_b_name="T11", bubble_meeting=False,
        )]
        race = compute_playoff_race(
            recs, playoff_spots=8, through_week=10, remaining=rem,
        )
        assert race.remaining[0].bubble_meeting is True
        assert race.remaining[1].bubble_meeting is False

    def test_format_playoff_race_contents(self):
        recs = [_rec(f"T{i}", 100 - i * 5, 50, 0) for i in range(10)]
        race = compute_playoff_race(recs, playoff_spots=8, through_week=12)
        text = format_playoff_race(race)
        assert "PLAYOFF CUTLINE" in text
        assert "WIN PERCENTAGE" in text
        assert "T0" in text and "T9" in text

    def test_team_week_result_perspective(self):
        rec = MatchupRecord(
            week=5, week_start="", week_end="", status="postevent",
            team_a_key="k.A", team_a_name="A", team_b_key="k.B",
            team_b_name="B", team_a_cat_wins=11, team_b_cat_wins=6,
            cat_ties=1, winner_team_key="k.A", category_results=[],
        )
        mine = _team_week_result(rec, "k.A")
        assert (mine.result, mine.cat_score, mine.opponent) == ("W", "11-6-1", "B")
        theirs = _team_week_result(rec, "k.B")
        assert (theirs.result, theirs.cat_score) == ("L", "6-11-1")


# ---------- ads ----------

class TestAds:
    def test_parse_json_array_with_fences(self):
        raw = "```json\n[{\"slug\": \"a\"}]\n```"
        assert _parse_json_array(raw) == [{"slug": "a"}]

    def test_parse_json_array_no_array_raises(self):
        with pytest.raises(ValueError):
            _parse_json_array("no json here")

    def test_library_roundtrip(self, tmp_path):
        path = tmp_path / "library.json"
        spots = [NgAdSpot(slug="s1", title="S1", copy="c", voice_id="v",
                          voice_character="vc", status="active"),
                 NgAdSpot(slug="s2", title="S2", copy="c", voice_id="v",
                          voice_character="vc", status="archived")]
        save_library(spots, path)
        loaded = load_library(path)
        assert [s.slug for s in loaded] == ["s1", "s2"]
        assert [s.slug for s in active_spots(loaded)] == ["s1"]

    def test_select_episode_ads_rotates(self, tmp_path):
        path = tmp_path / "library.json"
        save_library([
            NgAdSpot(slug=f"s{i}", title=f"S{i}", copy="c", voice_id="v",
                     voice_character="vc") for i in range(4)
        ], path)
        rotation = tmp_path / "rotation.json"
        first = select_episode_ads(rotation, 2, library_path=path)
        second = select_episode_ads(rotation, 2, library_path=path)
        assert {s.slug for s in first} == {"s0", "s1"}
        assert {s.slug for s in second} == {"s2", "s3"}

    @pytest.mark.anyio
    async def test_generate_ad_batch_applies_critic(self, tmp_path, monkeypatch):
        from gkl.nextgenpodcast import ads as ads_mod

        written = [
            {"slug": "good-spot", "title": "Good", "copy": "fine copy",
             "voice_id": ads_mod.VOICE_POOL[0][0], "voice_character": "x",
             "tags": ["satire"]},
            {"slug": "weak-spot", "title": "Weak", "copy": "flat copy",
             "voice_id": "not-a-real-voice", "voice_character": "x",
             "tags": []},
            {"slug": "bad-spot", "title": "Bad", "copy": "bad",
             "voice_id": ads_mod.VOICE_POOL[1][0], "voice_character": "x",
             "tags": []},
        ]
        verdicts = [
            {"slug": "good-spot", "verdict": "pass", "notes": ""},
            {"slug": "weak-spot", "verdict": "rewrite", "notes": "no ladder",
             "fixed_copy": "rewritten copy with a proper ladder"},
            {"slug": "bad-spot", "verdict": "fail", "notes": "no target"},
        ]
        calls = iter([json.dumps(written), json.dumps(verdicts)])

        async def fake_call(system, user, **kwargs):
            return next(calls)

        monkeypatch.setattr(ads_mod, "call_claude", fake_call)
        lib_path = tmp_path / "library.json"
        accepted, report = await ads_mod.generate_ad_batch(
            3, style_guide_path=ads_mod.DEFAULT_STYLE_GUIDE,
            library_path=lib_path, batch_label="test",
        )
        slugs = {s.slug for s in accepted}
        assert slugs == {"good-spot", "weak-spot"}
        weak = next(s for s in accepted if s.slug == "weak-spot")
        assert weak.copy == "rewritten copy with a proper ladder"
        # invalid voice ids are re-cast from the pool
        assert weak.voice_id in {vid for vid, _ in ads_mod.VOICE_POOL}
        # persisted
        assert {s.slug for s in load_library(lib_path)} == slugs

    def test_style_guide_exists(self):
        from gkl.nextgenpodcast.ads import DEFAULT_STYLE_GUIDE
        text = DEFAULT_STYLE_GUIDE.read_text()
        assert "escalation" in text.lower()
        assert "never knows it's the joke" in text.lower()
        assert "45-75" in text
        assert "divorce" in text.lower()  # the sensitive-topics rule

    def test_hard_rule_backstop(self):
        from gkl.nextgenpodcast.ads import violates_hard_rules
        assert violates_hard_rules("word " * 81) is not None
        assert violates_hard_rules("Since the divorce, he bets more.") is not None
        assert violates_hard_rules("A perfectly fine spot about bison.") is None

    @pytest.mark.anyio
    async def test_generate_batch_backstop_drops_violations(
        self, tmp_path, monkeypatch,
    ):
        from gkl.nextgenpodcast import ads as ads_mod
        written = [
            {"slug": "too-long", "title": "L", "copy": "word " * 90,
             "voice_id": ads_mod.VOICE_POOL[0][0], "voice_character": "x",
             "tags": []},
            {"slug": "divorce-joke", "title": "D",
             "copy": "He got a divorce and a boat.",
             "voice_id": ads_mod.VOICE_POOL[0][0], "voice_character": "x",
             "tags": []},
            {"slug": "clean", "title": "C", "copy": "Fifty tasteful words.",
             "voice_id": ads_mod.VOICE_POOL[0][0], "voice_character": "x",
             "tags": []},
        ]
        verdicts = [{"slug": s["slug"], "verdict": "pass", "notes": ""}
                    for s in written]
        calls = iter([json.dumps(written), json.dumps(verdicts)])

        async def fake_call(system, user, **kwargs):
            return next(calls)

        monkeypatch.setattr(ads_mod, "call_claude", fake_call)
        accepted, report = await ads_mod.generate_ad_batch(
            3, library_path=tmp_path / "library.json",
        )
        assert [s.slug for s in accepted] == ["clean"]
        backstopped = [v for v in report if "hard-rule backstop" in v.get("notes", "")]
        assert len(backstopped) == 2

    def test_committed_library_meets_the_bar(self):
        """The shipped library.json honors the refined style rules."""
        from gkl.nextgenpodcast.ads import (
            VOICE_POOL, active_spots, load_library, violates_hard_rules,
        )
        library = load_library()
        active = active_spots(library)
        assert len(active) >= 8
        pool = {vid for vid, _ in VOICE_POOL}
        for spot in active:
            words = len(spot.copy.split())
            assert 40 <= words <= 80, f"{spot.slug}: {words} words"
            assert violates_hard_rules(spot.copy) is None, spot.slug
            assert spot.voice_id in pool, spot.slug
        # the archived 2026-07-03 batch stays out of rotation
        assert all(s.status == "archived" for s in library
                   if s.batch == "2026-07-03")


# ---------- dialogue ----------

class TestDialogue:
    @pytest.mark.anyio
    async def test_fallback_after_dialogue_unavailable(self, tmp_path, monkeypatch):
        from gkl.nextgenpodcast import dialogue as dlg
        from gkl.nextgenpodcast.showbible import DEFAULT_CAST

        raw = "ACT 1\nHAWK: Hi there. [laughs]\nACT 2\nWEBB: Hello.\nACT 3\nHAWK: Bye.\n"
        script = parse_script(raw, SPEAKERS)

        async def unavailable(act, cast, out, *, api_key, base_url=None):
            raise dlg.DialogueUnavailable("ElevenLabs 403 on /v1/text-to-dialogue")

        per_turn_calls: list[int] = []

        async def fake_per_turn(act, cast, out, *, api_key, turn_gap_seconds=0.25,
                                bell_path=None):
            per_turn_calls.append(act.number)
            out.write_bytes(b"mp3")
            return sum(len(t.line) for t in act.turns)

        monkeypatch.setattr(dlg, "render_act_dialogue_v3", unavailable)
        monkeypatch.setattr(dlg, "_render_act_per_turn", fake_per_turn)
        monkeypatch.setattr(dlg, "_require_key", lambda k: "key")

        # Opt into the v3 dialogue path so the fallback-on-unavailable
        # behavior is exercised (per-turn is now the default path).
        results = await dlg.render_episode_voices(
            script, DEFAULT_CAST, tmp_path, prefer_dialogue=True,
        )
        assert [r.renderer for r in results] == ["per-turn"] * 3
        # v3 probed once, then never again
        assert per_turn_calls == [1, 2, 3]

    @pytest.mark.anyio
    async def test_dialogue_path_used_when_available(self, tmp_path, monkeypatch):
        from gkl.nextgenpodcast import dialogue as dlg
        from gkl.nextgenpodcast.showbible import DEFAULT_CAST

        raw = "ACT 1\nHAWK: Hi.\nACT 2\nWEBB: Hello.\nACT 3\nHAWK: Bye.\n"
        script = parse_script(raw, SPEAKERS)

        async def ok(act, cast, out, *, api_key, base_url=None):
            out.write_bytes(b"mp3")
            return 42

        monkeypatch.setattr(dlg, "render_act_dialogue_v3", ok)
        monkeypatch.setattr(dlg, "_require_key", lambda k: "key")
        results = await dlg.render_episode_voices(
            script, DEFAULT_CAST, tmp_path, prefer_dialogue=True,
        )
        assert all(r.renderer == "dialogue-v3" for r in results)
        assert all(r.audio_path.exists() for r in results)

    @pytest.mark.anyio
    async def test_bell_spliced_after_flagged_turn(self, tmp_path, monkeypatch):
        from gkl.nextgenpodcast import dialogue as dlg
        from gkl.nextgenpodcast.showbible import DEFAULT_CAST

        # Webb's second turn carries the bell cue.
        raw = (
            "ACT 1\nHAWK: Setup.\nWEBB: The mark says ring it. [bell]\n"
            "HAWK: There it goes.\n"
        )
        act = parse_script(raw, SPEAKERS, expected_acts=1).acts[0]
        assert [t.bell_after for t in act.turns] == [False, True, False]

        async def fake_tts(line, voice_id, out, *, api_key=None, voice_settings=None):
            out.write_bytes(b"clip")

        captured: list[list] = []

        def fake_concat(inputs, output, *, gap_seconds=0.25):
            captured.append([p.name for p in inputs])
            output.write_bytes(b"mixed")

        monkeypatch.setattr(dlg, "generate_tts_to_file", fake_tts)
        monkeypatch.setattr(dlg, "concat_audio_files", fake_concat)

        bell = tmp_path / "regression-bell.mp3"
        bell.write_bytes(b"ding")
        await dlg._render_act_per_turn(
            act, DEFAULT_CAST, tmp_path / "act_1.mp3", api_key="k", bell_path=bell,
        )
        names = captured[0]
        # 3 turn clips + 1 bell = 4 inputs; bell sits right after turn 2.
        assert names.count("regression-bell.mp3") == 1
        bell_i = names.index("regression-bell.mp3")
        assert bell_i == 2  # after the 2nd turn clip (index 0,1 then bell)

    @pytest.mark.anyio
    async def test_announcer_segments_rendered_to_slots(self, tmp_path, monkeypatch):
        from gkl.nextgenpodcast import dialogue as dlg
        from gkl.nextgenpodcast.showbible import DEFAULT_CAST

        raw = (
            "INTRO\nANNOUNCER: Tonight in the Lounge.\n"
            "ACT 1\nHAWK: A.\nWEBB: B.\n"
            "BUMPER 1\nANNOUNCER: After the break.\n"
            "ACT 2\nHAWK: C.\nWEBB: D.\n"
            "CALL-IN\nANNOUNCER: We've got a caller.\nCALLER: Hi.\nHAWK: Bye.\n"
            "BUMPER 2\nANNOUNCER: The race, next.\n"
            "ACT 3\nWEBB: E.\nHAWK: Ballgame.\n"
        )
        script = parse_script(
            raw, SPEAKERS, expected_acts=3, allow_call_in=True,
            has_announcer=True, expected_bumpers=2,
        )

        async def fake_tts(line, voice_id, out, *, api_key=None, voice_settings=None):
            # The announcer's own voice is used, not a host's.
            assert voice_id == DEFAULT_CAST.announcer.voice_id
            out.write_bytes(b"clip")

        monkeypatch.setattr(dlg, "generate_tts_to_file", fake_tts)
        monkeypatch.setattr(dlg, "concat_audio_files",
                            lambda inputs, output, **k: output.write_bytes(b"m"))
        monkeypatch.setattr(dlg, "_require_key", lambda k: "key")

        slots = await dlg.render_announcer_segments(script, DEFAULT_CAST, tmp_path)
        assert set(slots) == {
            "announcer_intro", "announcer_bumper_1", "announcer_bumper_2",
        }
        assert all(p.exists() for p in slots.values())


# ---------- pipeline helpers ----------

class TestPipelineHelpers:
    def test_load_prior_takeaways_merges_v1_and_nextgen(self, tmp_path):
        from gkl.nextgenpodcast.pipeline import load_prior_takeaways

        league = "469.l.6252"
        v1 = tmp_path / "podcast" / league
        ng = v1 / "nextgen"
        (v1 / "2026-w12").mkdir(parents=True)
        (v1 / "2026-w12" / "takeaways.md").write_text(
            "# W12\n- HOST: called the upset\n- GUEST: rang nothing\n"
        )
        (ng / "2026-w13").mkdir(parents=True)
        (ng / "2026-w13" / "takeaways.md").write_text("# W13\n- HAWK: locked in\n")
        # same-week collision: nextgen wins
        (v1 / "2026-w13").mkdir(parents=True)
        (v1 / "2026-w13" / "takeaways.md").write_text("# W13 v1\n- HOST: stale\n")

        out = load_prior_takeaways(
            tmp_path, league, "2026", 14, speakers=("HAWK", "WEBB"),
        )
        assert "--- Episode: Week 12 ---" in out
        assert "HAWK: called the upset" in out       # HOST renamed
        assert "WEBB: rang nothing" in out           # GUEST renamed
        assert "stale" not in out                    # nextgen preferred
        assert "locked in" in out
        # target week and later excluded
        assert "Week 14" not in out

    def test_load_prior_takeaways_empty(self, tmp_path):
        from gkl.nextgenpodcast.pipeline import load_prior_takeaways
        assert load_prior_takeaways(
            tmp_path, "x.l.1", "2026", 5, speakers=SPEAKERS,
        ) == ""

    def test_slot_paths_cover_recipes(self, tmp_path):
        from gkl.nextgenpodcast.pipeline import _slot_paths
        from gkl.nextgenpodcast.segments import (
            ALL_STAR_DEEP_DIVE, WEEKLY_RECAP_V2,
        )

        for spec, acts, ads in ((WEEKLY_RECAP_V2, 3, 2), (ALL_STAR_DEEP_DIVE, 2, 1)):
            announcer_paths = None
            if spec.has_announcer:
                announcer_paths = {"announcer_intro": tmp_path / "intro.mp3"}
                announcer_paths.update({
                    f"announcer_bumper_{i}": tmp_path / f"bumper{i}.mp3"
                    for i in range(1, ads + 1)
                })
            slots = _slot_paths(
                spec,
                voice_paths_by_act={n: tmp_path / f"a{n}.mp3" for n in range(1, acts + 1)},
                ad_paths=[tmp_path / f"ad{i}.mp3" for i in range(ads)],
                assets_root=tmp_path,
                call_in_path=(tmp_path / "call_in.mp3") if spec.has_call_in else None,
                announcer_paths=announcer_paths,
            )
            needed = {slot.kind for slot in spec.recipe.slots}
            assert needed <= set(slots), f"{spec.slug}: missing {needed - set(slots)}"

    def test_weekly_slot_paths_require_call_in(self, tmp_path):
        from gkl.nextgenpodcast.pipeline import _slot_paths
        from gkl.nextgenpodcast.segments import WEEKLY_RECAP_V2
        with pytest.raises(ValueError, match="call-in"):
            _slot_paths(
                WEEKLY_RECAP_V2,
                voice_paths_by_act={n: tmp_path / f"a{n}.mp3" for n in (1, 2, 3)},
                ad_paths=[tmp_path / "ad0.mp3", tmp_path / "ad1.mp3"],
                assets_root=tmp_path,
            )


# ---------- segments ----------

class TestSegments:
    def test_registry(self):
        from gkl.nextgenpodcast.segments import SEGMENTS
        assert set(SEGMENTS) == {"weekly-recap-v2", "all-star-deep-dive"}
        assert SEGMENTS["weekly-recap-v2"].acts == 3
        assert SEGMENTS["all-star-deep-dive"].acts == 2

    def test_artifacts_exist(self):
        assert WEEKLY_RECAP_V2.artifact.exists()
        assert ALL_STAR_DEEP_DIVE.artifact.exists()
