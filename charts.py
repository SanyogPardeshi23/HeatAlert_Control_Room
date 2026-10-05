"""
charts.py  -  Experiment 7: Drawing with the Tkinter Canvas

Every chart in the app is drawn by hand with Canvas methods:
create_line, create_rectangle, create_oval, create_polygon, create_text, create_arc.
Each chart redraws itself when the window is resized and shows a small
read-out box when the mouse moves over it.
"""

import math

import theme


def nice_ticks(low, high, count=5):
    """Round tick values between low and high, e.g. 24.0, 24.5, 25.0 ..."""
    if high <= low:
        high = low + 1
    raw_step = (high - low) / count
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if step >= raw_step:
            break
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 0.001:
        if value >= low - step * 0.001:
            ticks.append(round(value, 6))
        value += step
    return ticks


class Tooltip:
    """A small text box drawn on the canvas itself, so it never leaves the chart."""

    def __init__(self, canvas, font):
        self.canvas = canvas
        self.font = font

    def show(self, x, y, lines):
        self.hide()
        text_id = self.canvas.create_text(0, 0, text="\n".join(lines), anchor="nw",
                                          font=self.font, fill=theme.INK, tags="tooltip")
        x1, y1, x2, y2 = self.canvas.bbox(text_id)
        w, h = x2 - x1 + 16, y2 - y1 + 12
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        left = x + 14 if x + 14 + w < cw else x - 14 - w
        top = max(4, min(y - h // 2, ch - h - 4))
        self.canvas.coords(text_id, left + 8, top + 6)
        box = self.canvas.create_rectangle(left, top, left + w, top + h, fill="#ffffff",
                                           outline=theme.BASELINE, tags="tooltip")
        self.canvas.tag_raise(text_id, box)

    def hide(self):
        self.canvas.delete("tooltip")


class LineChart:
    """
    One or more series against the same x values (usually years).
    series = [{"name": "...", "values": [...], "colour": "#...", "width": 2, "dash": None}, ...]
    A value of None leaves a gap in that line.
    """

    def __init__(self, canvas, fonts, y_label="", value_format="{:.2f}", unit=" C"):
        self.canvas = canvas
        self.fonts = fonts
        self.y_label = y_label
        self.value_format = value_format
        self.unit = unit
        self.xs = []
        self.series = []
        self.reference = None
        self.tooltip = Tooltip(canvas, fonts["small"])
        self.margin = {"left": 56, "right": 18, "top": 34, "bottom": 30}
        canvas.bind("<Configure>", lambda e: self.draw())
        canvas.bind("<Motion>", self.on_motion)
        canvas.bind("<Leave>", lambda e: self.clear_hover())

    def set_data(self, xs, series, reference=None):
        """reference = (value, label) draws a dashed horizontal line, e.g. the normal."""
        self.xs = list(xs)
        self.series = series
        self.reference = reference
        self.draw()

    def plot_area(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        m = self.margin
        return m["left"], m["top"], w - m["right"], h - m["bottom"]

    def y_range(self):
        values = [v for s in self.series for v in s["values"] if v is not None]
        if self.reference:
            values.append(self.reference[0])
        low, high = min(values), max(values)
        pad = (high - low) * 0.08 or 0.5
        return low - pad, high + pad

    def to_px(self, i, value, area, low, high):
        x0, y0, x1, y1 = area
        n = max(1, len(self.xs) - 1)
        px = x0 + (x1 - x0) * i / n
        py = y1 - (y1 - y0) * (value - low) / (high - low)
        return px, py

    def draw(self):
        c = self.canvas
        c.delete("all")
        if c.winfo_width() < 50 or not self.xs or not self.series:
            if self.xs == []:
                c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, text="No data to show",
                              fill=theme.INK_MUTED, font=self.fonts["body"])
            return
        area = self.plot_area()
        x0, y0, x1, y1 = area
        low, high = self.y_range()

        for tick in nice_ticks(low, high, 5):
            _, py = self.to_px(0, tick, area, low, high)
            c.create_line(x0, py, x1, py, fill=theme.GRIDLINE)
            c.create_text(x0 - 8, py, text=f"{tick:g}", anchor="e", fill=theme.INK_MUTED, font=self.fonts["small"])
        c.create_line(x0, y1, x1, y1, fill=theme.BASELINE)
        if self.y_label:
            c.create_text(x0 - 46, y0 - 18, text=self.y_label, anchor="w", fill=theme.INK_SECONDARY,
                          font=self.fonts["small"])

        step = max(1, len(self.xs) // 8)
        for i in range(0, len(self.xs), step):
            px, _ = self.to_px(i, low, area, low, high)
            c.create_line(px, y1, px, y1 + 4, fill=theme.BASELINE)
            c.create_text(px, y1 + 14, text=str(self.xs[i]), fill=theme.INK_MUTED, font=self.fonts["small"])

        if self.reference:
            value, label = self.reference
            _, py = self.to_px(0, value, area, low, high)
            c.create_line(x0, py, x1, py, fill=theme.INK_MUTED, dash=(5, 4))

        for s in self.series:
            segment = []
            for i, value in enumerate(s["values"]):
                if value is None:
                    if len(segment) >= 4:
                        c.create_line(*segment, fill=s["colour"], width=s.get("width", 2), dash=s.get("dash"))
                    segment = []
                    continue
                segment.extend(self.to_px(i, value, area, low, high))
            if len(segment) >= 4:
                c.create_line(*segment, fill=s["colour"], width=s.get("width", 2), dash=s.get("dash"))

        # Legend sits top-right, outside the plot, so it never hides data or the y-axis label.
        items = [(s["name"], s["colour"], None) for s in self.series] if len(self.series) >= 2 else []
        if self.reference:
            items.append((self.reference[1], theme.INK_MUTED, (5, 4)))
        rx = x1
        for name, colour, dash in reversed(items):
            text_id = c.create_text(rx, y0 - 18, text=name, anchor="e", fill=theme.INK_SECONDARY,
                                    font=self.fonts["small"])
            tx1 = c.bbox(text_id)[0]
            c.create_line(tx1 - 24, y0 - 18, tx1 - 6, y0 - 18, fill=colour, width=2 if dash else 3, dash=dash)
            rx = tx1 - 40

    def clear_hover(self):
        self.canvas.delete("hover")
        self.tooltip.hide()

    def on_motion(self, event):
        if not self.xs or not self.series:
            return
        area = self.plot_area()
        x0, y0, x1, y1 = area
        if event.x < x0 or event.x > x1 or event.y < y0 or event.y > y1:
            self.clear_hover()
            return
        n = max(1, len(self.xs) - 1)
        i = round((event.x - x0) / (x1 - x0) * n)
        i = max(0, min(len(self.xs) - 1, i))
        low, high = self.y_range()
        self.canvas.delete("hover")
        px, _ = self.to_px(i, low, area, low, high)
        self.canvas.create_line(px, y0, px, y1, fill=theme.BASELINE, tags="hover")
        lines = [str(self.xs[i])]
        for s in self.series:
            value = s["values"][i] if i < len(s["values"]) else None
            if value is None:
                continue
            _, py = self.to_px(i, value, area, low, high)
            self.canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill=s["colour"], outline=theme.SURFACE,
                                    width=2, tags="hover")
            lines.append(f"{s['name']}: {self.value_format.format(value)}{self.unit}")
        self.tooltip.show(event.x, event.y, lines)


class StripesChart:
    """Warming stripes: one coloured bar per year, blue = cooler than normal, red = warmer."""

    def __init__(self, canvas, fonts, limit=0.8):
        self.canvas = canvas
        self.fonts = fonts
        self.limit = limit
        self.years = []
        self.values = []
        self.tooltip = Tooltip(canvas, fonts["small"])
        canvas.bind("<Configure>", lambda e: self.draw())
        canvas.bind("<Motion>", self.on_motion)
        canvas.bind("<Leave>", lambda e: self.tooltip.hide())

    def set_data(self, year_values):
        self.years = sorted(year_values)
        self.values = [year_values[y] for y in self.years]
        self.draw()

    def draw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or not self.years:
            return
        bar_w = (w - 20) / len(self.years)
        for i, value in enumerate(self.values):
            x = 10 + i * bar_w
            c.create_rectangle(x, 6, x + bar_w + 1, h - 22, fill=theme.diverging_colour(value, self.limit), width=0)
        c.create_text(10, h - 10, text=str(self.years[0]), anchor="w", fill=theme.INK_MUTED, font=self.fonts["small"])
        c.create_text(w - 10, h - 10, text=str(self.years[-1]), anchor="e", fill=theme.INK_MUTED, font=self.fonts["small"])
        c.create_text(w / 2, h - 10, text="blue = cooler than 1991-2020 normal      red = warmer",
                      fill=theme.INK_SECONDARY, font=self.fonts["small"])

    def on_motion(self, event):
        w = self.canvas.winfo_width()
        if not self.years or event.x < 10 or event.x > w - 10:
            self.tooltip.hide()
            return
        i = int((event.x - 10) / ((w - 20) / len(self.years)))
        i = max(0, min(len(self.years) - 1, i))
        self.tooltip.show(event.x, event.y, [str(self.years[i]), f"{self.values[i]:+.3f} C vs normal"])


class BarChart:
    """Vertical bars with a label under each one and the value above it."""

    def __init__(self, canvas, fonts, unit="months"):
        self.canvas = canvas
        self.fonts = fonts
        self.unit = unit
        self.labels = []
        self.values = []
        self.colours = []
        self.tooltip = Tooltip(canvas, fonts["small"])
        canvas.bind("<Configure>", lambda e: self.draw())
        canvas.bind("<Motion>", self.on_motion)
        canvas.bind("<Leave>", lambda e: self.tooltip.hide())

    def set_data(self, labels, values, colours):
        self.labels, self.values, self.colours = list(labels), list(values), list(colours)
        self.draw()

    def geometry(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        slot = (w - 20) / max(1, len(self.values))
        return w, h, slot, h - 26, 22

    def draw(self):
        c = self.canvas
        c.delete("all")
        if c.winfo_width() < 50 or not self.values:
            return
        w, h, slot, base, top = self.geometry()
        highest = max(self.values) or 1
        c.create_line(10, base, w - 10, base, fill=theme.BASELINE)
        for i, value in enumerate(self.values):
            x = 10 + i * slot
            bar_top = base - (base - top) * value / highest
            c.create_rectangle(x + slot * 0.18, bar_top, x + slot * 0.82, base, fill=self.colours[i], width=0)
            c.create_text(x + slot / 2, bar_top - 9, text=str(value), fill=theme.INK, font=self.fonts["small"])
            c.create_text(x + slot / 2, base + 13, text=str(self.labels[i]), fill=theme.INK_SECONDARY,
                          font=self.fonts["small"])

    def on_motion(self, event):
        if not self.values:
            return
        w, h, slot, base, top = self.geometry()
        i = int((event.x - 10) / slot)
        if 0 <= i < len(self.values) and top <= event.y <= base:
            total = sum(self.values) or 1
            self.tooltip.show(event.x, event.y, [str(self.labels[i]), f"{self.values[i]} {self.unit} "
                                                                        f"({self.values[i] / total:.0%} of total)"])
        else:
            self.tooltip.hide()


def draw_logo(canvas, cx, cy, r):
    """The HeatAlert mark from Experiment 7, Activity 2: a sun with a thermometer inside."""
    for i in range(8):
        angle = math.radians(i * 45)
        canvas.create_line(cx + (r + 3) * math.cos(angle), cy + (r + 3) * math.sin(angle),
                           cx + (r + r * 0.45) * math.cos(angle), cy + (r + r * 0.45) * math.sin(angle),
                           fill="#f0955f", width=max(2, r // 6), capstyle="round")
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#f5b041", outline="#d9682f", width=2)
    canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=200, extent=140, fill="#e8913a", outline="")
    tw = max(3, r // 4)
    canvas.create_rectangle(cx - tw, cy - r * 0.62, cx + tw, cy + r * 0.25, fill="#ffffff", outline="#ad4416", width=1)
    canvas.create_oval(cx - tw * 1.9, cy + r * 0.1, cx + tw * 1.9, cy + r * 0.1 + tw * 3.8, fill="#c0392b", outline="#72260a")
    canvas.create_rectangle(cx - tw * 0.45, cy - r * 0.42, cx + tw * 0.45, cy + r * 0.3, fill="#c0392b", outline="")
