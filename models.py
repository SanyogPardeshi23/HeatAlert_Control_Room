"""
models.py  -  Experiment 1: Classes, Objects and Constructors

Every monthly reading is stored as a WeatherRecord object.
A WeatherRecord is COMPOSED of three smaller objects:
    Period       -> when      (year, month)
    Temperature  -> what      (max, min, mean)
    Normal       -> usual     (1991-2020 IMD normal for that month)
"""

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Alert bands for the departure of maximum temperature from its normal (deg C).
# Chosen from the data itself: since 1991 about 19% of months are >= 0.5,
# about 6% are >= 1.0 and about 1% are >= 1.5.
ALERT_BANDS = [
    (1.5, "EXTREME"),
    (1.0, "SEVERE"),
    (0.5, "HIGH"),
    (0.0, "ELEVATED"),
]
LOWEST_LEVEL = "NORMAL"
ALERT_ORDER = ["NORMAL", "ELEVATED", "HIGH", "SEVERE", "EXTREME"]


def classify_departure(departure):
    """Turn a departure in deg C into an alert level word."""
    for limit, level in ALERT_BANDS:
        if departure >= limit:
            return level
    return LOWEST_LEVEL


class Period:
    def __init__(self, year, month):
        self.year = year
        self.month = month

    def month_number(self):
        return MONTHS.index(self.month) + 1

    def label(self):
        return f"{self.month[:3]} {self.year}"


class Temperature:
    def __init__(self, tmax, tmin, tmean):
        self.tmax = tmax
        self.tmin = tmin
        self.tmean = tmean


class Normal:
    def __init__(self, norm_max, norm_min, norm_mean):
        self.norm_max = norm_max
        self.norm_min = norm_min
        self.norm_mean = norm_mean


class WeatherRecord:
    def __init__(self, year, month, tmax, tmin, tmean, norm_max, norm_min, norm_mean, record_id=None):
        self.record_id = record_id
        self.period = Period(year, month)
        self.temperature = Temperature(tmax, tmin, tmean)
        self.normal = Normal(norm_max, norm_min, norm_mean)

    def departure(self):
        return round(self.temperature.tmax - self.normal.norm_max, 4)

    def mean_departure(self):
        return round(self.temperature.tmean - self.normal.norm_mean, 4)

    def alert_level(self):
        return classify_departure(self.departure())

    def __repr__(self):
        return f"WeatherRecord({self.period.label()}, max={self.temperature.tmax})"
