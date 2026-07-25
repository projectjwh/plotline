"""
DuckDB Database Schema and Initialization for LeeSearch Analytics.
Creates dimension and fact tables for robust trend analysis.
"""

import os
import duckdb
from datetime import datetime

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "leesearch.duckdb")

def get_connection():
    """Returns a connection to the DuckDB database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return duckdb.connect(DB_PATH)

def init_schema():
    """Initialize the database schema with all required tables."""
    conn = get_connection()
    
    # ============ DIMENSION TABLES ============
    
    # Comics Dimension
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_comics (
            comic_id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            author VARCHAR,
            source VARCHAR NOT NULL,
            genre VARCHAR,
            sub_genres VARCHAR[],
            synopsis TEXT,
            cover_url VARCHAR,
            tags VARCHAR[],
            update_schedule VARCHAR,
            first_seen_date DATE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Sources/Platforms Dimension
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_sources (
            source_id INTEGER PRIMARY KEY,
            source_name VARCHAR UNIQUE NOT NULL,
            region VARCHAR,
            url_base VARCHAR,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)
    
    # Genres Dimension
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_genres (
            genre_id INTEGER PRIMARY KEY,
            genre_name VARCHAR UNIQUE NOT NULL,
            parent_genre VARCHAR,
            description TEXT
        )
    """)
    
    # ============ FACT TABLES ============
    
    # Daily Metrics (Core Fact Table)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_daily_metrics (
            id INTEGER PRIMARY KEY,
            comic_id VARCHAR NOT NULL,
            date DATE NOT NULL,
            views BIGINT DEFAULT 0,
            likes BIGINT DEFAULT 0,
            comments BIGINT DEFAULT 0,
            rating DECIMAL(3,2),
            subscribers BIGINT DEFAULT 0,
            episode_count INTEGER DEFAULT 0,
            -- Derived Metrics
            engagement_ratio DECIMAL(18,6),
            views_gained BIGINT DEFAULT 0,
            likes_gained BIGINT DEFAULT 0,
            views_pct_change DECIMAL(18,4),
            velocity_7d DECIMAL(18,4),
            UNIQUE(comic_id, date)
        )
    """)
    
    # Genre Daily Aggregates
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_genre_daily (
            id INTEGER PRIMARY KEY,
            genre VARCHAR NOT NULL,
            source VARCHAR,
            date DATE NOT NULL,
            total_views BIGINT DEFAULT 0,
            total_likes BIGINT DEFAULT 0,
            title_count INTEGER DEFAULT 0,
            avg_engagement_ratio DECIMAL(18,6),
            market_share DECIMAL(18,6),
            hhi_index DECIMAL(18,6),
            UNIQUE(genre, source, date)
        )
    """)
    
    # Weekly Trend Aggregates
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agg_weekly_trends (
            id INTEGER PRIMARY KEY,
            genre VARCHAR NOT NULL,
            source VARCHAR,
            week_start DATE NOT NULL,
            week_end DATE NOT NULL,
            total_views BIGINT DEFAULT 0,
            velocity_7d DECIMAL(18,4),
            acceleration DECIMAL(18,4),
            trend_status VARCHAR,
            mann_kendall_z DECIMAL(18,4),
            p_value DECIMAL(18,6),
            r_squared DECIMAL(18,6),
            data_points INTEGER,
            UNIQUE(genre, source, week_start)
        )
    """)
    
    # Create Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON fact_daily_metrics(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_comic ON fact_daily_metrics(comic_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_genre_daily_date ON fact_genre_daily(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_weekly_genre ON agg_weekly_trends(genre)")
    
    # Create Sequences for IDs
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_daily_id START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_genre_id START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_weekly_id START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_source_id START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_genre_dim_id START 1")
    
    conn.close()
    print(f"Database schema initialized at: {DB_PATH}")

def verify_schema():
    """Verify the schema was created correctly."""
    conn = get_connection()
    tables = conn.execute("SHOW TABLES").fetchall()
    print("\n=== DATABASE TABLES ===")
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
        print(f"  {table[0]}: {count} rows")
    conn.close()

if __name__ == "__main__":
    print("Initializing DuckDB schema...")
    init_schema()
    verify_schema()
