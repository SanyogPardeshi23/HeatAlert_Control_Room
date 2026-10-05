"""
monitor.py  -  Experiment 5: Exception handling, Modules and Multithreading

Three worker threads stream REAL daily maximum temperatures at the same
time, one thread per city, from IMD's daily 1-degree grid.

Why a queue?
    Tkinter is not thread-safe. If a worker thread changed a widget
    directly, the window could freeze or crash at random. So the workers
    only PUT messages on a queue.Queue, and the screen checks the queue
    every 100 ms from the main thread and does all the drawing itself.

Faults:
    A real 99.9 "no data" value in the grid raises DataUnavailableError.
    The city cells used here happen to have no gaps in 2015-2025, so
    "Simulate sensor faults" can inject dropped and corrupted readings
    to demonstrate the exception handling.
"""

import queue
import random
import threading

VALID_MIN = -10.0
VALID_MAX = 55.0


class SensorError(Exception):
    pass


class DataUnavailableError(SensorError):
    pass


class InvalidSensorDataError(SensorError):
    pass


def validate_reading(value, label):
    if value is None:
        raise DataUnavailableError(f"{label}: no reading received")
    if value < VALID_MIN or value > VALID_MAX:
        raise InvalidSensorDataError(f"{label}: value {value} C is outside {VALID_MIN} to {VALID_MAX} C")
    return value


class Channel:
    """One stream of readings. Each reading = (label, value or None, normal or None, level_name)."""

    def __init__(self, name, readings):
        self.name = name
        self.readings = readings


class StreamMonitor:
    def __init__(self, channels, delay=0.15, simulate_faults=True, fault_rate=0.05, seed=None):
        self.channels = channels
        self.delay = delay
        self.simulate_faults = simulate_faults
        self.fault_rate = fault_rate
        self.seed = seed
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.threads = []

    def start(self):
        self.stop_event.clear()
        self.threads = []
        for index, channel in enumerate(self.channels):
            seed = None if self.seed is None else self.seed + index
            thread = threading.Thread(target=self._run_channel, args=(channel, seed),
                                      name=f"{channel.name}-worker", daemon=True)
            self.threads.append(thread)
            thread.start()

    def stop(self):
        self.stop_event.set()

    def is_running(self):
        return any(thread.is_alive() for thread in self.threads)

    def join(self, timeout=2.0):
        for thread in self.threads:
            thread.join(timeout)

    def _receive(self, value, rng):
        """With simulated faults on, sometimes drop the reading or corrupt it."""
        if self.simulate_faults:
            roll = rng.random()
            if roll < self.fault_rate / 2:
                return None
            if roll < self.fault_rate:
                return rng.choice([58.7, 61.3, -14.2, 99.9])
        return value

    def _run_channel(self, channel, seed):
        rng = random.Random(seed)
        processed = 0
        faults = 0
        heatwave_days = 0
        for label, value, normal, level in channel.readings:
            if self.stop_event.is_set():
                break
            try:
                reading = validate_reading(self._receive(value, rng), label)
                departure = None if normal is None else round(reading - normal, 2)
                if level != "NO HEATWAVE":
                    heatwave_days += 1
                self.events.put(("reading", channel.name, label, reading, departure, level))
            except DataUnavailableError as error:
                faults += 1
                self.events.put(("fault", channel.name, label, "DataUnavailableError", str(error)))
            except InvalidSensorDataError as error:
                faults += 1
                self.events.put(("fault", channel.name, label, "InvalidSensorDataError", str(error)))
            finally:
                processed += 1
            self.stop_event.wait(self.delay)
        self.events.put(("done", channel.name, processed, faults, heatwave_days))
