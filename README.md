# HeatAlert Control Room

**OOPL (Python) mini project — Climate Intelligence for Heatwave Monitoring, Prediction and Early Warning**

A Tkinter desktop app built on real IMD Pune data: 125 years of monthly All-India temperature,
plus 11 years of daily gridded maximum temperature for every 1-degree cell over India.
Each of the eight lab experiments is one working part of the app.

Submitted by — Information Technology, Division A, Batch A3, K. J. Somaiya School of Engineering, 2026-27:

| Name | Roll No. |
|---|---|
| Sanyog Pardeshi | 16010425081 |
| Harshad Saha | 16010425092 |
| Meher Rabadi | 16010425089 |

---

## Run it

```
python main.py
```

- Needs **Python 3.7 or newer**. Nothing to install: it uses only the standard library (`tkinter`, `sqlite3`, `csv`, `threading`, `abc`, `functools`).
- **Extract the whole folder first.** Running from inside the .zip fails because the app creates its database file in `data/`.
- On Ubuntu/Debian, if Tkinter is missing: `sudo apt install python3-tk`. Windows and macOS installers from python.org include it.
- First launch builds `data/heatalert.db` from the CSV (well under a second). To undo any edits, use **Database → Reset database to original IMD data**, or delete `heatalert.db`.

---

## Where each experiment lives

| Exp | Concept | In the app | File |
|---|---|---|---|
| 1 | Classes, objects, constructors | Every reading is a `WeatherRecord` made of `Period`, `Temperature`, `Normal` | `models.py` |
| 2 | Constructors and lists | Data Manager: add, edit, delete readings; per-month list statistics | `readings.py` |
| 3 | String handling, inheritance | Advisories: cleans a messy raw feed line; `HeatwaveAdvisory` inherits `WeatherBulletin` | `advisories.py` |
| 4 | Abstract classes, polymorphism | Reports: abstract `ClimateReport`, five subclasses, one `report.generate()` call | `reports.py` |
| 5 | Exceptions, modules, threads | Live Monitor: 3 city threads streaming real daily data, custom exceptions, queue to the GUI | `monitor.py` |
| 6 | Collections, functional programming | Analytics: tuple, list, set, dict, `lambda`, `map`, `filter`, `reduce` | `analytics.py` |
| 7 | Tkinter Canvas | Heatwave Map of India (961 grid cells), all charts, the logo — drawn by hand | `charts.py`, `gui.py` |
| 8 | SQLite | Four tables, all storage, and the SQL console (18 ready-made queries) | `database.py` |

