"""
readings.py  -  Experiment 2: Constructors and Lists

ReadingLog keeps one Python list of maximum temperatures per month.
The constructor builds those lists from WeatherRecord objects, and the
methods add to, remove from and summarise them.
"""

from models import MONTHS

VALID_MIN = -10.0
VALID_MAX = 55.0


def parse_temperature(text, field_name):
    """Convert text typed in a form into a float, or raise ValueError with a clear message."""
    cleaned = text.strip().replace("C", "").replace("c", "").strip()
    if not cleaned:
        raise ValueError(f"{field_name} is empty.")
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"{field_name} must be a number, not '{text.strip()}'.")
    if value < VALID_MIN or value > VALID_MAX:
        raise ValueError(f"{field_name} must be between {VALID_MIN} and {VALID_MAX} C.")
    return value


def parse_year(text):
    cleaned = text.strip()
    if not cleaned.isdigit():
        raise ValueError("Year must be a whole number like 2026.")
    year = int(cleaned)
    if year < 1901 or year > 2100:
        raise ValueError("Year must be between 1901 and 2100.")
    return year


class ReadingLog:
    def __init__(self, records):
        self.readings = {}
        for month in MONTHS:
            self.readings[month] = []
        for record in records:
            self.readings[record.period.month].append(record.temperature.tmax)

    def add(self, month, value):
        self.readings[month].append(value)

    def remove(self, month, value):
        if value in self.readings[month]:
            self.readings[month].remove(value)
            return True
        return False

    def stats(self, month):
        data = self.readings[month]
        if len(data) == 0:
            return 0, None, None, None
        return len(data), max(data), min(data), round(sum(data) / len(data), 4)

    def total_count(self):
        return sum(len(values) for values in self.readings.values())
