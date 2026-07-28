import os
import yaml
import sys
import polars as pl
import pandas as pd
from datetime import datetime, date

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

def generate_daily_report():
    """Generate a daily snapshot report with key metrics and top performers."""
    gold_dir = CONFIG['storage']['gold_path']
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "reports")
    os.makedirs(report_dir, exist_ok=True)

    # Load Data
    try:
        files = sorted([os.path.join(gold_dir, f) for f in os.listdir(gold_dir)
                        if f.startswith("gold_metrics_") and f.endswith(".parquet")])
        if not files:
            print("No gold data found.")
            return
        latest_file = files[-1]
        print(f"Loading data from {latest_file}")
        df = pl.read_parquet(latest_file)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # Get date range from full dataset
    min_date = df.select(pl.col("date").min()).item()
    max_date = df.select(pl.col("date").max()).item()
    date_range_str = f"{min_date} to {max_date}"
    today_str = str(max_date)
    
    # Filter to latest date's data
    df_today = df.filter(pl.col("date") == max_date)
    
    # Deduplicate by comic_id (keep highest views if duplicates exist)
    df_today = df_today.sort("views", descending=True).unique(subset=["comic_id"], keep="first")
    
    # Calculate percentage gain (views_gained / previous_views * 100)
    # previous_views = views - views_gained
    df_today = df_today.with_columns([
        ((pl.col("views") - pl.col("views_gained")).alias("prev_views")),
    ]).with_columns([
        pl.when(pl.col("prev_views") > 0)
          .then((pl.col("views_gained") / pl.col("prev_views") * 100).round(2))
          .otherwise(0.0)
          .alias("views_gained_pct")
    ])
    
    # Calculate Summary Stats
    total_comics = df_today.select(pl.col("comic_id").n_unique()).item()
    total_views = df_today.select(pl.col("views").sum()).item()
    total_likes = df_today.select(pl.col("likes").sum()).item()
    total_genres = df_today.select(pl.col("genre").n_unique()).item()
    
    # Top 10 by Views (unique)
    top_by_views = df_today.sort("views", descending=True).head(10).to_pandas()
    
    # Top Gainers (by views_gained) with percentage
    top_gainers = df_today.filter(pl.col("views_gained") > 0).sort("views_gained", descending=True).head(10).to_pandas()
    
    # Calculate engagement ratio per comic
    df_today = df_today.with_columns([
        (pl.col("likes") / pl.when(pl.col("views") > 0).then(pl.col("views")).otherwise(1))
        .alias("engagement_ratio")
    ])
    
    # Genre Breakdown with HHI and Engagement
    def calc_hhi(views_list):
        """Calculate Herfindahl-Hirschman Index for market concentration."""
        total = sum(views_list)
        if total == 0:
            return 0
        shares = [v / total for v in views_list]
        return sum(s**2 for s in shares) * 10000
    
    genre_stats = []
    for genre in df_today["genre"].unique().to_list():
        if not genre:
            continue
        genre_data = df_today.filter(pl.col("genre") == genre)
        views_list = genre_data["views"].to_list()
        
        hhi = calc_hhi(views_list)
        market_type = "Concentrated" if hhi > 2500 else "Moderate" if hhi > 1500 else "Competitive"
        avg_engagement = genre_data["engagement_ratio"].mean()
        
        genre_stats.append({
            "genre": genre,
            "total_views": sum(views_list),
            "title_count": len(views_list),
            "avg_engagement": round(avg_engagement * 100, 2) if avg_engagement and avg_engagement < 1 else 0,
            "hhi_index": round(hhi, 0),
            "market_type": market_type
        })
    
    # Declare columns so the report survives a day with no genre-tagged titles.
    genre_summary = pd.DataFrame(
        genre_stats,
        columns=["genre", "total_views", "title_count", "avg_engagement", "hhi_index", "market_type"],
    ).sort_values("total_views", ascending=False)

    # Generate HTML
    report_date = datetime.now().strftime("%Y-%m-%d")
    
    def df_to_html_table(df, columns=None):
        if columns:
            df = df[columns]
        return df.to_html(index=False, classes="data-table", border=0)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Daily Snapshot - {today_str}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 1000px; margin: 0 auto; padding: 20px; background-color: #f0f4f8; }}
            h1 {{ color: #1a365d; text-align: center; margin-bottom: 5px; }}
            .subtitle {{ text-align: center; color: #718096; margin-bottom: 30px; }}
            h2 {{ color: #2b6cb0; margin-top: 30px; border-bottom: 2px solid #4299e1; padding-bottom: 5px; }}
            .container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 30px; }}
            .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-card h3 {{ margin: 0; font-size: 2em; }}
            .stat-card p {{ margin: 5px 0 0 0; opacity: 0.9; }}
            .data-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            .data-table th {{ background: #4299e1; color: white; padding: 12px; text-align: left; }}
            .data-table td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; }}
            .data-table tr:hover {{ background: #f7fafc; }}
            .footer {{ text-align: center; margin-top: 40px; font-size: 0.9em; color: #a0aec0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Daily Snapshot Report</h1>
            <p class="subtitle">Data for {today_str} | Date Range: {date_range_str} | Generated {report_date}</p>

            <div class="stats-grid">
                <div class="stat-card">
                    <h3>{total_comics:,}</h3>
                    <p>Total Comics</p>
                </div>
                <div class="stat-card">
                    <h3>{total_views:,}</h3>
                    <p>Total Views</p>
                </div>
                <div class="stat-card">
                    <h3>{total_likes:,}</h3>
                    <p>Total Likes</p>
                </div>
                <div class="stat-card">
                    <h3>{total_genres}</h3>
                    <p>Active Genres</p>
                </div>
            </div>

            <h2>🏆 Top 10 by Views</h2>
            {df_to_html_table(top_by_views, ['title', 'genre', 'views', 'likes'])}

            <h2>📈 Top Gainers (Views Growth)</h2>
            {df_to_html_table(top_gainers, ['title', 'genre', 'views_gained', 'views_gained_pct', 'views'])}

            <h2>📚 Genre Summary</h2>
            {df_to_html_table(genre_summary)}

            <div class="footer">
                &copy; 2026 LeeSearch Intelligence Core | Daily Report
            </div>
        </div>
    </body>
    </html>
    """
    
    out_file = os.path.join(report_dir, f"Daily_Report_{today_str}.html")
    with open(out_file, "w", encoding='utf-8') as f:
        f.write(html_content)
    print(f"Daily Report generated: {out_file}")

if __name__ == "__main__":
    generate_daily_report()
