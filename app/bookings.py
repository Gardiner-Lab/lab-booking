"""
Bookings: what is booked when, by whom, and who else is in it.

    Booking      by anyone a room or piece of equipment is shared with, within
                 its rules (app/resources.py). People can be tagged in it: a
                 meeting's other people, a colleague at the microscope. It is
                 theirs too: in their bookings and their Lab Notebook.
    Changed      or cancelled by whoever booked it, or the thing's managers.
                 Someone tagged can take themselves out.
    Unavailable  managers block time (maintenance, a service visit): nobody
                 books it then.
    No clashes   checked here, inside one write transaction, against every
                 booking that overlaps: two people asking for the same slot at
                 the same moment cannot both have it. Something with a
                 capacity (shelves, blocks, seats) takes that many at once.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from app import resources as res
from app import times
from app.db import connect
from app.people import Person, archived, everyone
from app.resources import Forbidden, NotFound

# The calendar and the search ask for at most this many days at a time.
MAX_RANGE_DAYS = 62
MAX_PEOPLE = 50
MAX_SLOTS = 80


class Clash(ValueError):
    """It cannot be booked then: someone has it, or it is unavailable."""


def _people(conn, ids: Iterable[str]) -> Dict[str, List[str]]:
    ids = list(ids)
    found: Dict[str, List[str]] = {i: [] for i in ids}
    if ids:
        for r in conn.execute(f'SELECT booking_id, username FROM booking_people WHERE booking_id IN '
                              f'({", ".join("?" * len(ids))}) ORDER BY username COLLATE NOCASE', ids):
            found[r['booking_id']].append(r['username'])
    return found


def standing(rows) -> list:
    """
    The bookings that still stand: not those someone who has left (archived in
    the suite) made for after they left - those are freed for others. What they
    booked before stays, in the calendar and in notebooks.
    """
    gone = archived()
    if not gone:
        return list(rows)
    return [r for r in rows if not (r['booked_by'] in gone and r['ends_at'] > gone[r['booked_by']])]


def to_dict(person: Person, row, resource, people: List[str]) -> dict:
    mine = row['booked_by'] == person.username
    return {'id': row['id'], 'resource_id': row['resource_id'], 'start': row['starts_at'], 'end': row['ends_at'],
            'title': row['title'], 'notes': row['notes'], 'kind': row['kind'], 'status': row['status'],
            'booked_by': row['booked_by'], 'people': people, 'mine': mine,
            'tagged': person.username in people,
            'can_edit': row['status'] != 'cancelled' and (mine or res.can_manage(person, resource)),
            'resource': {'name': resource['name'], 'kind': resource['kind'], 'location': resource['location'],
                         'colour': resource['colour']}}


def _range(start: str, end: str):
    start_at, end_at = times.parse(start), times.parse(end)
    if end_at <= start_at:
        raise ValueError('The end comes before the start')
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError(f'Ask for at most {MAX_RANGE_DAYS} days at a time')
    return start_at, end_at


def in_range(person: Person, start: str, end: str, resource_ids: Optional[List[str]] = None,
             kind: Optional[str] = None) -> dict:
    """The bookings of what this person may see, between two times: of some things, or of one kind."""
    start_at, end_at = _range(start, end)
    shown = [r for r in res.visible(person)
             if (not resource_ids or r['id'] in resource_ids) and (not kind or r['kind'].casefold() == kind.casefold())]
    ids = [r['id'] for r in shown]
    if not ids:
        return {'resources': shown, 'bookings': []}
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM bookings WHERE resource_id IN ({', '.join('?' * len(ids))}) AND status != 'cancelled' "
            'AND starts_at < ? AND ends_at > ? ORDER BY starts_at',
            (*ids, times.store(end_at), times.store(start_at))).fetchall()
        rows = standing(rows)
        by_id = res.rows_by_id(conn, ids)
        people = _people(conn, [r['id'] for r in rows])
        return {'resources': shown,
                'bookings': [to_dict(person, r, by_id[r['resource_id']], people[r['id']]) for r in rows]}


def mine(person: Person, past_days: int = 0) -> List[dict]:
    """Their bookings and the ones they are tagged in, from today (or so many days back) on."""
    since = times.store(times.now() - timedelta(days=max(0, min(past_days, 366))))
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT b.* FROM bookings b LEFT JOIN booking_people p ON p.booking_id = b.id "
            "WHERE (b.booked_by = ? OR p.username = ?) AND b.status != 'cancelled' AND b.kind = 'booking' "
            "AND b.ends_at > ? ORDER BY b.starts_at LIMIT 300",
            (person.username, person.username, since)).fetchall()
        rows = standing(rows)
        by_id = res.rows_by_id(conn, {r['resource_id'] for r in rows})
        people = _people(conn, [r['id'] for r in rows])
        return [to_dict(person, r, by_id[r['resource_id']], people[r['id']]) for r in rows]


def get(person: Person, booking_id: str, conn=None) -> dict:
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
        if row is None:
            raise NotFound('No such booking')
        resource = res._get(conn, row['resource_id'])
        people = _people(conn, [booking_id])[booking_id]
        if not (res.can_see(person, resource, res._shares(conn, resource['id'])) or res.can_manage(person, resource)
                or person.username in people):
            raise NotFound('No such booking')
        return to_dict(person, row, resource, people)
    finally:
        if own:
            conn.close()


# --- the rules ---------------------------------------------------------------

def _fmt(value: datetime) -> str:
    return times.local(value).strftime('%a %d %b %H:%M')


def check_rules(resource, start: datetime, end: datetime, manager: bool, kept_start: Optional[datetime] = None) -> None:
    """Within the thing's rules: steps, length, how far ahead, opening hours and days."""
    name = resource['name']
    if end <= start:
        raise ValueError('It ends before it starts')
    now = times.now()
    if start < now - timedelta(minutes=1) and start != kept_start:
        raise ValueError('That time has passed')
    step = resource['step_minutes']
    local_start, local_end = times.local(start), times.local(end)
    length = (end - start).total_seconds() / 60
    if (local_start.hour * 60 + local_start.minute) % step or local_start.second or length % step:
        raise ValueError(f'{name} is booked in steps of {step} minutes')
    if length < resource['min_minutes']:
        raise ValueError(f'{name} is booked for at least {_duration(resource["min_minutes"])}')
    if resource['max_minutes'] and length > resource['max_minutes']:
        raise ValueError(f'{name} is booked for at most {_duration(resource["max_minutes"])}')
    if resource['advance_days'] and not manager and start > now + timedelta(days=resource['advance_days']):
        raise ValueError(f'{name} can be booked at most {resource["advance_days"]} days ahead')
    if res.always_open(resource):
        return
    day = local_start.date()
    if str(day.isoweekday()) not in resource['weekdays']:
        raise ValueError(f'{name} is not booked on {local_start.strftime("%A")}s')
    opens, closes = times.at(day, times.minutes(resource['open_from'])), times.at(day, times.minutes(resource['open_until']))
    if start < opens or end > closes:
        raise ValueError(f'{name} is booked from {resource["open_from"]} to {resource["open_until"]}, within one day')


