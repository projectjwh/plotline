"""LeeSearch pipeline orchestrator.

A dependency-light replacement for the (Windows-incompatible) Airflow DAG. Runs
the medallion pipeline end to end, each stage as an isolated module invocation,
with per-stage timing, a captured log, and a final summary. Live-scraping stages
are opt-in so a default run safely reprocesses existing Bronze.

Default stages (safe, no network):  parse -> gold -> earnings -> trends -> reports
Opt-in stages:                       --scrape (fresh rankings), --enrich N (detail metrics)

Examples
    python run_pipeline.py                     # process existing data end to end
    python run_pipeline.py --enrich 200        # + crawl 200 detail pages first
    python run_pipeline.py --scrape --enrich 500   # full refresh
    python run_pipeline.py --only parse,gold   # just those stages
    python run_pipeline.py --strict            # abort on first failure

Schedule it daily with Windows Task Scheduler (PowerShell, one-off setup):
    $py = (Get-Command python).Source
    $act = New-ScheduledTaskAction -Execute $py `
        -Argument "run_pipeline.py --enrich 300" -WorkingDirectory "<repo path>"
    $trg = New-ScheduledTaskTrigger -Daily -At 6am
    Register-ScheduledTask -TaskName "LeeSearch" -Action $act -Trigger $trg
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"

# (name, module-args, enabled-by-default)
STAGES = [
    ("scrape",   ["-m", "src.scrapers.scraper_core"],      False),
    ("enrich",   ["-m", "src.scrapers.detail_crawler"],    False),
    ("parse",    ["-m", "src.pipelines.parser"],           True),
    ("gold",     ["-m", "src.pipelines.pipeline_updates"], True),
    ("dq",       ["-m", "src.pipelines.dq_checks"],         True),
    ("earnings", ["-m", "src.models.earnings"],            True),
    ("plotscore", ["-m", "src.models.plotscore"],          True),
    ("entities", ["-m", "src.models.entity_resolution"],   True),
    ("signals",  ["-m", "src.models.trends_engine"],       True),
    ("kpis",     ["-m", "src.models.kpi_layers"],          True),
    ("style",    ["-m", "src.models.art_style"],           True),
    ("episodes", ["-m", "src.models.episode_analytics"],   True),
    ("units",    ["-m", "src.models.unit_stats"],          True),
    ("trends",   ["-m", "src.models.trend_detection"],     True),
    ("daily",    ["-m", "src.reports.daily_report"],       True),
    ("weekly",   ["-m", "src.reports.weekly_report"],      True),
    ("warehouse", ["-m", "src.db.warehouse"],             True),
]


def _run_stage(name: str, args: list[str], log) -> tuple[bool, float]:
    banner = f"\n{'='*66}\n▶ {name}  ({' '.join(args)})\n{'='*66}"
    print(banner); log.write(banner + "\n")
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, *args], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    dt = time.monotonic() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-12:])  # keep console readable
    print(tail); log.write(out + "\n")
    ok = proc.returncode == 0
    print(f"  {'✔ ok' if ok else '✗ FAILED'} — {name} in {dt:.1f}s (exit {proc.returncode})")
    return ok, dt


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the LeeSearch medallion pipeline.")
    ap.add_argument("--scrape", action="store_true", help="fetch fresh ranking pages first (live, Playwright)")
    ap.add_argument("--enrich", type=int, metavar="N", help="crawl N detail pages for metrics before parsing")
    ap.add_argument("--only", help="comma list of stages to run (overrides defaults)")
    ap.add_argument("--strict", action="store_true", help="abort on the first failing stage")
    args = ap.parse_args()

    enabled = {n for n, _, d in STAGES if d}
    if args.scrape:
        enabled.add("scrape")
    if args.enrich is not None:
        enabled.add("enrich")
    if args.only:
        enabled = {s.strip() for s in args.only.split(",")}

    # inject the enrich limit
    stages = []
    for name, sargs, _ in STAGES:
        if name not in enabled:
            continue
        if name == "enrich" and args.enrich is not None:
            sargs = sargs + ["--limit", str(args.enrich)]
        stages.append((name, sargs))

    LOGS.mkdir(exist_ok=True)
    log_path = LOGS / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"
    print(f"LeeSearch pipeline — {len(stages)} stages: {', '.join(n for n, _ in stages)}")
    print(f"Log: {log_path}")

    results = []
    with open(log_path, "w", encoding="utf-8") as log:
        for name, sargs in stages:
            ok, dt = _run_stage(name, sargs, log)
            results.append((name, ok, dt))
            if not ok and args.strict:
                print("\n✗ Aborting (--strict).")
                break

    total = sum(dt for _, _, dt in results)
    print(f"\n{'─'*50}\nSUMMARY ({total:.1f}s total)")
    for name, ok, dt in results:
        print(f"  {'✔' if ok else '✗'} {name:10} {dt:6.1f}s")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"\n{len(failed)} stage(s) failed: {', '.join(failed)}  (see {log_path})")
        return 1
    print("\nAll stages succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
