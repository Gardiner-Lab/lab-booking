"""
Booking: the Gardiner Lab suite's calendar for rooms and equipment.

Meeting rooms, microscopes, growth chambers: whatever a lab's lab admins add,
shared with the labs and chair groups they choose, booked ahead on a week
calendar or by searching for a free slot, with the people in each booking.
Bookings show in the Lab Notebook, on the day.
"""

import os

from flask import Flask, redirect, render_template, request

APP_VERSION = '0.1.1'

# The tabs this tool adds to the suite's dashboard (see the suite's pages/dashboard.html).
MANIFEST = {
    'tool': 'Booking',
    'tabs': [
        {'id': 'booking-mine', 'title': 'My bookings', 'icon': '📅', 'section': 'me',
         'src': '/booking/?embed=1#mine'},
        {'id': 'booking-manage', 'title': 'Rooms & equipment', 'icon': '🔬', 'section': 'admin',
         'roles': ['admin', 'lab_admin'], 'src': '/booking/?embed=1#manage'},
    ],
}


class PrefixMiddleware:
    """Mount the app under URL_PREFIX (/booking), as the suite's proxy passes the full path."""

    def __init__(self, wsgi_app, prefix: str):
        self.wsgi_app = wsgi_app
        self.prefix = '/' + prefix.strip('/')

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == self.prefix or path.startswith(self.prefix + '/'):
            environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + self.prefix
            environ['PATH_INFO'] = path[len(self.prefix):] or '/'
        return self.wsgi_app(environ, start_response)


def create_app() -> Flask:
    from app import db, people
    from app.api import api

    app = Flask(__name__)
    db.initialize(os.environ.get('BOOKING_DATABASE_PATH', '/booking/booking.db'))
    app.register_blueprint(api, url_prefix='/api')

    def links() -> dict:
        return {
            'suite_home': os.environ.get('SUITE_HOME_URL', '/'),
            'notebook': os.environ.get('NOTEBOOK_URL', '/notebook').rstrip('/'),
            'logout': os.environ.get('SUITE_LOGOUT_URL', '/account/logout'),
        }

    @app.route('/')
    def booking_page():
        person = people.current()
        if person is None:
            login = os.environ.get('SUITE_LOGIN_URL', '/account/login')
            return redirect(f'{login}?next={request.script_root}/')
        return render_template('booking.html', version=APP_VERSION, person=person, links=links(),
                               embed=request.args.get('embed') == '1')

    @app.route('/suite-manifest.json')
    def suite_manifest():
        return MANIFEST

    @app.route('/health')
    def health():
        return {'status': 'healthy', 'version': APP_VERSION}

    prefix = os.environ.get('URL_PREFIX', '').strip('/')
    if prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix)
    return app


app = create_app() if os.environ.get('BOOKING_NO_APP') != '1' else None

if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', 5007)), debug=True)