def _duration(mins: int) -> str:
    if mins % (60 * 24) == 0:
        days = mins // (60 * 24)
        return f'{days} day{"s" if days > 1 else ""}'
    if mins % 60 == 0:
        return f'{mins // 60} h'
    return f'{mins // 60} h {mins % 60} min' if mins > 60 else f'{mins} min'


def _overlapping(conn, resource_id: str, start: datetime, end: datetime, exclude: Optional[str] = None):
    return standing(conn.execute(
        "SELECT * FROM bookings WHERE resource_id = ? AND status != 'cancelled' AND starts_at < ? AND ends_at > ? "
        "AND id != ? ORDER BY starts_at",
        (resource_id, times.store(end), times.store(start), exclude or '')).fetchall())


def _peak(rows, start: str, end: str) -> int:
    """The most bookings at once between two times."""
    events = sorted([(max(r['starts_at'], start), 1) for r in rows] + [(min(r['ends_at'], end), -1) for r in rows],
                    key=lambda e: (e[0], e[1]))
    peak = load = 0
    for _, change in events:
        load += change
        peak = max(peak, load)
    return peak


def check_clash(conn, resource, start: datetime, end: datetime, kind: str, exclude: Optional[str] = None) -> None:
    rows = _overlapping(conn, resource['id'], start, end, exclude)
    closed = [r for r in rows if r['kind'] == 'closed']
    if closed:
        r = closed[0]
        raise Clash(f'{resource["name"]} is unavailable from {_fmt(times.load(r["starts_at"]))} '
                    f'to {_fmt(times.load(r["ends_at"]))}' + (f': {r["title"]}' if r['title'] else ''))
    if kind == 'closed':
        if rows:
            listed = '; '.join(f'{_fmt(times.load(r["starts_at"]))} by {r["booked_by"]}' for r in rows[:5])
            raise Clash(f'It is booked then - move or cancel these first: {listed}')
        return
    if _peak(rows, times.store(start), times.store(end)) + 1 > resource['capacity']:
        if resource['capacity'] == 1:
            r = rows[0]
            raise Clash(f'{resource["name"]} is booked by {r["booked_by"]} from {_fmt(times.load(r["starts_at"]))} '
                        f'to {_fmt(times.load(r["ends_at"]))}')
        raise Clash(f'All {resource["capacity"]} places of {resource["name"]} are booked for part of that time')


