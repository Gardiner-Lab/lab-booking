# Booking

The Gardiner Lab suite's calendar for rooms and equipment: meeting rooms,
microscopes, growth chambers, anything a lab books ahead.

- **Rooms and equipment are added by people, not code.** A lab's lab admins (and
  the suite's administrators) add them, with a kind (free text: Meeting room,
  Microscope, ...), where they are, a colour, and their rules: how many bookings at
  once (seats, shelves, blocks), the steps bookings start and end on, the
  shortest and longest booking, how far ahead, and when they are open. Retired,
  something is no longer booked and keeps its bookings; something never booked
  can be removed.
- **Shared** with its own lab, and with any other labs, chair groups or everyone.
  Whoever it is shared with sees it and books it.
- **A week calendar** for each thing, today highlighted with a line at the time
  now; or every thing of a kind side by side for a day. Drag across free time to
  book it; click a booking to see, change or cancel it.
- **Find a free slot**: by name, kind, place or description, at least so many
  places, over a span of days, for so long, between two times of day.
- **People in a booking**: tag colleagues; it is in their bookings too.
- **Unavailable time**: a thing's managers block time (maintenance, a service
  visit), when nobody books it.
- **No double booking**: each booking is checked against the ones it overlaps
  inside one write transaction.
- **In the Lab Notebook**: each day's page shows the day's bookings of whoever
  it belongs to, booked or tagged in (Lab Notebook 0.14.0 on).

Approval of bookings by a thing's managers is prepared for (`needs_approval`) but
not switched on: every booking stands.

## Running it

It runs in the [Gardiner Lab suite](https://github.com/Gardiner-Lab/gardiner-lab-suite),
behind its proxy, which says who is signed in (`X-Suite-User`). It reads the
suite's accounts and labs and never writes them.

| Variable | Default | |
| --- | --- | --- |
| `BOOKING_DATABASE_PATH` | `/booking/booking.db` | its own database |
| `SUITE_DATABASE_PATH` | `/suite/suite.db` | labs, lab admins and chair groups (read) |
| `MOCLO_DATABASE_PATH` | `/moclo/moclo.db` | the suite's accounts (read) |
| `URL_PREFIX` | `/booking` | where the proxy mounts it |
| `TZ` | `Europe/Amsterdam` | the lab's time: opening hours and days |
| `NOTEBOOK_URL` | `/notebook` | the Lab Notebook |

Times are stored in UTC, so the weeks the clocks change shift nothing.

## Developing

    pip install -r requirements.txt
    pytest -q
    node --check app/static/js/booking.js

## Licence

GPL-3.0, as the rest of the suite.
