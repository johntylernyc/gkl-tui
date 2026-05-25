"""CLI entry point for on-demand podcast generation.

Registered as `gkl-podcast` in pyproject.toml. Uses the same Yahoo auth
machinery as the main TUI so it picks up existing saved credentials.

Usage:
    gkl-podcast weekly-recap --week 4
    gkl-podcast weekly-recap --week 4 --league mlb.l.12345
    gkl-podcast weekly-recap --week 4 --quiet
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from gkl.podcast.pipeline import generate_weekly_recap_episode
from gkl.yahoo_api import League, YahooFantasyAPI
from gkl.yahoo_auth import (
    YahooAuth, is_web_mode, load_credentials, save_credentials,
)


# ---------- Auth + league resolution (mirrors gkl.app.main) ----------

def _load_or_prompt_credentials() -> tuple[str, str]:
    saved = load_credentials()
    if saved:
        return saved

    if is_web_mode():
        sys.exit(
            "GKL_YAHOO_CLIENT_ID and GKL_YAHOO_CLIENT_SECRET must be set "
            "in web mode."
        )

    client_id = os.environ.get("YAHOO_CLIENT_ID")
    client_secret = os.environ.get("YAHOO_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit(
            "No saved Yahoo credentials. Run the main `gkl` app once to "
            "set them up, or export YAHOO_CLIENT_ID + YAHOO_CLIENT_SECRET."
        )
    save_credentials(client_id, client_secret)
    return client_id, client_secret


def _build_api() -> YahooFantasyAPI:
    client_id, client_secret = _load_or_prompt_credentials()
    auth = YahooAuth(client_id=client_id, client_secret=client_secret)
    auth.get_token()
    return YahooFantasyAPI(auth)


def _pick_league(api: YahooFantasyAPI, league_key: str | None) -> League:
    leagues = api.get_user_leagues()
    if not leagues:
        sys.exit("No MLB leagues found on this Yahoo account.")

    if league_key:
        for lg in leagues:
            if lg.league_key == league_key:
                return lg
        sys.exit(
            f"No league with key {league_key!r}. Available: "
            + ", ".join(l.league_key for l in leagues)
        )

    if len(leagues) == 1:
        return leagues[0]

    print("Multiple leagues found — specify one with --league:")
    for lg in leagues:
        print(f"  {lg.league_key}  {lg.name}  (season {lg.season})")
    sys.exit(1)


# ---------- Subcommand: weekly-recap ----------

async def _run_weekly_recap(args: argparse.Namespace) -> int:
    api = _build_api()
    league = _pick_league(api, args.league)
    categories = api.get_stat_categories(league.league_key)

    target_week = args.week
    if target_week is None:
        # Default to the most recently completed week.
        if league.current_week <= 1:
            sys.exit(
                "No completed weeks yet this season — pass --week once at "
                "least one week has finished."
            )
        target_week = league.current_week - 1

    print(
        f"Generating Weekly Recap for {league.name} "
        f"(season {league.season}), Week {target_week}…"
    )
    result = await generate_weekly_recap_episode(
        api, league, categories, target_week,
        data_root=Path(args.data_root) if args.data_root else None,
        assets_root=Path(args.assets_root) if args.assets_root else None,
        user_team_key=args.user_team_key,
        user_team_name=args.user_team_name,
        verbose=not args.quiet,
    )
    print()
    print(f"Episode ready: {result.final_mp3}")
    print(
        f"Manifest: {result.episode_dir / 'episode.json'}  "
        f"(~{result.char_cost_estimate:,} chars of ElevenLabs usage)"
    )
    return 0


# ---------- Entry point ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gkl-podcast",
        description="Generate GKL fantasy baseball podcast episodes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    wr = subparsers.add_parser(
        "weekly-recap", help="Generate the Weekly Recap segment.",
    )
    wr.add_argument(
        "--week", type=int, default=None,
        help="Target week to recap (defaults to the most recently completed).",
    )
    wr.add_argument(
        "--league", type=str, default=None,
        help="League key (e.g. mlb.l.12345). Required if multiple leagues "
             "are on the Yahoo account.",
    )
    wr.add_argument(
        "--data-root", type=str, default=None,
        help="Override the per-episode output directory root (default: "
             "`data/` in the project root).",
    )
    wr.add_argument(
        "--assets-root", type=str, default=None,
        help="Override the committed asset library root (default: "
             "`assets/` in the project root).",
    )
    wr.add_argument(
        "--user-team-key", type=str, default=None,
        help="Optionally pass a team_key to Skipper for framing context.",
    )
    wr.add_argument(
        "--user-team-name", type=str, default=None,
        help="Optionally pass a team name to Skipper for framing context.",
    )
    wr.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-phase progress output.",
    )

    args = parser.parse_args()
    if args.command == "weekly-recap":
        sys.exit(asyncio.run(_run_weekly_recap(args)))
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
