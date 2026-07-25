"""Airflow DAG — LeeSearch medallion pipeline (Linux/cloud fallback).

On the local Windows box, prefer ``run_pipeline.py`` + Task Scheduler (Airflow
does not run natively on Windows). This DAG mirrors the same stages for a
Linux/cloud deployment. Key fixes vs. the original: the project root is derived
from the DAG file location (no hard-coded path), and every task uses module
invocation (``python -m src...``) so the package imports resolve.
"""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

# dags/ lives at the project root; derive it (override with LEESEARCH_HOME).
PROJECT_ROOT = os.environ.get(
    "LEESEARCH_HOME",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

default_args = {
    "owner": "leesearch",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _task(dag, task_id, module_args):
    return BashOperator(
        task_id=task_id,
        bash_command=f"cd {PROJECT_ROOT} && python -m {module_args}",
        dag=dag,
    )


with DAG(
    "web_comic_trend_research",
    default_args=default_args,
    description="Daily web comic/novel scrape → enrich → analyse → report",
    schedule_interval=timedelta(days=1),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["scraping", "etl", "comics"],
) as dag:
    scrape   = _task(dag, "scrape_rankings",  "src.scrapers.scraper_core")
    enrich   = _task(dag, "enrich_details",   "src.scrapers.detail_crawler --limit 300")
    parse    = _task(dag, "parse_bronze",     "src.pipelines.parser")
    gold     = _task(dag, "update_metrics",   "src.pipelines.pipeline_updates")
    earnings = _task(dag, "estimate_earnings", "src.models.earnings")
    plotscore = _task(dag, "compute_plotscore", "src.models.plotscore")
    entities = _task(dag, "resolve_entities",  "src.models.entity_resolution")
    signals  = _task(dag, "trend_signals",     "src.models.trends_engine")
    trends   = _task(dag, "run_trends",       "src.models.trend_detection")
    kpis     = _task(dag, "kpi_layers",       "src.models.kpi_layers")
    style    = _task(dag, "art_style",        "src.models.art_style")
    daily    = _task(dag, "daily_report",     "src.reports.daily_report")
    weekly   = _task(dag, "weekly_report",    "src.reports.weekly_report")
    warehouse = _task(dag, "build_warehouse", "src.db.warehouse")

    scrape >> enrich >> parse >> gold >> earnings >> plotscore >> entities >> signals >> kpis >> style >> trends >> [daily, weekly] >> warehouse
