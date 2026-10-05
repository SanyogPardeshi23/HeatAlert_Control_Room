"""
database.py  -  Experiment 8: Database-driven system using SQLite

Four tables:
    monthly_normals      12 rows   - IMD 1991-2020 normal for each month
    temperature_records  1500 rows - one row per month, 1901-2025
    heatwave_alerts      1500 rows - departure + alert level for each record
    grid_daily           ~4000 rows - one row per day 2015-2025 from IMD's daily
                                      1-degree grid: how many grid cells met the
                                      IMD heatwave rule, and the hottest cell

Normals live in their own table so they are stored once, not repeated
on all 1500 rows (normalisation). heatwave_alerts is rebuilt from the
other two tables after every change, so it can never go out of date.
"""

import csv
import os
import sqlite3

from models import MONTHS, WeatherRecord, classify_departure

ALLOWED_STATEMENTS = ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE")
READ_STATEMENTS = ("SELECT", "WITH")

PRESET_QUERIES = [
    ("Show the first 10 records",
     "SELECT * FROM temperature_records LIMIT 10"),
    ("Count all records",
     "SELECT COUNT(*) AS total_records FROM temperature_records"),
    ("Months hotter than 37 C (max)",
     "SELECT year, month, max_temp FROM temperature_records\nWHERE max_temp > 37\nORDER BY max_temp DESC"),
    ("Top 10 hottest months on record",
     "SELECT year, month, max_temp FROM temperature_records\nORDER BY max_temp DESC\nLIMIT 10"),
    ("Average, min and max per month",
     "SELECT month, COUNT(*) AS years, ROUND(AVG(max_temp), 3) AS avg_max,\n"
     "       MIN(max_temp) AS lowest, MAX(max_temp) AS highest\n"
     "FROM temperature_records\nGROUP BY month_num\nORDER BY month_num"),
    ("May records between 2015 and 2025",
     "SELECT * FROM temperature_records\nWHERE month = 'May' AND year BETWEEN 2015 AND 2025"),
    ("Each alert level only once",
     "SELECT DISTINCT alert_level FROM heatwave_alerts"),
    ("How many months at each alert level",
     "SELECT alert_level, COUNT(*) AS months FROM heatwave_alerts\nGROUP BY alert_level\nORDER BY months DESC"),
    ("Alert levels with more than 100 months",
     "SELECT alert_level, COUNT(*) AS months FROM heatwave_alerts\nGROUP BY alert_level\nHAVING COUNT(*) > 100"),
    ("Pre-monsoon months (Mar-Jun) only",
     "SELECT year, month, max_temp FROM temperature_records\n"
     "WHERE month IN ('March', 'April', 'May', 'June') AND year >= 2020"),
    ("Months starting with 'J'",
     "SELECT DISTINCT month FROM temperature_records\nWHERE month LIKE 'J%'"),
    ("JOIN: every EXTREME month",
     "SELECT t.year, t.month, t.max_temp, n.normal_max, a.departure, a.alert_level\n"
     "FROM temperature_records t\n"
     "JOIN monthly_normals n ON t.month_num = n.month_num\n"
     "JOIN heatwave_alerts a ON a.record_id = t.id\n"
     "WHERE a.alert_level = 'EXTREME'\nORDER BY a.departure DESC"),
    ("Hottest year by average max temperature",
     "SELECT year, ROUND(AVG(max_temp), 4) AS avg_max FROM temperature_records\n"
     "GROUP BY year\nORDER BY avg_max DESC\nLIMIT 5"),
    ("Daily grid: 10 days with the most heatwave cells",
     "SELECT date, heatwave_cells, severe_cells, hottest_temp, hottest_lat, hottest_lon\n"
     "FROM grid_daily\nORDER BY heatwave_cells DESC\nLIMIT 10"),
    ("Daily grid: heatwave cell-days per year",
     "SELECT year, SUM(heatwave_cells) AS heatwave_cell_days, SUM(severe_cells) AS severe_cell_days,\n"
     "       COUNT(CASE WHEN heatwave_cells > 0 THEN 1 END) AS days_with_heatwave, MAX(hottest_temp) AS hottest\n"
     "FROM grid_daily\nGROUP BY year\nORDER BY year"),
    ("Daily grid: hottest single reading each year",
     "SELECT g.year, g.date, g.hottest_temp, g.hottest_lat, g.hottest_lon\nFROM grid_daily g\n"
     "WHERE g.hottest_temp = (SELECT MAX(hottest_temp) FROM grid_daily WHERE year = g.year)\nORDER BY g.year"),
    ("JOIN grid + monthly: worst heatwave months",
     "SELECT t.year, t.month, t.max_temp, a.alert_level, SUM(g.heatwave_cells) AS heatwave_cell_days\n"
     "FROM grid_daily g\n"
     "JOIN temperature_records t ON t.year = g.year AND t.month_num = g.month\n"
     "JOIN heatwave_alerts a ON a.record_id = t.id\n"
     "GROUP BY t.id\nORDER BY heatwave_cell_days DESC\nLIMIT 10"),
    ("SEVERE or worse months per decade",
     "SELECT (t.year / 10) * 10 AS decade, COUNT(*) AS hot_months\n"
     "FROM temperature_records t JOIN heatwave_alerts a ON a.record_id = t.id\n"
     "WHERE a.alert_level IN ('SEVERE', 'EXTREME')\nGROUP BY decade\nORDER BY decade"),
]


