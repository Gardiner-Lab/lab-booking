"""
Who is signed in, their labs and chair groups, and who runs which lab.

The booking tool has no accounts of its own: it runs inside the Gardiner Lab
suite, whose proxy says who is signed in in an X-Suite-User header (set on
every request, and stripped from what the browser sends). Administrators are
marked in the suite's account directory (MoClo's users table); labs, who is a
lab admin in each, and the chair groups labs are in, are in the suite's own
database. Both are read, never written.

Only run this behind the suite's proxy: reachable directly, anyone could set
the header themselves.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from flask import g, request

HEADER = 'X-Suite-User'


def _read(path: str, sql: str, args=()) -> List[sqlite3.Row]:
    if not path or not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def directory_path() -> str:
    return os.environ.get('MOCLO_DATABASE_PATH', '/moclo/moclo.db')


def suite_path() -> str:
    return os.environ.get('SUITE_DATABASE_PATH', '/suite/suite.db')


def _has_column(table: str, column: str) -> bool:
    return column in {r['name'] for r in _read(suite_path(), f'PRAGMA table_info({table})')}


def labs() -> List[dict]:
    """Every lab: {'id', 'name', 'chair_group_id'}."""
    group = 'chair_group_id' if _has_column('labs', 'chair_group_id') else 'NULL AS chair_group_id'
    return [{'id': str(r['id']), 'name': r['name'],
             'chair_group_id': str(r['chair_group_id']) if r['chair_group_id'] is not None else None}
            for r in _read(suite_path(), f'SELECT id, name, {group} FROM labs ORDER BY name COLLATE NOCASE')]


def chair_groups() -> List[dict]:
    """Every chair group: {'id', 'name', 'labs': [lab ids]}."""
    in_group: Dict[str, List[str]] = {}
    for lab in labs():
        if lab['chair_group_id']:
            in_group.setdefault(lab['chair_group_id'], []).append(lab['id'])
    return [{'id': str(r['id']), 'name': r['name'], 'labs': in_group.get(str(r['id']), [])}
            for r in _read(suite_path(), 'SELECT id, name FROM chair_groups ORDER BY name COLLATE NOCASE')]


def memberships(username: str) -> List[dict]:
    """Their labs, first joined first: {'lab_id', 'lab', 'role', 'lab_admin'}."""
    admin = 'm.lab_admin' if _has_column('lab_members', 'lab_admin') else '0 AS lab_admin'
    rows = _read(suite_path(), f'SELECT labs.id AS lab_id, labs.name AS lab, m.role, {admin} '
                               'FROM lab_members m JOIN labs ON labs.id = m.lab_id '
                               'WHERE m.username = ? ORDER BY m.joined_at, m.rowid', (username,))
    return [{'lab_id': str(r['lab_id']), 'lab': r['lab'], 'role': r['role'] or 'member',
             # A lab admin is a lab lead who also runs the lab's people, and here its equipment.
             'lab_admin': bool(r['lab_admin']) and (r['role'] == 'lab_lead')} for r in rows]


def everyone() -> List[str]:
    """Everyone with an account, by name, to tag in bookings."""
    return [r['username'] for r in _read(directory_path(), 'SELECT username FROM users ORDER BY username COLLATE NOCASE')
            if r['username'] != 'system']


@dataclass
class Person:
    username: str
    is_admin: bool = False
    labs: List[dict] = field(default_factory=list)

    @property
    def lab_ids(self) -> Set[str]:
        return {m['lab_id'] for m in self.labs}

    @property
    def admin_lab_ids(self) -> Set[str]:
        """The labs whose rooms and equipment they manage: lab admins their own; administrators every lab."""
        if self.is_admin:
            return {lab['id'] for lab in labs()}
        return {m['lab_id'] for m in self.labs if m['lab_admin']}

    @property
    def chair_group_ids(self) -> Set[str]:
        mine = self.lab_ids
        return {lab['chair_group_id'] for lab in labs() if lab['id'] in mine and lab['chair_group_id']}

    @property
    def can_add(self) -> bool:
        return bool(self.admin_lab_ids)

    def to_dict(self) -> dict:
        return {'username': self.username, 'is_admin': self.is_admin,
                'labs': [{'id': m['lab_id'], 'name': m['lab'], 'lab_admin': m['lab_admin']} for m in self.labs],
                'can_add': self.can_add,
                'role': 'admin' if self.is_admin else 'lab_admin' if any(m['lab_admin'] for m in self.labs) else 'member'}


def current() -> Optional[Person]:
    """Whoever the suite says is signed in, for this request."""
    if 'person' in g:
        return g.person
    username = request.headers.get(HEADER, '').strip()
    person = None
    if username:
        rows = _read(directory_path(), 'SELECT is_admin FROM users WHERE username = ?', (username,))
        person = Person(username=username, is_admin=bool(rows and rows[0]['is_admin']), labs=memberships(username))
    g.person = person
    return person
