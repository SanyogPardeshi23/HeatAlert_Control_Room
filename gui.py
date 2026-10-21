"""
gui.py  -  the Tkinter front end.

App          the main window: sidebar on the left, one screen at a time on the right
Screen       parent class for every screen (build / refresh / on_show)
...Screen    one subclass per screen

All database work and every widget update happens on the main thread.
The Live Monitor's worker threads only talk to this file through a queue.
"""

import calendar
import datetime
import os
import queue
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import theme
from advisories import DailyHeatAdvisory, HeatwaveAdvisory, split_raw_feed
from analytics import SEASONS, STATION_INFO, analyse, linear_trend, moving_average, yearly_departures, yearly_means
from charts import BarChart, LineChart, StripesChart, Tooltip, draw_logo
from database import PRESET_QUERIES, ClimateDatabase, DatabaseError
from grid import (CITIES, LAT0, LEVEL_NAMES, LON0, SIZE, GridError, HeatwaveGrid, cell_index, cell_position,
                  date_of)
from models import ALERT_ORDER, MONTHS
from monitor import Channel, StreamMonitor
from readings import ReadingLog, parse_temperature, parse_year
from reports import (AnomalyReport, DailyHeatwaveReport, DecadeTrendReport, HeatSeasonReport, HottestMonthsReport,
                     YearSummaryReport)

APP_NAME = "HeatAlert Control Room"

TEAM = [
    ("Sanyog Pardeshi", "16010425081"),
    ("Harshad Saha", "16010425092"),
    ("Meher Rabadi", "16010425089"),
]

PROJECT_INFO = {
    "Branch": "Information Technology",
    "Course": "Object Oriented Programming Lab (Python)",
    "Institute": "K. J. Somaiya School of Engineering, Somaiya Vidyavihar University",
    "Academic year": "2026-27",
}

EXPERIMENT_MAP = [
    ("1", "Classes, objects, constructors", "Each reading is a WeatherRecord", "models.py"),
    ("2", "Constructors and lists", "Data Manager: add, delete, stats", "readings.py"),
    ("3", "String handling, inheritance", "Advisories: cleans raw feed text", "advisories.py"),
    ("4", "Abstract class, polymorphism", "Reports: one call, five report types", "reports.py"),
    ("5", "Exceptions, modules, threads", "Live Monitor: 3 city threads", "monitor.py"),
    ("6", "Collections, functional prog.", "Analytics: map, filter, reduce, lambda", "analytics.py"),
    ("7", "Tkinter Canvas drawing", "Heatwave map, charts, logo", "charts.py"),
    ("8", "SQLite database", "Database Console + all storage", "database.py"),
]


def tint(level):
    return theme.blend(theme.LEVEL_COLOURS[level], "#ffffff", 0.84)


def read_int(variable, name, low, high):
    try:
        value = int(str(variable.get()).strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number.")
    if value < low or value > high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return value


# ======================================================================
# Small reusable widgets
# ======================================================================

class Card(tk.Frame):
    """A white panel with a thin border and an optional title."""

    def __init__(self, parent, app, title=None, padding=14):
        super().__init__(parent, bg=theme.SURFACE, highlightbackground=theme.CARD_BORDER,
                         highlightthickness=1, bd=0)
        self.inner = tk.Frame(self, bg=theme.SURFACE)
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)
        if title:
            tk.Label(self.inner, text=title, bg=theme.SURFACE, fg=theme.INK, font=app.fonts["h2"],
                     anchor="w").pack(fill="x", pady=(0, 8))


class StatTile(tk.Frame):
    """A small card with a caption, a big number and a note underneath."""

    def __init__(self, parent, app, caption):
        super().__init__(parent, bg=theme.SURFACE, highlightbackground=theme.CARD_BORDER, highlightthickness=1)
        inner = tk.Frame(self, bg=theme.SURFACE)
        inner.pack(fill="both", expand=True, padx=14, pady=10)
        self.caption = tk.Label(inner, text=caption, bg=theme.SURFACE, fg=theme.INK_SECONDARY, font=app.fonts["small"],
                                anchor="w")
        self.caption.pack(fill="x")
        self.value = tk.Label(inner, text="-", bg=theme.SURFACE, fg=theme.INK, font=app.fonts["kpi"], anchor="w")
        self.value.pack(fill="x")
        self.note = tk.Label(inner, text="", bg=theme.SURFACE, fg=theme.INK_MUTED, font=app.fonts["small"],
                             anchor="w", justify="left")
        self.note.pack(fill="x")

    def set(self, value, note=""):
        self.value.config(text=value)
        self.note.config(text=note)

    def set_caption(self, text):
        self.caption.config(text=text)


class LevelBadge(tk.Label):
    """Alert level shown as a coloured label - the word is always written, never colour alone."""

    def __init__(self, parent, app):
        super().__init__(parent, text="", font=app.fonts["bold"], padx=10, pady=3)

    def set(self, level):
        colour = theme.LEVEL_COLOURS.get(level) or theme.DAILY_COLOURS.get(level, theme.INK_MUTED)
        if level == "NO HEATWAVE":
            colour = theme.INK_MUTED
        self.config(text=level, bg=colour, fg=theme.text_on(colour))


def make_tree(parent, columns, widths, height=12):
    frame = tk.Frame(parent, bg=theme.SURFACE)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    for column, width in zip(columns, widths):
        tree.heading(column, text=column)
        tree.column(column, width=width, anchor="w" if width >= 120 else "center", stretch=width >= 120)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")      # packed first so it is never squeezed out
    tree.pack(side="left", fill="both", expand=True)
    for level in ALERT_ORDER:
        tree.tag_configure(level, background=tint(level) if level != "NORMAL" else theme.SURFACE)
    tree.tag_configure("fault", background="#fbe4e0")
    tree.tag_configure("HEATWAVE", background=theme.blend(theme.DAILY_COLOURS["HEATWAVE"], "#ffffff", 0.80))
    tree.tag_configure("SEVERE HEATWAVE", background=theme.blend(theme.DAILY_COLOURS["SEVERE HEATWAVE"], "#ffffff", 0.75))
    return frame, tree


def wrapping_label(parent, app, text, font="body", colour=None):
    """A label that re-wraps its text whenever its width changes."""
    label = tk.Label(parent, text=text, bg=theme.SURFACE, fg=colour or theme.INK, font=app.fonts[font],
                     justify="left", anchor="w")

    def rewrap(event):
        new = max(50, event.width - 4)
        if abs(int(label.cget("wraplength")) - new) > 2:     # ignore tiny changes, or Tk can loop forever
            label.config(wraplength=new)

    label.bind("<Configure>", rewrap)
    return label


def labelled(parent, text, widget_factory, app):
    box = tk.Frame(parent, bg=theme.SURFACE)
    tk.Label(box, text=text, bg=theme.SURFACE, fg=theme.INK_SECONDARY, font=app.fonts["small"],
             anchor="w").pack(fill="x")
    widget = widget_factory(box)
    widget.pack(fill="x", pady=(2, 0))
    return box, widget


# ======================================================================
# Screen parent class
# ======================================================================

class Screen(tk.Frame):
    title = ""
    subtitle = ""

    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.PAGE)
        self.app = app
        self.seen_version = -1
        header = tk.Frame(self, bg=theme.PAGE)
        header.pack(fill="x", padx=24, pady=(18, 10))
        tk.Label(header, text=self.title, bg=theme.PAGE, fg=theme.INK, font=app.fonts["h1"],
                 anchor="w").pack(fill="x")
        tk.Label(header, text=self.subtitle, bg=theme.PAGE, fg=theme.INK_SECONDARY, font=app.fonts["body"],
                 anchor="w").pack(fill="x")
        self.body = tk.Frame(self, bg=theme.PAGE)
        self.body.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.build()

    def build(self):
        raise NotImplementedError

    def refresh(self):
        pass

    def on_show(self):
        """Called every time the screen is opened. Only refreshes if the data changed."""
        if self.seen_version != self.app.data_version:
            self.seen_version = self.app.data_version
            self.refresh()

    def on_close(self):
        pass


# ======================================================================
# 1. Dashboard  (Experiments 1, 6, 7)
# ======================================================================

