# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.2] - 2026-10-23

### Changed
- The suite it runs in is called Trellis Tools, as its docs now say.

## [0.1.1] - 2026-10-23

### Changed
- Someone who has left (archived in the suite) is no longer offered to tag, and what they booked for
  after they left is freed; what they booked before stays.

## [0.1.0] - 2026-10-23

### Added
- Rooms and equipment, added, changed, retired and removed by their lab's lab admins: a kind, where it
  is, a colour, and its rules (how many at once, steps, shortest and longest booking, how far ahead,
  opening hours and days, or round the clock for bookings over days).
- Shared with its lab and with other labs, chair groups or everyone.
- A week calendar for each thing, today highlighted with a line at the time now, and every thing of a
  kind side by side for a day; drag across free time to book it.
- Finding a free slot, by name, kind, place, places, days, length and time of day.
- People tagged in a booking, who see it in their bookings and can take themselves out.
- Unavailable time, set by a thing's managers.
- No double booking: checked inside one write transaction against every overlapping booking.
- Dashboard tabs in the suite: My bookings, and Rooms & equipment for lab admins.
