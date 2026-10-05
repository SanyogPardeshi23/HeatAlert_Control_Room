"""
reports.py  -  Experiment 4: Abstract classes and Polymorphism

ClimateReport is an abstract base class. It cannot be created on its own.
Every report type MUST provide its own generate() method.
The Reports screen keeps a list of report objects and calls generate()
on each one - it never checks which type it is. That is polymorphism.
"""

from abc import ABC, abstractmethod

from analytics import linear_trend, yearly_departures, yearly_means


class ClimateReport(ABC):
    def __init__(self, records, title):
        self.records = records
        self.title = title

    def header(self, width=64):
        return "\n".join(["=" * width, self.title.upper().center(width), "=" * width])

    @abstractmethod
    def generate(self):
        pass


class YearSummaryReport(ClimateReport):
    def __init__(self, records, year):
        super().__init__(records, f"Year summary - {year}")
        self.year = year

    def generate(self):
        rows = [r for r in self.records if r.period.year == self.year]
        if not rows:
            return self.header() + f"\nNo records for {self.year}."
        lines = [self.header(),
                 f"{'Month':<11}{'Max C':>9}{'Normal':>9}{'Depart.':>9}   Level",
                 "-" * 64]
        for r in rows:
            lines.append(f"{r.period.month:<11}{r.temperature.tmax:>9.2f}{r.normal.norm_max:>9.2f}"
                         f"{r.departure():>+9.2f}   {r.alert_level()}")
        hottest = max(rows, key=lambda r: r.departure())
        above = len([r for r in rows if r.departure() > 0])
        lines.append("-" * 64)
        lines.append(f"Months above normal : {above} of {len(rows)}")
        lines.append(f"Largest departure   : {hottest.period.month} ({hottest.departure():+.2f} C)")
        return "\n".join(lines)


class HottestMonthsReport(ClimateReport):
    def __init__(self, records, top_n=10):
        super().__init__(records, f"Top {top_n} warmest months vs normal (1901-2025)")
        self.top_n = top_n

    def generate(self):
        ranked = sorted(self.records, key=lambda r: r.departure(), reverse=True)[:self.top_n]
        lines = [self.header(), f"{'#':<4}{'Period':<16}{'Max C':>9}{'Depart.':>10}   Level", "-" * 64]
        for rank, r in enumerate(ranked, start=1):
            period = f"{r.period.month} {r.period.year}"
            lines.append(f"{rank:<4}{period:<16}{r.temperature.tmax:>9.2f}{r.departure():>+10.2f}   "
                         f"{r.alert_level()}")
        recent = len([r for r in ranked if r.period.year >= 2000])
        lines.append("-" * 64)
        lines.append(f"{recent} of these {self.top_n} months fall in 2000 or later.")
        return "\n".join(lines)


