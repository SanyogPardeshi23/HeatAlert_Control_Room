"""
grid.py  -  reads IMD's daily gridded maximum temperature files (binary .GRD)

Source: IMD Pune, "Daily Maximum Temp. (1.0 x 1.0) Binary"
Each file = one year. For every day there are 31 x 31 values (4-byte floats):
    latitude  7.5N, 8.5N ... 37.5N   (31 rows, south to north)
    longitude 67.5E, 68.5E ... 97.5E (31 columns, west to east)
365 days, or 366 in a leap year. 99.9 means "no data" (sea, or no station nearby).

IMD heatwave rules applied here (plains):
    HEATWAVE        max >= 40 C and departure from normal >= 4.5 C,  or  max >= 45 C
    SEVERE          max >= 40 C and departure from normal >= 6.5 C,  or  max >= 47 C
    IMD only declares a heatwave when the condition holds on 2 consecutive days,
    so a cell-day counts only if the day before or the day after also qualifies.

The "normal" for a cell and calendar day is the 2015-2025 average of a 15-day
window around that day. IMD's real normal uses 1991-2020; only 11 years of grid
files are available here, so this baseline is a little warmer and the
departure rule slightly UNDER-counts heatwaves. The 45 C / 47 C rules need no
normal and are applied exactly.
"""

import calendar
import datetime
import os
import re
import sys
from array import array

SIZE = 31
CELLS = SIZE * SIZE
LAT0 = 7.5
LON0 = 67.5
MISSING_ABOVE = 90.0
WINDOW = 15

NONE, HEATWAVE, SEVERE = 0, 1, 2
LEVEL_NAMES = {NONE: "NO HEATWAVE", HEATWAVE: "HEATWAVE", SEVERE: "SEVERE HEATWAVE"}

FILE_PATTERN = re.compile(r"Maxtemp_MaxT_(\d{4})\.GRD$", re.IGNORECASE)

# City -> nearest 1-degree grid cell centre (lat, lon)
CITIES = {
    "Delhi": (28.5, 77.5),
    "Jaipur": (26.5, 75.5),
    "Phalodi (Rajasthan)": (27.5, 72.5),
    "Lucknow": (26.5, 80.5),
    "Patna": (25.5, 85.5),
    "Ahmedabad": (23.5, 72.5),
    "Nagpur": (21.5, 79.5),
    "Bhubaneswar": (20.5, 85.5),
    "Hyderabad": (17.5, 78.5),
    "Pune": (18.5, 73.5),
}


class GridError(Exception):
    pass


def cell_index(lat, lon):
    row = int(round(lat - LAT0))
    col = int(round(lon - LON0))
    if not (0 <= row < SIZE and 0 <= col < SIZE):
        raise GridError(f"{lat}N {lon}E is outside the grid.")
    return row * SIZE + col


def cell_position(index):
    row, col = divmod(index, SIZE)
    return LAT0 + row, LON0 + col


def is_missing(value):
    return value != value or value > MISSING_ABOVE      # value != value is True only for NaN


def calendar_slot(year, day):
    """0-based day of the year -> 0..364. 29 February shares 28 February's slot."""
    if calendar.isleap(year) and day >= 59:
        return max(58, day - 1)
    return day


def date_of(year, day):
    return datetime.date(year, 1, 1) + datetime.timedelta(days=day)


def raw_level(value, normal):
    if is_missing(value):
        return NONE
    departure = None if normal is None else value - normal
    if value >= 47.0 or (value >= 40.0 and departure is not None and departure >= 6.5):
        return SEVERE
    if value >= 45.0 or (value >= 40.0 and departure is not None and departure >= 4.5):
        return HEATWAVE
    return NONE


class GridYear:
    def __init__(self, year, path):
        self.year = year
        self.days = 366 if calendar.isleap(year) else 365
        values = array("f")
        expected = self.days * CELLS
        size = os.path.getsize(path)
        if size != expected * 4:
            raise GridError(f"{os.path.basename(path)} has {size} bytes, expected {expected * 4} "
                            f"for {self.days} days of a 31 x 31 grid.")
        with open(path, "rb") as f:
            values.fromfile(f, expected)
        if sys.byteorder == "big":              # IMD files are little-endian
            values.byteswap()
        self.values = values
        self.levels = None                       # filled in by HeatwaveGrid

    def day(self, day):
        start = day * CELLS
        return self.values[start:start + CELLS]

    def value(self, day, index):
        return self.values[day * CELLS + index]


