"""
advisories.py  -  Experiment 3: String handling and Inheritance

WeatherBulletin       (parent)  cleans messy text: period and temperature
HeatwaveAdvisory      (child)   inherits all of that, adds the normal,
                                the departure, the alert level and a
                                formatted bulletin
"""

import textwrap

from models import MONTHS, classify_departure

GUIDANCE = {
    "NORMAL": [
        "Temperatures are at or below the usual level for this month.",
        "No heat-related action is needed.",
    ],
    "ELEVATED": [
        "Slightly warmer than usual for this month.",
        "Drink water regularly and watch for further updates.",
    ],
    "HIGH": [
        "Noticeably warmer than usual for this month.",
        "Avoid strenuous outdoor work between 12 noon and 3 pm.",
        "Keep drinking water even if you are not thirsty.",
    ],
    "SEVERE": [
        "Much warmer than usual for this month.",
        "Limit outdoor exposure during the afternoon.",
        "Check on elderly people, young children and outdoor workers.",
        "Outdoor workers should take frequent shaded rest breaks.",
    ],
    "EXTREME": [
        "Among the warmest departures in the 125-year record.",
        "Local heat action plans should be activated.",
        "Health facilities should prepare for heat-related illness.",
        "Avoid all non-essential outdoor activity in the afternoon.",
    ],
}

FOOTER = ("Based on the All-India monthly mean maximum temperature compared with the "
          "IMD 1991-2020 normal. For study purposes only - not an official IMD warning.")


def clean_month(text):
    """Accept 'aug', ' AUGUST ', 'August' and return 'August'."""
    word = text.strip().lower()
    for month in MONTHS:
        if len(word) >= 3 and month.lower().startswith(word[:3]):
            return month
    raise ValueError(f"'{text.strip()}' is not a month name.")


def clean_number(text):
    """Accept ' 31.87C ', '31.87 deg C', '31.87' and return 31.87."""
    cleaned = text.strip().lower().replace("deg", "").replace("c", "").replace("°", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"'{text.strip()}' is not a temperature.")


def split_raw_feed(line):
    """
    A raw feed line looks like:   "  aug 2023 | 31.87C | normal 31.01 C  "
    Returns the three pieces as strings: period, temperature, normal.
    """
    parts = [piece.strip() for piece in line.replace(",", "|").split("|")]
    parts = [piece for piece in parts if piece]
    if len(parts) != 3:
        raise ValueError("Expected 3 parts separated by '|':  month year | temperature | normal")
    period, temperature, normal = parts
    normal = normal.lower().replace("normal", "").strip()
    return period, temperature, normal


class WeatherBulletin:
    def __init__(self, raw_period, raw_temperature):
        pieces = raw_period.strip().split()
        if len(pieces) != 2:
            raise ValueError(f"Period must look like 'May 2024', not '{raw_period.strip()}'.")
        self.month = clean_month(pieces[0])
        if not pieces[1].isdigit():
            raise ValueError(f"'{pieces[1]}' is not a year.")
        self.year = int(pieces[1])
        self.max_temp = clean_number(str(raw_temperature))

    def get_period(self):
        return f"{self.month} {self.year}"

    def summary_line(self):
        return f"Region: All India | Period: {self.get_period()} | Max Temp: {self.max_temp:.2f} C"


