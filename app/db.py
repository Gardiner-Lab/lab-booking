"""
The booking database: what can be booked, who it is shared with, and the bookings.

Times are kept in UTC, as 'YYYY-MM-DDTHH:MM:SSZ', so they compare as text and
the weeks the clocks change cannot shift a booking; app/times.py turns them
into the lab's own time for opening hours and days.
"""

import os
import sqlite3
from typing import Optional

SCHEMA = """
-- A room, a piece of equipment, a growth chamber: anything people book.
CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                       -- free text: Meeting room, Microscope, ...
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    colour TEXT NOT NULL DEFAULT '#2563eb',
    capacity INTEGER NOT NULL DEFAULT 1,      -- bookings at once: 1, or shelves, blocks...
    step_minutes INTEGER NOT NULL DEFAULT 30, -- bookings start and end on these steps
    min_minutes INTEGER NOT NULL DEFAULT 30,
    max_minutes INTEGER,                      -- NULL: as long as wanted
    advance_days INTEGER,                     -- how far ahead; NULL: no limit
    open_from TEXT NOT NULL DEFAULT '00:00',  -- the lab's time
    open_until TEXT NOT NULL DEFAULT '24:00',
    weekdays TEXT NOT NULL DEFAULT '1234567', -- ISO weekdays it can be booked on
    needs_approval INTEGER NOT NULL DEFAULT 0,-- kept for later: bookings wait for a manager
    owner_lab_id TEXT,                        -- the suite's lab it belongs to
    owner_lab TEXT NOT NULL DEFAULT '',
    everyone INTEGER NOT NULL DEFAULT 0,      -- shared with every lab
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    retired_at TEXT                           -- no longer booked; its bookings are kept
);
-- Who else books it, besides its own lab: labs and chair groups (the suite's ids).
CREATE TABLE IF NOT EXISTS resource_shares (
    resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('lab', 'chair_group')),
    target_id TEXT NOT NULL,
    PRIMARY KEY (resource_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES resources(id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'booking' CHECK (kind IN ('booking', 'closed')),
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'pending', 'cancelled')),
    booked_by TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    cancelled_at TEXT,
    cancelled_by TEXT
);
CREATE INDEX IF NOT EXISTS bookings_when ON bookings (resource_id, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS bookings_by ON bookings (booked_by, starts_at);
-- People tagged in a booking: a meeting's other people, a colleague on the microscope.
CREATE TABLE IF NOT EXISTS booking_people (
    booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    PRIMARY KEY (booking_id, username)
);
CREATE INDEX IF NOT EXISTS booking_people_by ON booking_people (username);
"""

_path: Optional[str] = None


def path() -> str:
    return _path or os.environ.get('BOOKING_DATABASE_PATH', '/booking/booking.db')


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def initialize(db_path: Optional[str] = None) -> None:
    global _path
    _path = db_path or path()
    os.makedirs(os.path.dirname(_path) or '.', exist_ok=True)
    with connect() as conn:
        # The ordinary rollback journal, as the other tools use, not WAL: the
        # suite's backup and the Lab Notebook read this database from read-only
        # mounts, where SQLite cannot open a WAL database.
        conn.execute('PRAGMA journal_mode = DELETE')
        conn.executescript(SCHEMA)