class HeatwaveGrid:
    def __init__(self, folder):
        self.folder = folder
        self.files = {}
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                match = FILE_PATTERN.match(name)
                if match:
                    self.files[int(match.group(1))] = os.path.join(folder, name)
        self.years = sorted(self.files)
        self.loaded = {}
        self.baseline = None

    def available(self):
        return len(self.years) > 0

    def year(self, year):
        if year not in self.files:
            raise GridError(f"No grid file for {year}.")
        if year not in self.loaded:
            self.loaded[year] = GridYear(year, self.files[year])
        return self.loaded[year]

    # ---------- baseline ("normal") ----------

    def build_baseline(self):
        """Average of all years for each cell and calendar day, then smoothed over 15 days."""
        sums = [[0.0] * CELLS for _ in range(365)]
        counts = [[0] * CELLS for _ in range(365)]
        for y in self.years:
            grid = self.year(y)
            for day in range(grid.days):
                if calendar.isleap(y) and day == 59:      # 29 Feb is left out of the average
                    continue
                slot = calendar_slot(y, day)
                s, c = sums[slot], counts[slot]
                values = grid.day(day)
                for i in range(CELLS):
                    v = values[i]
                    if v <= MISSING_ABOVE:
                        s[i] += v
                        c[i] += 1

        half = WINDOW // 2
        baseline = []
        for slot in range(365):
            total = [0.0] * CELLS
            number = [0] * CELLS
            for k in range(slot - half, slot + half + 1):
                s, c = sums[k % 365], counts[k % 365]
                for i in range(CELLS):
                    if c[i]:
                        total[i] += s[i]
                        number[i] += c[i]
            baseline.append([total[i] / number[i] if number[i] else None for i in range(CELLS)])
        self.baseline = baseline

    def normal(self, year, day, index):
        if self.baseline is None:
            self.build_baseline()
        return self.baseline[calendar_slot(year, day)][index]

    # ---------- heatwave classification ----------

    def levels(self, year):
        """Final level (NONE / HEATWAVE / SEVERE) for every day and cell, using the 2-day rule."""
        grid = self.year(year)
        if grid.levels is not None:
            return grid.levels
        if self.baseline is None:
            self.build_baseline()
        raw = []
        for day in range(grid.days):
            base = self.baseline[calendar_slot(year, day)]
            values = grid.day(day)
            raw.append([raw_level(values[i], base[i]) for i in range(CELLS)])
        final = []
        for day in range(grid.days):
            before = raw[day - 1] if day > 0 else None
            after = raw[day + 1] if day + 1 < grid.days else None
            row = []
            for i, level in enumerate(raw[day]):
                confirmed = level and ((before and before[i]) or (after and after[i]))
                row.append(level if confirmed else NONE)
            final.append(row)
        grid.levels = final
        return final

    def cell_reading(self, year, day, index):
        """(max temp or None, normal or None, departure or None, level)."""
        grid = self.year(year)
        value = grid.value(day, index)
        if is_missing(value):
            return None, None, None, NONE
        normal = self.normal(year, day, index)
        departure = None if normal is None else round(value - normal, 2)
        return round(value, 2), None if normal is None else round(normal, 2), departure, self.levels(year)[day][index]

    def daily_summary(self, year):
        """One row per day: (date, cells_reported, heatwave_cells, severe_cells, hottest, hottest_index)."""
        grid = self.year(year)
        levels = self.levels(year)
        rows = []
        for day in range(grid.days):
            values = grid.day(day)
            reported = 0
            hottest, hottest_index = None, None
            for i in range(CELLS):
                v = values[i]
                if v <= MISSING_ABOVE:
                    reported += 1
                    if hottest is None or v > hottest:
                        hottest, hottest_index = v, i
            heat = sum(1 for level in levels[day] if level >= HEATWAVE)
            severe = sum(1 for level in levels[day] if level == SEVERE)
            rows.append((date_of(year, day), reported, heat, severe,
                         None if hottest is None else round(hottest, 2), hottest_index))
        return rows

    def nearest_city(self, index, max_distance=1.0):
        lat, lon = cell_position(index)
        best = None
        for name, (clat, clon) in CITIES.items():
            distance = max(abs(clat - lat), abs(clon - lon))
            if distance <= max_distance and (best is None or distance < best[1]):
                best = (name, distance)
        return best[0] if best else None