class DecadeTrendReport(ClimateReport):
    def __init__(self, records):
        super().__init__(records, "Decade averages and long-term trend")

    def generate(self):
        means = yearly_means(self.records)
        if len(means) < 2:
            return self.header() + "\nNot enough complete years to compute a trend."
        decades = {}
        for year, value in means.items():
            decades.setdefault((year // 10) * 10, []).append(value)
        lines = [self.header(), f"{'Decade':<10}{'Years':>7}{'Avg mean C':>14}", "-" * 64]
        for decade in sorted(decades):
            values = decades[decade]
            lines.append(f"{str(decade) + 's':<10}{len(values):>7}{sum(values) / len(values):>14.3f}")

        years = sorted(means)
        slope, _ = linear_trend(years, [means[y] for y in years])
        lines.append("-" * 64)
        lines.append(f"Complete years used : {len(years)} ({years[0]}-{years[-1]})")
        lines.append(f"Linear trend        : {slope * 100:+.2f} C per 100 years")
        lines.append("Annual value = average of the 12 monthly mean temperatures.")
        return "\n".join(lines)


class HeatSeasonReport(ClimateReport):
    """Focuses on March-June, the months when Indian heatwaves happen."""

    SEASON = ["March", "April", "May", "June"]

    def __init__(self, records, last_n_years=10):
        super().__init__(records, f"Heat season (Mar-Jun), last {last_n_years} years")
        self.last_n_years = last_n_years

    def generate(self):
        years = sorted({r.period.year for r in self.records})[-self.last_n_years:]
        lines = [self.header(), f"{'Year':<7}" + "".join(f"{m[:3]:>9}" for m in self.SEASON) + "    Worst",
                 "-" * 64]
        for year in years:
            rows = {r.period.month: r for r in self.records if r.period.year == year and r.period.month in self.SEASON}
            cells = ""
            for month in self.SEASON:
                cells += f"{rows[month].departure():>+9.2f}" if month in rows else f"{'--':>9}"
            worst = max(rows.values(), key=lambda r: r.departure()).alert_level() if rows else "--"
            lines.append(f"{year:<7}{cells}    {worst}")
        lines.append("-" * 64)
        lines.append("Values are departures of max temperature from the 1991-2020 normal (C).")
        return "\n".join(lines)


class AnomalyReport(ClimateReport):
    """Annual mean departure from normal for every year, as a text bar chart."""

    def __init__(self, records, from_year=1990):
        super().__init__(records, f"Annual departure from normal since {from_year}")
        self.from_year = from_year

    def generate(self):
        departures = yearly_departures(self.records)
        lines = [self.header()]
        for year in sorted(departures):
            if year < self.from_year:
                continue
            value = departures[year]
            bar = ("+" if value >= 0 else "-") * int(round(abs(value) * 40))
            lines.append(f"{year}  {value:+.3f}  {bar}")
        lines.append("-" * 64)
        lines.append("Each + or - is 0.025 C. Positive = warmer than the 1991-2020 normal.")
        return "\n".join(lines)


def available_years(records):
    return sorted({r.period.year for r in records})


class DailyHeatwaveReport(ClimateReport):
    """Uses IMD's daily 1-degree grid instead of the monthly series - same generate() call."""

    def __init__(self, grid, year):
        super().__init__([], f"Daily heatwave log - {year} (IMD 1-degree grid)")
        self.grid = grid
        self.year = year

    def generate(self):
        if self.year not in self.grid.years:
            return self.header() + f"\nNo daily grid file for {self.year}. Available: " \
                                   f"{self.grid.years[0]}-{self.grid.years[-1]}."
        rows = self.grid.daily_summary(self.year)
        spells = []
        current = None
        for date, reported, heat, severe, hottest, index in rows:
            if heat > 0:
                if current is None:
                    current = [date, date, heat, severe, hottest]
                else:
                    current[1] = date
                    current[2] = max(current[2], heat)
                    current[3] = max(current[3], severe)
                    current[4] = max(current[4], hottest)
            elif current is not None:
                spells.append(current)
                current = None
        if current is not None:
            spells.append(current)

        lines = [self.header(),
                 f"{'From':<12}{'To':<12}{'Days':>5}{'Peak cells':>12}{'Severe':>8}{'Hottest C':>11}", "-" * 64]
        for start, end, peak, severe, hottest in spells:
            days = (end - start).days + 1
            lines.append(f"{start.strftime('%d %b'):<12}{end.strftime('%d %b'):<12}{days:>5}{peak:>12}{severe:>8}"
                         f"{hottest:>11.1f}")
        total = sum(r[2] for r in rows)
        peak_day = max(rows, key=lambda r: r[2])
        lines.append("-" * 64)
        lines.append(f"Heatwave spells     : {len(spells)}")
        lines.append(f"Heatwave cell-days  : {total}")
        if peak_day[2]:
            lines.append(f"Worst day           : {peak_day[0].strftime('%d %B')} ({peak_day[2]} grid cells)")
        lines.append("A spell = consecutive days with at least one grid cell under the IMD rule.")
        return "\n".join(lines)
