"""
What can be booked: rooms, equipment, growth chambers - added, changed and
retired by the people who run them, not in code.

    Belongs to   one of the suite's labs. Its lab admins (and administrators)
                 add it, change it, retire it and manage its bookings.
    Shared with  its own lab always; and any other labs, chair groups, or
                 everyone, as its managers choose. Whoever it is shared with
                 sees it and books it.
    Its rules    the steps bookings start and end on, the shortest and longest
                 booking, how far ahead it can be booked, and when it is open.
    Retired      no longer booked, kept with its bookings; one never booked
                 can be removed outright.

Kinds (Meeting room, Microscope, ...) are free text: a new kind is a new name.
"""

import re
import uuid
from typing import Dict, List, Optional

from app import times
from app.db import connect
from app.people import Person, chair_groups, labs


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


STEPS = (5, 10, 15, 20, 30, 60)
COLOUR = re.compile(r'^#[0-9a-fA-F]{6}$')


def _shares(conn, resource_id: str) -> List[dict]:
    return [{'type': r['target_type'], 'id': r['target_id']} for r in conn.execute(
        'SELECT target_type, target_id FROM resource_shares WHERE resource_id = ? ORDER BY target_type, target_id',
        (resource_id,))]


def can_see(person: Person, row, shares: List[dict]) -> bool:
    if person.is_admin or row['everyone'] or (row['owner_lab_id'] in person.lab_ids):
        return True
    groups = person.chair_group_ids
    return any((s['type'] == 'lab' and s['id'] in person.lab_ids) or
               (s['type'] == 'chair_group' and s['id'] in groups) for s in shares)


def can_manage(person: Person, row) -> bool:
    return person.is_admin or row['owner_lab_id'] in person.admin_lab_ids


def always_open(row) -> bool:
    """Bookable round the clock, every day: a booking may then run over days (a growth chamber's weeks)."""
    return row['open_from'] == '00:00' and row['open_until'] == '24:00' and row['weekdays'] == '1234567'


def to_dict(person: Person, row, shares: List[dict], booked: Optional[int] = None) -> dict:
    out = {k: row[k] for k in ('id', 'name', 'kind', 'location', 'description', 'colour', 'capacity',
                                'step_minutes', 'min_minutes', 'max_minutes', 'advance_days', 'open_from',
                                'open_until', 'weekdays', 'owner_lab_id', 'owner_lab', 'retired_at', 'created_by')}
    out.update({'needs_approval': bool(row['needs_approval']), 'everyone': bool(row['everyone']),
                'shares': shares, 'always_open': always_open(row), 'can_manage': can_manage(person, row)})
    if booked is not None:
        out['bookings'] = booked
    return out


def _get(conn, resource_id: str):
    row = conn.execute('SELECT * FROM resources WHERE id = ?', (resource_id,)).fetchone()
    if row is None:
        raise NotFound('No such room or equipment')
    return row


def visible(person: Person, include_retired: bool = False) -> List[dict]:
    """What this person may book (and, with include_retired, what they manage that is retired too)."""
    with connect() as conn:
        rows = conn.execute('SELECT * FROM resources ORDER BY kind COLLATE NOCASE, name COLLATE NOCASE').fetchall()
        counts = {r['resource_id']: r['n'] for r in conn.execute(
            "SELECT resource_id, count(*) AS n FROM bookings GROUP BY resource_id")}
        out = []
        for row in rows:
            shares = _shares(conn, row['id'])
            if not can_see(person, row, shares) and not can_manage(person, row):
                continue
            if row['retired_at'] and not (include_retired and can_manage(person, row)):
                continue
            out.append(to_dict(person, row, shares, counts.get(row['id'], 0)))
        return out


def get(person: Person, resource_id: str, conn=None) -> dict:
    own = conn is None
    conn = conn or connect()
    try:
        row = _get(conn, resource_id)
        shares = _shares(conn, resource_id)
        if not (can_see(person, row, shares) or can_manage(person, row)):
            raise NotFound('No such room or equipment')
        return to_dict(person, row, shares)
    finally:
        if own:
            conn.close()