class DatabaseError(Exception):
    pass


class ClimateDatabase:
    def __init__(self, db_path, csv_path):
        self.db_path = db_path
        self.csv_path = csv_path
        self.connection = sqlite3.connect(db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.cursor = self.connection.cursor()
        self.create_schema()
        if self.count_records() == 0:
            self.import_csv()

    # ---------- setup ----------

    def create_schema(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_normals (
                month_num   INTEGER PRIMARY KEY,
                month       TEXT NOT NULL UNIQUE,
                normal_max  REAL NOT NULL,
                normal_min  REAL NOT NULL,
                normal_mean REAL NOT NULL
            )""")
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS temperature_records (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                year      INTEGER NOT NULL,
                month     TEXT NOT NULL,
                month_num INTEGER NOT NULL REFERENCES monthly_normals(month_num),
                max_temp  REAL NOT NULL,
                min_temp  REAL NOT NULL,
                mean_temp REAL NOT NULL,
                UNIQUE (year, month),
                CHECK (min_temp <= max_temp)
            )""")
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS grid_daily (
                date           TEXT PRIMARY KEY,
                year           INTEGER NOT NULL,
                month          INTEGER NOT NULL,
                cells_reported INTEGER NOT NULL,
                heatwave_cells INTEGER NOT NULL,
                severe_cells   INTEGER NOT NULL,
                hottest_temp   REAL,
                hottest_lat    REAL,
                hottest_lon    REAL
            )""")
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS heatwave_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id   INTEGER NOT NULL UNIQUE
                            REFERENCES temperature_records(id) ON DELETE CASCADE,
                departure   REAL NOT NULL,
                alert_level TEXT NOT NULL
            )""")
        self.connection.commit()

    def import_csv(self):
        if not os.path.exists(self.csv_path):
            raise DatabaseError(f"Dataset file not found: {os.path.basename(self.csv_path)}")

        normals = {}
        records = []
        with open(self.csv_path, newline="") as f:
            for row in csv.DictReader(f):
                month_num = int(row["month_num"])
                normals[month_num] = (month_num, row["month"], float(row["normal_max"]),
                                      float(row["normal_min"]), float(row["normal_mean"]))
                records.append((int(row["year"]), row["month"], month_num, float(row["max_temp"]),
                                float(row["min_temp"]), float(row["mean_temp"])))

        self.cursor.executemany(
            "INSERT OR REPLACE INTO monthly_normals VALUES (?, ?, ?, ?, ?)", list(normals.values()))
        self.cursor.executemany(
            "INSERT INTO temperature_records (year, month, month_num, max_temp, min_temp, mean_temp) "
            "VALUES (?, ?, ?, ?, ?, ?)", records)
        self.rebuild_alerts()
        self.connection.commit()

    def reset(self):
        """Throw away all edits and reload the original IMD data."""
        self.cursor.execute("DROP TABLE IF EXISTS heatwave_alerts")
        self.cursor.execute("DROP TABLE IF EXISTS temperature_records")
        self.cursor.execute("DROP TABLE IF EXISTS monthly_normals")
        self.connection.commit()
        self.create_schema()
        self.import_csv()

    def rebuild_alerts(self):
        self.cursor.execute("DELETE FROM heatwave_alerts")
        self.cursor.execute("""
            SELECT t.id, t.max_temp, n.normal_max
            FROM temperature_records t JOIN monthly_normals n ON t.month_num = n.month_num""")
        alerts = []
        for record_id, max_temp, normal_max in self.cursor.fetchall():
            departure = round(max_temp - normal_max, 4)
            alerts.append((record_id, departure, classify_departure(departure)))
        self.cursor.executemany(
            "INSERT INTO heatwave_alerts (record_id, departure, alert_level) VALUES (?, ?, ?)", alerts)

    def store_grid_daily(self, rows):
        """rows: (date, year, month, cells_reported, heatwave_cells, severe_cells, hottest, lat, lon)"""
        self.cursor.execute("DELETE FROM grid_daily")
        self.cursor.executemany("INSERT INTO grid_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.connection.commit()

    def grid_daily_count(self):
        self.cursor.execute("SELECT COUNT(*) FROM grid_daily")
        return self.cursor.fetchone()[0]

    def grid_year_totals(self):
        self.cursor.execute("SELECT year, SUM(heatwave_cells), SUM(severe_cells) FROM grid_daily "
                            "GROUP BY year ORDER BY year")
        return self.cursor.fetchall()

    # ---------- reading ----------

    def count_records(self):
        self.cursor.execute("SELECT COUNT(*) FROM temperature_records")
        return self.cursor.fetchone()[0]

    def year_range(self):
        self.cursor.execute("SELECT MIN(year), MAX(year) FROM temperature_records")
        return self.cursor.fetchone()

    def fetch_records(self, year_from=None, year_to=None, month=None):
        sql = """
            SELECT t.id, t.year, t.month, t.max_temp, t.min_temp, t.mean_temp,
                   n.normal_max, n.normal_min, n.normal_mean
            FROM temperature_records t JOIN monthly_normals n ON t.month_num = n.month_num
            WHERE 1 = 1"""
        params = []
        if year_from is not None:
            sql += " AND t.year >= ?"
            params.append(year_from)
        if year_to is not None:
            sql += " AND t.year <= ?"
            params.append(year_to)
        if month:
            sql += " AND t.month = ?"
            params.append(month)
        sql += " ORDER BY t.year, t.month_num"
        self.cursor.execute(sql, params)
        return [WeatherRecord(year, month, tmax, tmin, tmean, nmax, nmin, nmean, record_id=rid)
                for rid, year, month, tmax, tmin, tmean, nmax, nmin, nmean in self.cursor.fetchall()]

    # ---------- writing ----------

    def add_record(self, year, month, tmax, tmin, tmean):
        if month not in MONTHS:
            raise DatabaseError(f"Unknown month: {month}")
        try:
            self.cursor.execute(
                "INSERT INTO temperature_records (year, month, month_num, max_temp, min_temp, mean_temp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (year, month, MONTHS.index(month) + 1, tmax, tmin, tmean))
        except sqlite3.IntegrityError:
            raise DatabaseError(f"A record for {month} {year} already exists.")
        self.rebuild_alerts()
        self.connection.commit()

    def update_record(self, record_id, tmax, tmin, tmean):
        try:
            self.cursor.execute(
                "UPDATE temperature_records SET max_temp = ?, min_temp = ?, mean_temp = ? WHERE id = ?",
                (tmax, tmin, tmean, record_id))
        except sqlite3.IntegrityError as error:
            self.connection.rollback()
            raise DatabaseError(f"Update rejected: {error}")
        self.rebuild_alerts()
        self.connection.commit()

    def delete_record(self, record_id):
        self.cursor.execute("DELETE FROM temperature_records WHERE id = ?", (record_id,))
        self.connection.commit()

    # ---------- SQL console ----------

    def run_query(self, sql):
        """Run one statement typed by the user. Returns (columns, rows, message)."""
        statement = sql.strip().rstrip(";").strip()
        if not statement:
            raise DatabaseError("Type a query first.")
        first_word = statement.split()[0].upper()
        if first_word not in ALLOWED_STATEMENTS:
            raise DatabaseError(f"{first_word} is not allowed here. Use SELECT, INSERT, UPDATE or "
                                f"DELETE. Use 'Reset database' to restore the original data.")
        try:
            self.cursor.execute(statement)
        except sqlite3.Error as error:
            self.connection.rollback()
            raise DatabaseError(f"SQL error: {error}")

        if first_word in READ_STATEMENTS:
            columns = [d[0] for d in self.cursor.description]
            rows = self.cursor.fetchall()
            return columns, rows, f"{len(rows)} row(s) returned"

        changed = self.cursor.rowcount
        self.rebuild_alerts()
        self.connection.commit()
        return [], [], f"{changed} row(s) changed - alerts table rebuilt"

    def close(self):
        self.connection.close()
