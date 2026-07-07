"""Mocked end-to-end tests for the nextgenpodcast pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gkl.nextgenpodcast.datapack import (
    PlayoffRacePack, TeamSeasonPack, WeeklyRacePack, compute_playoff_race,
)
from gkl.nextgenpodcast.dialogue import ActRenderResult
from gkl.nextgenpodcast.pipeline import (
    generate_deep_dive_episode, generate_weekly_episode,
)
from gkl.nextgenpodcast.showrunner import Rundown, split_rundown_sections
from gkl.nextgenpodcast.showstate import (
    Prediction, ShowState, load_show_state, save_show_state,
    state_path_for_league,
)
from gkl.podcast.datapack import (
    DataPack, DataPackMeta, H2HRecord, TeamRoster,
)
from gkl.yahoo_api import League, StatCategory


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


LEAGUE = League(
    league_key="mlb.l.9999", league_id="9999", name="Test League",
    season="2026", current_week=15, num_teams=18,
)
CATEGORIES = [StatCategory(
    stat_id="12", display_name="HR", sort_order="1", position_type="B",
)]


def _fake_weekly_pack(target_week: int) -> WeeklyRacePack:
    meta = DataPackMeta(
        league_key=LEAGUE.league_key, league_name=LEAGUE.name,
        season=LEAGUE.season, segment="weekly-recap",
        target_week=target_week, current_week=LEAGUE.current_week,
        week_start="2026-06-22", week_end="2026-06-28",
        generated_at="now",
    )
    base = DataPack(
        meta=meta, categories=[], teams=[], roto_standings=[],
        h2h_records=[], power_rankings=[], target_week_matchups=[],
        rosters=[], target_week_rosters=[], transactions=[], mlb_games=[],
    )
    recs = [H2HRecord(
        team_key=f"k.{i}", name=f"Team{i}", manager=f"M{i}",
        wins=10 - i, losses=i, ties=0,
        cat_wins=150 - i * 5, cat_losses=50 + i * 5, cat_ties=2,
    ) for i in range(12)]
    race = compute_playoff_race(recs, playoff_spots=8, through_week=target_week)
    return WeeklyRacePack(base=base, race=race)


_RUNDOWN_TEXT = """\
**COLD OPEN**
Style: The grade.

**LEDGER GRADES**
GRADE: 2026-w13-HAWK-1 | correct | it happened

**ACT 1**
Hawk fronts.

**ACT 2**
Webb fronts.

**ACT 3**
Webb fronts, race first.

**ARGUMENT ACT**
Act 3, fall pick.

**CALL-IN**
CALLER: Donny from Pittsford | voice: gs0tAILXbY5DNrJrsM6F | granddad take
He thinks the closers should have been sold. Hawk agrees; Webb corrects his ERA number.

**NEW LEDGER ENTRIES**
PLANT: HAWK | Team7 climbs into the top eight | resolves-by: Week 17

**BITS BUDGET**
Bell in Act 2.

