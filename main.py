"""
main.py  -  start here:   python main.py

HeatAlert Control Room
OOPL (Python) mini project - Climate Intelligence for Heatwave Monitoring,
Prediction and Early Warning, using IMD Pune's All-India temperature data.
"""

import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def enable_sharp_text_on_windows():
    """Without this, Tkinter looks blurry on Windows laptops with display scaling."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main():
    if sys.version_info < (3, 7):
        print("Python 3.7 or newer is needed. You have", sys.version.split()[0])
        return
    try:
        import tkinter
    except ImportError:
        print("Tkinter is not installed. On Windows and macOS it comes with Python from python.org.")
        print("On Ubuntu/Debian run:  sudo apt install python3-tk")
        return

    sys.path.insert(0, BASE_DIR)
    from database import DatabaseError
    from gui import App

    enable_sharp_text_on_windows()
    try:
        app = App(BASE_DIR)
    except DatabaseError as error:
        print("Could not open the data:", error)
        print("Make sure the 'data' folder is next to main.py.")
        return
    except sqlite3.Error as error:
        print("Could not create the database:", error)
        print("If you opened this from inside a .zip file, extract the whole folder first, then run main.py.")
        return
    app.mainloop()


if __name__ == "__main__":
    main()
