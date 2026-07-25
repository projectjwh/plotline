"""
Data Migration Script: Migrate existing Parquet data to DuckDB.
"""

import os
import sys
import polars as pl
import duckdb
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.schema import get_connection, DB_PATH

# Fix Windows Console Encoding
sys.stdout.reconfigure(encoding='utf-8')

def migrate_parquet_to_duckdb():
    """Load existing Parquet data into DuckDB tables."""
    
    gold_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "gold")
    
    conn = get_connection()
    
    # Find latest gold metrics file
    parquet_files = sorted([f for f in os.listdir(gold_dir) if f.startswith("gold_metrics") and f.endswith(".parquet")])
    
    if not parquet_files:
        print("No Parquet files found to migrate.")
        return
    
    latest_file = os.path.join(gold_dir, parquet_files[-1])
    print(f"Loading data from: {latest_file}")
    
    # Load with Polars
    df = pl.read_parquet(latest_file)
    print(f"Loaded {len(df)} records")
    
    # Deduplicate by comic_id + date
    df_unique = df.unique(subset=["comic_id", "date"], keep="first")
    print(f"After deduplication: {len(df_unique)} unique records")
    
    # Calculate engagement ratio
    df_unique = df_unique.with_columns([
        (pl.col("likes") / pl.when(pl.col("views") > 0).then(pl.col("views")).otherwise(1))
        .alias("engagement_ratio")
    ])
    
    # Prepare for insert (match schema)
    records_inserted = 0
    
    for row in df_unique.iter_rows(named=True):
        try:
            conn.execute("""
                INSERT INTO fact_daily_metrics 
                (id, comic_id, date, views, likes, engagement_ratio, views_gained, likes_gained, views_pct_change)
                VALUES (nextval('seq_daily_id'), ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (comic_id, date) DO UPDATE SET
                    views = EXCLUDED.views,
                    likes = EXCLUDED.likes,
                    engagement_ratio = EXCLUDED.engagement_ratio,
                    views_gained = EXCLUDED.views_gained,
                    likes_gained = EXCLUDED.likes_gained,
                    views_pct_change = EXCLUDED.views_pct_change
            """, [
                row.get("comic_id", ""),
                row.get("date"),
                row.get("views", 0),
                row.get("likes", 0),
                row.get("engagement_ratio", 0.0),
                row.get("views_gained", 0),
                row.get("likes_gained", 0),
                row.get("views_pct_change", 0.0) if row.get("views_pct_change") else 0.0
            ])
            records_inserted += 1
        except Exception as e:
            print(f"Error inserting {row.get('comic_id')}: {e}")
    
    print(f"Inserted {records_inserted} records into fact_daily_metrics")
    
    # Populate dim_comics from unique comic_ids
    unique_comics = df_unique.select(["comic_id", "title", "genre", "source"]).unique(subset=["comic_id"])
    
    for row in unique_comics.iter_rows(named=True):
        try:
            conn.execute("""
                INSERT OR IGNORE INTO dim_comics (comic_id, title, genre, source, first_seen_date)
                VALUES (?, ?, ?, ?, CURRENT_DATE)
            """, [
                row.get("comic_id", ""),
                row.get("title", ""),
                row.get("genre", ""),
                row.get("source", "")
            ])
        except Exception as e:
            pass  # Ignore duplicates
    
    print(f"Populated dim_comics with {len(unique_comics)} unique comics")
    
    # Populate dim_genres
    unique_genres = df_unique.select("genre").unique()
    for row in unique_genres.iter_rows(named=True):
        try:
            conn.execute("""
                INSERT OR IGNORE INTO dim_genres (genre_id, genre_name)
                VALUES (nextval('seq_genre_dim_id'), ?)
            """, [row.get("genre", "")])
        except:
            pass
    
    print(f"Populated dim_genres")
    
    # Populate dim_sources
    unique_sources = df_unique.select("source").unique()
    for row in unique_sources.iter_rows(named=True):
        try:
            conn.execute("""
                INSERT OR IGNORE INTO dim_sources (source_id, source_name)
                VALUES (nextval('seq_source_id'), ?)
            """, [row.get("source", "")])
        except:
            pass
    
    print(f"Populated dim_sources")
    
    # Calculate and populate fact_genre_daily
    print("\nCalculating genre daily aggregates...")
    genre_daily = df_unique.group_by(["genre", "source", "date"]).agg([
        pl.col("views").sum().alias("total_views"),
        pl.col("likes").sum().alias("total_likes"),
        pl.col("comic_id").n_unique().alias("title_count"),
        pl.col("engagement_ratio").mean().alias("avg_engagement_ratio")
    ])
    
    # Calculate market share per date
    for row in genre_daily.iter_rows(named=True):
        try:
            conn.execute("""
                INSERT OR REPLACE INTO fact_genre_daily 
                (id, genre, source, date, total_views, total_likes, title_count, avg_engagement_ratio)
                VALUES (nextval('seq_genre_id'), ?, ?, ?, ?, ?, ?, ?)
            """, [
                row.get("genre", ""),
                row.get("source", ""),
                row.get("date"),
                row.get("total_views", 0),
                row.get("total_likes", 0),
                row.get("title_count", 0),
                row.get("avg_engagement_ratio", 0.0)
            ])
        except Exception as e:
            pass
    
    print(f"Populated fact_genre_daily with {len(genre_daily)} records")
    
    conn.close()
    print(f"\n✓ Migration complete! Database: {DB_PATH}")

def verify_migration():
    """Verify the migration was successful."""
    conn = get_connection()
    
    print("\n=== MIGRATION VERIFICATION ===")
    
    tables = ["dim_comics", "dim_genres", "dim_sources", "fact_daily_metrics", "fact_genre_daily"]
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count} rows")
        except Exception as e:
            print(f"  {table}: ERROR - {e}")
    
    # Sample data
    print("\n=== SAMPLE DATA: fact_daily_metrics ===")
    sample = conn.execute("""
        SELECT comic_id, date, views, likes, engagement_ratio 
        FROM fact_daily_metrics 
        ORDER BY views DESC 
        LIMIT 5
    """).fetchall()
    for row in sample:
        print(f"  {row}")
    
    conn.close()

if __name__ == "__main__":
    migrate_parquet_to_duckdb()
    verify_migration()
