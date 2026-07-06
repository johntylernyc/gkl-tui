"""CLI entry point for nextgenpodcast.

Registered as `gkl-nextgenpodcast` in pyproject.toml. Reuses the v1
CLI's Yahoo auth + league resolution.

Usage:
    gkl-nextgenpodcast weekly [--week N] [--league KEY]
    gkl-nextgenpodcast all-star --team <team_key> | --all [--through-week N]
    gkl-nextgenpodcast ads generate [--count N]
    gkl-nextgenpodcast ads render [--force]
    gkl-nextgenpodcast ads list
    gkl-nextgenpodcast assets [--force]     # Lounge Line sting etc.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from gkl.nextgenpodcast.showbible import LeagueShowConfig
from gkl.podcast.cli import _build_api, _pick_league


def _config(args: argparse.Namespace) -> LeagueShowConfig:
    if getattr(args, "playoff_spots", None):
        return LeagueShowConfig(playoff_spots=args.playoff_spots)
    return LeagueShowConfig()


async def _run_weekly(args: argparse.Namespace) -> int:
    from gkl.nextgenpodcast.pipeline import generate_weekly_episode

    api = _build_api()
    league = _pick_league(api, args.league)
    categories = api.get_stat_categories(league.league_key)

    target_week = args.week
    if target_week is None:
        if league.current_week <= 1:
            sys.exit("No completed weeks yet — pass --week once one finishes.")
        target_week = league.current_week - 1

    print(
        f"Generating Weekly Recap v2 for {league.name} "
        f"(season {league.season}), Week {target_week}…"
    )
    result = await generate_weekly_episode(
        api, league, categories, target_week,
        config=_config(args),
        data_root=Path(args.data_root) if args.data_root else None,
        assets_root=Path(args.assets_root) if args.assets_root else None,
        user_team_key=args.user_team_key,
        user_team_name=args.user_team_name,
        verbose=not args.quiet,
    )
    print(f"\nEpisode ready: {result.final_mp3}")
    print(
        f"Renderer: {result.renderer}  ·  ~{result.char_cost_estimate:,} TTS chars  ·  "
        f"{result.grades_applied} grade(s), {result.predictions_planted} plant(s)"
    )
    return 0


async def _run_all_star(args: argparse.Namespace) -> int:
    from gkl.nextgenpodcast.pipeline import (
        generate_all_star_series, generate_deep_dive_episode,
    )

    api = _build_api()
    league = _pick_league(api, args.league)
    categories = api.get_stat_categories(league.league_key)
    kwargs = dict(
        config=_config(args),
        data_root=Path(args.data_root) if args.data_root else None,
        assets_root=Path(args.assets_root) if args.assets_root else None,
        through_week=args.through_week,
        verbose=not args.quiet,
    )
    if args.all:
        results = await generate_all_star_series(api, league, categories, **kwargs)
        print(f"\n{len(results)} deep-dive episodes generated:")
        for r in results:
            print(f"  {r.episode_slug}: {r.final_mp3}")
        return 0
    if not args.team:
        sys.exit("Pass --team <team_key> or --all.")
    result = await generate_deep_dive_episode(
        api, league, categories, args.team, **kwargs,
    )
    print(f"\nEpisode ready: {result.final_mp3}")
    return 0


async def _run_ads(args: argparse.Namespace) -> int:
    from gkl.nextgenpodcast.ads import (
        generate_ad_batch, load_library, render_missing_ads,
    )
    from gkl.nextgenpodcast.pipeline import default_assets_root

    if args.ads_command == "generate":
        batch_label = date.today().isoformat()
        print(f"Writing a batch of {args.count} spots (critic pass included)…")
        accepted, verdicts = await generate_ad_batch(
            args.count, batch_label=batch_label,
        )
        print(f"Accepted {len(accepted)} of {len(verdicts)} written:")
        for spot in accepted:
            print(f"  {spot.slug}: {spot.title}")
        for v in verdicts:
            if v.get("verdict") != "pass":
                print(f"  [{v.get('verdict')}] {v.get('slug')}: {v.get('notes', '')}")
        print("Render with: gkl-nextgenpodcast ads render")
        return 0

    if args.ads_command == "render":
        assets_root = Path(args.assets_root) if args.assets_root else default_assets_root()
        rendered = await render_missing_ads(
            assets_root, force=args.force, log=print,
        )
        print(f"Rendered {len(rendered)} spot(s).")
        return 0

    if args.ads_command == "list":
        for spot in load_library():
            print(f"[{spot.status}] {spot.slug} — {spot.title} (batch {spot.batch})")
        return 0

    sys.exit("Unknown ads subcommand.")


async def _run_assets(args: argparse.Namespace) -> int:
    from gkl.nextgenpodcast.assets import render_missing_segment_assets
    from gkl.nextgenpodcast.pipeline import default_assets_root

    assets_root = Path(args.assets_root) if args.assets_root else default_assets_root()
    rendered = await render_missing_segment_assets(
        assets_root, force=args.force, log=print,
    )
    if rendered:
        print(f"Rendered {len(rendered)} asset(s).")
    else:
        print("All v2 segment assets already exist (use --force to regenerate).")
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--league", type=str, default=None)
    parser.add_argument("--data-root", type=str, default=None)
    parser.add_argument("--assets-root", type=str, default=None)
    parser.add_argument(
        "--playoff-spots", type=int, default=None,
        help="Playoff spots in the H2H standings (default 8).",
    )
    parser.add_argument("--quiet", action="store_true")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gkl-nextgenpodcast",
        description="Next-generation GKL podcast pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    weekly = sub.add_parser("weekly", help="Generate a Weekly Recap v2 episode.")
    weekly.add_argument("--week", type=int, default=None)
    weekly.add_argument("--user-team-key", type=str, default=None)
    weekly.add_argument("--user-team-name", type=str, default=None)
    _add_common(weekly)

    allstar = sub.add_parser(
        "all-star", help="Generate All-Star deep-dive episode(s).",
    )
    allstar.add_argument("--team", type=str, default=None,
                         help="Team key for a single deep dive.")
    allstar.add_argument("--all", action="store_true",
                         help="One episode per team in the league.")
    allstar.add_argument("--through-week", type=int, default=None)
    _add_common(allstar)

    ads = sub.add_parser("ads", help="Manage the generated ad library.")
    ads_sub = ads.add_subparsers(dest="ads_command", required=True)
    gen = ads_sub.add_parser("generate", help="Write + criticize a new batch.")
    gen.add_argument("--count", type=int, default=6)
    render = ads_sub.add_parser("render", help="TTS-render missing spots.")
    render.add_argument("--force", action="store_true")
    render.add_argument("--assets-root", type=str, default=None)
    ads_sub.add_parser("list", help="List the library.")

    assets = sub.add_parser(
        "assets", help="Render v2 segment assets (Lounge Line sting).",
    )
    assets.add_argument("--force", action="store_true")
    assets.add_argument("--assets-root", type=str, default=None)

    args = parser.parse_args()
    if args.command == "weekly":
        sys.exit(asyncio.run(_run_weekly(args)))
    if args.command == "all-star":
        sys.exit(asyncio.run(_run_all_star(args)))
    if args.command == "ads":
        sys.exit(asyncio.run(_run_ads(args)))
    if args.command == "assets":
        sys.exit(asyncio.run(_run_assets(args)))
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
