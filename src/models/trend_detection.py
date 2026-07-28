"""
Enhanced Trend Detection Module.
Uses robust statistical methods for trend analysis.
"""

import os
import yaml
import sys
import polars as pl
import numpy as np
from scipy import stats
from datetime import datetime

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')

# Import advanced metrics
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from models.advanced_metrics import (
    mann_kendall_enhanced, 
    linear_trend_analysis, 
    herfindahl_hirschman_index,
    coefficient_of_variation,
    engagement_ratio
)

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

def run_enhanced_trend_detection():
    """
    Performs robust trend detection with:
    - Mann-Kendall test with proper p-values
    - Linear regression with R² and confidence intervals
    - Market concentration (HHI)
    - Volatility measures (CV)
    - Engagement analysis
    """
    gold_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), CONFIG['storage']['gold_path'])
    
    # Load metrics
    try:
        # Get the latest gold file
        files = sorted([f for f in os.listdir(gold_dir) if f.startswith("gold_metrics") and f.endswith(".parquet")])
        if not files:
            print("No gold metrics files found.")
            return
        latest_file = os.path.join(gold_dir, files[-1])
        print(f"Loading from: {latest_file}")
        df = pl.read_parquet(latest_file)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    print(f"Loaded {len(df)} records for analysis\n")

    # Deduplicate
    df = df.unique(subset=["comic_id", "date"], keep="first")

    # Calculate engagement ratio
    df = df.with_columns([
        (pl.col("likes") / pl.when(pl.col("views") > 0).then(pl.col("views")).otherwise(1))
        .alias("engagement_ratio")
    ])

    # Group by Genre + Date -> Daily aggregates
    ts_df = df.group_by(["genre", "date"]).agg([
        pl.col("views").sum().alias("daily_views"),
        pl.col("likes").sum().alias("daily_likes"),
        pl.col("comic_id").n_unique().alias("title_count"),
        pl.col("engagement_ratio").mean().alias("avg_engagement")
    ]).sort(["genre", "date"])

    # Analyze each genre
    results = []
    unique_genres = ts_df["genre"].unique().to_list()
    
    print(f"Analyzing {len(unique_genres)} genres with enhanced statistics...")
    print("=" * 80)

    for genre in unique_genres:
        if not genre:
            continue
            
        genre_data = ts_df.filter(pl.col("genre") == genre).sort("date")
        views_series = genre_data["daily_views"].to_list()
        likes_series = genre_data["daily_likes"].to_list()
        dates = list(range(len(views_series)))
        
        if len(views_series) < 3:
            continue

        # 1. Mann-Kendall Test
        mk_result = mann_kendall_enhanced(views_series)
        
        # 2. Linear Regression
        lr_result = linear_trend_analysis(dates, views_series)
        
        # 3. Market Concentration (HHI) - based on title share of views
        title_views = df.filter(pl.col("genre") == genre).group_by("comic_id").agg(
            pl.col("views").sum()
        )["views"].to_list()
        hhi = herfindahl_hirschman_index(title_views) if title_views else 0
        
        # 4. Volatility
        cv = coefficient_of_variation(views_series)
        
        # 5. Engagement
        avg_engagement = np.mean(genre_data["avg_engagement"].to_list())
        
        # Calculate total metrics
        total_views = sum(views_series)
        total_titles = genre_data["title_count"].max() or 0
        
        results.append({
            "genre": genre,
            # Volume Metrics
            "total_views": total_views,
            "title_count": total_titles,
            "avg_engagement": round(avg_engagement, 6),
            # Trend Statistics
            "trend_status": mk_result["trend"],
            "mann_kendall_z": round(mk_result["z_score"], 4),
            "mk_p_value": round(mk_result["p_value"], 6),
            "theil_sen_slope": round(mk_result["theil_sen_slope"], 2),
            # Regression Statistics
            "linear_slope": round(lr_result["slope"], 2),
            "r_squared": round(lr_result["r_squared"], 4),
            "lr_p_value": round(lr_result["p_value"], 6),
            "is_significant": mk_result["is_significant"] and lr_result["is_significant"],
            # Market Structure
            "hhi_index": round(hhi, 2),
            "market_type": "Concentrated" if hhi > 2500 else "Moderate" if hhi > 1500 else "Competitive",
            # Volatility
            "cv": round(cv, 4),
            "volatility": "High" if cv > 0.5 else "Medium" if cv > 0.2 else "Low",
            "data_points": len(views_series)
        })

    # Create result DataFrame
    result_df = pl.DataFrame(results).sort("total_views", descending=True)

    # Print Report
    print("\n" + "=" * 80)
    print("ENHANCED TREND ANALYSIS REPORT")
    print("=" * 80)
    
    print("\n📈 RISING GENRES (Statistically Significant):")
    rising = result_df.filter(
        (pl.col("trend_status") == "Rising") & (pl.col("is_significant") == True)
    )
    if len(rising) > 0:
        for row in rising.iter_rows(named=True):
            print(f"  • {row['genre']}: Z={row['mann_kendall_z']:.2f}, p={row['mk_p_value']:.4f}, R²={row['r_squared']:.2f}")
    else:
        print("  (None with statistical significance)")
    
    print("\n📉 FALLING GENRES:")
    falling = result_df.filter(pl.col("trend_status") == "Falling")
    if len(falling) > 0:
        for row in falling.iter_rows(named=True):
            print(f"  • {row['genre']}: Z={row['mann_kendall_z']:.2f}, p={row['mk_p_value']:.4f}")
    else:
        print("  (None)")
    
    print("\n🎯 MARKET CONCENTRATION:")
    for row in result_df.head(5).iter_rows(named=True):
        print(f"  • {row['genre']}: HHI={row['hhi_index']:.0f} ({row['market_type']})")
    
    print("\n📊 TOP ENGAGEMENT RATIOS:")
    top_engagement = result_df.sort("avg_engagement", descending=True).head(5)
    for row in top_engagement.iter_rows(named=True):
        print(f"  • {row['genre']}: {row['avg_engagement']:.4%}")

    # Save Report
    out_path = os.path.join(gold_dir, f"enhanced_trend_report_{int(datetime.now().timestamp())}.csv")
    result_df.write_csv(out_path)
    print(f"\n✓ Full report saved to: {out_path}")
    
    return result_df

if __name__ == "__main__":
    run_enhanced_trend_detection()

