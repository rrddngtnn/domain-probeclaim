"""Humanized scheduling, jitter delays, and quiet-hour windows."""
from __future__ import annotations

import datetime
import random
import time

QUIET_START, QUIET_END, TZ_OFFSET = 0, 6, 7  # 00:00-06:00 local time


def now_local(tz_offset=TZ_OFFSET):
    return (datetime.datetime.now(datetime.timezone.utc)
            .replace(tzinfo=None)
            + datetime.timedelta(hours=tz_offset))


def in_quiet_hours(dt=None, start=QUIET_START, end=QUIET_END, tz_offset=TZ_OFFSET):
    h = (dt or now_local(tz_offset)).hour
    return start <= h < end


def human_delay(base=90, spread=180, rest_chance=0.12, rng=None):
    """Calculate randomized operational delay."""
    r = rng or random
    d = base + r.random() * spread
    if r.random() < rest_chance:
        d += r.randint(300, 1800)
    return d


def sleep_human(base=90, spread=180, rest_chance=0.12, rng=None,
                sleep=None):
    """Execute randomized delay, supporting sleep mock injection."""
    d = human_delay(base, spread, rest_chance, rng)
    (sleep or time.sleep)(d)
    return d


def between_accounts(min_s=1500, max_s=4500, rng=None):
    r = rng or random
    return r.randint(min_s, max_s)


def rest_bonus(chance=0.2, lo=600, hi=2400, rng=None):
    r = rng or random
    return r.randint(lo, hi) if r.random() < chance else 0


def next_slots(count=1, gap_min=1500, gap_max=7200, rng=None, start=None):
    """Generate distributed execution timestamps."""
    r = rng or random
    t = start or now_local()
    out = []
    for _ in range(count):
        t = t + datetime.timedelta(seconds=r.randint(gap_min, gap_max))
        out.append(t)
    return out
