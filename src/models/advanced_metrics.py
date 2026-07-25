"""
Advanced Analytics Metrics Module.
Provides robust trend detection beyond simple view/title counting.
"""

import numpy as np
from scipy import stats
from typing import List, Tuple, Dict, Optional
import polars as pl

def engagement_ratio(likes: int, views: int) -> float:
    """Calculate engagement ratio (likes per view)."""
    if views <= 0:
        return 0.0
    return likes / views

def velocity(current: float, previous: float, period_days: int = 7) -> float:
    """Calculate velocity (rate of change over period)."""
    if previous <= 0:
        return 0.0
    return (current - previous) / previous

def acceleration(velocity_current: float, velocity_previous: float) -> float:
    """Calculate acceleration (change in velocity)."""
    return velocity_current - velocity_previous

def moving_average(values: List[float], window: int = 7) -> List[float]:
    """Calculate rolling moving average."""
    if len(values) < window:
        return values
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(np.mean(values[:i+1]))
        else:
            result.append(np.mean(values[i-window+1:i+1]))
    return result

def coefficient_of_variation(values: List[float]) -> float:
    """Calculate coefficient of variation (volatility measure)."""
    if len(values) < 2:
        return 0.0
    mean = np.mean(values)
    if mean == 0:
        return 0.0
    return np.std(values) / mean

def herfindahl_hirschman_index(market_shares: List[float]) -> float:
    """
    Calculate HHI (Herfindahl-Hirschman Index) for market concentration.
    
    HHI ranges from 0 to 10,000:
    - < 1,500: Unconcentrated (competitive)
    - 1,500-2,500: Moderately concentrated
    - > 2,500: Highly concentrated (few dominate)
    """
    # Market shares should sum to 1 (100%)
    total = sum(market_shares)
    if total == 0:
        return 0.0
    
    normalized = [s / total for s in market_shares]
    hhi = sum(s**2 for s in normalized) * 10000
    return hhi

def linear_trend_analysis(x: List[float], y: List[float]) -> Dict:
    """
    Perform robust linear regression with statistical significance.
    
    Returns:
        slope: Rate of change
        intercept: Starting point
        r_squared: Explained variance (0-1)
        p_value: Statistical significance (<0.05 is significant)
        std_err: Standard error of slope
        confidence_interval: 95% CI for slope
    """
    if len(x) < 3 or len(y) < 3:
        return {
            "slope": 0.0,
            "intercept": 0.0,
            "r_squared": 0.0,
            "p_value": 1.0,
            "std_err": 0.0,
            "confidence_interval": (0.0, 0.0),
            "is_significant": False
        }
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    r_squared = r_value ** 2
    ci_margin = 1.96 * std_err  # 95% confidence
    
    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "p_value": p_value,
        "std_err": std_err,
        "confidence_interval": (slope - ci_margin, slope + ci_margin),
        "is_significant": p_value < 0.05
    }

def mann_kendall_enhanced(values: List[float]) -> Dict:
    """
    Enhanced Mann-Kendall trend test with proper statistics.
    
    Returns:
        s: Test statistic
        z_score: Standardized score
        p_value: Two-tailed p-value
        trend: "Rising", "Falling", or "Stable"
        is_significant: True if p < 0.05
    """
    n = len(values)
    if n < 4:
        return {
            "s": 0,
            "z_score": 0.0,
            "p_value": 1.0,
            "trend": "Insufficient Data",
            "is_significant": False,
            "theil_sen_slope": 0.0
        }
    
    # Calculate S statistic
    s = 0
    for k in range(n - 1):
        for j in range(k + 1, n):
            s += np.sign(values[j] - values[k])
    
    # Variance with tie correction (simplified)
    var_s = (n * (n - 1) * (2 * n + 5)) / 18
    
    # Z-score
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0
    
    # Two-tailed p-value
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))
    
    # Theil-Sen slope (robust median slope)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if j != i:
                slopes.append((values[j] - values[i]) / (j - i))
    theil_sen = np.median(slopes) if slopes else 0.0
    
    # Determine trend
    if p_value < 0.05:
        trend = "Rising" if z > 0 else "Falling"
    else:
        trend = "Stable"
    
    return {
        "s": s,
        "z_score": z,
        "p_value": p_value,
        "trend": trend,
        "is_significant": p_value < 0.05,
        "theil_sen_slope": theil_sen
    }