def kinds() -> List[str]:
    with connect() as conn:
        return [r['kind'] for r in conn.execute(
            'SELECT DISTINCT kind FROM resources WHERE retired_at IS NULL ORDER BY kind COLLATE NOCASE')]


def sharing_choices(person: Person) -> dict:
    """For the form: the labs it can belong to (theirs to run), and the labs and chair groups to share with."""
    run = person.admin_lab_ids
    all_labs = labs()
    return {'own_labs': [lab for lab in all_labs if lab['id'] in run],
            'labs': all_labs, 'chair_groups': chair_groups()}


def _int(data, key, default, low, high, allow_none=False, what=''):
    value = data.get(key, default)
    if value in (None, '') and allow_none:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{what or key} is a whole number') from None
    if not low <= value <= high:
        raise ValueError(f'{what or key} is from {low} to {high}')
    return value


def _clean(person: Person, data: dict, old=None) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Send the room or equipment as JSON')
    pick = (lambda k, d: data[k] if k in data else (old[k] if old is not None else d))
    name = ' '.join(str(pick('name', '') or '').split())[:120]
    kind = ' '.join(str(pick('kind', '') or '').split())[:60]
    if not name:
        raise ValueError('Give it a name')
    if not kind:
        raise ValueError('Say what kind it is, e.g. Meeting room or Microscope')
    colour = str(pick('colour', '#2563eb') or '#2563eb')
    if not COLOUR.match(colour):
        raise ValueError('A colour is #rrggbb')
    merged = {k: pick(k, d) for k, d in (('capacity', 1), ('step_minutes', 30), ('min_minutes', 30),
                                          ('max_minutes', None), ('advance_days', None))}
    step = _int(merged, 'step_minutes', 30, 5, 60, what='The time step')
    if step not in STEPS:
        raise ValueError(f'The time step is one of {", ".join(map(str, STEPS))} minutes')
    capacity = _int(merged, 'capacity', 1, 1, 500, what='How many at once')
    shortest = _int(merged, 'min_minutes', step, 5, 60 * 24 * 366, what='The shortest booking')
    longest = _int(merged, 'max_minutes', None, 5, 60 * 24 * 366, allow_none=True, what='The longest booking')
    ahead = _int(merged, 'advance_days', None, 1, 3660, allow_none=True, what='How far ahead')
    if shortest % step or (longest and longest % step):
        raise ValueError(f'Booking lengths are whole steps of {step} minutes')
    if longest and longest < shortest:
        raise ValueError('The longest booking is shorter than the shortest')
    open_from = times.clean_hhmm(pick('open_from', '00:00'), '00:00')
    open_until = times.clean_hhmm(pick('open_until', '24:00'), '24:00')
    if times.minutes(open_until) <= times.minutes(open_from):
        raise ValueError('It closes before it opens')
    if times.minutes(open_from) % step or times.minutes(open_until) % step:
        raise ValueError(f'Opening hours fall on steps of {step} minutes')
    weekdays = ''.join(sorted(set(str(pick('weekdays', '1234567') or '')) & set('1234567')))
    if not weekdays:
        raise ValueError('Choose at least one day it can be booked on')
    owner = str(pick('owner_lab_id', '') or '')
    lab_names = {lab['id']: lab['name'] for lab in labs()}
    if owner not in lab_names:
        raise ValueError('Choose the lab it belongs to')
    if owner not in person.admin_lab_ids:
        raise Forbidden("Only that lab's lab admins (or an administrator) can give it that lab")
    shares = data.get('shares') if 'shares' in data else None
    known_groups = {g['id'] for g in chair_groups()}
    if shares is not None:
        if not isinstance(shares, list):
            raise ValueError('Shares are a list')
        clean = set()
        for s in shares:
            kind_, id_ = (s or {}).get('type'), str((s or {}).get('id') or '')
            if (kind_ == 'lab' and id_ in lab_names) or (kind_ == 'chair_group' and id_ in known_groups):
                if not (kind_ == 'lab' and id_ == owner):
                    clean.add((kind_, id_))
            else:
                raise ValueError('Share with a lab or a chair group of the suite')
        shares = sorted(clean)
    return {'name': name, 'kind': kind, 'colour': colour, 'capacity': capacity, 'step_minutes': step,
            'min_minutes': shortest, 'max_minutes': longest, 'advance_days': ahead,
            'open_from': open_from, 'open_until': open_until, 'weekdays': weekdays,
            'location': ' '.join(str(pick('location', '') or '').split())[:120],
            'description': str(pick('description', '') or '').strip()[:2000],
            # Kept for later, when some things need a manager's yes.
            'needs_approval': 1 if pick('needs_approval', 0) else 0,
            'everyone': 1 if pick('everyone', 0) else 0,
            'owner_lab_id': owner, 'owner_lab': lab_names[owner], 'shares': shares}


