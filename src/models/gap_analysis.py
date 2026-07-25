import os
import yaml
import sys
import polars as pl

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from datetime import datetime

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r") as f:
    CONFIG = yaml.safe_load(f)

def calculate_gap_analysis():
    """Identifies Blue Ocean opportunities (High Demand, Low Supply)."""
    gold_dir = CONFIG['storage']['gold_path']
    
    # Load latest gold parquet
    files = [os.path.join(gold_dir, f) for f in os.listdir(gold_dir) if f.endswith(".parquet")]
    if not files:
        print("No Gold data found.")
        return
        
    # Pick latest
    latest_file = max(files, key=os.path.getmtime)
    print(f"Analyzing {latest_file}...")
    
    df = pl.read_parquet(latest_file)
    
    # GAP ANALYSIS
    # Group by Genre
    # Supply = Unique Comic IDs
    # Demand = Sum of Views (Proxy for attention)
    # Velocity = Sum of Views Gained (Proxy for *current* heat)
    
    gap_df = df.group_by("genre").agg([
        pl.col("comic_id").n_unique().alias("supply_count"),
        pl.col("views").sum().alias("total_demand"),
        pl.col("views_gained").sum().alias("velocity_demand")
    ])
    
    # Calculate Saturation & Opportunity
    # Saturation = Supply / Demand (High = Bad)
    # Opportunity = Demand / Supply (High = Good)
    
    # Avoid division by zero
    gap_df = gap_df.with_columns([
        (pl.col("total_demand") / (pl.col("supply_count") + 1)).alias("opportunity_score"),
        (pl.col("supply_count") / (pl.col("total_demand") + 1)).alias("saturation_index")
    ])
    
    # Sort by Opportunity (Best first)
    gap_df = gap_df.sort("opportunity_score", descending=True)
    
    print("\n=== GAP ANALYSIS REPORT (Blue Ocean) ===")
    print(gap_df)
    
    # Export for Dashboard
    out_path = os.path.join(CONFIG['storage']['gold_path'], f"gap_analysis_{int(datetime.now().timestamp())}.csv")
    gap_df.write_csv(out_path)
    print(f"\nReport saved to {out_path}")

if __name__ == "__main__":
    calculate_gap_analysis()