**SIGN-OFF**
Ledger stakes.
"""


def _script_text(
    acts: int, tag: str, *, call_in: bool = False, announcer: bool = False,
) -> str:
    parts = []
    if announcer:
        parts.append("INTRO")
        parts.append(f"ANNOUNCER: {tag} tonight, the race tightens.")
    for n in range(1, acts + 1):
        parts.append(f"ACT {n}")
        parts.append(f"HAWK: {tag} act {n} from the gut.")
        parts.append(f"WEBB: {tag} act {n} from the spreadsheet.")
        if call_in and n == 2:
            parts.append("CALL-IN")
            if announcer:
                parts.append(f"ANNOUNCER: {tag} we've got Donny. What's on your mind?")
            parts.append(f"HAWK: {tag} lounge line, who have we got?")
            parts.append(f"CALLER: {tag} Donny from Pittsford, sell the closers!")
            parts.append(f"WEBB: {tag} Donny, the number is two ninety-six.")
        # A bumper precedes each ad break: after Act 1, and after the
        # call-in (which follows Act 2). Not after the final act.
        if announcer and n < acts:
            parts.append(f"BUMPER {n}")
            parts.append(f"ANNOUNCER: {tag} after the break, bumper {n}.")
    return "\n".join(parts) + "\n"


def _takeaways_text() -> str:
    return (
        "# Weekly Recap Takeaways — Week 14\n\n"
        "## Topics covered\n- Act 1: scoreboard\n\n"
        "## Takes worth revisiting\n- HAWK: Team7 is surging\n\n"
        "## Act 2 segment call-outs\n- Regression Watch: Player X flagged lucky\n\n"
        "## Ledger — new predictions\n"
        "- PLANT: HAWK | Team7 climbs into the top eight | resolves-by: Week 17\n\n"
        "## Ledger — grades delivered\n"
        "- GRADE: HAWK | correct | graded on air\n"
    )


def _install_assets(assets_root: Path) -> None:
    seg = assets_root / "podcast" / "weekly-recap"
    seg.mkdir(parents=True, exist_ok=True)
    for name in ("intro-stinger", "intro-music", "outro-music",
                 "outro-stinger", "ad-break-stinger", "returning-stinger"):
        (seg / f"{name}.mp3").write_bytes(b"asset")
    v1_ads = assets_root / "podcast" / "ads" / "library"
    v1_ads.mkdir(parents=True, exist_ok=True)


def _patch_common(
    monkeypatch: pytest.MonkeyPatch, *, acts: int, call_in: bool = False,
    announcer: bool = False,
) -> None:
    pl = "gkl.nextgenpodcast.pipeline"

    async def fake_seed(*a, **k):
        return "## Act 1\n### Story\nHook."

    async def fake_showrunner(artifact, tokens, **k):
        return Rundown(
            text=_RUNDOWN_TEXT, sections=split_rundown_sections(_RUNDOWN_TEXT),
        )

    async def fake_run_stage(artifact, stage, tokens, **k):
        # The chain must thread each stage's output into the next stage's
        # tokens — assert the wiring here.
        if stage == "draft":
            assert "rundown" in tokens and "Style: The grade." in tokens["rundown"]
            return _script_text(acts, "draft", call_in=call_in, announcer=announcer)
        if stage == "fact_check":
            assert "draft act 1" in tokens["draft_script"]
            # fact-checker must receive the FULL summary variant
            assert tokens["data_summary"] == tokens["checker_data_summary"]
            return _script_text(acts, "checked", call_in=call_in, announcer=announcer)
        if stage == "punch_up":
            assert "checked act 1" in tokens["fact_checked_script"]
            return _script_text(acts, "punched", call_in=call_in, announcer=announcer)
        if stage == "edit":
            assert "punched act 1" in tokens["script"]
            return _script_text(acts, "final", call_in=call_in, announcer=announcer)
        if stage == "takeaways":
            assert "final act 1" in tokens["final_script"]
            return _takeaways_text()
        raise AssertionError(f"unexpected stage {stage}")

    async def fake_voices(script, cast, output_dir, **k):
        out = []
        for act in script.acts:
            p = output_dir / f"act_{act.number}.mp3"
            p.write_bytes(b"voice")
            out.append(ActRenderResult(
                act=act.number, audio_path=p, turn_count=len(act.turns),
                char_cost=sum(len(t.line) for t in act.turns),
                renderer="per-turn",
            ))
        return out

    async def fake_announcer(script, cast, output_dir, **k):
        slots: dict = {}
        if script.intro:
            p = output_dir / "announcer_intro.mp3"
            p.write_bytes(b"sid")
            slots["announcer_intro"] = p
        for i, _ in enumerate(script.bumpers, 1):
            p = output_dir / f"announcer_bumper_{i}.mp3"
            p.write_bytes(b"sid")
            slots[f"announcer_bumper_{i}"] = p
        return slots

    async def fake_call_in(turns, cast, caller_voice, out_path, **k):
        assert any(t.speaker == "CALLER" for t in turns)
        out_path.write_bytes(b"call-in")
        return sum(len(t.line) for t in turns)

    def fake_select(data_root, assets_root, league_key, n,
                    exclude_voice_ids=frozenset()):
        paths = []
        for i in range(n):
            p = assets_root / "podcast" / "ads" / "library" / f"fake-{i}.mp3"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"ad")
            paths.append(p)
        return [f"fake-{i}" for i in range(n)], paths

    monkeypatch.setattr(f"{pl}.run_seed", fake_seed)
    monkeypatch.setattr(f"{pl}.run_showrunner", fake_showrunner)
    monkeypatch.setattr(f"{pl}.run_stage", fake_run_stage)
    monkeypatch.setattr(f"{pl}.render_episode_voices", fake_voices)
    monkeypatch.setattr(f"{pl}.render_announcer_segments", fake_announcer)
    monkeypatch.setattr(f"{pl}.render_call_in", fake_call_in)
    monkeypatch.setattr(f"{pl}._select_ads", fake_select)
    monkeypatch.setattr(
        f"{pl}.mix_episode", lambda recipe, slots, out: out.write_bytes(b"mp3"),
    )


@pytest.mark.anyio
async def test_weekly_episode_end_to_end(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    assets_root = tmp_path / "assets"
    _install_assets(assets_root)

    # Pre-seed an open prediction so the rundown's grade has a target.
    state_path = state_path_for_league(data_root, LEAGUE.league_key)
    state = ShowState()
    state.add_prediction(Prediction(
        id="2026-w13-HAWK-1", season="2026", week_made=13,
        speaker="HAWK", text="it will happen",
    ))
    save_show_state(state, state_path)

    async def fake_pack(*a, **k):
        return _fake_weekly_pack(14)

    monkeypatch.setattr(
        "gkl.nextgenpodcast.pipeline.build_weekly_race_datapack", fake_pack,
    )
    _patch_common(monkeypatch, acts=3, call_in=True, announcer=True)

    result = await generate_weekly_episode(
        api=None, league=LEAGUE, categories=CATEGORIES, target_week=14,
        data_root=data_root, assets_root=assets_root,
    )

    ep = result.episode_dir
    for name in ("datapack.json", "suggested-topics.md", "rundown.md",
                 "draft-script.md", "fact-checked-script.md",
                 "punched-up-script.md", "script.md", "script-tts.md",
                 "takeaways.md", "episode.json", "final.mp3",
                 "call_in.mp3"):
        assert (ep / name).exists(), f"missing {name}"
    assert "final act 1" in (ep / "script.md").read_text()

    # Ledger: grade applied + plant recorded, state persisted.
    saved = load_show_state(state_path)
    graded = next(p for p in saved.predictions if p.id == "2026-w13-HAWK-1")
    assert graded.status == "correct"
    plants = [p for p in saved.predictions if p.status == "open"]
    assert len(plants) == 1
    assert plants[0].speaker == "HAWK"
    assert "Team7" in plants[0].text
    assert saved.records("2026") == {"HAWK": (1, 0)}

    # Variety history recorded, caller included.
    assert saved.episodes[-1].slug == "2026-w14"
    assert "The grade" in saved.episodes[-1].cold_open
    assert "Donny from Pittsford" in saved.episodes[-1].caller
    assert "gs0tAILXbY5DNrJrsM6F" in saved.episodes[-1].caller

    # Manifest sane.
    manifest = json.loads((ep / "episode.json").read_text())
    assert manifest["segment"] == "weekly-recap-v2"
    assert manifest["grades_applied"] == 1
    assert manifest["predictions_planted"] == 1
    assert manifest["renderer"] == "per-turn"
    assert manifest["ad_slugs"] == ["fake-0", "fake-1"]
    assert "Donny from Pittsford" in manifest["caller"]
    # call-in text flowed into script.md between acts 2 and 3
    script_md = (ep / "script.md").read_text()
    assert script_md.index("ACT 2") < script_md.index("CALL-IN") < script_md.index("ACT 3")

    # Playoff race made it into the datapack json.
    pack = json.loads((ep / "datapack.json").read_text())
    assert "playoff_race" in pack
    assert pack["playoff_race"]["playoff_spots"] == 8


@pytest.mark.anyio
async def test_deep_dive_episode_end_to_end(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    assets_root = tmp_path / "assets"
    _install_assets(assets_root)

    recs = [H2HRecord(
        team_key=f"k.{i}", name=f"Team{i}", manager=f"M{i}",
        wins=10 - i, losses=i, ties=0,
        cat_wins=150 - i * 5, cat_losses=50 + i * 5, cat_ties=2,
    ) for i in range(12)]
    race = compute_playoff_race(recs, playoff_spots=8, through_week=14)
    pack = TeamSeasonPack(
        league_key=LEAGUE.league_key, league_name=LEAGUE.name,
        season="2026", team_key="k.7", team_name="Team7", manager="M7",
        through_week=14, generated_at="now", weekly_results=[],
        roto_entry=None, roto_rank=9, race=race,
        roster=TeamRoster(team_key="k.7", team_name="Team7", manager="M7",
                          players=[]),
        transactions=[], momentum_line="", matchup_records=[],
    )

    async def fake_pack_builder(*a, **k):
        return pack

    monkeypatch.setattr(
        "gkl.nextgenpodcast.pipeline.build_team_season_pack", fake_pack_builder,
    )
    _patch_common(monkeypatch, acts=2)

    result = await generate_deep_dive_episode(
        api=None, league=LEAGUE, categories=CATEGORIES, team_key="k.7",
        data_root=data_root, assets_root=assets_root, through_week=14,
    )

    assert result.segment == "all-star-deep-dive"
    assert result.episode_slug == "allstar-w14-t7"
    assert result.final_mp3.exists()
    # Two acts only.
    assert (result.episode_dir / "act_1.mp3").exists()
    assert (result.episode_dir / "act_2.mp3").exists()
    assert not (result.episode_dir / "act_3.mp3").exists()