COLUMNS = ('name', 'kind', 'location', 'description', 'colour', 'capacity', 'step_minutes', 'min_minutes',
           'max_minutes', 'advance_days', 'open_from', 'open_until', 'weekdays', 'needs_approval', 'everyone',
           'owner_lab_id', 'owner_lab')


def _set_shares(conn, resource_id: str, shares) -> None:
    if shares is None:
        return
    conn.execute('DELETE FROM resource_shares WHERE resource_id = ?', (resource_id,))
    conn.executemany('INSERT INTO resource_shares (resource_id, target_type, target_id) VALUES (?, ?, ?)',
                     [(resource_id, t, i) for t, i in shares])


def create(person: Person, data: dict) -> dict:
    if not person.can_add:
        raise Forbidden('Lab admins add rooms and equipment')
    clean = _clean(person, data)
    if clean['shares'] is None:
        # New: shared with its lab's chair group, which can be changed.
        group = next((lab['chair_group_id'] for lab in labs() if lab['id'] == clean['owner_lab_id']), None)
        clean['shares'] = [('chair_group', group)] if group else []
    resource_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(f'INSERT INTO resources (id, {", ".join(COLUMNS)}, created_by) '
                     f'VALUES (?, {", ".join("?" * len(COLUMNS))}, ?)',
                     (resource_id, *[clean[c] for c in COLUMNS], person.username))
        _set_shares(conn, resource_id, clean['shares'])
        return get(person, resource_id, conn)


def update(person: Person, resource_id: str, data: dict) -> dict:
    with connect() as conn:
        old = _get(conn, resource_id)
        if not can_manage(person, old):
            raise Forbidden("Only its lab's lab admins (or an administrator) change it")
        clean = _clean(person, data, old)
        conn.execute(f'UPDATE resources SET {", ".join(f"{c} = ?" for c in COLUMNS)}, '
                     'updated_at = CURRENT_TIMESTAMP WHERE id = ?', (*[clean[c] for c in COLUMNS], resource_id))
        _set_shares(conn, resource_id, clean['shares'])
        return get(person, resource_id, conn)


def retire(person: Person, resource_id: str, retired: bool = True) -> dict:
    with connect() as conn:
        row = _get(conn, resource_id)
        if not can_manage(person, row):
            raise Forbidden("Only its lab's lab admins (or an administrator) retire it")
        conn.execute('UPDATE resources SET retired_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (times.store(times.now()) if retired else None, resource_id))
        return get(person, resource_id, conn)


def delete(person: Person, resource_id: str) -> None:
    with connect() as conn:
        row = _get(conn, resource_id)
        if not can_manage(person, row):
            raise Forbidden("Only its lab's lab admins (or an administrator) remove it")
        if conn.execute('SELECT 1 FROM bookings WHERE resource_id = ? LIMIT 1', (resource_id,)).fetchone():
            raise ValueError('It has been booked: retire it instead, which keeps its bookings')
        conn.execute('DELETE FROM resources WHERE id = ?', (resource_id,))


def rows_by_id(conn, ids) -> Dict[str, object]:
    ids = list(ids)
    if not ids:
        return {}
    return {r['id']: r for r in conn.execute(
        f'SELECT * FROM resources WHERE id IN ({", ".join("?" * len(ids))})', ids)}
