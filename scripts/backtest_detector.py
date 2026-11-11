"""Replay the detector over a copy of the database with several rule sets (D44, #47).

    uv run python scripts/backtest_detector.py data/escapadinha.db
    uv run python scripts/backtest_detector.py data/escapadinha.db --preset data-reliability --runs 19-57
    uv run python scripts/backtest_detector.py data/escapadinha.db --days 14 --candidates --json out.json
    uv run python scripts/backtest_detector.py data/escapadinha.db --preset stays --days 14
    uv run python scripts/backtest_detector.py data/escapadinha.db --preset probe --json out.json

Read-only: the file is opened read-only and copied into memory (`escapadinha.backtest`). Routes
and the configured detector come from the repository's config.yaml and the copy's `routes`
table; no network, no secrets. Prints Markdown (the tables of
docs/research/2026-10-18-detector-backtest.md), optionally the same figures as JSON.
`--preset probe` replays no detector: it compares every deal from the cache with the PC
probe's searches of its trip and replays a grid of probe-expiry rules over the deals' lives
(`backtest.probe_report`, docs/research/2026-11-11-probe-expiry.md; `--runs`/`--days` do
not apply).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from escapadinha import backtest, routes
from escapadinha.config import Context

REPO = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path, help="database copy (opened read-only)")
    parser.add_argument("--preset", choices=(*backtest.PRESETS, backtest.PROBE_PRESET), default="d44",
                        help="rule sets to compare (default: d44)")
    parser.add_argument("--runs", help="replay these run ids, e.g. 19-57 (default: --days)")
    parser.add_argument("--days", type=int, default=14,
                        help="replay the runs of the N Lisbon days before the latest run (default 14)")
    parser.add_argument("--candidates", action="store_true", help="list every candidate")
    parser.add_argument("--state", action="store_true",
                        help="also describe every route-month's typical low at the latest run")
    parser.add_argument("--json", type=Path, help="also write the figures as JSON here")
    args = parser.parse_args(argv)

    ctx = Context(root=REPO)
    conn = backtest.open_copy(args.db)
    if args.preset == backtest.PROBE_PRESET:
        data = backtest.probe_report(backtest.cache_deals(conn), backtest.default_rules(),
                                     ctx.config.detector.recheck_tolerance_pct,
                                     controls=backtest.cache_deals(conn, source=backtest.ryanair.SOURCE))
        sys.stdout.write(backtest.probe_markdown(data))
        if args.json:
            args.json.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        return 0
    all_runs = backtest.completed_runs(conn)
    ids = tuple(int(x) for x in args.runs.split("-")) if args.runs else None
    runs = backtest.select_runs(all_runs, ids=ids, days=args.days)
    if not runs:
        print("No completed runs in that window.", file=sys.stderr)
        return 1
    cfg = ctx.config.routes
    watched = [r for r in routes.all_routes(conn, cfg) if not cfg.excluded(r.origin, r.destination)]
    sets = backtest.rule_sets(ctx.config.detector, args.preset, routes_cfg=cfg, watched=watched)
    replays = backtest.replay(conn, watched, sets, runs, all_runs=all_runs)
    sys.stdout.write(backtest.markdown(replays, candidates=args.candidates))
    figures = backtest.to_json(replays)
    if args.state:
        data = backtest.state(conn, watched, ctx.config.detector)
        sys.stdout.write("\n" + backtest.state_markdown(data, ctx.config.detector))
        figures["state"] = data
    if args.json:
        args.json.write_text(json.dumps(figures, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
