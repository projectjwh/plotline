# Scheduling & automation

Plotline ships three ways to schedule the pipeline. All are **defined**; whether any is
**running** depends on your setup.

```{admonition} Built vs. running
:class: important
| Mechanism | Defined? | Running by default? |
|---|---|---|
| `run_pipeline.py` orchestrator | ✅ | Only when you invoke it |
| Windows Task Scheduler | 📄 documented | ❌ not registered until you create the task |
| Airflow DAG (`dags/comic_scraper_dag.py`, daily) | ✅ | ❌ needs a running Airflow instance |
| GitHub Actions (`.github/workflows/refresh.yml`, daily 06:17 UTC) | ✅ | ❌ only fires once pushed to GitHub **with secrets set** |
```

Two limits apply to **every** schedule:

1. The pipeline stops at the **warehouse** — it does not rebuild the explorer HTML. Run
   `build_explorer` as a following step if you want a fresh artifact.
2. Re-publishing the explorer to a hosted URL (e.g. a Claude artifact) is a manual/authoring
   step and cannot be automated by a cron.

## Option A — Windows Task Scheduler (most reliable locally)

Runs on this machine, from a residential IP (so scraping is less likely to be blocked):

```powershell
Register-ScheduledTask -TaskName "Plotline" -Action (New-ScheduledTaskAction `
  -Execute (Get-Command python).Source -Argument "run_pipeline.py --enrich 300" `
  -WorkingDirectory "C:\path\to\leesearch") `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 6am)
```

Notes: the task only fires when the PC is on at that time (add wake/"run when available" if
needed); a light `--enrich 300` daily is reasonable, with a heavier full crawl weekly.

## Option B — GitHub Actions (`refresh.yml`)

A daily cron (`06:17 UTC`) plus manual dispatch. To actually run end-to-end it needs repo
secrets for object storage (`R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
`R2_BUCKET`, `R2_PUBLIC_BASE`) so `publish_warehouse` can upload the artifact. Caveat:
datacenter IPs are often blocked by the target platforms, so the local run is the dependable
fallback for scraping.

## Option C — Airflow

`dags/comic_scraper_dag.py` chains scrape → parse → metrics → analytics on a daily schedule,
for teams already running Airflow (Linux). On Windows, prefer Option A.

## Recommended daily job

```bash
python run_pipeline.py --enrich 300 \
  && python -m src.reports.build_explorer --covers 6000 --out reports/leesearch_explorer.html
```

Wrap that in whichever scheduler fits your environment.