Other files: `grid.py` (reads IMD's binary daily grid and applies the IMD heatwave rule), `gui.py` (all screens),
`theme.py` (colours and fonts), `main.py` (start here), `verify_data.py` (checks all the data).

The GUI itself uses inheritance and polymorphism too: every screen is a subclass of `Screen`, and the app calls `screen.on_show()` on whichever one you open.

---

## The data

**Source:** India Meteorological Department, Climate Research & Services, Pune — *All India Time Series of Temperature (1901–2025), based on 1991–2020 normals* — `imdpune.gov.in/cmpg/Product/allindia_temp.html`

- `data/imd_all_india_1901_2025.csv` — 1,500 rows: every month from January 1901 to December 2025, with max, min and mean temperature and that month's 1991–2020 normal.
- `raw/max.txt`, `raw/min.txt`, `raw/mean.txt` — the three IMD tables exactly as published (year, 12 months, annual).

**Daily grid:** IMD Pune — *Daily Maximum Temp. (1.0 × 1.0) Binary* — `data/grid/Maxtemp_MaxT_2015.GRD` … `2025.GRD`.
Each file is one year: for every day, 31 × 31 four-byte floats covering 7.5–37.5°N and 67.5–97.5°E, with 99.9 meaning
no data. `grid.py` reads them with Python's built-in `array` module, so there's still nothing to install.

**Verification** — run `python verify_data.py`:

1. IMD publishes max, min and mean as three separate tables. For all 1,638 cells, mean = (max + min) / 2 within 0.001 °C. One wrong digit in any table would break this.
2. Every value in the CSV matches the raw tables exactly.
3. Every grid file has the right size, and the grid averaged over India tracks IMD's All-India monthly series:
   correlation 0.999 over 132 months, average gap 0.14 °C. They aren't identical because IMD builds the
   All-India series from station records, not from this grid.

**The daily grid finds the real heatwaves:** 2019 and 2024 are the two biggest years. The 2024 peak is 28 May
(74 grid cells, the day Delhi set its record). 19 May 2016 is a SEVERE heatwave at Phalodi, the day of India's
51 °C record. The 2015 peak is 23 May, during the Andhra Pradesh / Telangana heatwave.

**Cross-check with IMD's own statements:** the app computes 2024 as **+0.64 °C** above normal, the warmest year since 1901, and IMD reported +0.65 °C. The app's long-term trend is **+0.68 °C per 100 years** for 1901–2025; IMD reported +0.63 °C for 1901–2021.

---

## Things to be ready to explain

**How is the heatwave decided on the daily grid?**
IMD's rule for the plains, applied to every grid cell: heatwave when max ≥ 40 °C and ≥ 4.5 °C above normal,
or max ≥ 45 °C; severe at ≥ 6.5 °C above normal or ≥ 47 °C. IMD only declares it when the condition holds
on 2 days in a row, so the app applies that too. The 45 °C and 47 °C parts are exact. For the departure part,
the "normal" is the 2015–2025 average for that cell and date (15-day window), because only 11 years of grid
are available, not IMD's 1991–2020 normal. That baseline is a little warmer, so if anything the app
**under**-counts heatwaves. A grid cell is about 100 × 100 km, so it also reads lower than the hottest
single station: the grid shows 48.5 °C at Phalodi on the day the station recorded 51 °C.

**Why are the monthly alert thresholds so small (0.5, 1.0, 1.5 °C)?**
These are All-India *monthly averages*. IMD's real heatwave rule (4.5 °C above normal) applies to *one station on one day*, and a national monthly average never moves that much. The bands were chosen from the data itself. Since 1991, about 19% of months are ≥ 0.5 °C above normal, about 6% are ≥ 1.0 °C, and about 1% are ≥ 1.5 °C. The bulletins say clearly that they are for study, not official warnings.

**Is all the data real?**
Every temperature is IMD's. Two things are simulated on purpose, and both are kept separate from the data:

- the sensor faults in the Live Monitor, switched with "Simulate sensor faults". The monitor streams real daily grid readings, and a real 99.9 "no data" value would raise the same exception, but the ten city cells happen to have no gaps in 2015–2025;
- the messy text in the Advisories examples, because the experiment is about cleaning text.

**Why does the Live Monitor use a queue?**
Tkinter is not thread-safe. If a worker thread changed a widget directly, the window could freeze or crash at random. The three workers only `put()` messages on a `queue.Queue`. The screen checks the queue every 100 ms on the main thread and does all the drawing itself.

**Why four tables in the database?**
Normals are stored once in `monthly_normals` instead of being repeated on all 1,500 rows. `heatwave_alerts` is derived data, rebuilt by Python after every change, including changes made in the SQL console, so it can never go out of date. `grid_daily` has one row per day (4,018 days) summarising the daily grid, so it can be queried with SQL and JOINed with the monthly table. The console blocks `DROP` and `ALTER` so the app's own tables can't be destroyed mid-demo.

**Why `try` / `except` inside the loop in the monitor?**
A bad reading is reported and the loop moves on to the next one. If the `try` were outside the loop, the first fault would end the whole thread.

---

## Tested

- Every backend module under Python 3.8, 3.11 and 3.12.
- 47 scripted GUI checks under Python 3.10 and 3.12: bad input on every form, add/update/delete, duplicate records, SQL writes with confirm and cancel, blocked `DROP`, reset (including rebuilding the grid table), the map's step/play/year change/hover, impossible dates, stopping the monitor mid-stream, and closing the window while threads run. All pass with no errors.
- The pure-Python grid reader matches a separate numpy implementation exactly, for every cell and day.
- All nine screens rendered and checked at 1280 × 780.
