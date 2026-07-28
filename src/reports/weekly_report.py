import os
import yaml
import sys
import polars as pl
from datetime import datetime

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

def generate_weekly_report():
    gold_dir = CONFIG['storage']['gold_path']
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "reports")
    os.makedirs(report_dir, exist_ok=True)

    # Load Gold Data
    # In production, we might load a specific date range. For now, load all current snapshots.
    try:
        # Scan for the LATEST gold file only to avoid duplication if we have many
        # Or load all if they are partitioned. Currently we save full snapshots.
        # Let's take the most recent parquet file.
        files = sorted([os.path.join(gold_dir, f) for f in os.listdir(gold_dir)
                        if f.startswith("gold_metrics_") and f.endswith(".parquet")])
        if not files:
            print("No gold data found.")
            return
        
        latest_file = files[-1]
        print(f"Loading latest gold data: {latest_file}")
        df = pl.read_parquet(latest_file)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # Ensure Date type
    df = df.with_columns(pl.col("date").cast(pl.Date))
    
    # Calculate "Week" (ISO Week)
    df = df.with_columns(
        pl.col("date").dt.week().alias("week"),
        pl.col("date").dt.year().alias("year")
    )

    # Rank Calculation (Daily Rank based on Views)
    df = df.sort(["date", "views"], descending=[False, True]).with_columns(
        pl.col("views").rank("dense", descending=True).over("date").alias("daily_rank")
    )

    # --- REPORT 1: Trends by Genre with HHI ---
    print("Generating Genre Trends with Market Concentration...")
    
    # Calculate engagement ratio
    df = df.with_columns([
        (pl.col("likes") / pl.when(pl.col("views") > 0).then(pl.col("views")).otherwise(1))
        .alias("engagement_ratio")
    ])
    
    genre_trends = df.group_by(["year", "week", "genre"]).agg([
        pl.col("views").sum().alias("total_readership"),
        pl.col("likes").sum().alias("total_likes"),
        pl.col("comic_id").n_unique().alias("active_novels_count"),
        pl.col("daily_rank").mean().alias("avg_rank"),
        pl.col("engagement_ratio").mean().alias("avg_engagement")
    ]).sort(["year", "week", "total_readership"], descending=True)

    # Calculate HHI per genre
    def calc_hhi_for_genre(df, genre):
        genre_data = df.filter(pl.col("genre") == genre)
        views_list = genre_data["views"].to_list()
        total = sum(views_list)
        if total == 0:
            return 0, "N/A"
        shares = [v / total for v in views_list]
        hhi = sum(s**2 for s in shares) * 10000
        market_type = "Concentrated" if hhi > 2500 else "Moderate" if hhi > 1500 else "Competitive"
        return round(hhi, 0), market_type

    hhi_data = []
    for genre in df["genre"].unique().to_list():
        if not genre:
            continue
        hhi, market_type = calc_hhi_for_genre(df, genre)
        hhi_data.append({"genre": genre, "hhi_index": hhi, "market_type": market_type})
    
    hhi_df = pl.DataFrame(hhi_data)

    # --- REPORT 2: Trends by Geo/Demographics (Source Proxy) ---
    print("Generating Geo/Source Trends...")
    geo_trends = df.group_by(["year", "week", "source"]).agg([
        pl.col("views").sum().alias("total_readership"),
        pl.col("likes").sum().alias("total_likes"),
        pl.col("comic_id").n_unique().alias("title_count"),
        pl.col("views_gained").sum().alias("velocity_readership"),
        pl.col("engagement_ratio").mean().alias("avg_engagement")
    ]).sort(["year", "week", "total_readership"], descending=True)

    # --- REPORT 3: Genre x Publisher ---
    print("Generating Genre x Publisher Trends...")
    cross_trends = df.group_by(["year", "week", "source", "genre"]).agg([
        pl.col("views").sum().alias("total_readership"),
        pl.col("comic_id").n_unique().alias("title_count"),
        pl.col("engagement_ratio").mean().alias("avg_engagement")
    ]).sort(["year", "week", "source", "total_readership"], descending=True)

    # --- OUTPUT MARKDOWN ---
    report_date = datetime.now().strftime("%Y-%m-%d")
    md_lines = [f"# Weekly Web Comic Trend Report ({report_date})", ""]

    md_lines.append("## 1. Trends by Genre")
    md_lines.append(genre_trends.to_pandas().to_markdown(index=False))
    md_lines.append("")

    md_lines.append("## 2. Geography / Demographics (Source Breakdown)")
    md_lines.append(geo_trends.to_pandas().to_markdown(index=False))
    md_lines.append("")

    md_lines.append("## 3. Market Concentration (HHI)")
    md_lines.append("*HHI < 1500: Competitive | 1500-2500: Moderate | > 2500: Concentrated*")
    md_lines.append("")
    md_lines.append(hhi_df.to_pandas().to_markdown(index=False))
    md_lines.append("")

    md_lines.append("## 4. Genre x Publisher Matrix")
    md_lines.append(cross_trends.to_pandas().to_markdown(index=False))
    md_lines.append("")

    out_file = os.path.join(report_dir, f"weekly_report_{int(datetime.now().timestamp())}.md")
    with open(out_file, "w", encoding='utf-8') as f:
        f.write("\n".join(md_lines))
    
    print(f"Report generated: {out_file}")

if __name__ == "__main__":
    generate_weekly_report()
