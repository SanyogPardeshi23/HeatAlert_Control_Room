"""
analytics.py  -  Experiment 6: Collections and Functional Programming

tuple  -> STATION_INFO (fixed, cannot change)
list   -> temperature readings
set    -> the alert levels that actually occurred
dict   -> counts per level, and the summary returned to the screen
lambda, map(), filter(), reduce()  -> the analysis pipeline
"""

from functools import reduce

from models import ALERT_ORDER, MONTHS

STATION_INFO = ("IMD-CRS-PUNE", "All India", "India", "1991-2020 normals")

SEASONS = {
    "All months": MONTHS,
    "Winter (Jan-Feb)": ["January", "February"],
    "Pre-monsoon (Mar-May)": ["March", "April", "May"],
    "Monsoon (Jun-Sep)": ["June", "July", "August", "September"],
    "Post-monsoon (Oct-Dec)": ["October", "November", "December"],
}

to_fahrenheit = lambda c: round(c * 9 / 5 + 32, 2)
to_fahrenheit_delta = lambda d: round(d * 9 / 5, 2)


def analyse(records, threshold, unit="C"):
    """
    Run the functional pipeline on a list of WeatherRecord objects.
    threshold is a departure in deg C: readings at or above it are flagged.
    """
    if not records:
        return None

    labels = [r.period.label() for r in records]
    readings_c = [r.temperature.tmax for r in records]
    departures = list(map(lambda r: r.departure(), records))

    if unit == "F":
        readings = list(map(to_fahrenheit, readings_c))
    else:
        readings = readings_c

    flagged = list(filter(lambda r: r.departure() >= threshold, records))
    above_normal = list(filter(lambda d: d > 0, departures))

    total = reduce(lambda a, b: a + b, readings)
    highest = reduce(lambda a, b: a if a >= b else b, readings)
    lowest = reduce(lambda a, b: a if a <= b else b, readings)
    hottest_record = reduce(lambda a, b: a if a.departure() >= b.departure() else b, records)

    observed_levels = set(map(lambda r: r.alert_level(), records))
    level_counts = {}
    for level in ALERT_ORDER:
        level_counts[level] = 0
    for record in records:
        level_counts[record.alert_level()] += 1

    return {
        "count": len(records),
        "labels": labels,
        "readings": readings,
        "departures": departures,
        "flagged": flagged,
        "above_normal_count": len(above_normal),
        "total": round(total, 4),
        "average": round(total / len(readings), 4),
        "highest": highest,
        "lowest": lowest,
        "hottest": (hottest_record.period.label(), hottest_record.departure()),
        "observed_levels": observed_levels,
        "level_counts": level_counts,
        "unit": unit,
    }


def yearly_means(records, field="tmean"):
    """Average of the 12 monthly values for each year. Years missing a month are skipped."""
    by_year = {}
    for record in records:
        by_year.setdefault(record.period.year, []).append(getattr(record.temperature, field))
    return {year: round(sum(v) / 12, 4) for year, v in by_year.items() if len(v) == 12}


def yearly_departures(records):
    by_year = {}
    for record in records:
        by_year.setdefault(record.period.year, []).append(record.mean_departure())
    return {year: round(sum(v) / 12, 4) for year, v in by_year.items() if len(v) == 12}


def linear_trend(xs, ys):
    """Least-squares slope and intercept. Slope is in units of y per unit of x."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0, mean_y
    slope = numerator / denominator
    return slope, mean_y - slope * mean_x


def moving_average(values, window):
    """Centred moving average. The first and last few points have no value (None)."""
    half = window // 2
    result = []
    for i in range(len(values)):
        if i < half or i >= len(values) - half:
            result.append(None)
        else:
            chunk = values[i - half:i + half + 1]
            result.append(sum(chunk) / len(chunk))
    return result