class HeatwaveAdvisory(WeatherBulletin):
    def __init__(self, raw_period, raw_temperature, raw_normal):
        super().__init__(raw_period, raw_temperature)
        self.normal = clean_number(str(raw_normal))

    def get_departure(self):
        return round(self.max_temp - self.normal, 4)

    def get_level(self):
        return classify_departure(self.get_departure())

    def headline(self):
        tags = ["IMD", "CRS PUNE", "HEAT ADVISORY"]
        return " | ".join(tags)

    def build_bulletin(self, width=64):
        level = self.get_level()
        departure = self.get_departure()
        sign = "+" if departure >= 0 else ""
        lines = []
        lines.append("=" * width)
        lines.append(self.headline().center(width))
        lines.append(f"ALERT LEVEL: {level}".center(width))
        lines.append("=" * width)
        lines.append("Region".ljust(18) + ": All India")
        lines.append("Period".ljust(18) + f": {self.get_period()}")
        lines.append("Max temperature".ljust(18) + f": {self.max_temp:.2f} C")
        lines.append("Normal (1991-2020)".ljust(18) + f": {self.normal:.2f} C")
        lines.append("Departure".ljust(18) + f": {sign}{departure:.2f} C")
        lines.append("-" * width)
        lines.append("GUIDANCE")
        for item in GUIDANCE[level]:
            wrapped = textwrap.wrap(item, width - 4)
            lines.append("  - " + wrapped[0])
            for extra in wrapped[1:]:
                lines.append("    " + extra)
        lines.append("-" * width)
        lines.extend(textwrap.wrap(FOOTER, width))
        return "\n".join(lines)


DAILY_GUIDANCE = {
    "NO HEATWAVE": [
        "IMD heatwave conditions are not met in this grid cell today.",
        "Normal summer precautions are enough.",
    ],
    "HEATWAVE": [
        "IMD heatwave conditions are met (2 days in a row).",
        "Avoid going out in the sun between 12 noon and 3 pm.",
        "Drink water often, even if not thirsty. Use ORS if needed.",
        "Check on elderly people, children and outdoor workers.",
    ],
    "SEVERE HEATWAVE": [
        "IMD SEVERE heatwave conditions are met.",
        "Very high risk of heat illness and heat stroke for all ages.",
        "Stay indoors in the afternoon. Outdoor work should stop.",
        "Hospitals should prepare for heat-stroke cases.",
    ],
}


class DailyHeatAdvisory(WeatherBulletin):
    """
    Second child of WeatherBulletin. Same cleaned period and temperature,
    but it applies IMD's real daily heatwave rule to one grid cell.
    """

    def __init__(self, raw_period, day_of_month, place, lat, lon, raw_temperature, normal, level):
        super().__init__(raw_period, raw_temperature)
        self.day_of_month = day_of_month
        self.place = place.strip().title()
        self.lat = lat
        self.lon = lon
        self.normal = normal
        self.level = level

    def get_period(self):
        return f"{self.day_of_month} {self.month} {self.year}"

    def get_level(self):
        return self.level

    def get_departure(self):
        return None if self.normal is None else round(self.max_temp - self.normal, 2)

    def build_bulletin(self, width=64):
        lines = ["=" * width, "IMD | CRS PUNE | DAILY HEAT BULLETIN".center(width),
                 f"STATUS: {self.level}".center(width), "=" * width]
        lines.append("Place".ljust(18) + f": {self.place} (grid cell {self.lat}N {self.lon}E)")
        lines.append("Date".ljust(18) + f": {self.get_period()}")
        lines.append("Max temperature".ljust(18) + f": {self.max_temp:.1f} C")
        if self.normal is not None:
            lines.append("Normal (2015-25)".ljust(18) + f": {self.normal:.1f} C")
            lines.append("Departure".ljust(18) + f": {self.get_departure():+.1f} C")
        lines.append("-" * width)
        lines.append("IMD RULE (plains)")
        lines.append("  Heatwave : max >= 40 C and +4.5 C above normal, or max >= 45 C")
        lines.append("  Severe   : max >= 40 C and +6.5 C above normal, or max >= 47 C")
        lines.append("  Declared only when met on 2 consecutive days.")
        lines.append("-" * width)
        lines.append("GUIDANCE")
        for item in DAILY_GUIDANCE[self.level]:
            lines.append("  - " + item)
        lines.append("-" * width)
        lines.extend(textwrap.wrap("Source: IMD daily 1-degree gridded maximum temperature. A grid cell "
                                   "averages about 100 x 100 km, so it reads lower than the hottest "
                                   "single station. For study purposes only - not an official IMD warning.", width))
        return "\n".join(lines)
