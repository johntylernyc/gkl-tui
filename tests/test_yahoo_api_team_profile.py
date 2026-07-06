"""Tests for TeamProfile parsing (manager biographical lookup)."""

from __future__ import annotations

from unittest.mock import MagicMock

from gkl.yahoo_api import TeamProfile, YahooFantasyAPI


def _team_wrapper(meta: list[dict]) -> list:
    """Wrap a metadata list the way Yahoo nests a single team's payload."""
    return [meta]


class TestParseTeamProfile:
    def test_full_payload(self):
        wrapper = _team_wrapper([
            {"team_key": "469.l.6252.t.7"},
            {"team_id": "7"},
            {"name": "Sho Me The Money"},
            {"team_logos": [{"team_logo": {
                "size": "large", "url": "https://example.com/logo.png",
            }}]},
            {"waiver_priority": "3"},
            {"number_of_moves": "12"},
            {"number_of_trades": "2"},
            {"clinched_playoffs": 1},
            {"managers": [{"manager": {
                "manager_id": "5",
                "nickname": "Goose",
                "guid": "ABC123XYZ",
                "is_current_login": "1",
                "felo_score": "850",
                "felo_tier": "gold",
            }}]},
        ])

        profile = YahooFantasyAPI._parse_team_profile(wrapper)

        assert profile == TeamProfile(
            team_key="469.l.6252.t.7",
            name="Sho Me The Money",
            manager_nickname="Goose",
            manager_guid="ABC123XYZ",
            felo_score="850",
            felo_tier="gold",
            is_current_login=True,
            waiver_priority=3,
            number_of_moves=12,
            number_of_trades=2,
            clinched_playoffs=True,
            team_logo_url="https://example.com/logo.png",
        )

    def test_missing_optional_fields_default_safely(self):
        wrapper = _team_wrapper([
            {"team_key": "469.l.6252.t.3"},
            {"name": "Boys of Summer"},
            {"managers": [{"manager": {"nickname": "Ryan"}}]},
        ])

        profile = YahooFantasyAPI._parse_team_profile(wrapper)

        assert profile.team_key == "469.l.6252.t.3"
        assert profile.name == "Boys of Summer"
        assert profile.manager_nickname == "Ryan"
        assert profile.manager_guid == ""
        assert profile.felo_score == ""
        assert profile.felo_tier == ""
        assert profile.is_current_login is False
        assert profile.waiver_priority == 0
        assert profile.number_of_moves == 0
        assert profile.number_of_trades == 0
        assert profile.clinched_playoffs is False
        assert profile.team_logo_url == ""

    def test_malformed_managers_block_does_not_raise(self):
        wrapper = _team_wrapper([
            {"team_key": "469.l.6252.t.9"},
            {"name": "Weird Team"},
            {"managers": []},
            {"team_logos": []},
        ])
        profile = YahooFantasyAPI._parse_team_profile(wrapper)
        assert profile.team_key == "469.l.6252.t.9"
        assert profile.manager_nickname == ""
        assert profile.team_logo_url == ""

    def test_empty_wrapper_does_not_raise(self):
        profile = YahooFantasyAPI._parse_team_profile([])
        assert profile.team_key == ""
        assert profile.name == ""


class TestGetTeamProfiles:
    def test_fetches_and_parses_all_teams(self):
        api = YahooFantasyAPI.__new__(YahooFantasyAPI)
        api._get = MagicMock(return_value={
            "league": [{}, {"teams": {
                "count": "2",
                "0": {"team": _team_wrapper([
                    {"team_key": "469.l.6252.t.1"},
                    {"name": "Team One"},
                    {"managers": [{"manager": {"nickname": "Alice"}}]},
                ])},
                "1": {"team": _team_wrapper([
                    {"team_key": "469.l.6252.t.2"},
                    {"name": "Team Two"},
                    {"managers": [{"manager": {"nickname": "Bob"}}]},
                ])},
            }}],
        })

        profiles = api.get_team_profiles("469.l.6252")

        assert [p.team_key for p in profiles] == [
            "469.l.6252.t.1", "469.l.6252.t.2",
        ]
        assert [p.manager_nickname for p in profiles] == ["Alice", "Bob"]
        api._get.assert_called_once_with(
            "league/469.l.6252/teams", cache_ttl=3600,
        )

    def test_malformed_response_returns_empty_list(self):
        api = YahooFantasyAPI.__new__(YahooFantasyAPI)
        api._get = MagicMock(return_value={"unexpected": "shape"})
        assert api.get_team_profiles("469.l.6252") == []
