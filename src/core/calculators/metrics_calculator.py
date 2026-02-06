# src/core/calculators/metrics_calculator.py
import statistics
from typing import List, Dict, Any


def calculate_derived_metrics(
        stats_summary: Dict[str, Any],
        player_stats: List[Dict[str, Any]],
        market_history: List[Dict[str, Any]],
        current_market_value: int,
        team_slug: str,
        schedule_list: List[Dict[str, Any]],
        threshold: int
) -> Dict[str, Any]:
    """
    Calculates aggregated metrics from raw stats and market history.

    Metrics included:
    - Market: Max, Min, Avg, Season Trend.
    - Performance: Total Points, Net Average (Played), Gross Average (Available).
    - Split: Home vs Away averages (Net).
    - Form: Last 3 and 5 matches average.
    - Economics: Profitability (Points per Million).
    - Availability: Start percentage and Average minutes.

    :param stats_summary: dict, Summary of player's stats (total matches, availability, etc.)
    :param player_stats: list, Output from FFStatsScraper (match breakdown)
    :param market_history: list, Market value history [{'date':..., 'value':...}]
    :param current_market_value: int, Current market value
    :param team_slug: str, Player's team slug to determine home/away splits
    :param schedule_list: list, The full match schedule to map match_id to home/away
    :param threshold: int, Points threshold to consider a match as "successful" for regularity
    :return: dict, Calculated metrics
    """

    # Map the schedule by match_id for quick home/away lookup
    schedule_map = {}
    for match in schedule_list:
        mid = match.get('ff_match_id')
        if mid:
            # Saving only the home team slug for quick access
            home_slug = match.get('home_team', {}).get('slug')
            schedule_map[str(mid)] = home_slug

    metrics = {
        # --- MARKET ---
        "market_val_max": 0,
        "market_val_min": 0,
        "market_val_avg": 0,

        "rentability": 0.0,  # Points per Million

        "daily_trend": 0.0,  # Absolute change from first to last market value in the season
        "weekly_trend": 0.0,  # Absolute change from last week to current market value

        "perc_daily_trend": 0.0,  # % change from first to last market value in the season
        "perc_weekly_trend": 0.0,  # % change from last week to current market value

        # --- PERFORMANCE ---
        "total_points": 0,
        "total_points_home": 0,
        "total_points_away": 0,

        "avg_points_net": 0.0,  # Real performance when on pitch
        "avg_points_gross": 0.0,  # Risk-adjusted performance (includes bench zeros)

        "avg_points_home": 0.0,
        "avg_points_away": 0.0,

        "avg_last_3": 0.0,
        "avg_last_5": 0.0,

        # Is the player fiable?
        "regularity": 0.0,  # % of matches with points > threshold when available

        # Does this player oscillate a lot in points per match? (high volatility can be a risk factor)
        "volatility": 0.0,  # Standard deviation of points per match when available

        # --- AVAILABILITY ---
        "perc_starter": 0.0,  # % of matches started when available
        "avg_minutes": 0.0,  # Average minutes played when available
    }

    # 1. MARKET METRICS
    if market_history:
        values = [entry['value'] for entry in market_history]
        metrics['market_val_max'] = max(values)
        metrics['market_val_min'] = min(values)
        metrics['market_val_avg'] = int(statistics.mean(values))

        # Trends
        if len(values) >= 2:
            val_today = values[-1]  # Assuming market_history is ordered from oldest to newest
            val_yesterday = values[-2]

            diff_day = val_today - val_yesterday
            metrics['daily_trend'] = diff_day
            if val_yesterday > 0:
                metrics['perc_daily_trend'] = round((diff_day / val_yesterday) * 100, 2)

        if len(values) >= 8:
            val_today = values[-1]
            val_week_ago = values[-8]

            diff_week = val_today - val_week_ago
            metrics['weekly_trend'] = diff_week
            if val_week_ago > 0:
                metrics['perc_weekly_trend'] = round((diff_week / val_week_ago) * 100, 2)

    # 2. DATA EXTRACTION FROM SUMMARY
    big_stats = stats_summary.get('big_stats', {})
    info_stats = stats_summary.get('info_stats', {})

    try:
        count_played = int(big_stats.get('partidos_jugados', 0))
    except (ValueError, TypeError):
        count_played = 0

    try:
        count_bench_unused = int(info_stats.get('convocado_sin_jugar', 0))
    except (ValueError, TypeError):
        count_bench_unused = 0

    try:
        count_starters = int(big_stats.get('titular', 0))
    except (ValueError, TypeError):
        count_starters = 0

    count_available = count_played + count_bench_unused

    # 3. PERFORMANCE METRICS
    points_home_list = []
    points_away_list = []
    points_history_available = []  # For form/regularity (includes 0s from bench)
    total_minutes = 0

    # Sort stats by date/jornada ensures order with the first match of the season first
    # Assuming player_stats is already sorted by FFStatsScraper
    for match in player_stats:
        # Data Extraction
        try:
            puntos = float(match.get('fantasy_points_total', 0))
        except (ValueError, TypeError):
            puntos = 0.0

        try:
            minutes_map = match.get('minutes_played', {})
            minutes = int(minutes_map.get('value', 0))
        except (ValueError, TypeError):
            minutes = 0

        total_minutes += minutes

        status = match.get('status', 'alineable')

        # LOGIC: AVAILABLE (Played OR Bench)
        # If scraper marks as 'alineable', he was available.
        if status == 'alineable':
            metrics['total_points'] += puntos
            points_history_available.append(puntos)

        # LOGIC: PLAYED (Actually on pitch)
        if minutes > 0:
            # Home/Away Split
            match_id = match.get('match_id')
            is_home = False

            if match_id and str(match_id) in schedule_map:
                home_slug = schedule_map[str(match_id)]
                if home_slug == team_slug:
                    is_home = True

            if is_home:
                metrics['total_points_home'] += puntos
                points_home_list.append(puntos)
            else:
                metrics['total_points_away'] += puntos
                points_away_list.append(puntos)

    # Averages and Ratios
    # Net Average (only when on pitch)
    if count_played > 0:
        metrics['avg_points_net'] = round(metrics['total_points'] / count_played, 2)
        metrics['avg_minutes'] = round(total_minutes / count_played, 1)

    # Gross Average (includes bench zeros)
    if count_available > 0:
        metrics['avg_points_gross'] = round(metrics['total_points'] / count_available, 2)
        metrics['perc_starter'] = round((count_starters / count_available) * 100, 2)

        # Regularity: % of matches with points >= threshold when available
        matches_with_points = sum(1 for p in points_history_available if p >= threshold)
        metrics['regularity'] = round((matches_with_points / count_available) * 100, 1)

        # Volatility: Standard deviation of points when available
        if len(points_history_available) > 1:
            metrics['volatility'] = round(statistics.stdev(points_history_available), 2)

    # Home/Away Averages
    if len(points_home_list) > 0:
        metrics['avg_points_home'] = round(sum(points_home_list) / len(points_home_list), 2)

    if len(points_away_list) > 0:
        metrics['avg_points_away'] = round(sum(points_away_list) / len(points_away_list), 2)

    # Form: Last 3 and 5 matches average (when available), assuming player_stats is sorted from oldest to newest
    if points_history_available:
        last_3 = points_history_available[-3:]
        metrics['avg_last_3'] = round(statistics.mean(last_3), 2)

        last_5 = points_history_available[-5:]
        metrics['avg_last_5'] = round(statistics.mean(last_5), 2)

    # Rentability: Points per Million of market value (only if current market value > 0 to avoid division by zero)
    if current_market_value > 0:
        val_in_millions = current_market_value / 1_000_000
        metrics['rentability'] = round(metrics['total_points'] / val_in_millions, 2)

    return metrics