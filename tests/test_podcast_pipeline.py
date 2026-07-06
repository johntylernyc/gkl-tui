"""Tests for the Phase 7 pipeline orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gkl.podcast.datapack import DataPack, DataPackMeta
from gkl.podcast.pipeline import (
    _slot_paths_for_weekly_recap, generate_weekly_recap_episode,
    load_prior_takeaways,
)
from gkl.podcast.script_writer import Act, DialogueTurn, Script, ScriptVersions
from gkl.podcast.voice import ActRenderResult
from gkl.yahoo_api import League, StatCategory


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# -- Slot-path assembly ------------------------------------------------------

def test_slot_paths_maps_voices_and_ads_and_assets(tmp_path: Path) -> None:
    voices = {
        1: tmp_path / "acts" / "act_1.mp3",
        2: tmp_path / "acts" / "act_2.mp3",
        3: tmp_path / "acts" / "act_3.mp3",
    }
    ads = [
        tmp_path / "ads" / "victory-serum.mp3",
        tmp_path / "ads" / "meatstone.mp3",
    ]
    slots = _slot_paths_for_weekly_recap(
        voice_paths_by_act=voices, ad_paths=ads, assets_root=tmp_path,
    )
    seg_dir = tmp_path / "podcast" / "weekly-recap"
    assert slots["intro_stinger"] == seg_dir / "intro-stinger.mp3"
    assert slots["body_act_1"] == voices[1]
    assert slots["body_act_3"] == voices[3]
    assert slots["ad_1"] == ads[0]
    assert slots["ad_2"] == ads[1]


def test_slot_paths_covers_every_recipe_kind(tmp_path: Path) -> None:
    from gkl.podcast.segments.weekly_recap import WEEKLY_RECAP_RECIPE
    voices = {n: tmp_path / f"act_{n}.mp3" for n in (1, 2, 3)}
    ads = [tmp_path / "ad1.mp3", tmp_path / "ad2.mp3"]
    slots = _slot_paths_for_weekly_recap(
        voice_paths_by_act=voices, ad_paths=ads, assets_root=tmp_path,
    )
    missing = WEEKLY_RECAP_RECIPE.kinds - set(slots.keys())
    assert missing == set()


# -- End-to-end orchestration (mocked sub-phases) ---------------------------

@pytest.mark.anyio
async def test_generate_weekly_recap_writes_all_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    league = League(
        league_key="mlb.l.9999", league_id="9999", name="Test League",
        season="2026", current_week=5, num_teams=18,
    )
    categories = [StatCategory(
        stat_id="12", display_name="HR", sort_order="1", position_type="B",
    )]

    fake_meta = DataPackMeta(
        league_key="mlb.l.9999", league_name="Test League", season="2026",
        segment="weekly-recap", target_week=4, current_week=5,
        week_start="2026-04-14", week_end="2026-04-20",
        generated_at="2026-04-24T00:00:00+00:00",
    )
    fake_datapack = DataPack(
        meta=fake_meta, categories=[], teams=[], roto_standings=[],
        h2h_records=[], power_rankings=[], target_week_matchups=[],
        rosters=[], target_week_rosters=[], transactions=[], mlb_games=[],
    )

    async def fake_build_datapack(*a, **k):
        return fake_datapack

    async def fake_seed(*a, **k):
        return (
            "## Act 1\n### Alpha wins\nHook: Alpha crushed Beta.\n\n"
            "## Act 2\n### Big pickup\nHook: A big add.\n\n"
            "## Act 3\n### Standout\nHook: Player X breakout."
        )

    def _fake_script(tag: str) -> Script:
        return Script(acts=[
            Act(number=n, turns=[
                DialogueTurn(
                    speaker="HOST", line=f"{tag} act {n} line A.",
                ),
                DialogueTurn(
                    speaker="GUEST", line=f"{tag} act {n} line B.",
                ),
            ])
            for n in (1, 2, 3)
        ])

    async def fake_write_script(*a, **k):
        return ScriptVersions(
            draft=_fake_script("draft"),
            fact_checked=_fake_script("fact-checked"),
            final=_fake_script("final"),
        )

    async def fake_render_voices(
        script, host_voice_id, guest_voice_id, output_dir, **k,
    ):
        results = []
        for act in script.acts:
            p = output_dir / f"act_{act.number}.mp3"
            p.write_bytes(b"fake-act")
            results.append(ActRenderResult(
                act=act.number, audio_path=p,
                turn_count=len(act.turns),
                char_cost=sum(len(t.line) for t in act.turns),
            ))
        return results

    # Make every asset file the recipe references exist so the final
    # mixer slot-resolution doesn't complain.
    assets_root = tmp_path / "assets"
    ads_dir = assets_root / "podcast" / "ads" / "library"
    ads_dir.mkdir(parents=True)
    for slug in ("victory-serum", "memorial-mattress"):
        (ads_dir / f"{slug}.mp3").write_bytes(b"fake-ad")

    seg_dir = assets_root / "podcast" / "weekly-recap"
    seg_dir.mkdir(parents=True)
    for name in (
        "intro-stinger", "intro-music", "outro-music", "outro-stinger",
        "ad-break-stinger", "returning-stinger",
    ):
        (seg_dir / f"{name}.mp3").write_bytes(b"fake-asset")

    from gkl.podcast.ads import AdSpot

    def fake_select_ads(rotation_path, n=2, library=None):
        return [
            AdSpot(slug="victory-serum", title="T", copy="x" * 200,
                   voice_id="v1", voice_character="test"),
            AdSpot(slug="memorial-mattress", title="T", copy="x" * 200,
                   voice_id="v2", voice_character="test"),
        ]

    def fake_mix(recipe, slot_paths, output_path):
        output_path.write_bytes(b"final-mp3")

    async def fake_write_takeaways(script, datapack, **k):
        return "# Weekly Recap Takeaways — Week 4\n\n## Topics covered\n- Act 1: hooks"

    monkeypatch.setattr(
        "gkl.podcast.pipeline.build_weekly_recap_datapack", fake_build_datapack,
    )
    monkeypatch.setattr("gkl.podcast.pipeline.seed_weekly_recap", fake_seed)
    monkeypatch.setattr("gkl.podcast.pipeline.write_script", fake_write_script)
    monkeypatch.setattr(
        "gkl.podcast.pipeline.write_takeaways", fake_write_takeaways,
    )
    monkeypatch.setattr(
        "gkl.podcast.pipeline.render_episode_voices", fake_render_voices,
    )
    monkeypatch.setattr(
        "gkl.podcast.pipeline.select_ads_for_episode", fake_select_ads,
    )
    monkeypatch.setattr("gkl.podcast.pipeline.mix_episode", fake_mix)

    data_root = tmp_path / "data"
    result = await generate_weekly_recap_episode(
        api=None, league=league, categories=categories, target_week=4,
        data_root=data_root, assets_root=assets_root,
    )

    assert result.segment == "weekly-recap"
    assert result.target_week == 4
    assert result.episode_dir.exists()
    assert result.final_mp3.exists()
    assert result.datapack_path.exists()
    assert result.suggested_topics_path.exists()
    # All three Phase 3 intermediates plus the final + TTS-normalized scripts
    assert (result.episode_dir / "draft-script.md").exists()
    assert (result.episode_dir / "fact-checked-script.md").exists()
    assert (result.episode_dir / "script.md").exists()
    assert (result.episode_dir / "script-tts.md").exists()
    # script.md is the editor's output; script-tts.md is what TTS actually gets
    final_text = (result.episode_dir / "script.md").read_text()
    assert "final act" in final_text
    for n in (1, 2, 3):
        assert (result.episode_dir / f"act_{n}.mp3").exists()

    # Phase 3d takeaways must be persisted alongside the script
    takeaways_path = result.episode_dir / "takeaways.md"
    assert takeaways_path.exists()
    assert "Weekly Recap Takeaways" in takeaways_path.read_text()
    assert result.takeaways_path == takeaways_path
    # No prior episodes on disk for this fresh run
    assert result.prior_episodes_used == 0

    manifest = json.loads((result.episode_dir / "episode.json").read_text())
    assert manifest["target_week"] == 4
    assert manifest["league_key"] == "mlb.l.9999"
    assert manifest["ad_slugs"] == ["victory-serum", "memorial-mattress"]
    assert manifest["char_cost_estimate"] > 0
    assert manifest["takeaways_path"].endswith("takeaways.md")
    assert manifest["prior_episodes_used"] == 0


@pytest.mark.anyio
async def test_generate_weekly_recap_char_cost_sums_turn_chars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """char_cost_estimate must reflect the TTS characters across all acts."""
    league = League(
        league_key="mlb.l.1", league_id="1", name="X", season="2026",
        current_week=5, num_teams=2,
    )
    categories: list[StatCategory] = []

    meta = DataPackMeta(
        league_key="mlb.l.1", league_name="X", season="2026",
        segment="weekly-recap", target_week=4, current_week=5,
        week_start="2026-04-14", week_end="2026-04-20",
        generated_at="now",
    )
    datapack = DataPack(
        meta=meta, categories=[], teams=[], roto_standings=[], h2h_records=[],
        power_rankings=[], target_week_matchups=[], rosters=[],
        target_week_rosters=[], transactions=[], mlb_games=[],
    )

    async def _dp(*a, **k): return datapack
    async def _seed(*a, **k):
        return "## Act 1\nA\n\n## Act 2\nB\n\n## Act 3\nC"

    async def _script(*a, **k):
        s = Script(acts=[
            Act(number=n, turns=[
                DialogueTurn(speaker="HOST", line="X" * 100),
            ])
            for n in (1, 2, 3)
        ])
        return ScriptVersions(draft=s, fact_checked=s, final=s)

    async def _voices(script, host_voice_id, guest_voice_id, output_dir, **k):
        return [
            ActRenderResult(
                act=a.number,
                audio_path=output_dir / f"act_{a.number}.mp3",
                turn_count=len(a.turns),
                char_cost=sum(len(t.line) for t in a.turns),
            )
            for a in script.acts
        ]

    from gkl.podcast.ads import AdSpot

    async def _takeaways(*a, **k): return "# Takeaways stub"

    monkeypatch.setattr("gkl.podcast.pipeline.build_weekly_recap_datapack", _dp)
    monkeypatch.setattr("gkl.podcast.pipeline.seed_weekly_recap", _seed)
    monkeypatch.setattr("gkl.podcast.pipeline.write_script", _script)
    monkeypatch.setattr("gkl.podcast.pipeline.write_takeaways", _takeaways)
    monkeypatch.setattr("gkl.podcast.pipeline.render_episode_voices", _voices)
    monkeypatch.setattr(
        "gkl.podcast.pipeline.select_ads_for_episode",
        lambda *a, **k: [
            AdSpot(slug="x", title="x", copy="x", voice_id="v", voice_character="c"),
            AdSpot(slug="y", title="y", copy="y", voice_id="v", voice_character="c"),
        ],
    )
    monkeypatch.setattr(
        "gkl.podcast.pipeline.mix_episode",
        lambda recipe, slots, out: out.write_bytes(b""),
    )

    assets_root = tmp_path / "assets"
    assets_root.mkdir()

    result = await generate_weekly_recap_episode(
        api=None, league=league, categories=categories, target_week=4,
        data_root=tmp_path / "data", assets_root=assets_root,
    )

    # Each act contributes 100 chars (one turn of 100 X's). Total = 300.
    assert result.char_cost_estimate == 300


# -- Prior-takeaways loader --------------------------------------------------

def _write_episode_takeaways(
    league_dir: Path, season: str, week: int, content: str,
) -> Path:
    episode_dir = league_dir / f"{season}-w{week:02d}"
    episode_dir.mkdir(parents=True, exist_ok=True)
    path = episode_dir / "takeaways.md"
    path.write_text(content)
    return path


def test_load_prior_takeaways_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    assert load_prior_takeaways(league_dir, "2026", 5) == ""


def test_load_prior_takeaways_concatenates_oldest_first(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    _write_episode_takeaways(league_dir, "2026", 1, "Week 1 content")
    _write_episode_takeaways(league_dir, "2026", 2, "Week 2 content")
    _write_episode_takeaways(league_dir, "2026", 3, "Week 3 content")

    result = load_prior_takeaways(league_dir, "2026", current_target_week=4)

    # All three episodes included, oldest first
    assert "Week 1 content" in result
    assert "Week 2 content" in result
    assert "Week 3 content" in result
    assert result.index("Week 1") < result.index("Week 2") < result.index("Week 3")
    # Includes per-episode header so the model can attribute callbacks
    assert "Week 1" in result
    assert "Week 2" in result


def test_load_prior_takeaways_excludes_current_target_week(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    _write_episode_takeaways(league_dir, "2026", 3, "prior")
    _write_episode_takeaways(league_dir, "2026", 4, "current run leftover")

    result = load_prior_takeaways(league_dir, "2026", current_target_week=4)

    assert "prior" in result
    # Re-running week 4 must not feed its own takeaways back into itself
    assert "current run leftover" not in result


def test_load_prior_takeaways_caps_at_window(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    for w in range(1, 9):  # 8 prior weeks
        _write_episode_takeaways(league_dir, "2026", w, f"Week {w} content")

    result = load_prior_takeaways(
        league_dir, "2026", current_target_week=9, window=6,
    )

    # Only the 6 most recent (weeks 3..8) should be included
    assert "Week 3 content" in result
    assert "Week 8 content" in result
    assert "Week 1 content" not in result
    assert "Week 2 content" not in result


def test_load_prior_takeaways_isolates_seasons(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    _write_episode_takeaways(league_dir, "2025", 3, "OLD SEASON")
    _write_episode_takeaways(league_dir, "2026", 3, "CURRENT SEASON")

    result = load_prior_takeaways(league_dir, "2026", current_target_week=5)

    assert "CURRENT SEASON" in result
    assert "OLD SEASON" not in result


def test_load_prior_takeaways_skips_dirs_without_takeaways_file(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    # Episode dir exists but no takeaways.md yet (mid-build state)
    (league_dir / "2026-w03").mkdir(parents=True)
    _write_episode_takeaways(league_dir, "2026", 4, "has takeaways")

    result = load_prior_takeaways(league_dir, "2026", current_target_week=5)

    assert "has takeaways" in result
    # Loader must not crash on the in-flight w03 dir


def test_load_prior_takeaways_skips_empty_files(tmp_path: Path) -> None:
    league_dir = tmp_path / "podcast" / "mlb.l.1"
    _write_episode_takeaways(league_dir, "2026", 3, "")  # empty
    _write_episode_takeaways(league_dir, "2026", 4, "real content")

    result = load_prior_takeaways(league_dir, "2026", current_target_week=5)

    assert "real content" in result
