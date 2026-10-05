"""
theme.py  -  colours and fonts used across the app, kept in one place.

Alert colours are a single-hue (orange-red) ramp that gets darker as the
level gets worse, checked with a palette validator for step visibility.
NORMAL is a neutral gray because it is not part of the heat scale.
Colour is never the only signal: every level is also written as a word.
"""

SURFACE = "#fcfcfb"
PAGE = "#f4f3ef"
CARD_BORDER = "#e1e0d9"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

SIDEBAR = "#1d2329"
SIDEBAR_HOVER = "#2a323a"
SIDEBAR_ACTIVE = "#d9682f"
SIDEBAR_TEXT = "#c9cfd6"

ACCENT = "#d9682f"
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"

LEVEL_COLOURS = {
    "NORMAL": "#898781",
    "ELEVATED": "#f0955f",
    "HIGH": "#d9682f",
    "SEVERE": "#ad4416",
    "EXTREME": "#72260a",
}

DAILY_COLOURS = {
    "NO HEATWAVE": "#e4e1d9",
    "HEATWAVE": "#d9682f",
    "SEVERE HEATWAVE": "#72260a",
}

SERIES_3 = "#1baf7a"

# Sequential single-hue ramp for the temperature map (light = cooler, dark = hotter).
# Bin edges include IMD's thresholds 40, 45 and 47 C.
TEMP_BINS = [20, 25, 30, 35, 40, 45, 47]
TEMP_RAMP = ["#ffe5d8", "#fac8b1", "#f4a988", "#e98759", "#d8662a", "#b94a00", "#922f0a", "#671e04"]


def temp_colour(value):
    for edge, colour in zip(TEMP_BINS, TEMP_RAMP):
        if value < edge:
            return colour
    return TEMP_RAMP[-1]


DIVERGING_COOL = "#104281"
DIVERGING_MID = "#f0efec"
DIVERGING_WARM = "#8f1d1d"


def _hex_to_rgb(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def blend(colour_a, colour_b, t):
    a, b = _hex_to_rgb(colour_a), _hex_to_rgb(colour_b)
    return _rgb_to_hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def diverging_colour(value, limit=1.0):
    """Blue for below 0, gray at 0, red above 0. Clipped at +/- limit."""
    t = max(-1.0, min(1.0, value / limit))
    if t < 0:
        return blend(DIVERGING_MID, DIVERGING_COOL, -t)
    return blend(DIVERGING_MID, DIVERGING_WARM, t)


def _luminance(colour):
    channels = []
    for c in _hex_to_rgb(colour):
        c = c / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_on(background):
    """Black or white text, whichever reads better on this background."""
    lum = _luminance(background)
    contrast_white = 1.05 / (lum + 0.05)
    contrast_black = (lum + 0.05) / 0.05
    return "#ffffff" if contrast_white >= contrast_black else INK


def _pick(available, wanted, fallback):
    lookup = {name.lower(): name for name in available}
    for family in wanted:
        if family.lower() in lookup:
            return lookup[family.lower()]
    return fallback


def pick_font_family(available):
    return _pick(available, ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Helvetica", "Arial",
                             "Liberation Sans", "DejaVu Sans"), "TkDefaultFont")


def pick_mono_family(available):
    return _pick(available, ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono",
                             "Liberation Mono", "Courier New"), "TkFixedFont")