def calculate_market_share(genre_views: Dict[str, int]) -> Dict[str, float]:
    """Calculate market share for each genre."""
    total = sum(genre_views.values())
    if total == 0:
        return {k: 0.0 for k in genre_views}
    return {k: v / total for k, v in genre_views.items()}

def z_score_outlier(value: float, values: List[float], threshold: float = 2.0) -> Tuple[float, bool]:
    """
    Calculate Z-score and determine if value is an outlier.
    
    Returns:
        z_score: How many std deviations from mean
        is_outlier: True if |z| > threshold
    """
    if len(values) < 2:
        return 0.0, False
    
    mean = np.mean(values)
    std = np.std(values)
    
    if std == 0:
        return 0.0, False
    
    z = (value - mean) / std
    return z, abs(z) > threshold

def calculate_all_metrics(df: pl.DataFrame) -> pl.DataFrame:
    """
    Calculate all advanced metrics for a DataFrame with daily comic data.
    
    Expects columns: comic_id, date, views, likes, genre
    """
    # Sort by comic and date
    df = df.sort(["comic_id", "date"])
    
    # Calculate engagement ratio
    df = df.with_columns([
        (pl.col("likes") / pl.when(pl.col("views") > 0).then(pl.col("views")).otherwise(1))
        .alias("engagement_ratio")
    ])
    
    # Calculate views gained (day-over-day)
    df = df.with_columns([
        pl.col("views").diff().over("comic_id").fill_null(0).alias("views_gained"),
        pl.col("likes").diff().over("comic_id").fill_null(0).alias("likes_gained")
    ])
    
    # Calculate percentage change
    df = df.with_columns([
        (pl.col("views_gained") / pl.when(pl.col("views") - pl.col("views_gained") > 0)
         .then(pl.col("views") - pl.col("views_gained")).otherwise(1) * 100)
        .alias("views_pct_change")
    ])
    
    # Calculate 7-day rolling velocity (requires window functions)
    df = df.with_columns([
        pl.col("views").rolling_mean(window_size=7).over("comic_id").alias("views_ma_7d")
    ])
    
    return df

if __name__ == "__main__":
    # Test the functions
    test_values = [100, 120, 115, 140, 160, 155, 180, 200, 210, 230]
    
    print("=== Advanced Metrics Test ===\n")
    
    # Mann-Kendall test
    mk_result = mann_kendall_enhanced(test_values)
    print(f"Mann-Kendall Test:")
    print(f"  Trend: {mk_result['trend']}")
    print(f"  Z-Score: {mk_result['z_score']:.4f}")
    print(f"  P-Value: {mk_result['p_value']:.6f}")
    print(f"  Significant: {mk_result['is_significant']}")
    print(f"  Theil-Sen Slope: {mk_result['theil_sen_slope']:.4f}")
    
    # Linear regression
    x = list(range(len(test_values)))
    lr_result = linear_trend_analysis(x, test_values)
    print(f"\nLinear Regression:")
    print(f"  Slope: {lr_result['slope']:.4f}")
    print(f"  R²: {lr_result['r_squared']:.4f}")
    print(f"  P-Value: {lr_result['p_value']:.6f}")
    print(f"  95% CI: ({lr_result['confidence_interval'][0]:.4f}, {lr_result['confidence_interval'][1]:.4f})")
    
    # HHI
    market_shares = [0.4, 0.3, 0.15, 0.10, 0.05]  # Top 5 players
    hhi = herfindahl_hirschman_index(market_shares)
    print(f"\nHHI Index: {hhi:.2f}")
    print(f"  Market: {'Concentrated' if hhi > 2500 else 'Moderate' if hhi > 1500 else 'Competitive'}")
    
    # Coefficient of Variation
    cv = coefficient_of_variation(test_values)
    print(f"\nCoefficient of Variation: {cv:.4f}")
