"""The booking tool: rooms and equipment, who books them, the rules, clashes, people, the search."""

import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

AMS = ZoneInfo('Europe/Amsterdam')


def weekday_ahead(days=3, weekday=0):
    """A day at least so many days ahead, on a given weekday (0 Monday)."""
    d = date.today() + timedelta(days=days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def at(day, hhmm):
    h, m = map(int, hhmm.split(':'))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=AMS).isoformat()


ROOM = {'name': 'Meeting room 2.14', 'kind': 'Meeting room', 'location': 'Kruyt 2.14', 'capacity': 1,
        'step_minutes': 30, 'min_minutes': 30, 'max_minutes': 240, 'open_from': '08:00', 'open_until': '18:00',
        'weekdays': '12345', 'owner_lab_id': 'lab-g'}


def add(client, **changes):
    res = client.post('/api/resources', json={**ROOM, **changes})
    assert res.status_code == 201, res.get_json()
    return res.get_json()['resource']


def book(client, resource, day, start, end, **extra):
    return client.post('/api/bookings', json={'resource_id': resource['id'], 'start': at(day, start),
                                              'end': at(day, end), **extra})


# --- rooms and equipment -------------------------------------------------------

def test_lab_admins_add_equipment_for_their_own_lab(as_user):
    ana = as_user('ana')
    room = add(ana)
    assert room['owner_lab'] == 'Gardiner Lab' and room['can_manage']
    # New: shared with the lab's chair group.
    assert room['shares'] == [{'type': 'chair_group', 'id': 'cg-plant'}]
    assert ana.post('/api/resources', json={**ROOM, 'owner_lab_id': 'lab-s'}).status_code == 403
    for name in ('lead', 'ben'):        # a lab lead who is not lab admin, a member
        assert as_user(name).post('/api/resources', json=ROOM).status_code == 403
    assert as_user('boss').post('/api/resources', json={**ROOM, 'owner_lab_id': 'lab-j'}).status_code == 201


def test_equipment_is_seen_by_its_lab_and_whoever_it_is_shared_with(as_user):
    ana = as_user('ana')
    room = add(ana)
    seen = lambda who: [r['id'] for r in as_user(who).get('/api/resources').get_json()['resources']]
    assert room['id'] in seen('ben') and room['id'] in seen('sam')      # own lab; the chair group
    assert room['id'] not in seen('jo') and room['id'] not in seen('lou')
    # Shared with another chair group and another lab too.
    ana.put(f"/api/resources/{room['id']}", json={'shares': [{'type': 'chair_group', 'id': 'cg-chem'},
                                                              {'type': 'lab', 'id': 'lab-l'}]})
    assert room['id'] in seen('jo') and room['id'] in seen('lou') and room['id'] not in seen('sam')
    # Or with everyone.
    ana.put(f"/api/resources/{room['id']}", json={'shares': [], 'everyone': True})
    assert all(room['id'] in seen(u) for u in ('sam', 'jo', 'lou'))
    # Not shared, not bookable.
    ana.put(f"/api/resources/{room['id']}", json={'everyone': False})
    assert book(as_user('sam'), room, weekday_ahead(), '10:00', '11:00').status_code == 404


