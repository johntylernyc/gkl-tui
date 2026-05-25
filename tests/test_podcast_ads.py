"""Tests for the ad library and LRU rotation (Phase 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gkl.podcast.ads import (
    AD_LIBRARY, AdSpot, find_ad, rotation_path_for_league,
    select_ads_for_episode,
)


# -- Library sanity ---------------------------------------------------------

def test_ad_library_has_at_least_12_spots() -> None:
    """Enough ads so a 2-per-episode rotation doesn't repeat for 6 weeks."""
    assert len(AD_LIBRARY) >= 12


def test_ad_slugs_are_unique() -> None:
    slugs = [ad.slug for ad in AD_LIBRARY]
    assert len(slugs) == len(set(slugs))


def test_ad_copy_is_reasonable_length() -> None:
    """Each ad should be ~15 seconds at ~150 wpm — roughly 200-400 chars."""
    for ad in AD_LIBRARY:
        assert 150 <= ad.char_count() <= 400, (
            f"{ad.slug}: {ad.char_count()} chars outside 150-400 range"
        )


def test_find_ad_returns_matching_spot() -> None:
    ad = find_ad("victory-serum")
    assert ad.slug == "victory-serum"


def test_find_ad_raises_on_unknown_slug() -> None:
    with pytest.raises(KeyError):
        find_ad("does-not-exist")


def test_ad_asset_path_is_under_library_folder(tmp_path: Path) -> None:
    ad = AdSpot(
        slug="test-slug", title="T", copy="x",
        voice_id="v", voice_character="x",
    )
    path = ad.asset_path(tmp_path)
    assert path == tmp_path / "podcast" / "ads" / "library" / "test-slug.mp3"


def test_all_library_ads_have_voice_ids() -> None:
    for ad in AD_LIBRARY:
        assert ad.voice_id, f"{ad.slug} is missing voice_id"
        assert ad.voice_character, f"{ad.slug} is missing voice_character"


def test_library_voice_ids_are_all_distinct() -> None:
    """Per-ad voices are the whole point of per-ad casting."""
    voice_ids = [ad.voice_id for ad in AD_LIBRARY]
    assert len(voice_ids) == len(set(voice_ids))


# -- LRU rotation ------------------------------------------------------------

def _small_library() -> list[AdSpot]:
    return [
        AdSpot(
            slug=f"ad-{i}", title=f"T{i}", copy="x" * 200,
            voice_id=f"voice-{i}", voice_character="test",
        )
        for i in range(1, 6)
    ]


def test_first_call_initializes_rotation(tmp_path: Path) -> None:
    lib = _small_library()
    path = tmp_path / "rotation.json"
    picked = select_ads_for_episode(path, n=2, library=lib)
    assert [a.slug for a in picked] == ["ad-1", "ad-2"]

    # Rotation persisted with picked ads moved to the back
    data = json.loads(path.read_text())
    assert data["rotation"] == ["ad-3", "ad-4", "ad-5", "ad-1", "ad-2"]


def test_subsequent_calls_avoid_most_recent_ads(tmp_path: Path) -> None:
    lib = _small_library()
    path = tmp_path / "rotation.json"

    first = [a.slug for a in select_ads_for_episode(path, n=2, library=lib)]
    second = [a.slug for a in select_ads_for_episode(path, n=2, library=lib)]
    third = [a.slug for a in select_ads_for_episode(path, n=2, library=lib)]

    assert first == ["ad-1", "ad-2"]
    assert second == ["ad-3", "ad-4"]
    assert third == ["ad-5", "ad-1"]
    # Third episode's ad-1 was first aired episode 1 — full-cycle before repeat
    assert set(first) & set(second) == set()
    assert set(second) & set(third) == set()


def test_rotation_handles_new_ads_appended_to_library(tmp_path: Path) -> None:
    lib_small = _small_library()
    path = tmp_path / "rotation.json"
    # Prime with the small library
    select_ads_for_episode(path, n=2, library=lib_small)  # ad-1, ad-2 aired

    # Add two new ads to the "library"
    lib_grown = lib_small + [
        AdSpot(slug="ad-6", title="T6", copy="x" * 200,
               voice_id="v6", voice_character="test"),
        AdSpot(slug="ad-7", title="T7", copy="x" * 200,
               voice_id="v7", voice_character="test"),
    ]
    picked = [a.slug for a in select_ads_for_episode(path, n=2, library=lib_grown)]
    # Newly added ads go to the tail; next picks should come from the
    # not-yet-aired middle section
    assert picked == ["ad-3", "ad-4"]

    data = json.loads(path.read_text())
    # ad-6, ad-7 are in rotation, waiting their turn
    assert "ad-6" in data["rotation"]
    assert "ad-7" in data["rotation"]


def test_rotation_handles_removed_ads_from_library(tmp_path: Path) -> None:
    lib_full = _small_library()
    path = tmp_path / "rotation.json"
    # Prime with all 5 aired
    select_ads_for_episode(path, n=5, library=lib_full)
    # State now: rotation = ["ad-1", ..., "ad-5"] (all moved to back in order)

    # Shrink library (remove ad-3 and ad-5)
    lib_small = [ad for ad in lib_full if ad.slug not in {"ad-3", "ad-5"}]
    picked = [a.slug for a in select_ads_for_episode(path, n=2, library=lib_small)]
    assert set(picked).issubset({"ad-1", "ad-2", "ad-4"})


def test_rotation_raises_when_library_too_small(tmp_path: Path) -> None:
    path = tmp_path / "rotation.json"
    tiny = [AdSpot(
        slug="solo", title="X", copy="x" * 200,
        voice_id="v", voice_character="test",
    )]
    with pytest.raises(ValueError, match="need at least 2"):
        select_ads_for_episode(path, n=2, library=tiny)


def test_rotation_recovers_from_corrupt_state_file(tmp_path: Path) -> None:
    lib = _small_library()
    path = tmp_path / "rotation.json"
    path.write_text("not valid json {{")
    picked = [a.slug for a in select_ads_for_episode(path, n=2, library=lib)]
    # Should re-initialize from library order
    assert picked == ["ad-1", "ad-2"]


def test_rotation_path_for_league(tmp_path: Path) -> None:
    path = rotation_path_for_league(tmp_path, "mlb.l.12345")
    assert path == tmp_path / "podcast" / "mlb.l.12345" / "ad-rotation.json"
