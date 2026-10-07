"""
Predict when library manga will next get a chapter.

Android Mihon's Upcoming tab works from each series' release rhythm. This
does the same from the upload dates already stored for each chapter:

- Chapters uploaded on the same day count as one release, so a batch drop
  does not look like a daily schedule.
- The interval is the median gap between the last few releases, which a
  single late or early chapter does not throw off.
- A series that is finished, too irregular, or silent for several intervals
  (probably on hiatus) gets no prediction rather than a wrong one.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

DAY = 86400.0

# Fewer releases than this give no rhythm to speak of.
MIN_RELEASES = 3
# How many recent releases the interval is taken from.
RECENT_RELEASES = 10
# Gaps longer than this are too irregular to predict.
MAX_INTERVAL_DAYS = 60
# No release for this many intervals: most likely on hiatus.
HIATUS_FACTOR = 3
# How far ahead the view looks.
HORIZON_DAYS = 30

FINISHED_STATUSES = {"completed", "cancelled", "publishing finished"}


@dataclass
class Prediction:
    manga: object
    next_release: float        # timestamp of the expected day
    interval_days: float
    last_release: float
    overdue: bool = False


def release_interval_days(upload_times: Iterable[Optional[float]]) -> Optional[float]:
    """Median days between recent releases, or None when there is no usable rhythm."""
    days = sorted({int(t // DAY) for t in upload_times if t})
    if len(days) < MIN_RELEASES:
        return None
    recent = days[-RECENT_RELEASES:]
    gaps = [b - a for a, b in zip(recent, recent[1:])]
    interval = statistics.median(gaps)
    if interval < 1 or interval > MAX_INTERVAL_DAYS:
        return None
    return float(interval)


def _start_of_day(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def predict(manga, upload_times: Sequence[Optional[float]], now: float) -> Optional[Prediction]:
    """The next expected release for one manga, or None."""
    if (getattr(manga, "status", "") or "").lower() in FINISHED_STATUSES:
        return None
    times = [t for t in upload_times if t]
    interval = release_interval_days(times)
    if interval is None:
        return None
    last = max(times)
    if now - last > HIATUS_FACTOR * interval * DAY:
        return None
    expected = last + interval * DAY
    today = _start_of_day(now)
    if expected < today:
        # Late, but not long enough to call it a hiatus: due any day now.
        return Prediction(manga, today, interval, last, overdue=True)
    return Prediction(manga, _start_of_day(expected), interval, last)


def upcoming(
    entries: Iterable[Tuple[object, Sequence[Optional[float]]]],
    now: Optional[float] = None,
    horizon_days: int = HORIZON_DAYS,
) -> List[Prediction]:
    """
    Predictions for ``(manga, chapter upload times)`` pairs, soonest first.

    Overdue series come first, then by expected day, then by title.
    """
    now = time.time() if now is None else now
    limit = _start_of_day(now) + horizon_days * DAY
    found = []
    for manga, times in entries:
        prediction = predict(manga, times, now)
        if prediction is not None and prediction.next_release <= limit:
            found.append(prediction)
    found.sort(key=lambda p: (not p.overdue, p.next_release, (getattr(p.manga, "title", "") or "").lower()))
    return found


def day_label(ts: float, now: float) -> str:
    """"Today", "Tomorrow", or a short date such as "Wed, 9 Oct"."""
    days = round((_start_of_day(ts) - _start_of_day(now)) / DAY)
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    lt = time.localtime(ts)
    return f"{time.strftime('%a', lt)}, {lt.tm_mday} {time.strftime('%b', lt)}"


def group_by_day(predictions: Sequence[Prediction], now: Optional[float] = None):
    """[(label, [predictions])] in order, with overdue series under "Due now"."""
    now = time.time() if now is None else now
    groups: List[Tuple[str, List[Prediction]]] = []
    for prediction in predictions:
        label = "Due now" if prediction.overdue else day_label(prediction.next_release, now)
        if groups and groups[-1][0] == label:
            groups[-1][1].append(prediction)
        else:
            groups.append((label, [prediction]))
    return groups


def describe_interval(days: float) -> str:
    """"Daily", "Weekly", "Every 2 weeks", "Every 10 days"..."""
    days = round(days)
    if days == 1:
        return "Daily"
    if days == 7:
        return "Weekly"
    if days % 7 == 0:
        return f"Every {days // 7} weeks"
    return f"Every {days} days"


__all__ = [
    "Prediction",
    "day_label",
    "describe_interval",
    "group_by_day",
    "predict",
    "release_interval_days",
    "upcoming",
]