def test_only_its_managers_change_retire_or_remove_it(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    room = add(ana)
    assert ben.put(f"/api/resources/{room['id']}", json={'name': 'Mine'}).status_code == 403
    assert ana.put(f"/api/resources/{room['id']}", json={'name': 'Room 2.14 (big)'}).get_json()['resource']['name'] == 'Room 2.14 (big)'
    assert ben.delete(f"/api/resources/{room['id']}").status_code == 403
    assert book(ben, room, weekday_ahead(), '10:00', '11:00').status_code == 201
    # Booked once: retired instead, which keeps its bookings.
    assert ana.delete(f"/api/resources/{room['id']}").status_code == 400
    ana.post(f"/api/resources/{room['id']}/retire", json={'retired': True})
    assert room['id'] not in [r['id'] for r in ben.get('/api/resources').get_json()['resources']]
    assert room['id'] in [r['id'] for r in ana.get('/api/resources?retired=1').get_json()['resources']]
    assert book(ana, room, weekday_ahead(), '12:00', '13:00').status_code == 400
    ana.post(f"/api/resources/{room['id']}/retire", json={'retired': False})
    assert book(ana, room, weekday_ahead(), '12:00', '13:00').status_code == 201
    # Never booked: removed outright.
    scope = add(ana, name='Old scope', kind='Microscope')
    assert ana.delete(f"/api/resources/{scope['id']}").status_code == 200


def test_equipment_settings_are_checked(as_user):
    ana = as_user('ana')
    for bad in ({'name': ''}, {'kind': ''}, {'step_minutes': 7}, {'min_minutes': 45}, {'max_minutes': 15},
                {'open_from': '18:00', 'open_until': '08:00'}, {'open_from': '08:10'}, {'weekdays': ''},
                {'colour': 'red'}, {'capacity': 0}, {'shares': [{'type': 'lab', 'id': 'nowhere'}]}):
        assert ana.post('/api/resources', json={**ROOM, **bad}).status_code == 400, bad
    kinds = ana.get('/api/me').get_json()['kinds']
    add(ana, kind='Growth chamber')
    assert 'Growth chamber' in ana.get('/api/me').get_json()['kinds'] and kinds == []


# --- booking -----------------------------------------------------------------

def test_booking_within_the_rules(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    room = add(ana, advance_days=30)
    day = weekday_ahead()
    assert book(ben, room, day, '10:00', '11:30').status_code == 201
    errors = {
        'steps': book(ben, room, day, '12:15', '13:15'),
        'too short': book(ben, room, day, '12:00', '12:00'),
        'too long': book(ben, room, day, '08:00', '13:00'),
        'before opening': book(ben, room, day, '07:00', '09:00'),
        'after closing': book(ben, room, day, '17:00', '18:30'),
        'weekend': book(ben, room, weekday_ahead(weekday=5), '10:00', '11:00'),
        'too far ahead': book(ben, room, weekday_ahead(40), '10:00', '11:00'),
        'past': book(ben, room, date.today() - timedelta(days=7), '10:00', '11:00'),
    }
    for why, res in errors.items():
        assert res.status_code == 400, (why, res.get_json())
    assert 'at most 30 days ahead' in errors['too far ahead'].get_json()['error']
    # Its managers book further ahead.
    assert book(ana, room, weekday_ahead(40), '10:00', '11:00').status_code == 201


def test_no_double_booking(as_user):
    ana, ben, cal = as_user('ana'), as_user('ben'), as_user('cal')
    room = add(ana)
    day = weekday_ahead()
    assert book(ben, room, day, '10:00', '11:00').status_code == 201
    res = book(cal, room, day, '10:30', '11:30')
    assert res.status_code == 409 and 'booked by ben' in res.get_json()['error']
    # Back to back is fine.
    assert book(cal, room, day, '11:00', '12:00').status_code == 201
    assert book(cal, room, day, '09:00', '10:00').status_code == 201


def test_two_at_once_cannot_both_have_it(as_user, world):
    ana = as_user('ana')
    room = add(ana)
    day = weekday_ahead()
    results = []

    def go(name):
        client = world['app'].test_client()
        client.environ_base['HTTP_X_SUITE_USER'] = name
        results.append(book(client, room, day, '14:00', '15:00').status_code)
    threads = [threading.Thread(target=go, args=(n,)) for n in ('ben', 'cal', 'sam', 'lead')]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409, 409, 409]


def test_capacity_lets_that_many_book_at_once(as_user):
    ana = as_user('ana')
    chamber = add(ana, name='Growth chamber 3', kind='Growth chamber', capacity=2, step_minutes=60, min_minutes=60,
                  max_minutes=None, open_from='00:00', open_until='24:00', weekdays='1234567')
    day = weekday_ahead()
    later = day + timedelta(days=14)
    # Always open: a booking runs over days.
    first = as_user('ben').post('/api/bookings', json={'resource_id': chamber['id'], 'start': at(day, '09:00'),
                                                      'end': at(later, '09:00')})
    assert first.status_code == 201
    assert book(as_user('cal'), chamber, day + timedelta(days=2), '09:00', '17:00').status_code == 201
    res = book(as_user('sam'), chamber, day + timedelta(days=2), '12:00', '13:00')
    assert res.status_code == 409 and 'All 2 places' in res.get_json()['error']
    assert book(as_user('sam'), chamber, day + timedelta(days=2), '17:00', '18:00').status_code == 201


def test_unavailable_time_blocks_bookings(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    room = add(ana)
    day = weekday_ahead()
    assert book(ben, room, day, '13:00', '14:00', kind='closed').status_code == 403
    assert book(ben, room, day, '10:00', '11:00').status_code == 201
    # Over someone's booking: they come first.
    assert book(ana, room, day, '09:00', '12:00', kind='closed', title='Projector repair').status_code == 409
    assert book(ana, room, day, '12:00', '16:00', kind='closed', title='Projector repair').status_code == 201
    res = book(ben, room, day, '13:00', '14:00')
    assert res.status_code == 409 and 'unavailable' in res.get_json()['error'] and 'Projector repair' in res.get_json()['error']


def test_who_changes_and_cancels(as_user):
    ana, ben, cal = as_user('ana'), as_user('ben'), as_user('cal')
    room = add(ana)
    day = weekday_ahead()
    booking = book(ben, room, day, '10:00', '11:00', title='Lab meeting').get_json()['booking']
    assert booking['can_edit'] and booking['mine']
    assert cal.put(f"/api/bookings/{booking['id']}", json={'title': 'Mine now'}).status_code == 403
    assert cal.delete(f"/api/bookings/{booking['id']}").status_code == 403
    moved = ben.put(f"/api/bookings/{booking['id']}", json={'start': at(day, '15:00'), 'end': at(day, '16:30')})
    assert moved.status_code == 200 and moved.get_json()['booking']['start'].endswith(':00:00Z')
    # Moving onto someone else's time is a clash; onto its own old time is not.
    other = book(cal, room, day, '10:00', '11:00').get_json()['booking']
    assert ben.put(f"/api/bookings/{booking['id']}", json={'start': at(day, '10:30'), 'end': at(day, '11:30')}).status_code == 409
    assert ben.put(f"/api/bookings/{booking['id']}", json={'start': at(day, '16:00'), 'end': at(day, '17:00')}).status_code == 200
    # Its managers can cancel anyone's.
    assert ana.delete(f"/api/bookings/{other['id']}").status_code == 200
    assert book(cal, room, day, '10:00', '11:00').status_code == 201


def test_people_are_tagged_in_a_booking(as_user):
    ana, ben, cal = as_user('ana'), as_user('ben'), as_user('cal')
    room = add(ana)
    day = weekday_ahead()
    res = book(ben, room, day, '10:00', '11:00', title='Project meeting', people=['Cal', 'jo', 'ben', 'cal'])
    booking = res.get_json()['booking']
    assert booking['people'] == ['cal', 'jo']          # the booker is not tagged in their own
    assert book(ben, room, day, '12:00', '13:00', people=['nobody']).status_code == 400
    # In the bookings of those tagged, who may see it even without seeing the room.
    mine = cal.get('/api/bookings/mine').get_json()['bookings']
    assert [b['id'] for b in mine] == [booking['id']] and mine[0]['tagged'] and not mine[0]['can_edit']
    assert as_user('jo').get(f"/api/bookings/{booking['id']}").status_code == 200
    assert as_user('lou').get(f"/api/bookings/{booking['id']}").status_code == 404
    # The booker changes who is in it; someone tagged takes themselves out.
    ben.put(f"/api/bookings/{booking['id']}", json={'people': ['cal', 'sam']})
    assert as_user('sam').get('/api/bookings/mine').get_json()['bookings'][0]['id'] == booking['id']
    assert cal.delete(f"/api/bookings/{booking['id']}/people/me").status_code == 200
    assert cal.get('/api/bookings/mine').get_json()['bookings'] == []
    assert cal.delete(f"/api/bookings/{booking['id']}/people/me").status_code == 404


def test_the_week_shows_what_is_booked(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    room = add(ana)
    scope = add(ana, name='Confocal', kind='Microscope')
    day = weekday_ahead()
    book(ben, room, day, '10:00', '11:00')
    book(ben, scope, day, '10:00', '12:00')
    cancelled = book(ben, room, day, '14:00', '15:00').get_json()['booking']
    ben.delete(f"/api/bookings/{cancelled['id']}")
    week = {'from': at(day - timedelta(days=day.weekday()), '00:00'),
            'to': at(day - timedelta(days=day.weekday()) + timedelta(days=7), '00:00')}
    one = ben.get('/api/bookings', query_string={**week, 'resource': room['id']}).get_json()
    assert len(one['bookings']) == 1 and one['bookings'][0]['resource']['name'] == 'Meeting room 2.14'
    kind = ben.get('/api/bookings', query_string={**week, 'kind': 'microscope'}).get_json()
    assert [b['resource_id'] for b in kind['bookings']] == [scope['id']]
    assert as_user('lou').get('/api/bookings', query_string=week).get_json()['bookings'] == []
    assert ben.get('/api/bookings', query_string={'from': week['from'], 'to': at(day + timedelta(days=90), '00:00')}).status_code == 400


def test_finding_a_free_slot(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    room = add(ana)
    add(ana, name='Seminar room', capacity=1, location='Kruyt 1.01', description='Projector, 20 seats')
    day = weekday_ahead()
    book(ben, room, day, '08:00', '12:00')
    assert book(ben, room, day, '13:00', '17:00').status_code == 201
    assert book(ben, room, day, '17:00', '18:00').status_code == 201
    q = {'from': day.isoformat(), 'to': day.isoformat(), 'minutes': 60}
    slots = ben.get('/api/free', query_string={**q, 'q': '2.14'}).get_json()['slots']
    assert [(s['start'][11:16], s['end'][11:16]) for s in slots] == [(datetime.fromisoformat(at(day, '12:00')).astimezone(ZoneInfo('UTC')).strftime('%H:%M'),
                                                                      datetime.fromisoformat(at(day, '13:00')).astimezone(ZoneInfo('UTC')).strftime('%H:%M'))]
    assert ben.get('/api/free', query_string={**q, 'q': '2.14', 'minutes': 90}).get_json()['slots'] == []
    # By kind, between two times of day: both rooms, the seminar room free all afternoon.
    found = ben.get('/api/free', query_string={**q, 'kind': 'Meeting room', 'time_from': '12:00',
                                               'time_until': '17:00'}).get_json()['slots']
    assert sorted(s['resource']['name'] for s in found) == ['Meeting room 2.14', 'Seminar room']
    assert ben.get('/api/free', query_string={**q, 'q': 'projector'}).get_json()['slots'][0]['resource']['name'] == 'Seminar room'
    # Not shared with them: not found.
    assert as_user('lou').get('/api/free', query_string=q).get_json()['slots'] == []


def test_the_page_and_the_dashboard_tabs(as_user, world):
    assert as_user('ben').get('/').status_code == 200
    anon = world['app'].test_client()
    assert anon.get('/').status_code == 302 and anon.get('/api/resources').status_code == 401
    tabs = anon.get('/suite-manifest.json').get_json()['tabs']
    assert {t['id'] for t in tabs} == {'booking-mine', 'booking-manage'}
    assert as_user('ana').get('/api/me').get_json()['person']['role'] == 'lab_admin'
    assert as_user('ben').get('/api/me').get_json()['person']['can_add'] is False
