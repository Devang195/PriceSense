"""Calendar helpers for synthetic-data generation only.
These approximate sale windows are not used by the forecasting engine.
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_NAME = "PriceSense Adaptive (PAF)"
CALENDAR_FILE = Path(__file__).with_name("sale_calendar.json")
MIN_TRAIN = 56


@lru_cache(maxsize=1)
def load_calendar():
    config = json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))
    windows = []
    for item in config["windows"]:
        month, day = map(int, item["start"].split("-"))
        date(2001, month, day)  # reject invalid or leap-only recurring dates
        days = int(item["days"])
        if not 1 <= days <= 30:
            raise ValueError("Sale calendar duration must be 1–30 days")
        jitter = int(item.get("jitter_days", 0))
        if not 0 <= jitter <= 7:
            raise ValueError("Sale-window jitter must be 0–7 days")
        windows.append((str(item["name"]), month, day, days, jitter))
    return tuple(windows)


def calendar_features(dates):
    """Return sale flags, decaying post-sale flags, and overlapping window labels."""
    dates = pd.DatetimeIndex(dates)
    sale = np.zeros(len(dates))
    recovery = np.zeros(len(dates))
    events = []
    if len(dates) == 0:
        return sale, recovery, events
    for year in range(dates[0].year - 1, dates[-1].year + 1):
        for name, month, day, length, jitter in load_calendar():
            nominal = pd.Timestamp(year=year, month=month, day=day)
            # Average flags over plausible dates and durations, not actual future sales.
            shifts = range(-jitter, jitter + 1)
            durations = range(max(3, length - 1), length + 3) if jitter else [length]
            probability = np.zeros(len(dates))
            recovery_probability = np.zeros(len(dates))
            relative = np.asarray((dates - nominal).days, dtype=float)
            for shift in shifts:
                for duration in durations:
                    after = relative - shift - duration + 1
                    probability += (relative >= shift) & (after <= 0)
                    recovery_probability += np.where((after >= 1) & (after <= 5), (6 - after) / 6, 0)
            total = len(shifts) * len(durations)
            probability /= total
            recovery_probability /= total
            sale = np.maximum(sale, probability)
            recovery = np.maximum(recovery, recovery_probability)
            if np.any(probability > 0):
                window_start = nominal - pd.Timedelta(days=jitter)
                window_end = nominal + pd.Timedelta(days=jitter + max(durations) - 1)
                events.append({"name": name, "start": window_start.date().isoformat(), "end": window_end.date().isoformat()})
    return sale, recovery, sorted(events, key=lambda e: e["start"])