def _clean_people(people, booker: str) -> List[str]:
    if people in (None, ''):
        return []
    if not isinstance(people, list):
        raise ValueError('People are a list of usernames')
    known = {u.casefold(): u for u in everyone(include_archived=True)}
    out = []
    for name in people:
        found = known.get(str(name or '').strip().casefold())
        if found is None:
            raise ValueError(f'No one is called {name}')
        if found != booker and found not in out:
            out.append(found)
    if len(out) > MAX_PEOPLE:
        raise ValueError(f'Tag at most {MAX_PEOPLE} people')
    return out


def _text(data: dict, key: str, limit: int, old: str = '') -> str:
    return str(data.get(key, old) or '').strip()[:limit]


# --- booking, changing, cancelling ----------------------------------------------

def create(person: Person, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Send the booking as JSON')
    kind = data.get('kind') or 'booking'
    if kind not in ('booking', 'closed'):
        raise ValueError('A booking, or time it is unavailable')
    start, end = times.parse(data.get('start')), times.parse(data.get('end'))
    people = _clean_people(data.get('people'), person.username) if kind == 'booking' else []
    booking_id = uuid.uuid4().hex
    conn = connect()
    try:
        conn.execute('BEGIN IMMEDIATE')       # the check and the booking, with no one else's in between
        resource = res._get(conn, str(data.get('resource_id') or ''))
        manager = res.can_manage(person, resource)
        if not (res.can_see(person, resource, res._shares(conn, resource['id'])) or manager):
            raise NotFound('No such room or equipment')
        if resource['retired_at']:
            raise ValueError(f'{resource["name"]} is no longer booked')
        if kind == 'closed' and not manager:
            raise Forbidden('Only its managers mark it unavailable')
        if kind == 'booking':
            check_rules(resource, start, end, manager)
        elif end <= start:
            raise ValueError('It ends before it starts')
        check_clash(conn, resource, start, end, kind)
        # Some things may later need a manager's yes (needs_approval); for now every booking stands.
        conn.execute('INSERT INTO bookings (id, resource_id, starts_at, ends_at, title, notes, kind, status, '
                     "booked_by, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                     (booking_id, resource['id'], times.store(start), times.store(end), _text(data, 'title', 200),
                      _text(data, 'notes', 4000), kind, person.username, person.username))
        conn.executemany('INSERT INTO booking_people (booking_id, username) VALUES (?, ?)',
                         [(booking_id, u) for u in people])
        conn.commit()
        return get(person, booking_id, conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update(person: Person, booking_id: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Send the booking as JSON')
    conn = connect()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
        if row is None:
            raise NotFound('No such booking')
        old_resource = res._get(conn, row['resource_id'])
        if not (row['booked_by'] == person.username or res.can_manage(person, old_resource)):
            raise Forbidden('Only whoever booked it, or its managers, change it')
        if row['status'] == 'cancelled':
            raise ValueError('It was cancelled')
        resource = res._get(conn, str(data.get('resource_id') or row['resource_id']))
        manager = res.can_manage(person, resource)
        if resource['id'] != old_resource['id'] and not (
                res.can_see(person, resource, res._shares(conn, resource['id'])) or manager):
            raise NotFound('No such room or equipment')
        old_start, old_end = times.load(row['starts_at']), times.load(row['ends_at'])
        start = times.parse(data['start']) if data.get('start') else old_start
        end = times.parse(data['end']) if data.get('end') else old_end
        moved = (start, end, resource['id']) != (old_start, old_end, old_resource['id'])
        if moved:
            if resource['retired_at']:
                raise ValueError(f'{resource["name"]} is no longer booked')
            if row['kind'] == 'booking':
                check_rules(resource, start, end, manager, kept_start=old_start)
            elif end <= start:
                raise ValueError('It ends before it starts')
            check_clash(conn, resource, start, end, row['kind'], exclude=booking_id)
        conn.execute('UPDATE bookings SET resource_id = ?, starts_at = ?, ends_at = ?, title = ?, notes = ?, '
                     'updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (resource['id'], times.store(start), times.store(end), _text(data, 'title', 200, row['title']),
                      _text(data, 'notes', 4000, row['notes']), person.username, booking_id))
        if 'people' in data and row['kind'] == 'booking':
            people = _clean_people(data.get('people'), row['booked_by'])
            conn.execute('DELETE FROM booking_people WHERE booking_id = ?', (booking_id,))
            conn.executemany('INSERT INTO booking_people (booking_id, username) VALUES (?, ?)',
                             [(booking_id, u) for u in people])
        conn.commit()
        return get(person, booking_id, conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel(person: Person, booking_id: str) -> None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
        if row is None:
            raise NotFound('No such booking')
        if not (row['booked_by'] == person.username or res.can_manage(person, res._get(conn, row['resource_id']))):
            raise Forbidden('Only whoever booked it, or its managers, cancel it')
        conn.execute("UPDATE bookings SET status = 'cancelled', cancelled_at = ?, cancelled_by = ? WHERE id = ?",
                     (times.store(times.now()), person.username, booking_id))


def leave(person: Person, booking_id: str) -> None:
    """Someone tagged takes themselves out."""
    with connect() as conn:
        found = conn.execute('DELETE FROM booking_people WHERE booking_id = ? AND username = ?',
                             (booking_id, person.username)).rowcount
    if not found:
        raise NotFound('You are not in that booking')


# --- finding a free slot ----------------------------------------------------------

def _free_spans(rows, capacity: int, start: datetime, end: datetime) -> List[tuple]:
    """Where fewer than capacity bookings run at once (unavailable time counts as full), between two times."""
    marks = {start, end}
    spans = []
    for r in rows:
        s, e = max(times.load(r['starts_at']), start), min(times.load(r['ends_at']), end)
        if s < e:
            spans.append((s, e, capacity if r['kind'] == 'closed' else 1))
            marks.update((s, e))
    points = sorted(marks)
    free: List[tuple] = []
    for a, b in zip(points, points[1:]):
        load = sum(w for s, e, w in spans if s < b and e > a)
        if load < capacity:
            if free and free[-1][1] == a:
                free[-1] = (free[-1][0], b)
            else:
                free.append((a, b))
    return free


def _on_step(value: datetime, step: int) -> datetime:
    """The first time on the thing's steps, at or after this one, in the lab's time."""
    local = times.local(value)
    mins = local.hour * 60 + local.minute + (1 if local.second or local.microsecond else 0)
    return times.at(local.date(), -(-mins // step) * step)


def free(person: Person, *, day_from: date, day_to: date, minutes: int, query: str = '', kind: str = '',
         min_capacity: int = 1, time_from: Optional[str] = None, time_until: Optional[str] = None) -> List[dict]:
    """
    Free slots of at least so many minutes, over a span of days: in whatever
    matches (a name, kind, place or description; a kind; at least so many
    places), optionally only between two times of day. Each slot is a free
    span, earliest first, to book any part of.
    """
    if day_to < day_from:
        raise ValueError('The last day comes before the first')
    if (day_to - day_from).days >= MAX_RANGE_DAYS:
        raise ValueError(f'Look at most {MAX_RANGE_DAYS} days at a time')
    if minutes < 5:
        raise ValueError('Ask for at least 5 minutes')
    window_from = times.minutes(times.clean_hhmm(time_from, '00:00'))
    window_until = times.minutes(times.clean_hhmm(time_until, '24:00'))
    if window_until <= window_from:
        raise ValueError('The time of day ends before it starts')
    words = query.casefold().split()
    matching = [r for r in res.visible(person)
                if (not kind or r['kind'].casefold() == kind.casefold()) and r['capacity'] >= min_capacity
                and all(any(w in (r[k] or '').casefold() for k in ('name', 'kind', 'location', 'description'))
                        for w in words)
                and minutes >= r['min_minutes'] and (not r['max_minutes'] or minutes <= r['max_minutes'])]
    now = times.now()
    range_start, range_end = max(times.at(day_from, 0), now), times.at(day_to, 24 * 60)
    slots = []
    with connect() as conn:
        rows_of = {r['id']: _overlapping(conn, r['id'], range_start, range_end) for r in matching}
    for r in matching:
        until = range_end
        if r['advance_days'] and not r['can_manage']:
            until = min(until, now + timedelta(days=r['advance_days']))
        whole_days = window_from == 0 and window_until == 24 * 60
        if r['always_open'] and whole_days:
            windows = [(range_start, until)]
        else:
            windows = []
            day = day_from
            while day <= day_to:
                if str(day.isoweekday()) in r['weekdays']:
                    opens = max(times.minutes(r['open_from']), window_from)
                    closes = min(times.minutes(r['open_until']), window_until)
                    if closes > opens:
                        windows.append((max(times.at(day, opens), range_start), min(times.at(day, closes), until)))
                day += timedelta(days=1)
        for span_start, span_end in _free_spans(rows_of[r['id']], r['capacity'], range_start, until):
            for w_start, w_end in windows:
                s, e = max(span_start, w_start), min(span_end, w_end)
                if e <= s:
                    continue
                s = _on_step(s, r['step_minutes'])
                if (e - s).total_seconds() / 60 >= minutes:
                    slots.append({'resource_id': r['id'], 'resource': {k: r[k] for k in ('name', 'kind', 'location', 'colour',
                                                                                           'capacity', 'step_minutes')},
                                  'start': times.store(s), 'end': times.store(e)})
    slots.sort(key=lambda s: (s['start'], s['resource']['name'].casefold()))
    return slots[:MAX_SLOTS]
