import os
import yaml
import sys
import polars as pl
from datetime import datetime
from glob import glob

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

def _load_silver(silver_dir):
    """Prefer the new partitioned Silver (data/silver/comics/**); fall back to
    the legacy flat comics_update_*.parquet files if it is not present yet."""
    partitioned = glob(os.path.join(silver_dir, "comics", "**", "*.parquet"), recursive=True)
    if partitioned:
        # source/date live in the stored columns already, so ignore path hive cols.
        return pl.scan_parquet(partitioned, hive_partitioning=False)
    legacy = glob(os.path.join(silver_dir, "*.parquet"))
    if legacy:
        return pl.scan_parquet(legacy)
    return None

def run_silver_to_gold():
    """Aggregates Silver data into Gold metrics (Velocity, Growth)."""
    silver_dir = CONFIG['storage']['silver_path']
    gold_dir = CONFIG['storage']['gold_path']

    lazy_df = _load_silver(silver_dir)
    if lazy_df is None:
        print("No silver data found.")
        return

    # Sort by ID and Date
    df = lazy_df.sort(["comic_id", "scraped_at"]).collect()
    
    print(f"Loaded {len(df)} records from Silver.")

    # Calculate Velocity (Day over Day changes)
    # Since we might have multiple snapshots per day, we take the latest per day first
    df_daily = df.with_columns(
        pl.col("scraped_at").dt.date().alias("date")
    ).group_by(["comic_id", "date"]).agg([
        pl.col("title").first(),
        pl.col("genre").first(),
        pl.col("source").first(),
        pl.col("views").max(),
        pl.col("likes").max()
    ]).sort(["comic_id", "date"])

    # Calculate Deltas
    df_metrics = df_daily.with_columns([
        pl.col("views").diff().over("comic_id").alias("views_gained"),
        pl.col("likes").diff().over("comic_id").alias("likes_gained"),
    ])

    # Fill nulls (first day usually null) with 0 for gaining metrics
    df_metrics = df_metrics.with_columns([
        pl.col("views_gained").fill_null(0),
        pl.col("likes_gained").fill_null(0)
    ])
    
    # 7-Day Rolling Velocity
    # Note: For now, we just output the snapshot. 
    # In a real system, we'd calculate Rolling Avg here.
    
    print("Metrics Calculated. Saving to Gold...")
    output_path = os.path.join(gold_dir, f"gold_metrics_{int(datetime.now().timestamp())}.parquet")
    df_metrics.write_parquet(output_path)
    print(f"Saved to {output_path}")
    print(df_metrics.head())

if __name__ == "__main__":
    run_silver_to_gold()
