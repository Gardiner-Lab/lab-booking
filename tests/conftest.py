import os
import sqlite3
import tempfile

import pytest

os.environ['BOOKING_NO_APP'] = '1'
os.environ['TZ'] = 'Europe/Amsterdam'


def _make(path, script, rows=()):
    conn = sqlite3.connect(path)
    conn.executescript(script)
    for sql, args in rows:
        conn.execute(sql, args)
    conn.commit()
    conn.close()


@pytest.fixture()
def world(monkeypatch):
    """
    A suite with two chair groups: Plant Biology (the Gardiner and Smith labs) and
    Chemistry (the Jones lab), and the Lone lab in none. ana leads and runs the
    Gardiner lab (lab admin); lead leads it without running it; ben and cal are
    members; sam is in Smith, jo in Jones, lou in Lone; boss is an administrator.
    """
    d = tempfile.mkdtemp()
    paths = {k: os.path.join(d, f'{k}.db') for k in ('booking', 'moclo', 'suite')}
    users = ('ana', 'lead', 'ben', 'cal', 'sam', 'jo', 'lou', 'boss')
    _make(paths['moclo'], 'CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE, is_admin INTEGER DEFAULT 0);',
          [('INSERT INTO users VALUES (?, ?, ?)', (u, u, 1 if u == 'boss' else 0)) for u in users + ('system',)])
    _make(paths['suite'],
          'CREATE TABLE chair_groups (id TEXT PRIMARY KEY, name TEXT);'
          'CREATE TABLE labs (id TEXT PRIMARY KEY, name TEXT, chair_group_id TEXT);'
          'CREATE TABLE lab_members (username TEXT, lab_id TEXT, role TEXT, lab_admin INTEGER DEFAULT 0, '
          'joined_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (username, lab_id));',
          [('INSERT INTO chair_groups VALUES (?, ?)', g) for g in (('cg-plant', 'Plant Biology'), ('cg-chem', 'Chemistry'))]
          + [('INSERT INTO labs VALUES (?, ?, ?)', lab) for lab in
             (('lab-g', 'Gardiner Lab', 'cg-plant'), ('lab-s', 'Smith Lab', 'cg-plant'),
              ('lab-j', 'Jones Lab', 'cg-chem'), ('lab-l', 'Lone Lab', None))]
          + [('INSERT INTO lab_members (username, lab_id, role, lab_admin) VALUES (?, ?, ?, ?)', m) for m in
             (('ana', 'lab-g', 'lab_lead', 1), ('lead', 'lab-g', 'lab_lead', 0), ('ben', 'lab-g', 'member', 0),
              ('cal', 'lab-g', 'member', 0), ('sam', 'lab-s', 'member', 0), ('jo', 'lab-j', 'member', 0),
              ('lou', 'lab-l', 'member', 0))])
    for key, env in (('booking', 'BOOKING_DATABASE_PATH'), ('moclo', 'MOCLO_DATABASE_PATH'), ('suite', 'SUITE_DATABASE_PATH')):
        monkeypatch.setenv(env, paths[key])
    from app import db
    db._path = None
    from app.main import create_app
    app = create_app()
    app.testing = True
    return {'app': app, 'paths': paths}


@pytest.fixture()
def as_user(world):
    def make(username):
        client = world['app'].test_client()
        client.environ_base['HTTP_X_SUITE_USER'] = username
        return client
    return make
