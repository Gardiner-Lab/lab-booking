# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.5.0] - 2026-11-08

### Demo
- **The teaching demo sees only the demo's.** Someone in the suite's demo (its chair group, recorded by the suite's demo) sees only the demo labs' rooms and equipment, even ones a real lab shares with everyone or with a demo lab, can tag only the demo's people, and is offered only the demo's labs and chair group to share with.

## [0.4.0] - 2026-10-31

### Added
- Every page's top bar now links to **all** the suite's tools, not a few: a row of them beside the tool's own
  name, the one you are on marked, names shown where there is room and icons alone when it is narrow. The list
  is the suite's own (`/tools.json`), so a tool added there appears here too; on its own, outside the suite,
  nothing is added.
- The bar is in two rows: the suite's on top — its tools, the dashboard, help, about and who is signed in —
  and this tool's own pages on the row under it, as the MoClo tool and Lab Stocks already read. A page with no
  pages of its own keeps a single row.

## [0.3.0] - 2026-10-30
- The pages no longer assume whose lab is running the suite: "the Gardiner Lab" and "the lab's own server"
  are now "your lab" and "your own server", so they read correctly wherever it is deployed.

### Added
- **About** and **Help** pages. *How to use Booking* covers booking, finding a free slot, the people with you,
  changing and cancelling, what each refusal means, and &mdash; for lab admins &mdash; adding a room or
  instrument, setting its rules and sharing it. Both are linked from the top bar, and Help from the empty
  calendar.

## [0.2.0] - 2026-10-23

### Changed
- **Trellis Tools' look**: the header every module shares (Trellis Tools, then this module's icon and name,
  its tabs, the person and Log out), and the suite's palette - green for what you do, brown for structure,
  on warm paper-white - from static/trellis/trellis.css, copied in from the suite (design/sync.sh). New rooms and
  equipment are green to start with.
- Its dashboard tabs name a Trellis Tools glyph ("glyph"), shown in place of their emoji.

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