class DashboardScreen(Screen):
    title = "Dashboard"
    subtitle = "All-India temperature 1901-2025 from IMD Pune, compared with the 1991-2020 normal"

    def build(self):
        app = self.app
        tiles = tk.Frame(self.body, bg=theme.PAGE)
        tiles.pack(fill="x")
        self.tile_latest = StatTile(tiles, app, "Latest month")
        self.tile_warmest = StatTile(tiles, app, "Warmest year on record")
        self.tile_last_year = StatTile(tiles, app, "Latest year vs normal")
        self.tile_trend = StatTile(tiles, app, "Long-term warming trend")
        self.tile_extreme = StatTile(tiles, app, "EXTREME months")
        for i, tile in enumerate((self.tile_latest, self.tile_warmest, self.tile_last_year,
                                  self.tile_trend, self.tile_extreme)):
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            tiles.columnconfigure(i, weight=1)
        self.latest_badge = LevelBadge(self.tile_latest.winfo_children()[0], app)
        self.latest_badge.pack(anchor="w", pady=(4, 0))

        lower = tk.Frame(self.body, bg=theme.PAGE)
        lower.pack(fill="both", expand=True, pady=(12, 0))
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=3)
        lower.rowconfigure(1, weight=1)

        trend_card = Card(lower, app, "Annual mean temperature")
        trend_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        canvas = tk.Canvas(trend_card.inner, bg=theme.SURFACE, highlightthickness=0, height=240)
        canvas.pack(fill="both", expand=True)
        self.trend_chart = LineChart(canvas, app.fonts, y_label="deg C", value_format="{:.2f}")

        stripes_card = Card(lower, app, "Warming stripes - each bar is one year")
        stripes_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(10, 0))
        canvas = tk.Canvas(stripes_card.inner, bg=theme.SURFACE, highlightthickness=0, height=70)
        canvas.pack(fill="both", expand=True)
        self.stripes = StripesChart(canvas, app.fonts)

        month_card = Card(lower, app, "One month across 125 years")
        month_card.grid(row=0, column=1, rowspan=2, sticky="nsew")
        picker_row = tk.Frame(month_card.inner, bg=theme.SURFACE)
        picker_row.pack(fill="x", pady=(0, 6))
        tk.Label(picker_row, text="Month", bg=theme.SURFACE, fg=theme.INK_SECONDARY,
                 font=app.fonts["small"]).pack(side="left")
        self.month_var = tk.StringVar(value="May")
        picker = ttk.Combobox(picker_row, textvariable=self.month_var, values=MONTHS, state="readonly", width=12)
        picker.pack(side="left", padx=8)
        picker.bind("<<ComboboxSelected>>", lambda e: self.draw_month())
        canvas = tk.Canvas(month_card.inner, bg=theme.SURFACE, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.month_chart = LineChart(canvas, app.fonts, y_label="max temp, deg C")

    def refresh(self):
        records = self.app.records
        if not records:
            return
        latest = records[-1]
        self.tile_latest.set(latest.period.label(),
                             f"max {latest.temperature.tmax:.2f} C ({latest.departure():+.2f} vs normal)")
        self.latest_badge.set(latest.alert_level())

        means = yearly_means(records)
        departures = yearly_departures(records)
        years = sorted(means)
        if years:
            warmest = max(years, key=lambda y: means[y])
            self.tile_warmest.set(str(warmest), f"annual mean {means[warmest]:.2f} C")
            last = years[-1]
            self.tile_last_year.set(f"{departures[last]:+.2f} C", f"{last}, annual mean departure")
            slope, _ = linear_trend(years, [means[y] for y in years])
            self.tile_trend.set(f"{slope * 100:+.2f} C", f"per 100 years ({years[0]}-{years[-1]})")
        extreme = [r for r in records if r.alert_level() == "EXTREME"]
        recent = [r for r in extreme if r.period.year >= 2000]
        self.tile_extreme.set(str(len(extreme)), f"{len(recent)} of them since 2000")

        values = [means[y] for y in years]
        month_normals = {r.period.month: r.normal.norm_mean for r in records}
        normal = sum(month_normals.values()) / len(month_normals)
        self.trend_chart.set_data(years, [
            {"name": "Annual mean", "values": values, "colour": theme.SERIES_1, "width": 1},
            {"name": "11-year average", "values": moving_average(values, 11), "colour": theme.SERIES_2, "width": 3},
        ], reference=(normal, f"1991-2020 normal {normal:.2f} C"))
        self.stripes.set_data(departures)
        self.draw_month()

    def draw_month(self):
        month = self.month_var.get()
        rows = [r for r in self.app.records if r.period.month == month]
        if not rows:
            self.month_chart.set_data([], [])
            return
        self.month_chart.set_data([r.period.year for r in rows], [
            {"name": month, "values": [r.temperature.tmax for r in rows], "colour": theme.ACCENT, "width": 2},
        ], reference=(rows[0].normal.norm_max, f"normal {rows[0].normal.norm_max:.2f} C"))


# ======================================================================
# 2. Heatwave Map  (daily IMD grid - Experiments 1, 6, 7)
# ======================================================================

class HeatwaveMapScreen(Screen):
    title = "Heatwave Map"
    subtitle = "Daily maximum temperature on IMD's 1-degree grid, 2015-2025, with IMD's heatwave rule applied to every cell"

    LABELLED_CITIES = ("Delhi", "Phalodi (Rajasthan)", "Patna", "Nagpur", "Hyderabad", "Ahmedabad", "Bhubaneswar")

    def build(self):
        app = self.app
        self.heat_grid = app.heat_grid
        if not self.heat_grid.available():
            card = Card(self.body, app, "Daily grid files not found")
            card.pack(fill="x")
            wrapping_label(card.inner, app, "Put the IMD files named Maxtemp_MaxT_YYYY.GRD in data/grid/ "
                                            "and restart the app.").pack(fill="x")
            return
        self.year_var = tk.StringVar(value=str(self.heat_grid.years[-2] if len(self.heat_grid.years) > 1 else self.heat_grid.years[0]))
        self.day_var = tk.IntVar(value=0)
        self.view_var = tk.StringVar(value="temp")
        self.playing = False
        self.rects = {}
        self.geometry = None
        self.shown_year = None

        controls = Card(self.body, app, padding=10)
        controls.pack(fill="x")
        row = controls.inner
        box, picker = labelled(row, "Year", lambda p: ttk.Combobox(p, textvariable=self.year_var, state="readonly",
                                                                    values=[str(y) for y in self.heat_grid.years], width=6), app)
        box.pack(side="left", padx=(0, 12))
        picker.bind("<<ComboboxSelected>>", lambda e: self.change_year())
        date_box = tk.Frame(row, bg=theme.SURFACE)
        date_box.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.date_label = tk.Label(date_box, text="", bg=theme.SURFACE, fg=theme.INK, font=app.fonts["bold"], anchor="w")
        self.date_label.pack(fill="x")
        self.scale = ttk.Scale(date_box, from_=0, to=364, orient="horizontal", command=self.on_scale)
        self.scale.pack(fill="x", pady=(2, 0))
        ttk.Button(row, text="<", width=3, command=lambda: self.step(-1)).pack(side="left", pady=(14, 0))
        ttk.Button(row, text=">", width=3, command=lambda: self.step(1)).pack(side="left", padx=(4, 8), pady=(14, 0))
        self.play_button = ttk.Button(row, text="Play", width=7, style="Accent.TButton", command=self.toggle_play)
        self.play_button.pack(side="left", pady=(14, 0))
        ttk.Button(row, text="Worst day", command=self.jump_to_worst).pack(side="left", padx=(8, 12), pady=(14, 0))
        views = tk.Frame(row, bg=theme.SURFACE)
        views.pack(side="left", pady=(14, 0))
        for text, value in (("Temperature", "temp"), ("Heatwave status", "status")):
            ttk.Radiobutton(views, text=text, value=value, variable=self.view_var, style="Card.TRadiobutton",
                            command=self.paint).pack(side="left", padx=(0, 6))

        lower = tk.Frame(self.body, bg=theme.PAGE)
        lower.pack(fill="both", expand=True, pady=(10, 0))
        lower.columnconfigure(0, weight=3, uniform="map")
        lower.columnconfigure(1, weight=2, uniform="map")
        lower.rowconfigure(0, weight=1)
        map_card = Card(lower, app, padding=8)
        map_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.canvas = tk.Canvas(map_card.inner, bg=theme.SURFACE, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.tooltip = Tooltip(self.canvas, app.fonts["small"])
        self.canvas.bind("<Configure>", lambda e: self.layout())
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda e: self.tooltip.hide())

        side = tk.Frame(lower, bg=theme.PAGE)
        side.grid(row=0, column=1, sticky="nsew")
        tiles = tk.Frame(side, bg=theme.PAGE)
        tiles.pack(fill="x")
        self.tile_cells = StatTile(tiles, app, "Grid cells in heatwave")
        self.tile_hot = StatTile(tiles, app, "Hottest grid cell")
        self.tile_cells.grid(row=0, column=0, sticky="nsew")
        self.tile_hot.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        tiles.columnconfigure(0, weight=1, uniform="tiles")
        tiles.columnconfigure(1, weight=1, uniform="tiles")
        bars_card = Card(side, app, "Heatwave cell-days per year")
        bars_card.pack(fill="both", expand=True, pady=(10, 0))
        canvas = tk.Canvas(bars_card.inner, bg=theme.SURFACE, highlightthickness=0, height=170)
        canvas.pack(fill="both", expand=True)
        self.bars = BarChart(canvas, app.fonts, unit="cell-days")
        rule = Card(side, app, "IMD heatwave rule (plains)")
        rule.pack(fill="x", pady=(10, 0))
        wrapping_label(rule.inner, app, "Heatwave: max >= 40 C and +4.5 C above normal, or max >= 45 C.\n"
                                        "Severe: +6.5 C above normal, or max >= 47 C.\n"
                                        "Must hold on 2 days in a row. Normal = 2015-2025 average for that "
                                        "cell and date.", colour=theme.INK_SECONDARY).pack(fill="x")

    # ---------- data ----------

    def refresh(self):
        if not self.heat_grid.available():
            return
        totals = self.app.db.grid_year_totals()
        self.year_totals = {year: heat for year, heat, severe in totals}
        self.change_year(keep_day=True)

    def current_year(self):
        return int(self.year_var.get())

    def change_year(self, keep_day=False):
        year = self.current_year()
        data = self.heat_grid.year(year)
        self.levels = self.heat_grid.levels(year)
        self.summary = self.heat_grid.daily_summary(year)
        self.land = [any(data.value(d, i) <= 90 for d in range(0, data.days, 7)) for i in range(961)]
        self.scale.configure(to=data.days - 1)
        first_time = self.shown_year is None
        self.shown_year = year
        if first_time or not keep_day or self.day_var.get() >= data.days:
            self.day_var.set(max(range(data.days), key=lambda d: self.summary[d][2]))
        self.scale.set(self.day_var.get())
        years = sorted(self.year_totals)
        self.bars.set_data(years, [self.year_totals[y] for y in years],
                           [theme.ACCENT if y == year else theme.BASELINE for y in years])
        self.layout()

    def step(self, delta):
        days = self.heat_grid.year(self.current_year()).days
        self.day_var.set(max(0, min(days - 1, self.day_var.get() + delta)))
        self.scale.set(self.day_var.get())
        self.paint()

    def on_scale(self, value):
        day = int(float(value))
        if day != self.day_var.get():
            self.day_var.set(day)
            self.paint()

    def jump_to_worst(self):
        self.day_var.set(max(range(len(self.summary)), key=lambda d: self.summary[d][2]))
        self.scale.set(self.day_var.get())
        self.paint()

    def toggle_play(self):
        self.playing = not self.playing
        self.play_button.config(text="Pause" if self.playing else "Play")
        if self.playing:
            self.play_tick()

    def play_tick(self):
        if not self.playing:
            return
        days = self.heat_grid.year(self.current_year()).days
        if self.day_var.get() >= days - 1:
            self.toggle_play()
            return
        self.step(1)
        self.after(120, self.play_tick)

    # ---------- drawing ----------

    def layout(self):
        """Create one rectangle per land cell. Colours are set later by paint()."""
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 100 or not hasattr(self, "land"):
            return
        c.delete("all")
        self.rects = {}
        legend_h = 46
        size = min((w - 60) / SIZE, (h - legend_h - 26) / SIZE)
        x0 = 44 + (w - 60 - size * SIZE) / 2
        y0 = 8
        self.geometry = (x0, y0, size)
        for index in range(961):
            if not self.land[index]:
                continue
            row, col = divmod(index, SIZE)
            x = x0 + col * size
            y = y0 + (SIZE - 1 - row) * size          # north at the top
            self.rects[index] = c.create_rectangle(x + 0.5, y + 0.5, x + size - 0.5, y + size - 0.5,
                                                   fill=theme.SURFACE, outline=theme.BASELINE, width=1)
        for lat in (10, 15, 20, 25, 30, 35):
            y = y0 + (SIZE - 1 - (lat - LAT0)) * size + size / 2
            c.create_text(x0 - 6, y, text=f"{lat}N", anchor="e", fill=theme.INK_MUTED, font=self.app.fonts["small"])
        for lon in (70, 75, 80, 85, 90, 95):
            x = x0 + (lon - LON0) * size + size / 2
            c.create_text(x, y0 + SIZE * size + 10, text=f"{lon}E", fill=theme.INK_MUTED, font=self.app.fonts["small"])
        for name, (lat, lon) in CITIES.items():
            index = cell_index(lat, lon)
            x = x0 + (lon - LON0) * size + size / 2
            y = y0 + (SIZE - 1 - (lat - LAT0)) * size + size / 2
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#ffffff", outline=theme.INK, width=1, tags="city")
            if name in self.LABELLED_CITIES:
                label = name.split(" (")[0]
                text_id = c.create_text(x + 6, y, text=label, anchor="w", fill=theme.INK, font=self.app.fonts["small"],
                                        tags="city")
                x1, y1, x2, y2 = c.bbox(text_id)
                patch = c.create_rectangle(x1 - 2, y1, x2 + 2, y2, fill="#ffffff", outline="", tags="city")
                c.tag_raise(text_id, patch)
        self.legend_top = y0 + SIZE * size + 24
        self.paint()

    def paint(self):
        if not self.rects or not hasattr(self, "summary"):
            return
        year, day = self.current_year(), self.day_var.get()
        data = self.heat_grid.year(year)
        values = data.day(day)
        levels = self.levels[day]
        status_view = self.view_var.get() == "status"
        for index, rect in self.rects.items():
            v = values[index]
            level = levels[index]
            if v > 90:
                self.canvas.itemconfigure(rect, fill="#f1efe9", outline=theme.BASELINE, width=1)
                continue
            if status_view:
                fill = theme.DAILY_COLOURS[LEVEL_NAMES[level]]
                outline, width = theme.BASELINE, 1
            else:
                fill = theme.temp_colour(v)
                outline, width = (theme.INK, 2) if level else (theme.SURFACE, 1)
            self.canvas.itemconfigure(rect, fill=fill, outline=outline, width=width)
        self.canvas.tag_raise("city")
        self.draw_legend(status_view)

        date, reported, heat, severe, hottest, hot_index = self.summary[day]
        self.date_label.config(text=date.strftime("%A, %d %B %Y"))
        self.tile_cells.set(str(heat), f"{severe} severe, {reported} reporting")
        if hottest is None:
            self.tile_hot.set("-", "no data")
        else:
            lat, lon = cell_position(hot_index)
            place = self.heat_grid.nearest_city(hot_index)
            self.tile_hot.set(f"{hottest:.1f} C", f"{lat}N {lon}E" + (f" (near {place.split(' (')[0]})" if place else ""))

    def draw_legend(self, status_view):
        c = self.canvas
        c.delete("legend")
        x0, _, size = self.geometry
        y = self.legend_top
        if status_view:
            x = x0
            for name in ("NO HEATWAVE", "HEATWAVE", "SEVERE HEATWAVE"):
                c.create_rectangle(x, y, x + 14, y + 14, fill=theme.DAILY_COLOURS[name], outline=theme.BASELINE, tags="legend")
                text_id = c.create_text(x + 20, y + 7, text=name.title(), anchor="w", fill=theme.INK_SECONDARY,
                                        font=self.app.fonts["small"], tags="legend")
                x = c.bbox(text_id)[2] + 18
            return
        labels = ["<20", "20", "25", "30", "35", "40", "45", "47+"]
        swatch = 34
        for i, (colour, label) in enumerate(zip(theme.TEMP_RAMP, labels)):
            x = x0 + i * swatch
            c.create_rectangle(x, y, x + swatch - 2, y + 12, fill=colour, outline="", tags="legend")
            c.create_text(x + 1, y + 20, text=label, anchor="w", fill=theme.INK_MUTED, font=self.app.fonts["small"],
                          tags="legend")
        x = x0 + 8 * swatch + 16
        c.create_rectangle(x, y - 1, x + 14, y + 13, fill=theme.TEMP_RAMP[4], outline=theme.INK, width=2, tags="legend")
        c.create_text(x + 20, y + 6, text="outlined = IMD heatwave", anchor="w", fill=theme.INK_SECONDARY,
                      font=self.app.fonts["small"], tags="legend")

    def on_motion(self, event):
        if not self.geometry or not hasattr(self, "summary"):
            return
        x0, y0, size = self.geometry
        col = int((event.x - x0) // size)
        row = SIZE - 1 - int((event.y - y0) // size)
        if not (0 <= col < SIZE and 0 <= row < SIZE):
            self.tooltip.hide()
            return
        index = row * SIZE + col
        if index not in self.rects:
            self.tooltip.hide()
            return
        lat, lon = cell_position(index)
        value, normal, departure, level = self.heat_grid.cell_reading(self.current_year(), self.day_var.get(), index)
        place = self.heat_grid.nearest_city(index, max_distance=0.0)
        lines = [f"{lat}N {lon}E" + (f"  ({place})" if place else "")]
        if value is None:
            lines.append("No data on this day")
        else:
            lines.append(f"Max temp : {value:.1f} C")
            if normal is not None:
                lines.append(f"Normal   : {normal:.1f} C  ({departure:+.1f})")
            lines.append(f"Status   : {LEVEL_NAMES[level]}")
        self.tooltip.show(event.x, event.y, lines)

    def on_close(self):
        self.playing = False


# ======================================================================
# 3. Data Manager  (Experiments 2 and 8)
# ======================================================================

class DataManagerScreen(Screen):
    title = "Data Manager"
    subtitle = "Browse, add, edit and delete readings. Changes are saved to the SQLite database."

    def build(self):
        app = self.app
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(1, weight=1)

        filters = Card(self.body, app, padding=10)
        filters.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        row = filters.inner
        self.from_var = tk.StringVar(value="2000")
        self.to_var = tk.StringVar(value="2025")
        self.month_var = tk.StringVar(value="All months")
        for text, var in (("From year", self.from_var), ("To year", self.to_var)):
            box, _ = labelled(row, text, lambda p, v=var: ttk.Spinbox(p, from_=1901, to=2100, textvariable=v, width=8), app)
            box.pack(side="left", padx=(0, 12))
        box, _ = labelled(row, "Month", lambda p: ttk.Combobox(p, textvariable=self.month_var, state="readonly",
                                                                values=["All months"] + MONTHS, width=13), app)
        box.pack(side="left", padx=(0, 12))
        ttk.Button(row, text="Apply filter", style="Accent.TButton", command=self.refresh).pack(side="left", pady=(14, 0))
        self.count_label = tk.Label(row, text="", bg=theme.SURFACE, fg=theme.INK_SECONDARY, font=app.fonts["body"])
        self.count_label.pack(side="right", pady=(14, 0))

        table_card = Card(self.body, app, padding=8)
        table_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        frame, self.tree = make_tree(table_card.inner, ("Year", "Month", "Max C", "Min C", "Mean C", "Departure", "Level"),
                                     (56, 96, 72, 72, 72, 80, 92), height=16)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        side = tk.Frame(self.body, bg=theme.PAGE, width=300)
        side.grid(row=1, column=1, sticky="ns")
        form = Card(side, app, "Add or edit a reading")
        form.pack(fill="x")
        self.form_vars = {name: tk.StringVar() for name in ("Year", "Max C", "Min C", "Mean C")}
        self.form_month = tk.StringVar(value="January")
        grid = tk.Frame(form.inner, bg=theme.SURFACE)
        grid.pack(fill="x")
        entries = [("Year", lambda p: ttk.Entry(p, textvariable=self.form_vars["Year"], width=10)),
                   ("Month", lambda p: ttk.Combobox(p, textvariable=self.form_month, values=MONTHS,
                                                    state="readonly", width=11)),
                   ("Max C", lambda p: ttk.Entry(p, textvariable=self.form_vars["Max C"], width=10)),
                   ("Min C", lambda p: ttk.Entry(p, textvariable=self.form_vars["Min C"], width=10)),
                   ("Mean C", lambda p: ttk.Entry(p, textvariable=self.form_vars["Mean C"], width=10))]
        for i, (text, factory) in enumerate(entries):
            box, _ = labelled(grid, text, factory, app)
            box.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 10), pady=(0, 8))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        buttons = tk.Frame(form.inner, bg=theme.SURFACE)
        buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(buttons, text="Add", width=7, style="Accent.TButton", command=self.add).pack(side="left")
        ttk.Button(buttons, text="Update", width=7, command=self.update).pack(side="left", padx=6)
        ttk.Button(buttons, text="Delete", width=7, command=self.delete).pack(side="left")
        ttk.Button(buttons, text="Clear", width=6, command=self.clear_form).pack(side="right")

        stats = Card(side, app, "Monthly statistics (lists)")
        stats.pack(fill="both", expand=True, pady=(10, 0))
        self.stats_month = tk.StringVar(value="May")
        picker = ttk.Combobox(stats.inner, textvariable=self.stats_month, values=MONTHS, state="readonly", width=13)
        picker.pack(anchor="w")
        picker.bind("<<ComboboxSelected>>", lambda e: self.show_stats())
        self.stats_label = tk.Label(stats.inner, text="", bg=theme.SURFACE, fg=theme.INK, font=app.fonts["mono"],
                                    justify="left", anchor="w")
        self.stats_label.pack(fill="x", pady=(8, 0))
        self.selected_id = None

    def filtered_records(self):
        year_from = read_int(self.from_var, "From year", 1901, 2100)
        year_to = read_int(self.to_var, "To year", 1901, 2100)
        if year_from > year_to:
            raise ValueError("'From year' must not be after 'To year'.")
        month = None if self.month_var.get() == "All months" else self.month_var.get()
        return self.app.db.fetch_records(year_from, year_to, month)

    def refresh(self):
        try:
            records = self.filtered_records()
        except ValueError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        for r in records:
            level = r.alert_level()
            self.tree.insert("", "end", iid=str(r.record_id), tags=(level,), values=(
                r.period.year, r.period.month, f"{r.temperature.tmax:.4f}", f"{r.temperature.tmin:.4f}",
                f"{r.temperature.tmean:.4f}", f"{r.departure():+.2f}", level))
        self.count_label.config(text=f"{len(records)} of {len(self.app.records)} records shown")
        self.log = ReadingLog(self.app.records)
        self.show_stats()

    def show_stats(self):
        count, high, low, avg = self.log.stats(self.stats_month.get())
        if count == 0:
            self.stats_label.config(text="No readings for this month.")
            return
        self.stats_label.config(text=f"Readings : {count}\nHighest  : {high:.2f} C\n"
                                     f"Lowest   : {low:.2f} C\nAverage  : {avg:.2f} C")

    def on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        self.selected_id = int(selection[0])
        values = self.tree.item(selection[0], "values")
        self.form_vars["Year"].set(values[0])
        self.form_month.set(values[1])
        self.form_vars["Max C"].set(values[2])
        self.form_vars["Min C"].set(values[3])
        self.form_vars["Mean C"].set(values[4])

    def read_form(self):
        year = parse_year(self.form_vars["Year"].get())
        tmax = parse_temperature(self.form_vars["Max C"].get(), "Max")
        tmin = parse_temperature(self.form_vars["Min C"].get(), "Min")
        tmean = parse_temperature(self.form_vars["Mean C"].get(), "Mean")
        if tmin > tmax:
            raise ValueError("Min temperature cannot be higher than max temperature.")
        if not (tmin <= tmean <= tmax):
            raise ValueError("Mean temperature must lie between min and max.")
        return year, self.form_month.get(), tmax, tmin, tmean

    def add(self):
        try:
            year, month, tmax, tmin, tmean = self.read_form()
            self.app.db.add_record(year, month, tmax, tmin, tmean)
        except (ValueError, DatabaseError) as error:
            messagebox.showerror(APP_NAME, str(error), parent=self)
            return
        self.log.add(month, tmax)
        self.app.data_changed(f"Added {month} {year}")

    def update(self):
        if self.selected_id is None:
            messagebox.showinfo(APP_NAME, "Select a row in the table first.", parent=self)
            return
        try:
            _, _, tmax, tmin, tmean = self.read_form()
            self.app.db.update_record(self.selected_id, tmax, tmin, tmean)
        except (ValueError, DatabaseError) as error:
            messagebox.showerror(APP_NAME, str(error), parent=self)
            return
        self.app.data_changed("Record updated")

    def delete(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(APP_NAME, "Select a row in the table first.", parent=self)
            return
        values = self.tree.item(selection[0], "values")
        if not messagebox.askyesno(APP_NAME, f"Delete {values[1]} {values[0]}?", parent=self):
            return
        self.app.db.delete_record(int(selection[0]))
        self.log.remove(values[1], float(values[2]))
        self.selected_id = None
        self.app.data_changed(f"Deleted {values[1]} {values[0]}")

    def clear_form(self):
        for var in self.form_vars.values():
            var.set("")
        self.selected_id = None
        self.tree.selection_remove(*self.tree.selection())


# ======================================================================
# 4. Advisories  (Experiment 3)
# ======================================================================

class AdvisoryScreen(Screen):
    title = "Advisories"
    subtitle = "Build a heat bulletin from a monthly record, a city's daily grid reading, or a messy raw feed line"

    EXAMPLES = ["  aug 2023 | 31.87C | normal 31.01 C  ",
                "MARCH   2022|33.63 deg C|normal 31.70",
                " june 1926 , 36.64c , normal 34.6 "]

    def build(self):
        app = self.app
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)
        left = tk.Frame(self.body, bg=theme.PAGE, width=360)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        db_card = Card(left, app, "From the database")
        db_card.pack(fill="x")
        self.source_var = tk.StringVar(value="daily" if app.heat_grid.available() else "monthly")
        sources = tk.Frame(db_card.inner, bg=theme.SURFACE)
        sources.pack(fill="x", pady=(0, 6))
        ttk.Radiobutton(sources, text="Monthly record", value="monthly", variable=self.source_var,
                        style="Card.TRadiobutton", command=self.toggle_source).pack(side="left", padx=(0, 10))
        self.daily_radio = ttk.Radiobutton(sources, text="Daily grid (one city)", value="daily", variable=self.source_var,
                                           style="Card.TRadiobutton", command=self.toggle_source)
        self.daily_radio.pack(side="left")
        if not app.heat_grid.available():
            self.daily_radio.state(["disabled"])
        row = tk.Frame(db_card.inner, bg=theme.SURFACE)
        row.pack(fill="x")
        self.year_var = tk.StringVar(value="2024")
        self.month_var = tk.StringVar(value="May")
        self.day_var = tk.StringVar(value="28")
        self.city_var = tk.StringVar(value="Delhi")
        box, _ = labelled(row, "Year", lambda p: ttk.Spinbox(p, from_=1901, to=2100, textvariable=self.year_var, width=6), app)
        box.pack(side="left", padx=(0, 8))
        box, _ = labelled(row, "Month", lambda p: ttk.Combobox(p, textvariable=self.month_var, values=MONTHS,
                                                                state="readonly", width=10), app)
        box.pack(side="left", padx=(0, 8))
        box, self.day_box = labelled(row, "Day", lambda p: ttk.Spinbox(p, from_=1, to=31, textvariable=self.day_var,
                                                                        width=4), app)
        box.pack(side="left")
        city_row = tk.Frame(db_card.inner, bg=theme.SURFACE)
        city_row.pack(fill="x", pady=(6, 0))
        box, self.city_box = labelled(city_row, "City (nearest grid cell)", lambda p: ttk.Combobox(
            p, textvariable=self.city_var, values=list(CITIES), state="readonly", width=24), app)
        box.pack(side="left")
        ttk.Button(db_card.inner, text="Generate bulletin", style="Accent.TButton",
                   command=self.from_database).pack(anchor="w", pady=(10, 0))
        self.toggle_source()

        raw_card = Card(left, app, "From a raw feed line")
        raw_card.pack(fill="x", pady=(10, 0))
        tk.Label(raw_card.inner, text="Format:  month year | max temp | normal", bg=theme.SURFACE,
                 fg=theme.INK_SECONDARY, font=app.fonts["small"], anchor="w").pack(fill="x")
        self.raw_var = tk.StringVar(value=self.EXAMPLES[0])
        ttk.Entry(raw_card.inner, textvariable=self.raw_var, font=app.fonts["mono"]).pack(fill="x", pady=(4, 6))
        examples = tk.Frame(raw_card.inner, bg=theme.SURFACE)
        examples.pack(fill="x")
        tk.Label(examples, text="Try:", bg=theme.SURFACE, fg=theme.INK_MUTED, font=app.fonts["small"]).pack(side="left")
        for i in range(len(self.EXAMPLES)):
            ttk.Button(examples, text=f"Example {i + 1}", style="Small.TButton",
                       command=lambda i=i: self.raw_var.set(self.EXAMPLES[i])).pack(side="left", padx=(4, 0))
        ttk.Button(raw_card.inner, text="Clean and generate", style="Accent.TButton",
                   command=self.from_raw).pack(anchor="w", pady=(10, 0))

        clean_card = Card(left, app, "What the string methods extracted")
        clean_card.pack(fill="both", expand=True, pady=(10, 0))
        self.clean_label = tk.Label(clean_card.inner, text="", bg=theme.SURFACE, fg=theme.INK, font=app.fonts["mono"],
                                    justify="left", anchor="nw")
        self.clean_label.pack(fill="both", expand=True)

        right = Card(self.body, app)
        right.grid(row=0, column=1, sticky="nsew")
        top = tk.Frame(right.inner, bg=theme.SURFACE)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="Bulletin", bg=theme.SURFACE, fg=theme.INK, font=app.fonts["h2"]).pack(side="left")
        self.badge = LevelBadge(top, app)
        self.badge.pack(side="left", padx=10)
        ttk.Button(top, text="Save as .txt", command=self.save).pack(side="right")
        self.text = tk.Text(right.inner, font=app.fonts["mono"], bg=theme.SURFACE, fg=theme.INK, relief="flat",
                            wrap="none", padx=6, pady=6)
        self.text.pack(fill="both", expand=True)

    def refresh(self):
        if not self.text.get("1.0", "end").strip():
            self.from_database()

    def toggle_source(self):
        state = ["!disabled"] if self.source_var.get() == "daily" else ["disabled"]
        self.day_box.state(state)
        self.city_box.state(state + (["readonly"] if state == ["!disabled"] else []))

    def show(self, advisory, source):
        self.badge.set(advisory.get_level())
        self.text.delete("1.0", "end")
        self.text.insert("1.0", advisory.build_bulletin())
        departure = advisory.get_departure()
        normal = "-" if advisory.normal is None else advisory.normal
        self.clean_label.config(text=f"Source    : {source}\nPeriod    : {advisory.get_period()}\n"
                                     f"Max temp  : {advisory.max_temp}\nNormal    : {normal}\n"
                                     f"Departure : {'-' if departure is None else format(departure, '+.4f')}\n"
                                     f"Class     : {type(advisory).__name__}")

    def from_database(self):
        try:
            year = read_int(self.year_var, "Year", 1901, 2100)
        except ValueError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self)
            return
        if self.source_var.get() == "daily":
            self.from_grid(year)
            return
        rows = self.app.db.fetch_records(year, year, self.month_var.get())
        if not rows:
            messagebox.showinfo(APP_NAME, f"No record for {self.month_var.get()} {year}.", parent=self)
            return
        r = rows[0]
        advisory = HeatwaveAdvisory(f"{r.period.month} {r.period.year}", str(r.temperature.tmax), str(r.normal.norm_max))
        self.show(advisory, "database (monthly)")

    def from_grid(self, year):
        grid = self.app.heat_grid
        if year not in grid.years:
            messagebox.showinfo(APP_NAME, f"Daily grid data covers {grid.years[0]}-{grid.years[-1]} only.", parent=self)
            return
        try:
            day = read_int(self.day_var, "Day", 1, 31)
            date = datetime.date(year, MONTHS.index(self.month_var.get()) + 1, day)
        except ValueError as error:
            messagebox.showwarning(APP_NAME, f"Not a real date: {error}", parent=self)
            return
        lat, lon = CITIES[self.city_var.get()]
        index = cell_index(lat, lon)
        value, normal, departure, level = grid.cell_reading(year, (date - datetime.date(year, 1, 1)).days, index)
        if value is None:
            messagebox.showinfo(APP_NAME, "The grid has no reading for that cell on that day.", parent=self)
            return
        advisory = DailyHeatAdvisory(f"{self.month_var.get()} {year}", day, self.city_var.get(), lat, lon,
                                     str(value), normal, LEVEL_NAMES[level])
        self.show(advisory, "daily grid")

    def from_raw(self):
        try:
            period, temperature, normal = split_raw_feed(self.raw_var.get())
            advisory = HeatwaveAdvisory(period, temperature, normal)
        except ValueError as error:
            messagebox.showerror(APP_NAME, f"Could not read that line:\n{error}", parent=self)
            return
        self.show(advisory, "raw feed")

    def save(self):
        content = self.text.get("1.0", "end").strip()
        if not content:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile="heat_advisory.txt",
                                            filetypes=[("Text file", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            self.app.set_status(f"Saved {os.path.basename(path)}")


# ======================================================================
# 5. Reports  (Experiment 4)
# ======================================================================

class ReportsScreen(Screen):
    title = "Reports"
    subtitle = "Pick report types. Each is a different class (one even uses another dataset), but all run with the same call: report.generate()"

    def build(self):
        app = self.app
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)
        left = Card(self.body, app, "Choose reports")
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        self.year_var = tk.StringVar(value="2024")
        self.top_var = tk.StringVar(value="10")
        self.last_var = tk.StringVar(value="10")
        self.since_var = tk.StringVar(value="1990")
        grid_years = app.heat_grid.years or [2024]
        self.grid_year_var = tk.StringVar(value="2024" if 2024 in grid_years else str(grid_years[-1]))
        self.choices = []
        options = [
            ("Year summary", "Year", self.year_var, 1901, 2100),
            ("Warmest months ranking", "How many", self.top_var, 3, 50),
            ("Heat season (Mar-Jun)", "Last N years", self.last_var, 3, 60),
            ("Annual departure bars", "Since year", self.since_var, 1901, 2100),
            ("Decade averages and trend", None, None, 0, 0),
            ("Daily heatwave log (grid)", "Year", self.grid_year_var, grid_years[0], grid_years[-1]),
        ]
        for name, param, var, low, high in options:
            checked = tk.BooleanVar(value=name in ("Year summary", "Heat season (Mar-Jun)", "Decade averages and trend"))
            row = tk.Frame(left.inner, bg=theme.SURFACE)
            row.pack(fill="x", pady=4)
            ttk.Checkbutton(row, text=name, variable=checked, style="Card.TCheckbutton").pack(anchor="w")
            if param:
                sub = tk.Frame(row, bg=theme.SURFACE)
                sub.pack(fill="x", padx=(24, 0))
                tk.Label(sub, text=param, bg=theme.SURFACE, fg=theme.INK_SECONDARY, font=app.fonts["small"]).pack(side="left")
                ttk.Spinbox(sub, from_=low, to=high, textvariable=var, width=7).pack(side="left", padx=6)
            self.choices.append((name, checked))
        ttk.Button(left.inner, text="Generate", style="Accent.TButton", command=self.generate).pack(anchor="w", pady=(12, 4))
        ttk.Button(left.inner, text="Save as .txt", command=self.save).pack(anchor="w")
        tk.Label(left.inner, text="for report in selected:\n    text += report.generate()", bg="#f4f3ef", fg=theme.INK,
                 font=app.fonts["mono"], justify="left", anchor="w", padx=8, pady=6).pack(fill="x", pady=(16, 0))

        right = Card(self.body, app, padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        self.text = tk.Text(right.inner, font=app.fonts["mono"], bg=theme.SURFACE, fg=theme.INK, relief="flat",
                            wrap="none", padx=8, pady=6)
        scroll = ttk.Scrollbar(right.inner, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def refresh(self):
        self.generate()

    def build_reports(self):
        records = self.app.records
        selected = {name for name, checked in self.choices if checked.get()}
        reports = []
        if "Year summary" in selected:
            reports.append(YearSummaryReport(records, read_int(self.year_var, "Year", 1901, 2100)))
        if "Warmest months ranking" in selected:
            reports.append(HottestMonthsReport(records, read_int(self.top_var, "How many", 3, 50)))
        if "Heat season (Mar-Jun)" in selected:
            reports.append(HeatSeasonReport(records, read_int(self.last_var, "Last N years", 3, 60)))
        if "Annual departure bars" in selected:
            reports.append(AnomalyReport(records, read_int(self.since_var, "Since year", 1901, 2100)))
        if "Decade averages and trend" in selected:
            reports.append(DecadeTrendReport(records))
        if "Daily heatwave log (grid)" in selected:
            reports.append(DailyHeatwaveReport(self.app.heat_grid, read_int(self.grid_year_var, "Grid year", 1901, 2100)))
        return reports

    def generate(self):
        try:
            reports = self.build_reports()
        except ValueError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self)
            return
        self.text.delete("1.0", "end")
        if not reports:
            self.text.insert("1.0", "Tick at least one report on the left.")
            return
        text = ""
        for report in reports:
            text += report.generate() + "\n\n"
        self.text.insert("1.0", text)
        self.app.set_status(f"Generated {len(reports)} report(s)")

    def save(self):
        content = self.text.get("1.0", "end").strip()
        if not content:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile="climate_reports.txt",
                                            filetypes=[("Text file", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            self.app.set_status(f"Saved {os.path.basename(path)}")


# ======================================================================
# 6. Live Monitor  (Experiment 5)
# ======================================================================

class MonitorScreen(Screen):
    title = "Live Monitor"
    subtitle = "Three threads stream real daily readings for three cities at the same time. Bad readings raise exceptions that are caught and logged."

    PERIODS = {"Heat season (Mar-Jun)": (3, 6), "Peak (Apr-May)": (4, 5), "Whole year": (1, 12)}
    COLOURS = (theme.SERIES_1, theme.SERIES_2, theme.SERIES_3)

    def build(self):
        app = self.app
        self.heat_grid = app.heat_grid
        self.monitor = None
        if not self.heat_grid.available():
            card = Card(self.body, app, "Daily grid files not found")
            card.pack(fill="x")
            wrapping_label(card.inner, app, "Put the IMD files named Maxtemp_MaxT_YYYY.GRD in data/grid/ "
                                            "and restart the app.").pack(fill="x")
            return
        controls = Card(self.body, app, padding=10)
        controls.pack(fill="x")
        top = tk.Frame(controls.inner, bg=theme.SURFACE)
        top.pack(fill="x")
        self.city_vars = []
        for i, default in enumerate(("Delhi", "Phalodi (Rajasthan)", "Patna")):
            var = tk.StringVar(value=default)
            box, _ = labelled(top, f"Thread {i + 1} - city", lambda p, v=var: ttk.Combobox(
                p, textvariable=v, values=list(CITIES), state="readonly", width=19), app)
            box.pack(side="left", padx=(0, 12))
            self.city_vars.append(var)
        self.year_var = tk.StringVar(value="2024" if 2024 in self.heat_grid.years else str(self.heat_grid.years[-1]))
        box, _ = labelled(top, "Year", lambda p: ttk.Combobox(p, textvariable=self.year_var, state="readonly",
                                                               values=[str(y) for y in self.heat_grid.years], width=6), app)
        box.pack(side="left", padx=(0, 12))
        self.period_var = tk.StringVar(value="Heat season (Mar-Jun)")
        box, _ = labelled(top, "Period", lambda p: ttk.Combobox(p, textvariable=self.period_var, state="readonly",
                                                                 values=list(self.PERIODS), width=19), app)
        box.pack(side="left")

        bottom = tk.Frame(controls.inner, bg=theme.SURFACE)
        bottom.pack(fill="x", pady=(8, 0))
        self.speed_var = tk.DoubleVar(value=0.08)
        self.faults_var = tk.BooleanVar(value=True)
        tk.Label(bottom, text="Delay per reading", bg=theme.SURFACE, fg=theme.INK_SECONDARY,
                 font=app.fonts["small"]).pack(side="left")
        ttk.Scale(bottom, from_=0.01, to=0.4, variable=self.speed_var, length=140).pack(side="left", padx=(6, 14))
        ttk.Checkbutton(bottom, text="Simulate sensor faults", variable=self.faults_var,
                        style="Card.TCheckbutton").pack(side="left", padx=(0, 14))
        self.start_button = ttk.Button(bottom, text="Start", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(bottom, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.status = tk.Label(bottom, text="Idle", bg=theme.SURFACE, fg=theme.INK_SECONDARY, font=app.fonts["body"])
        self.status.pack(side="right")

        tiles = tk.Frame(self.body, bg=theme.PAGE)
        tiles.pack(fill="x", pady=10)
        self.tiles = []
        self.badges = []
        for i in range(3):
            tile = StatTile(tiles, app, f"Thread {i + 1}")
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            tiles.columnconfigure(i, weight=1, uniform="monitor")
            badge = LevelBadge(tile.winfo_children()[0], app)
            badge.pack(anchor="w", pady=(4, 0))
            self.tiles.append(tile)
            self.badges.append(badge)

        lower = tk.Frame(self.body, bg=theme.PAGE)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=3, uniform="monitor_lower")
        lower.columnconfigure(1, weight=2, uniform="monitor_lower")
        lower.rowconfigure(0, weight=1)
        chart_card = Card(lower, app, "Daily maximum temperature as it arrives (gaps = caught faults)")
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        canvas = tk.Canvas(chart_card.inner, bg=theme.SURFACE, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.chart = LineChart(canvas, app.fonts, y_label="max temp, deg C", value_format="{:.1f}")
        log_card = Card(lower, app, "Event log", padding=8)
        log_card.grid(row=0, column=1, sticky="nsew")
        frame, self.log = make_tree(log_card.inner, ("Thread", "Date", "Result"), (96, 56, 200), height=10)
        frame.pack(fill="both", expand=True)

    def build_channels(self):
        year = int(self.year_var.get())
        first_month, last_month = self.PERIODS[self.period_var.get()]
        grid_year = self.heat_grid.year(year)
        days = [d for d in range(grid_year.days) if first_month <= date_of(year, d).month <= last_month]
        cities = [var.get() for var in self.city_vars]
        if len(set(cities)) < 3:
            raise ValueError("Pick three different cities, one per thread.")
        channels = []
        for city in cities:
            index = cell_index(*CITIES[city])
            readings = []
            for d in days:
                value, normal, departure, level = self.heat_grid.cell_reading(year, d, index)
                readings.append((date_of(year, d).strftime("%d %b"), value, normal, LEVEL_NAMES[level]))
            channels.append(Channel(city.split(" (")[0], readings))
        return channels, [date_of(year, d).strftime("%d %b") for d in days]

    def start(self):
        try:
            channels, labels = self.build_channels()
        except (ValueError, GridError) as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self)
            return
        self.names = [c.name for c in channels]
        self.labels = labels
        self.index = {label: i for i, label in enumerate(labels)}
        self.values = {name: [None] * len(labels) for name in self.names}
        self.counts = {name: [0, 0, 0] for name in self.names}       # ok, faults, heatwave days
        self.finished = set()
        for tile, badge, name in zip(self.tiles, self.badges, self.names):
            tile.set_caption(f"{name} thread")
            tile.set("-", "waiting for data")
            badge.config(text="", bg=theme.SURFACE)
        self.log.delete(*self.log.get_children())
        self.redraw_chart()
        self.monitor = StreamMonitor(channels, delay=self.speed_var.get(), simulate_faults=self.faults_var.get())
        self.monitor.start()
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status.config(text=f"Running - {len(labels)} days x 3 threads")
        self.after(100, self.poll)

    def stop(self):
        if self.monitor:
            self.monitor.stop()
            self.status.config(text="Stopping...")

    def poll(self):
        """Runs on the main thread every 100 ms: empties the queue and updates the screen."""
        if not self.monitor:
            return
        self.monitor.delay = self.speed_var.get()
        handled = 0
        while handled < 300:
            try:
                event = self.monitor.events.get_nowait()
            except queue.Empty:
                break
            handled += 1
            self.handle(event)
        if handled:
            self.redraw_chart()
        if len(self.finished) == 3 or (not self.monitor.is_running() and self.monitor.events.empty()):
            faults = sum(c[1] for c in self.counts.values())
            heat = sum(c[2] for c in self.counts.values())
            stopped = self.monitor.stop_event.is_set()
            self.status.config(text=f"{'Stopped' if stopped else 'Finished'} - {heat} heatwave day(s), "
                                    f"{faults} fault(s) caught, no thread crashed")
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")
            self.monitor = None
            return
        self.after(100, self.poll)

    def handle(self, event):
        kind, name = event[0], event[1]
        slot = self.names.index(name)
        if kind == "reading":
            _, _, label, value, departure, level = event
            self.values[name][self.index[label]] = value
            self.counts[name][0] += 1
            if level != "NO HEATWAVE":
                self.counts[name][2] += 1
            dep = "" if departure is None else f"  ({departure:+.1f} vs normal)"
            ok, faults, heat = self.counts[name]
            self.tiles[slot].set(f"{value:.1f} C", f"{label}{dep}\nok {ok}   faults {faults}   heatwave days {heat}")
            self.badges[slot].set(level)
            text = f"{value:.1f} C" + (f"  {level}" if level != "NO HEATWAVE" else "")
            self.add_log(name, label, text, (level,) if level != "NO HEATWAVE" else ())
        elif kind == "fault":
            _, _, label, error_name, message = event
            self.counts[name][1] += 1
            self.add_log(name, label, f"{error_name} caught", ("fault",))
        elif kind == "done":
            self.finished.add(name)

    def add_log(self, name, label, text, tags):
        self.log.insert("", 0, values=(name, label, text), tags=tags)
        children = self.log.get_children()
        if len(children) > 400:
            self.log.delete(*children[400:])

    def redraw_chart(self):
        self.chart.set_data(self.labels, [
            {"name": name, "values": self.values[name], "colour": colour, "width": 2}
            for name, colour in zip(self.names, self.COLOURS)], reference=(45.0, "45 C heatwave line"))

    def on_close(self):
        if self.monitor:
            self.monitor.stop()
            self.monitor.join(1.0)


# ======================================================================
# 7. Analytics  (Experiment 6)
# ======================================================================

class AnalyticsScreen(Screen):
    title = "Analytics"
    subtitle = "A functional pipeline: lambda, map(), filter() and reduce() over the selected readings"

    def build(self):
        app = self.app
        controls = Card(self.body, app, padding=10)
        controls.pack(fill="x")
        row = controls.inner
        self.from_var = tk.StringVar(value="1991")
        self.to_var = tk.StringVar(value="2025")
        self.season_var = tk.StringVar(value="Pre-monsoon (Mar-May)")
        self.unit_var = tk.StringVar(value="C")
        self.threshold_var = tk.StringVar(value="1.0")
        for text, var in (("From year", self.from_var), ("To year", self.to_var)):
            box, _ = labelled(row, text, lambda p, v=var: ttk.Spinbox(p, from_=1901, to=2100, textvariable=v, width=8), app)
            box.pack(side="left", padx=(0, 12))
        box, _ = labelled(row, "Season", lambda p: ttk.Combobox(p, textvariable=self.season_var, values=list(SEASONS),
                                                                 state="readonly", width=22), app)
        box.pack(side="left", padx=(0, 12))
        box, _ = labelled(row, "Flag if departure >= (C)", lambda p: ttk.Spinbox(
            p, from_=0.0, to=3.0, increment=0.1, textvariable=self.threshold_var, width=6), app)
        box.pack(side="left", padx=(0, 12))
        units = tk.Frame(row, bg=theme.SURFACE)
        units.pack(side="left", padx=(0, 12), pady=(14, 0))
        for text, value in (("Celsius", "C"), ("Fahrenheit", "F")):
            ttk.Radiobutton(units, text=text, value=value, variable=self.unit_var, style="Card.TRadiobutton").pack(side="left")
        ttk.Button(row, text="Run", style="Accent.TButton", command=self.refresh).pack(side="left", pady=(14, 0))

        tiles = tk.Frame(self.body, bg=theme.PAGE)
        tiles.pack(fill="x", pady=10)
        self.tiles = {}
        for i, key in enumerate(("Readings", "Average max", "Highest max", "Lowest max", "Above normal", "Flagged")):
            tile = StatTile(tiles, app, key)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            tiles.columnconfigure(i, weight=1)
            self.tiles[key] = tile

        lower = tk.Frame(self.body, bg=theme.PAGE)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=4, uniform="analytics")
        lower.columnconfigure(1, weight=4, uniform="analytics")
        lower.columnconfigure(2, weight=3, uniform="analytics")
        lower.rowconfigure(0, weight=1)
        bar_card = Card(lower, app, "Months at each alert level")
        bar_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        canvas = tk.Canvas(bar_card.inner, bg=theme.SURFACE, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.bars = BarChart(canvas, app.fonts)

        pipe_card = Card(lower, app, "Pipeline steps")
        pipe_card.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.pipeline = tk.Label(pipe_card.inner, text="", bg=theme.SURFACE, fg=theme.INK, font=app.fonts["mono_small"],
                                 justify="left", anchor="nw")
        self.pipeline.pack(fill="both", expand=True)

        flagged_card = Card(lower, app, "Flagged months", padding=8)
        flagged_card.grid(row=0, column=2, sticky="nsew")
        frame, self.flagged = make_tree(flagged_card.inner, ("Period", "Departure", "Level"), (84, 80, 86), height=8)
        frame.pack(fill="both", expand=True)

    def refresh(self):
        try:
            year_from = read_int(self.from_var, "From year", 1901, 2100)
            year_to = read_int(self.to_var, "To year", 1901, 2100)
            threshold = float(self.threshold_var.get())
        except ValueError as error:
            messagebox.showwarning(APP_NAME, str(error) if "year" in str(error).lower()
                                   else "Threshold must be a number.", parent=self)
            return
        months = SEASONS[self.season_var.get()]
        records = list(filter(lambda r: year_from <= r.period.year <= year_to and r.period.month in months,
                              self.app.records))
        result = analyse(records, threshold, self.unit_var.get())
        if result is None:
            messagebox.showinfo(APP_NAME, "No readings match those filters.", parent=self)
            return
        u = result["unit"]
        self.tiles["Readings"].set(str(result["count"]), f"{self.season_var.get()}")
        self.tiles["Average max"].set(f"{result['average']:.2f} {u}", "reduce() total / count")
        self.tiles["Highest max"].set(f"{result['highest']:.2f} {u}", "reduce() keeps the larger")
        self.tiles["Lowest max"].set(f"{result['lowest']:.2f} {u}", "reduce() keeps the smaller")
        self.tiles["Above normal"].set(str(result["above_normal_count"]), "filter(departure > 0)")
        self.tiles["Flagged"].set(str(len(result["flagged"])), f"departure >= {threshold:.1f} C")

        counts = result["level_counts"]
        self.bars.set_data(ALERT_ORDER, [counts[level] for level in ALERT_ORDER],
                           [theme.LEVEL_COLOURS[level] for level in ALERT_ORDER])

        hottest_label, hottest_dep = result["hottest"]
        observed = ", ".join(level for level in ALERT_ORDER if level in result["observed_levels"])
        conversion = "map(to_fahrenheit, ...)" if u == "F" else "(Celsius, no conversion)"
        self.pipeline.config(text=(
            f"station   = {STATION_INFO[0]}  (tuple)\n\n"
            f"readings  = list of {result['count']} max temps\n"
            f"converted = {conversion}\n"
            f"            -> {result['count']} values in {u}\n\n"
            f"filter(departure >= {threshold:.1f})\n"
            f"            -> {len(result['flagged'])} flagged\n"
            f"filter(departure > 0)\n"
            f"            -> {result['above_normal_count']} above normal\n\n"
            f"reduce(a + b)        = {result['total']:.2f}\n"
            f"reduce(max-of-two)   = {result['highest']:.2f}\n"
            f"reduce(warmest dep.) = {hottest_label} ({hottest_dep:+.2f} C)\n\n"
            f"set(levels seen)     =\n    {{{observed}}}\n"
            f"dict counts          = {len(counts)} keys"))

        self.flagged.delete(*self.flagged.get_children())
        for r in sorted(result["flagged"], key=lambda r: r.departure(), reverse=True):
            level = r.alert_level()
            self.flagged.insert("", "end", tags=(level,), values=(r.period.label(), f"{r.departure():+.2f} C", level))


# ======================================================================
# 8. Database Console  (Experiment 8)
# ======================================================================

class DatabaseScreen(Screen):
    title = "Database Console"
    subtitle = "Run SQL on the SQLite database. Pick a ready-made query or write your own (Ctrl+Enter to run)."

    def build(self):
        app = self.app
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)
        left = Card(self.body, app, "Ready-made queries", padding=8)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.presets = tk.Listbox(left.inner, font=app.fonts["body"], activestyle="none", width=40,
                                  bg=theme.SURFACE, fg=theme.INK, selectbackground="#fde3d3", selectforeground=theme.INK,
                                  highlightthickness=0, bd=0)
        for title, _ in PRESET_QUERIES:
            self.presets.insert("end", title)
        self.presets.pack(fill="both", expand=True)
        self.presets.bind("<<ListboxSelect>>", self.load_preset)
        self.presets.bind("<Double-Button-1>", lambda e: self.run())
        ttk.Button(left.inner, text="Reset database to original IMD data", command=self.reset).pack(fill="x", pady=(8, 0))
        self.table_info = tk.Label(left.inner, text="", bg=theme.SURFACE, fg=theme.INK_SECONDARY,
                                   font=app.fonts["small"], justify="left", anchor="w")
        self.table_info.pack(fill="x", pady=(8, 0))

        right = tk.Frame(self.body, bg=theme.PAGE)
        right.grid(row=0, column=1, sticky="nsew")
        editor = Card(right, app, padding=8)
        editor.pack(fill="x")
        self.sql = tk.Text(editor.inner, height=6, font=app.fonts["mono"], bg=theme.SURFACE, fg=theme.INK,
                           relief="flat", wrap="word", padx=6, pady=4, insertbackground=theme.INK)
        self.sql.pack(fill="x")
        self.sql.bind("<Control-Return>", lambda e: (self.run(), "break")[1])
        bar = tk.Frame(editor.inner, bg=theme.SURFACE)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Run query", style="Accent.TButton", command=self.run).pack(side="left")
        self.result_label = tk.Label(bar, text="", bg=theme.SURFACE, fg=theme.INK_SECONDARY, font=app.fonts["body"])
        self.result_label.pack(side="left", padx=12)

        results = Card(right, app, padding=8)
        results.pack(fill="both", expand=True, pady=(10, 0))
        self.results_frame = results.inner
        self.results_tree = None
        self.presets.selection_set(0)
        self.load_preset()

    def refresh(self):
        db = self.app.db
        counts = []
        for table in ("monthly_normals", "temperature_records", "heatwave_alerts", "grid_daily"):
            _, rows, _ = db.run_query(f"SELECT COUNT(*) FROM {table}")
            counts.append(f"{table}: {rows[0][0]} rows")
        self.table_info.config(text="Tables\n" + "\n".join(counts))
        statement = self.sql.get("1.0", "end").strip()
        if statement and statement.split()[0].upper() in ("SELECT", "WITH"):
            self.run()

    def load_preset(self, event=None):
        selection = self.presets.curselection()
        if not selection:
            return
        self.sql.delete("1.0", "end")
        self.sql.insert("1.0", PRESET_QUERIES[selection[0]][1])

    def run(self):
        statement = self.sql.get("1.0", "end").strip()
        first = statement.split()[0].upper() if statement else ""
        if first in ("INSERT", "UPDATE", "DELETE"):
            if not messagebox.askyesno(APP_NAME, f"This {first} will change the saved data. Continue?", parent=self):
                return
        try:
            columns, rows, message = self.app.db.run_query(statement)
        except DatabaseError as error:
            self.result_label.config(text=str(error), fg="#ad4416")
            return
        self.result_label.config(text=message, fg=theme.INK_SECONDARY)
        if columns:
            self.show_results(columns, rows)
        else:
            self.app.data_changed(message)

    def show_results(self, columns, rows):
        if self.results_tree is not None:
            self.results_tree.master.destroy()
        widths = [max(70, min(220, 9 * max(len(str(c)), 6))) for c in columns]
        frame, tree = make_tree(self.results_frame, columns, widths, height=12)
        for column, width in zip(columns, widths):
            tree.column(column, width=width, anchor="w", stretch=True)
        frame.pack(fill="both", expand=True)
        for row in rows[:2000]:
            tree.insert("", "end", values=[f"{v:.4f}" if isinstance(v, float) else v for v in row])
        self.results_tree = tree

    def reset(self):
        if not messagebox.askyesno(APP_NAME, "Delete every change and reload the original 1,500 IMD records?",
                                   parent=self):
            return
        self.app.db.reset()
        self.app.ensure_grid_table(force=True)
        self.app.data_changed("Database reset to the original IMD data")


# ======================================================================
# 9. About
# ======================================================================

class AboutScreen(Screen):
    title = "About this project"
    subtitle = "Climate Intelligence for Heatwave Monitoring, Prediction and Early Warning"

    def build(self):
        app = self.app
        # uniform= fixes the column proportions, so wrapping text can never resize them
        self.body.columnconfigure(0, weight=2, uniform="about")
        self.body.columnconfigure(1, weight=3, uniform="about")
        self.body.rowconfigure(1, weight=1)

        intro = Card(self.body, app)
        intro.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        logo = tk.Canvas(intro.inner, width=96, height=96, bg=theme.SURFACE, highlightthickness=0)
        logo.pack(side="left", padx=(0, 12), anchor="n")
        draw_logo(logo, 48, 48, 26)
        text = tk.Frame(intro.inner, bg=theme.SURFACE)
        text.pack(side="left", fill="both", expand=True)
        wrapping_label(text, app, APP_NAME, font="h1").pack(fill="x")
        wrapping_label(text, app, "OOPL Python mini project. Every lab experiment becomes one working part "
                                  "of this app.", colour=theme.INK_SECONDARY).pack(fill="x", pady=(4, 0))

        student = Card(self.body, app, "Submitted by")
        student.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(10, 0))
        rows = [(f"Roll {roll}", name) for name, roll in TEAM] + list(PROJECT_INFO.items())
        for key, value in rows:
            row = tk.Frame(student.inner, bg=theme.SURFACE)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=key, width=15, anchor="w", bg=theme.SURFACE, fg=theme.INK_SECONDARY,
                     font=app.fonts["body"]).pack(side="left")
            wrapping_label(row, app, value, font="bold").pack(side="left", fill="x", expand=True)

        source = Card(self.body, app, "Data source")
        source.grid(row=0, column=1, sticky="nsew")
        wrapping_label(source.inner, app, (
                     "India Meteorological Department, Climate Research & Services, Pune - "
                     "All India Time Series of Temperature (1901-2025), based on 1991-2020 normals.\n"
                     "imdpune.gov.in/cmpg/Product/allindia_temp.html\n\n"
                     "1,500 monthly records (125 years x 12 months) of max, min and mean temperature. "
                     "Checked: mean = (max + min) / 2 within 0.001 C in every cell of the three IMD tables.\n\n"
                     "Plus IMD's daily 1-degree gridded maximum temperature (binary .GRD), 2015-2025: "
                     "11 years x 365 days x 961 grid cells, used for the Heatwave Map, Live Monitor and daily bulletins.")
                       ).pack(fill="x")

        mapping = Card(self.body, app, "Where each experiment lives", padding=8)
        mapping.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        frame, tree = make_tree(mapping.inner, ("Exp", "Concept", "In the app", "File"), (40, 180, 222, 96), height=8)
        frame.pack(fill="both", expand=True)
        for row in EXPERIMENT_MAP:
            tree.insert("", "end", values=row)


# ======================================================================
# Main window
# ======================================================================

class App(tk.Tk):
    SCREENS = [
        ("dashboard", "Dashboard", DashboardScreen),
        ("map", "Heatwave Map", HeatwaveMapScreen),
        ("data", "Data Manager", DataManagerScreen),
        ("advisory", "Advisories", AdvisoryScreen),
        ("reports", "Reports", ReportsScreen),
        ("monitor", "Live Monitor", MonitorScreen),
        ("analytics", "Analytics", AnalyticsScreen),
        ("database", "Database", DatabaseScreen),
        ("about", "About", AboutScreen),
    ]

    def __init__(self, base_dir):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1280x780")
        self.minsize(1120, 680)
        self.configure(bg=theme.PAGE)

        data_dir = os.path.join(base_dir, "data")
        self.db = ClimateDatabase(os.path.join(data_dir, "heatalert.db"),
                                  os.path.join(data_dir, "imd_all_india_1901_2025.csv"))
        self.heat_grid = HeatwaveGrid(os.path.join(data_dir, "grid"))
        self.ensure_grid_table()
        self.data_version = 0
        self.records = self.db.fetch_records()

        self.setup_fonts()
        self.setup_style()
        self.build_layout()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show("dashboard")

    def ensure_grid_table(self, force=False):
        """Fill the grid_daily table from the .GRD files if it is empty or out of date."""
        if not self.heat_grid.available():
            return
        expected = sum(366 if calendar.isleap(y) else 365 for y in self.heat_grid.years)
        if not force and self.db.grid_daily_count() == expected:
            return
        rows = []
        for year in self.heat_grid.years:
            for date, reported, heat, severe, hottest, index in self.heat_grid.daily_summary(year):
                lat, lon = cell_position(index) if index is not None else (None, None)
                rows.append((date.isoformat(), year, date.month, reported, heat, severe, hottest, lat, lon))
        self.db.store_grid_daily(rows)

    def setup_fonts(self):
        families = set(tkfont.families(self))
        sans = theme.pick_font_family(families)
        mono = theme.pick_mono_family(families)
        self.fonts = {
            "small": (sans, 9), "body": (sans, 10), "bold": (sans, 10, "bold"), "nav": (sans, 11),
            "h2": (sans, 11, "bold"), "h1": (sans, 17, "bold"), "kpi": (sans, 18, "bold"),
            "mono": (mono, 10), "mono_small": (mono, 9), "brand": (sans, 13, "bold"),
        }
        self.option_add("*Font", self.fonts["body"])

    def setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=self.fonts["body"], background=theme.SURFACE, foreground=theme.INK)
        style.configure("Treeview", background=theme.SURFACE, fieldbackground=theme.SURFACE, rowheight=24,
                        bordercolor=theme.CARD_BORDER, borderwidth=0)
        style.configure("Treeview.Heading", font=self.fonts["bold"], background="#efeee9", foreground=theme.INK,
                        relief="flat", bordercolor=theme.CARD_BORDER)
        style.map("Treeview", background=[("selected", "#fbd0b5")], foreground=[("selected", theme.INK)])
        style.configure("TButton", padding=(12, 5), background="#ffffff", bordercolor=theme.BASELINE,
                        lightcolor="#ffffff", darkcolor="#ffffff")
        style.map("TButton", background=[("active", "#f4f3ef"), ("disabled", "#f4f3ef")])
        style.configure("Small.TButton", padding=(6, 2), font=self.fonts["small"])
        style.configure("Accent.TButton", background=theme.ACCENT, foreground="#ffffff", bordercolor=theme.ACCENT,
                        lightcolor=theme.ACCENT, darkcolor=theme.ACCENT, font=self.fonts["bold"])
        style.map("Accent.TButton", background=[("disabled", "#e6b39a"), ("active", "#c45a24")],
                  foreground=[("disabled", "#ffffff")])
        for name in ("Card.TCheckbutton", "Card.TRadiobutton"):
            style.configure(name, background=theme.SURFACE, foreground=theme.INK)
            style.map(name, background=[("active", theme.SURFACE)])
        style.configure("TEntry", padding=4, fieldbackground="#ffffff")
        style.configure("TSpinbox", padding=3, fieldbackground="#ffffff", arrowsize=12)
        style.configure("TCombobox", padding=3, fieldbackground="#ffffff")
        style.configure("Vertical.TScrollbar", background="#efeee9", troughcolor=theme.SURFACE,
                        bordercolor=theme.SURFACE, arrowcolor=theme.INK_SECONDARY)
        style.configure("Horizontal.TScale", background=theme.SURFACE, troughcolor="#e1e0d9")

    def build_layout(self):
        sidebar = tk.Frame(self, bg=theme.SIDEBAR, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=theme.SIDEBAR)
        brand.pack(fill="x", pady=(18, 22), padx=16)
        logo = tk.Canvas(brand, width=40, height=40, bg=theme.SIDEBAR, highlightthickness=0)
        logo.pack(side="left")
        draw_logo(logo, 20, 20, 11)
        names = tk.Frame(brand, bg=theme.SIDEBAR)
        names.pack(side="left", padx=8)
        tk.Label(names, text="HeatAlert", bg=theme.SIDEBAR, fg="#ffffff", font=self.fonts["brand"], anchor="w").pack(fill="x")
        tk.Label(names, text="Control Room", bg=theme.SIDEBAR, fg=theme.SIDEBAR_TEXT, font=self.fonts["small"],
                 anchor="w").pack(fill="x")

        self.nav_items = {}
        for key, label, _ in self.SCREENS:
            item = tk.Label(sidebar, text=label, bg=theme.SIDEBAR, fg=theme.SIDEBAR_TEXT, font=self.fonts["nav"],
                            anchor="w", padx=22, pady=9, cursor="hand2")
            item.pack(fill="x")
            item.bind("<Button-1>", lambda e, k=key: self.show(k))
            item.bind("<Enter>", lambda e, k=key: self.hover(k, True))
            item.bind("<Leave>", lambda e, k=key: self.hover(k, False))
            self.nav_items[key] = item
        tk.Label(sidebar, text="Data: IMD Pune\n1901-2025", bg=theme.SIDEBAR, fg="#7d8792", font=self.fonts["small"],
                 justify="left", anchor="w").pack(side="bottom", fill="x", padx=22, pady=16)

        main = tk.Frame(self, bg=theme.PAGE)
        main.pack(side="left", fill="both", expand=True)
        self.status_bar = tk.Label(main, text="", bg="#ebe9e3", fg=theme.INK_SECONDARY, font=self.fonts["small"],
                                   anchor="w", padx=12, pady=4)
        self.status_bar.pack(side="bottom", fill="x")
        self.container = tk.Frame(main, bg=theme.PAGE)
        self.container.pack(fill="both", expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.screens = {}
        for key, _, screen_class in self.SCREENS:
            screen = screen_class(self.container, self)
            screen.grid(row=0, column=0, sticky="nsew")
            self.screens[key] = screen
        self.current = None
        self.set_status(f"{len(self.records)} records loaded from {os.path.basename(self.db.db_path)}")

    def hover(self, key, entering):
        if key == self.current:
            return
        self.nav_items[key].config(bg=theme.SIDEBAR_HOVER if entering else theme.SIDEBAR)

    def show(self, key):
        for name, item in self.nav_items.items():
            active = name == key
            item.config(bg=theme.SIDEBAR_ACTIVE if active else theme.SIDEBAR,
                        fg="#ffffff" if active else theme.SIDEBAR_TEXT)
        self.current = key
        screen = self.screens[key]
        screen.tkraise()
        self.update_idletasks()
        screen.on_show()

    def data_changed(self, message):
        """Any screen that changes data calls this so every other screen refreshes when opened."""
        self.records = self.db.fetch_records()
        self.data_version += 1
        self.set_status(f"{message}  |  {len(self.records)} records in the database")
        self.screens[self.current].on_show()

    def set_status(self, text):
        self.status_bar.config(text=text)

    def on_close(self):
        for screen in self.screens.values():
            screen.on_close()
        self.db.close()
        self.destroy()
