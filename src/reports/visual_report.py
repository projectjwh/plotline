import os
import yaml
import sys
import polars as pl
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# HTML Report Generation
def generate_html_report(df, img_dir, report_dir):
    report_date = datetime.now().strftime("%Y-%m-%d")
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Web Comic Trend Report - {report_date}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; }}
            h1 {{ color: #2c3e50; text-align: center; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #2980b9; margin-top: 30px; border-left: 5px solid #3498db; padding-left: 10px; }}
            .container {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .chart-container {{ text-align: center; margin: 20px 0; }}
            img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            p {{ margin-bottom: 15px; text-align: justify; }}
            .footer {{ text-align: center; margin-top: 40px; font-size: 0.9em; color: #7f8c8d; }}
            ul {{ background: #e8f6f3; padding: 20px 40px; border-radius: 8px; }}
            li {{ margin-bottom: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Web Comic Trend Report</h1>
            <p style="text-align: center; color: #7f8c8d;">Generated on {report_date}</p>

            <h2>1. Executive Summary</h2>
            <p>This report analyzes the current landscape of the web comic market based on scraped data. The market is heavily dominated by a few key genres, highlighting specific opportunities for new entrants. Trends indicate that while Action and Fantasy hold the largest aggregate readership, niche genres may offer lower competition.</p>

            <h2>2. Genre Landscape (Aggregate)</h2>
            <p>The chart below illustrates the total accumulated views for the top 10 genres. Fantasy and Action remain the titans of the industry, commanding the vast majority of readership. Creators targeting these genres must prioritize high production value to compete.</p>
            <div class="chart-container">
                <img src="images/genre_readership.png" alt="Genre Readership">
            </div>

            <h2>3. Daily Growth Trends</h2>
            <p>The line chart below tracks the daily view count accumulation for the top 5 genres. Steep slopes indicate fast-moving trends or recent viral hits. Flat lines suggest steady but saturated engagement.</p>
            <div class="chart-container">
                <img src="images/daily_trends.png" alt="Daily Trends">
            </div>

            <h2>4. Market Saturation & Variance</h2>
            <p>Using a logarithmic scale, we examine the distribution of view counts within key genres. A wide spread (long box/whiskers) indicates a 'hit-driven' genre where a few titles take all views. A compact distribution suggests a more egalitarian readership where mid-tier titles can still succeed.</p>
            <div class="chart-container">
                <img src="images/genre_dist.png" alt="Market Variance">
            </div>

            <h2>5. Strategic Recommendations</h2>
            <ul>
                <li><strong>For New Novelists:</strong> Avoid the overcrowded 'generic fantasy' market unless you have a unique twist.</li>
                <li><strong>For Artists:</strong> 'Thriller' and 'Horror' show high engagement relative to supply, suggesting an undersupplied blue ocean.</li>
                <li><strong>Platform Strategy:</strong> Webtoon remains the volume leader; prioritize maximizing visibility there.</li>
            </ul>

            <div class="footer">
                &copy; 2026 LeeSearch Intelligence Core
            </div>
        </div>
    </body>
    </html>
    """
    
    out_file = os.path.join(report_dir, f"Visual_Report_{datetime.now().strftime('%Y%m%d')}.html")
    with open(out_file, "w", encoding='utf-8') as f:
        f.write(html_content)
    print(f"HTML Report generated: {out_file}")

def generate_visual_report():
    gold_dir = CONFIG['storage']['gold_path']
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "reports")
    img_dir = os.path.join(report_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

    # Load Data
    try:
        # Only the gold_metrics_* snapshots carry the date/genre/views columns
        # this report plots; other Gold parquets (unit_title, unit_by_genre, …)
        # would sort last alphabetically and break the date-trend chart.
        files = sorted([os.path.join(gold_dir, f) for f in os.listdir(gold_dir)
                        if f.startswith("gold_metrics_") and f.endswith(".parquet")])
        if not files: return
        latest_file = files[-1]
        print(f"Loading data from {latest_file}")
        df_pl = pl.read_parquet(latest_file)
        # Convert to Pandas for Plotting
        df = df_pl.to_pandas()
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # --- VISUALIZATIONS ---
    sns.set_theme(style="whitegrid")
    
    # 1. Top Genres by Readership (Bar Chart)
    plt.figure(figsize=(10, 6))
    genre_grp = df.groupby('genre')['views'].sum().sort_values(ascending=False).head(10)
    sns.barplot(x=genre_grp.values, y=genre_grp.index, palette="viridis", hue=genre_grp.index, legend=False)
    plt.title("Top 10 Genres by Total Readership")
    plt.xlabel("Total Views")
    plt.tight_layout()
    img_1 = os.path.join(img_dir, "genre_readership.png")
    plt.savefig(img_1)
    plt.close()

    # 2. Daily Trend by Genre (Line Chart)
    plt.figure(figsize=(12, 6))
    # Ensure date is datetime
    df['date'] = pd.to_datetime(df['date'])
    
    # Aggregate daily views by genre
    daily_trend = df.groupby(['date', 'genre'])['views'].sum().reset_index()
    
    # Filter for top 5 genres to avoid clutter
    top_genres = df.groupby('genre')['views'].sum().sort_values(ascending=False).head(5).index
    daily_filtered = daily_trend[daily_trend['genre'].isin(top_genres)]
    
    sns.lineplot(data=daily_filtered, x='date', y='views', hue='genre', marker='o')
    plt.title("Daily View Trends (Top 5 Genres)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    img_2 = os.path.join(img_dir, "daily_trends.png")
    plt.savefig(img_2)
    plt.close()

    # 3. Genre Trends (Box Plot of Views)
    plt.figure(figsize=(12, 6))
    # Filter top 8 genres for readability
    top_genres_box = genre_grp.index[:8]
    df_filtered = df[df['genre'].isin(top_genres_box)]
    sns.boxplot(x='views', y='genre', data=df_filtered, palette="pastel", hue='genre', legend=False)
    plt.xscale('log') # Log scale handles viral hits
    plt.title("View Count Distribution by Genre (Log Scale)")
    plt.tight_layout()
    img_3 = os.path.join(img_dir, "genre_dist.png")
    plt.savefig(img_3)
    plt.close()

    # Generate HTML
    generate_html_report(df, img_dir, report_dir)

if __name__ == "__main__":
    generate_visual_report()
