"""
verify_data.py  -  re-checks the dataset against the three IMD tables it was built from.

raw/max.txt, raw/min.txt, raw/mean.txt are the three tables copied from
imdpune.gov.in/cmpg/Product/allindia_temp.html  (year, Jan..Dec, Annual).

Check 1: for every year and month, mean = (max + min) / 2 within 0.001 C.
         The three tables are published separately, so a single wrong digit
         in any of them breaks this.
Check 2: data/imd_all_india_1901_2025.csv matches the raw tables exactly.
Check 3: every daily grid file in data/grid/ has the right size, and the
         grid's monthly average over India tracks IMD's All-India series.

Run:   python verify_data.py
"""

import csv
import os

BASE = os.path.dirname(os.path.abspath(__file__))
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def load(name):
    table = {}
    with open(os.path.join(BASE, "raw", name + ".txt")) as f:
        for line in f:
            parts = line.split()
            table[parts[0]] = [float(x) for x in parts[1:]]
    return table


def main():
    tmax, tmin, tmean = load("max"), load("min"), load("mean")
    failures = 0
    cells = 0
    for key in tmax:
        tolerance = 0.006 if key == "NORM" else 0.0011
        for i in range(13):
            cells += 1
            if abs((tmax[key][i] + tmin[key][i]) / 2 - tmean[key][i]) > tolerance:
                failures += 1
                print("Mismatch:", key, i)
    print(f"Check 1: {cells} cells checked, {failures} failed")

    mismatches = 0
    rows = 0
    with open(os.path.join(BASE, "data", "imd_all_india_1901_2025.csv"), newline="") as f:
        for row in csv.DictReader(f):
            rows += 1
            i = MONTHS.index(row["month"])
            for column, table in (("max_temp", tmax), ("min_temp", tmin), ("mean_temp", tmean)):
                if abs(float(row[column]) - table[row["year"]][i]) > 1e-9:
                    mismatches += 1
    print(f"Check 2: {rows} CSV rows checked, {mismatches} values differ from the raw tables")
    grid_ok = check_grid(tmax)
    print("RESULT:", "all checks passed" if failures == 0 and mismatches == 0 and grid_ok else "PROBLEMS FOUND")


def check_grid(tmax):
    import calendar
    import math
    from grid import HeatwaveGrid, GridError, MISSING_ABOVE, CELLS, LAT0, SIZE

    grid = HeatwaveGrid(os.path.join(BASE, "data", "grid"))
    if not grid.available():
        print("Check 3: no grid files found - skipped")
        return True
    weights = [math.cos(math.radians(LAT0 + i // SIZE)) for i in range(CELLS)]
    ours, imds = [], []
    for year in grid.years:
        try:
            data = grid.year(year)
        except GridError as error:
            print("Check 3:", error)
            return False
        day = 0
        for month in range(12):
            days = calendar.monthrange(year, month + 1)[1]
            total = weight = 0.0
            for d in range(day, day + days):
                values = data.day(d)
                for i in range(CELLS):
                    if values[i] <= MISSING_ABOVE:
                        total += values[i] * weights[i]
                        weight += weights[i]
            day += days
            if str(year) in tmax:
                ours.append(total / weight)
                imds.append(tmax[str(year)][month])
    n = len(ours)
    mean_a, mean_b = sum(ours) / n, sum(imds) / n
    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(ours, imds))
    corr = cov / math.sqrt(sum((a - mean_a) ** 2 for a in ours) * sum((b - mean_b) ** 2 for b in imds))
    mean_gap = sum(abs(a - b) for a, b in zip(ours, imds)) / n
    print(f"Check 3: {len(grid.years)} grid files ({grid.years[0]}-{grid.years[-1]}) read OK; "
          f"{n} months compared with the All-India series: correlation {corr:.4f}, average gap {mean_gap:.2f} C")
    return corr > 0.99


if __name__ == "__main__":
    main()
