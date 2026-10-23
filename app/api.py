"""The booking tool's API, under /booking/api. Everything needs someone signed in (people.current)."""

from datetime import date
from functools import wraps

from flask import Blueprint, jsonify, request

from app import bookings, people, resources
from app.bookings import Clash
from app.resources import Forbidden, NotFound

api = Blueprint('api', __name__)


def signed_in(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        person = people.current()
        if person is None:
            return jsonify({'error': 'Sign in first'}), 401
        try:
            return fn(person, *args, **kwargs)
        except Clash as exc:
            return jsonify({'error': str(exc), 'clash': True}), 409
        except Forbidden as exc:
            return jsonify({'error': str(exc)}), 403
        except NotFound as exc:
            return jsonify({'error': str(exc)}), 404
        except (ValueError, KeyError) as exc:
            return jsonify({'error': str(exc).strip("'")}), 400
    return wrapper


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('Send JSON')
    return data


@api.route('/me')
@signed_in
def me(person):
    return jsonify({'person': person.to_dict(), 'kinds': resources.kinds()})


@api.route('/people')
@signed_in
def everyone(person):
    """Everyone with an account, to tag in a booking."""
    return jsonify({'people': people.everyone()})


# --- rooms and equipment -------------------------------------------------------

@api.route('/resources')
@signed_in
def list_resources(person):
    return jsonify({'resources': resources.visible(person, include_retired=request.args.get('retired') == '1'),
                    'kinds': resources.kinds()})


@api.route('/resources/choices')
@signed_in
def resource_choices(person):
    return jsonify(resources.sharing_choices(person))


@api.route('/resources', methods=['POST'])
@signed_in
def add_resource(person):
    return jsonify({'resource': resources.create(person, body())}), 201


@api.route('/resources/<resource_id>', methods=['PUT'])
@signed_in
def change_resource(person, resource_id):
    return jsonify({'resource': resources.update(person, resource_id, body())})


@api.route('/resources/<resource_id>/retire', methods=['POST'])
@signed_in
def retire_resource(person, resource_id):
    return jsonify({'resource': resources.retire(person, resource_id, bool(body().get('retired', True)))})


@api.route('/resources/<resource_id>', methods=['DELETE'])
@signed_in
def remove_resource(person, resource_id):
    resources.delete(person, resource_id)
    return jsonify({'ok': True})


# --- bookings ------------------------------------------------------------------

@api.route('/bookings')
@signed_in
def list_bookings(person):
    """?from=&to= (ISO times), and resource=id,id or kind=..."""
    ids = [i for i in (request.args.get('resource') or '').split(',') if i]
    return jsonify(bookings.in_range(person, request.args.get('from', ''), request.args.get('to', ''),
                                     ids or None, request.args.get('kind') or None))


@api.route('/bookings/mine')
@signed_in
def my_bookings(person):
    return jsonify({'bookings': bookings.mine(person, int(request.args.get('past') or 0))})


@api.route('/bookings', methods=['POST'])
@signed_in
def book(person):
    return jsonify({'booking': bookings.create(person, body())}), 201


@api.route('/bookings/<booking_id>')
@signed_in
def one_booking(person, booking_id):
    return jsonify({'booking': bookings.get(person, booking_id)})


@api.route('/bookings/<booking_id>', methods=['PUT'])
@signed_in
def change_booking(person, booking_id):
    return jsonify({'booking': bookings.update(person, booking_id, body())})


@api.route('/bookings/<booking_id>', methods=['DELETE'])
@signed_in
def cancel_booking(person, booking_id):
    bookings.cancel(person, booking_id)
    return jsonify({'ok': True})


@api.route('/bookings/<booking_id>/people/me', methods=['DELETE'])
@signed_in
def leave_booking(person, booking_id):
    bookings.leave(person, booking_id)
    return jsonify({'ok': True})


@api.route('/free')
@signed_in
def free_slots(person):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD&minutes=&q=&kind=&capacity=&time_from=HH:MM&time_until=HH:MM"""
    a = request.args
    try:
        day_from = date.fromisoformat(a.get('from', ''))
        day_to = date.fromisoformat(a.get('to', '') or a.get('from', ''))
    except ValueError:
        raise ValueError('Give the days as YYYY-MM-DD') from None
    return jsonify({'slots': bookings.free(
        person, day_from=day_from, day_to=day_to, minutes=int(a.get('minutes') or 60), query=a.get('q', ''),
        kind=a.get('kind', ''), min_capacity=int(a.get('capacity') or 1),
        time_from=a.get('time_from') or None, time_until=a.get('time_until') or None)})
