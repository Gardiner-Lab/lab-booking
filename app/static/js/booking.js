/*
 * Booking: the week calendar, finding a free slot, your bookings, and the rooms
 * and equipment a lab admin runs.
 *
 * Addresses: #calendar (=id of the thing, &d=YYYY-MM-DD, &v=week or day), #find,
 * #mine, #manage. Times travel as UTC (toISOString); the page shows them in the
 * browser's own time, the lab's.
 */
'use strict';

const BK = window.BK;
const HOUR_PX = 44;
const DAY_MIN = 24 * 60;
const KIND_IDEAS = ['Meeting room', 'Microscope', 'Growth chamber', 'PCR machine', 'qPCR machine', 'Centrifuge',
  'Fume hood', 'Flow cabinet', 'Gel imager', 'Plate reader', 'Spectrophotometer'];
const WEEKDAYS = [['1', 'Mon'], ['2', 'Tue'], ['3', 'Wed'], ['4', 'Thu'], ['5', 'Fri'], ['6', 'Sat'], ['7', 'Sun']];

const state = { resources: [], kinds: [], people: null, choices: null };
const $ = (id) => document.getElementById(id);

/** A small element builder: el('td', { class: 'x', onclick }, 'text', child, ...). */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'style') node.setAttribute('style', value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== 'string') node[key] = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function toast(message, kind = '') {
  const t = el('div', { class: `toast ${kind}` }, message);
  $('toasts').append(t);
  setTimeout(() => t.remove(), kind === 'error' ? 6000 : 3000);
}

async function api(method, path, body) {
  const res = await fetch(`${BK.base}/api${path}`, {
    method, cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status})`);
  return data;
}

/* --- dates, in the browser's (the lab's) time ------------------------------------------ */

const pad = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes());
const addMin = (d, n) => new Date(d.getTime() + n * 60000);
const sameDay = (a, b) => ymd(a) === ymd(b);
const monday = (d) => addDays(midnight(d), -((d.getDay() + 6) % 7));
const fromYmd = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const atMin = (day, mins) => new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, mins);
const minOf = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
const fmtDay = (d) => d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const fmtLongDay = (d) => d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

function fmtSpan(start, end) {
  const s = new Date(start);
  const e = new Date(end);
  if (sameDay(s, e) || (hm(e) === '00:00' && sameDay(s, addMin(e, -1)))) {
    return `${fmtDay(s)} ${hm(s)}–${hm(e) === '00:00' ? '24:00' : hm(e)}`;
  }
  return `${fmtDay(s)} ${hm(s)} – ${fmtDay(e)} ${hm(e)}`;
}

function fmtMinutes(m) {
  if (m % DAY_MIN === 0) return `${m / DAY_MIN} day${m / DAY_MIN > 1 ? 's' : ''}`;
  if (m >= 60) return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`;
  return `${m} min`;
}

/* --- data ---------------------------------------------------------------------- */

async function loadResources(retired = false) {
  const data = await api('GET', `/resources${retired ? '?retired=1' : ''}`);
  if (!retired) state.resources = data.resources;
  state.kinds = data.kinds;
  return data.resources;
}

async function loadPeople() {
  if (!state.people) state.people = (await api('GET', '/people')).people;
  return state.people;
}

const resourceById = (id) => state.resources.find((r) => r.id === id);

function remember(key, value) { try { localStorage.setItem(`booking.${key}`, value); } catch { /* private window */ } }
function recall(key) { try { return localStorage.getItem(`booking.${key}`); } catch { return null; } }

/* --- routing ------------------------------------------------------------------- */

function route() {
  const [view, rest] = (location.hash.slice(1) || 'calendar').split(/=(.*)/s);
  const params = new URLSearchParams((rest || '').replace(/^([^&=]*)(&|$)/, 'id=$1$2'));
  for (const tab of document.querySelectorAll('.view-tab')) tab.classList.toggle('active', tab.dataset.view === view);
  const show = { calendar: showCalendar, find: showFind, mine: showMine, manage: showManage }[view] || showCalendar;
  show(params).catch((err) => { $('main').replaceChildren(el('p', { class: 'empty' }, err.message)); });
}

function go(view, params = {}) {
  const id = params.id || '';
  const rest = Object.entries(params).filter(([k, v]) => k !== 'id' && v).map(([k, v]) => `&${k}=${encodeURIComponent(v)}`).join('');
  const hash = `#${view}${id || rest ? `=${id}${rest}` : ''}`;
  if (location.hash === hash) route(); else location.hash = hash;
}

/* --- the calendar ------------------------------------------------------------------- */

async function showCalendar(params) {
  await loadResources();
  const main = $('main');
  if (!state.resources.length) {
    main.replaceChildren(el('div', { class: 'empty' },
      el('p', {}, 'Nothing to book yet.'),
      BK.person.can_add ? el('p', {}, el('a', { class: 'btn btn-primary', href: '#manage' }, '＋ Add a room or piece of equipment'))
        : el('p', {}, 'Your lab admin adds the rooms and equipment people book.')));
    return;
  }
  const date = params.get('d') ? fromYmd(params.get('d')) : midnight(new Date());
  let view = params.get('v') === 'day' ? 'day' : 'week';
  let resource = resourceById(params.get('id') || '') || resourceById(recall('resource') || '') || state.resources[0];
  const kind = params.get('k') || resource.kind;
  if (view === 'day' && !state.resources.some((r) => r.kind === kind)) view = 'week';
  remember('resource', resource.id);

  const filter = el('input', { type: 'search', placeholder: 'Search rooms and equipment', 'aria-label': 'Search rooms and equipment' });
  const list = el('div');
  const drawList = () => {
    const words = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
    const shown = state.resources.filter((r) => words.every((w) => `${r.name} ${r.kind} ${r.location} ${r.description}`.toLowerCase().includes(w)));
    const kinds = [...new Set(shown.map((r) => r.kind))];
    list.replaceChildren(...kinds.flatMap((k) => [
      el('div', { class: 'kind-head' }, k,
        el('button', { type: 'button', title: `Every ${k.toLowerCase()} side by side, one day`,
          onclick: () => go('calendar', { id: resource.id, d: ymd(date), v: 'day', k }) }, 'all, by day')),
      ...shown.filter((r) => r.kind === k).map((r) => el('button', {
        type: 'button', class: `thing ${view === 'week' && r.id === resource.id ? 'active' : ''}`,
        onclick: () => go('calendar', { id: r.id, d: ymd(date) }),
      }, el('span', { class: 'dot', style: `background:${r.colour}` }),
      el('span', {}, r.name, r.location ? el('span', { class: 'where' }, r.location) : null))),
    ]), ...(shown.length ? [] : [el('p', { class: 'hint' }, 'Nothing matches.')]));
  };
  filter.addEventListener('input', drawList);
  drawList();

  const step = view === 'week' ? 7 : 1;
  const start = view === 'week' ? monday(date) : midnight(date);
  const end = addDays(start, step);
  const shownResources = view === 'week' ? [resource] : state.resources.filter((r) => r.kind === kind);
  const query = view === 'week' ? `resource=${resource.id}` : `kind=${encodeURIComponent(kind)}`;
  const data = await api('GET', `/bookings?from=${start.toISOString()}&to=${end.toISOString()}&${query}`);

  const title = view === 'week'
    ? [el('h2', {}, el('span', { class: 'dot', style: `background:${resource.colour};margin-right:.4rem` }), resource.name),
      el('span', { class: 'sub' }, [resource.location, rulesSummary(resource)].filter(Boolean).join(' · '))]
    : [el('h2', {}, `${kind} · ${fmtLongDay(start)}`)];
  const label = view === 'week' ? `${fmtDay(start)} – ${fmtDay(addDays(end, -1))}` : '';
  const jump = el('input', { type: 'date', value: ymd(date), 'aria-label': 'Go to a date',
    onchange: (e) => e.target.value && go('calendar', { id: resource.id, d: e.target.value, v: view, k: view === 'day' ? kind : '' }) });
  const move = (n) => go('calendar', { id: resource.id, d: ymd(addDays(date, n * step)), v: view, k: view === 'day' ? kind : '' });
  const tools = el('div', { class: 'cal-tools' }, ...title, el('span', { class: 'spacer' }),
    el('span', { class: 'sub' }, label),
    el('button', { class: 'btn', type: 'button', title: view === 'week' ? 'The week before' : 'The day before', onclick: () => move(-1) }, '‹'),
    el('button', { class: 'btn', type: 'button', onclick: () => go('calendar', { id: resource.id, v: view, k: view === 'day' ? kind : '' }) }, 'Today'),
    el('button', { class: 'btn', type: 'button', title: view === 'week' ? 'The week after' : 'The day after', onclick: () => move(1) }, '›'),
    jump,
    el('span', { class: 'segmented' },
      el('button', { type: 'button', class: view === 'week' ? 'on' : '', onclick: () => go('calendar', { id: resource.id, d: ymd(date) }) }, 'Week'),
      el('button', { type: 'button', class: view === 'day' ? 'on' : '', title: `Every ${resource.kind.toLowerCase()} side by side`,
        onclick: () => go('calendar', { id: resource.id, d: ymd(date), v: 'day', k: resource.kind }) }, `All ${kind.toLowerCase()}s`)),
    el('button', { class: 'btn btn-primary', type: 'button', onclick: () => {
      const now = new Date();
      const s = atMin(midnight(now), Math.ceil((now.getHours() * 60 + now.getMinutes()) / resource.step_minutes) * resource.step_minutes);
      openBooking({ resource, start: s, end: addMin(s, Math.max(resource.min_minutes, 60)) });
    } }, '＋ Book'));

  const columns = view === 'week'
    ? Array.from({ length: 7 }, (_, i) => ({ day: addDays(start, i), resource }))
    : shownResources.map((r) => ({ day: start, resource: r }));
  const calendar = grid(columns, data.bookings, view);
  main.replaceChildren(el('div', { class: 'cal-layout' },
    el('aside', { class: 'things' }, filter, list),
    el('section', {}, tools, calendar,
      el('div', { class: 'legend' }, el('span', { class: 'l-mine' }, 'Yours, or you are in it'), el('span', { class: 'l-other' }, 'Someone else’s'),
        el('span', { class: 'l-closed' }, 'Closed or unavailable'),
        el('span', {}, 'Drag across free time to book it; click a booking to see it.')))));
  const scroller = calendar.querySelector('.cal-scroll');
  const first = Math.min(...columns.map((c) => minOf(c.resource.open_from)));
  scroller.scrollTop = Math.max(0, (first > 0 ? first : 7 * 60) / 60 * HOUR_PX - 8);
}

function rulesSummary(r) {
  const bits = [];
  if (!r.always_open) {
    const days = WEEKDAYS.filter(([d]) => r.weekdays.includes(d)).map(([, n]) => n);
    bits.push(`${r.weekdays === '12345' ? 'Mon–Fri' : r.weekdays === '1234567' ? 'every day' : days.join(', ')} ${r.open_from}–${r.open_until}`);
  } else bits.push('round the clock');
  if (r.capacity > 1) bits.push(`${r.capacity} at once`);
  if (r.max_minutes) bits.push(`up to ${fmtMinutes(r.max_minutes)}`);
  if (r.advance_days) bits.push(`book up to ${r.advance_days} days ahead`);
  return bits.join(' · ');
}

/** When a thing is open on a day, in minutes [from, until], or null when it is not. */
function openOn(r, day) {
  const iso = String(((day.getDay() + 6) % 7) + 1);
  if (!r.weekdays.includes(iso)) return null;
  return [minOf(r.open_from), minOf(r.open_until)];
}

/** Lanes for bookings that overlap, so they sit side by side. */
function lanes(items) {
  const ends = [];
  for (const it of items.sort((a, b) => a.s - b.s || b.e - a.e)) {
    let lane = ends.findIndex((e) => e <= it.s);
    if (lane < 0) { lane = ends.length; ends.push(it.e); } else ends[lane] = it.e;
    it.lane = lane;
  }
  for (const it of items) {
    it.of = Math.max(1, ...items.filter((o) => o.s < it.e && o.e > it.s).map((o) => o.lane + 1));
  }
  return items;
}

function grid(columns, bookings, view) {
  const now = new Date();
  const g = el('div', { class: 'cal-grid', style: `grid-template-columns: 3.4rem repeat(${columns.length}, minmax(${view === 'week' ? 5.5 : 9}rem, 1fr))` });
  g.append(el('div', { class: 'cal-corner' }));
  for (const c of columns) {
    const today = sameDay(c.day, now);
    g.append(el('div', { class: `cal-head ${today && view === 'week' ? 'today' : ''}` }, view === 'week'
      ? [c.day.toLocaleDateString('en-GB', { weekday: 'short' }), el('span', { class: 'big' }, c.day.getDate()),
        el('span', { class: 'sub' }, c.day.toLocaleDateString('en-GB', { month: 'short' }))]
      : [el('span', { class: 'dot', style: `background:${c.resource.colour}` }), ' ', el('b', {}, c.resource.name),
        el('span', { class: 'sub' }, c.resource.location || c.resource.kind)]));
  }
  g.append(el('div', { class: 'cal-hours' }, Array.from({ length: 24 }, (_, h) => el('div', { class: 'cal-hour' }, h ? `${pad(h)}:00` : ''))));
  const pxPerMin = HOUR_PX / 60;
  for (const c of columns) {
    const dayStart = c.day;
    const dayEnd = addDays(c.day, 1);
    const today = sameDay(c.day, now);
    const col = el('div', { class: `cal-col ${today ? 'today' : ''} ${dayEnd <= now ? 'past' : ''}` });
    const open = openOn(c.resource, c.day);
    const shade = (a, b) => b > a && col.append(el('div', { class: 'closed', style: `top:${a * pxPerMin}px;height:${(b - a) * pxPerMin}px` }));
    if (!open) shade(0, DAY_MIN); else { shade(0, open[0]); shade(open[1], DAY_MIN); }
    if (today) {
      col.append(el('div', { class: 'now', style: `top:${(now.getHours() * 60 + now.getMinutes()) * pxPerMin}px` }));
    }
    const mine = lanes(bookings.filter((b) => b.resource_id === c.resource.id && new Date(b.start) < dayEnd && new Date(b.end) > dayStart)
      .map((b) => ({ b, s: Math.max(0, (new Date(b.start) - dayStart) / 60000), e: Math.min(DAY_MIN, (new Date(b.end) - dayStart) / 60000) })));
    for (const it of mine) {
      const { b } = it;
      const cls = ['bk', b.kind === 'closed' ? 'closed-time' : '', b.mine ? 'mine' : '', b.tagged ? 'tagged' : ''].join(' ');
      const width = 100 / it.of;
      const who = b.kind === 'closed' ? 'Unavailable' : b.booked_by + (b.people.length ? ` +${b.people.length}` : '');
      col.append(el('div', {
        class: cls, title: `${fmtSpan(b.start, b.end)}\n${b.title || ''}\n${who}`.trim(),
        style: `--c:${b.resource.colour};top:${it.s * pxPerMin + 1}px;height:${Math.max(18, (it.e - it.s) * pxPerMin - 2)}px;`
          + `left:calc(${it.lane * width}% + 2px);width:calc(${width}% - 4px)`,
        onpointerdown: (e) => e.stopPropagation(),
        onclick: () => openBooking({ booking: b, resource: resourceById(b.resource_id) || c.resource }),
      }, el('span', { class: 't' }, b.title || (b.kind === 'closed' ? 'Unavailable' : b.booked_by)),
      el('span', { class: 'w' }, `${hm(new Date(b.start))}–${hm(new Date(b.end))}${b.title && b.kind !== 'closed' ? ` · ${who}` : ''}`)));
    }
    pickOn(col, c, pxPerMin);
    g.append(col);
  }
  return el('div', { class: 'cal' }, el('div', { class: 'cal-scroll' }, g));
}

/** Drag across free time (or click it) to book it, on the thing's steps. */
function pickOn(col, column, pxPerMin) {
  const step = column.resource.step_minutes;
  const at = (e) => Math.max(0, Math.min(DAY_MIN, (e.clientY - col.getBoundingClientRect().top) / pxPerMin));
  let from = null;
  let sel = null;
  const span = (to) => {
    const a = Math.floor(Math.min(from, to) / step) * step;
    const b = Math.max(a + Math.max(step, column.resource.min_minutes), Math.ceil(Math.max(from, to) / step) * step);
    return [a, Math.min(b, DAY_MIN)];
  };
  col.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    from = at(e);
    col.setPointerCapture(e.pointerId);
    sel = el('div', { class: 'sel' });
    col.append(sel);
    draw(from);
  });
  const draw = (to) => {
    const [a, b] = span(to);
    sel.style.top = `${a * pxPerMin}px`;
    sel.style.height = `${(b - a) * pxPerMin}px`;
    sel.textContent = `${hm(atMin(column.day, a))}–${b === DAY_MIN ? '24:00' : hm(atMin(column.day, b))}`;
  };
  col.addEventListener('pointermove', (e) => { if (sel) draw(at(e)); });
  col.addEventListener('pointerup', (e) => {
    if (!sel) return;
    const [a, b] = span(at(e));
    sel.remove();
    sel = null;
    openBooking({ resource: column.resource, start: atMin(column.day, a), end: atMin(column.day, b) });
  });
  col.addEventListener('pointercancel', () => { if (sel) { sel.remove(); sel = null; } });
}

/* --- one booking --------------------------------------------------------------------- */

function tagInput(initial, disabled) {
  const people = [...initial];
  const box = el('div', { class: 'tag-box' });
  const listId = `people-${Math.random().toString(36).slice(2)}`;
  const input = el('input', { type: 'text', list: listId, placeholder: disabled ? '' : 'Add someone…', disabled, 'aria-label': 'People in this booking' });
  const datalist = el('datalist', { id: listId });
  loadPeople().then((all) => datalist.replaceChildren(...all.filter((p) => p !== BK.person.username).map((p) => el('option', { value: p }))));
  const draw = () => box.replaceChildren(...people.map((p) => el('span', { class: 'chip' }, p,
    disabled ? null : el('button', { type: 'button', title: `Take ${p} out`, onclick: () => { people.splice(people.indexOf(p), 1); draw(); } }, '×'))),
  input, datalist);
  const add = () => {
    const names = input.value.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
    for (const name of names) {
      const known = (state.people || []).find((p) => p.toLowerCase() === name.toLowerCase());
      if (!known) { toast(`No one is called ${name}`, 'error'); continue; }
      if (!people.includes(known) && known !== BK.person.username) people.push(known);
    }
    input.value = '';
    draw();
    input.focus();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); if (input.value.trim()) add(); }
    if (e.key === 'Backspace' && !input.value && people.length) { people.pop(); draw(); }
  });
  input.addEventListener('change', () => { if ((state.people || []).includes(input.value.trim())) add(); });
  draw();
  return { node: box, value: () => { if (input.value.trim()) add(); return people; } };
}

/** The booking dialog: a new booking at a time, or one to see, change or cancel. */
async function openBooking({ booking = null, resource, start, end }) {
  const dlg = $('dialog');
  const editable = !booking || booking.can_edit;
  const choices = state.resources.length ? state.resources : await loadResources();
  resource = resource || choices[0];
  const s = booking ? new Date(booking.start) : start;
  const e = booking ? new Date(booking.end) : end;
  const closedTime = booking ? booking.kind === 'closed' : false;
  const field = (label, input) => el('label', { class: 'field' }, el('span', {}, label), input);
  const what = el('select', { disabled: !editable }, choices.map((r) => el('option', { value: r.id, selected: r.id === resource.id }, `${r.name}${r.location ? ` · ${r.location}` : ''}`)));
  const stepOf = () => (resourceById(what.value) || resource).step_minutes * 60;
  const startDay = el('input', { type: 'date', value: ymd(s), disabled: !editable, required: true });
  const startTime = el('input', { type: 'time', value: hm(s), step: stepOf(), disabled: !editable, required: true });
  const endDay = el('input', { type: 'date', value: ymd(e), disabled: !editable, required: true });
  const endTime = el('input', { type: 'time', value: hm(e), step: stepOf(), disabled: !editable, required: true });
  startDay.addEventListener('change', () => {
    // The end keeps the booking's length.
    const length = new Date(`${endDay.value}T${endTime.value}`) - new Date(`${ymd(s)}T${hm(s)}`);
    const ns = new Date(`${startDay.value}T${startTime.value}`);
    if (length > 0 && !Number.isNaN(ns.getTime())) { const ne = new Date(ns.getTime() + length); endDay.value = ymd(ne); endTime.value = hm(ne); }
  });
  what.addEventListener('change', () => { startTime.step = stepOf(); endTime.step = stepOf(); });
  const title = el('input', { type: 'text', maxlength: 200, value: booking ? booking.title : '', disabled: !editable,
    placeholder: closedTime ? 'e.g. Service visit' : 'What for, e.g. Lab meeting, imaging GFP lines' });
  const tags = tagInput(booking ? booking.people : [], !editable);
  const notes = el('textarea', { maxlength: 4000, disabled: !editable }, booking ? booking.notes : '');
  const manager = () => (resourceById(what.value) || resource).can_manage;
  const unavailable = el('input', { type: 'checkbox', checked: closedTime, disabled: Boolean(booking) });
  const unavailableRow = el('label', { class: 'checks', hidden: !(manager() && (!booking || closedTime)) }, unavailable,
    ' Mark it unavailable (maintenance, a service visit): nobody can book it then');
  what.addEventListener('change', () => { unavailableRow.hidden = !manager() || Boolean(booking); });
  const error = el('div', { class: 'error', hidden: true });
  const cancelBtn = booking && booking.can_edit ? el('button', { type: 'button', class: 'btn btn-danger', onclick: async (ev) => {
    if (!ev.target.classList.contains('really')) { ev.target.classList.add('really'); ev.target.textContent = 'Really cancel?'; return; }
    try { await api('DELETE', `/bookings/${booking.id}`); dlg.close(); toast('Cancelled.'); route(); } catch (err) { showError(err); }
  } }, closedTime ? 'Remove' : 'Cancel booking') : null;
  const leaveBtn = booking && !booking.can_edit && booking.tagged ? el('button', { type: 'button', class: 'btn btn-danger', onclick: async () => {
    try { await api('DELETE', `/bookings/${booking.id}/people/me`); dlg.close(); toast('You are out of that booking.'); route(); } catch (err) { showError(err); }
  } }, 'Take me out') : null;
  const showError = (err) => { error.textContent = err.message; error.hidden = false; };
  const form = el('form', { method: 'dialog' },
    el('h2', {}, booking ? (closedTime ? 'Unavailable' : editable ? 'Booking' : `${booking.booked_by}’s booking`) : 'Book'),
    booking ? el('p', { class: 'hint', style: 'margin:0' }, `${fmtSpan(booking.start, booking.end)} · booked by ${booking.booked_by}`) : null,
    error,
    field('What', what),
    el('div', { class: 'row' }, field('Starts', startDay), field('at', startTime)),
    el('div', { class: 'row' }, field('Ends', endDay), field('at', endTime)),
    unavailableRow,
    field(closedTime ? 'Why' : 'What for', title),
    closedTime ? null : field('People in it', tags.node),
    closedTime ? null : el('p', { class: 'hint', style: 'margin:-.4rem 0 0' }, 'They see it in their bookings and on that day in their Lab Notebook.'),
    field('Notes', notes),
    el('div', { class: 'foot' }, el('span', { class: 'left' }, cancelBtn, leaveBtn),
      el('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, editable ? 'Close' : 'Done'),
      editable ? el('button', { type: 'submit', class: 'btn btn-primary' }, booking ? 'Save' : 'Book') : null));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!editable) return;
    const startAt = new Date(`${startDay.value}T${startTime.value}`);
    const endAt = new Date(`${endDay.value}T${endTime.value}`);
    if (Number.isNaN(startAt.getTime()) || Number.isNaN(endAt.getTime())) { showError(new Error('Give the start and the end')); return; }
    const body = { resource_id: what.value, start: startAt.toISOString(), end: endAt.toISOString(), title: title.value,
      notes: notes.value };
    if (!closedTime && !unavailable.checked) body.people = tags.value();
    if (!booking && unavailable.checked) body.kind = 'closed';
    try {
      await api(booking ? 'PUT' : 'POST', booking ? `/bookings/${booking.id}` : '/bookings', body);
      dlg.close();
      toast(booking ? 'Saved.' : `Booked: ${fmtSpan(startAt.toISOString(), endAt.toISOString())}.`);
      route();
    } catch (err) { showError(err); }
  });
  dlg.replaceChildren(form);
  dlg.showModal();
  (editable ? title : form.querySelector('.foot .btn')).focus();
}

/* --- finding a free slot ---------------------------------------------------------------- */

const LENGTHS = [15, 30, 45, 60, 90, 120, 180, 240, 360, 480, DAY_MIN, 2 * DAY_MIN, 7 * DAY_MIN, 14 * DAY_MIN];

async function showFind(params) {
  await loadResources();
  const today = midnight(new Date());
  const q = el('input', { type: 'search', placeholder: 'e.g. confocal, 2.14, projector', value: params.get('q') || '' });
  const kind = el('select', {}, el('option', { value: '' }, 'Any'), state.kinds.map((k) => el('option', { value: k, selected: k === params.get('kind') }, k)));
  const places = el('input', { type: 'number', min: 1, value: params.get('capacity') || 1 });
  const from = el('input', { type: 'date', value: params.get('from') || ymd(today), min: ymd(today) });
  const to = el('input', { type: 'date', value: params.get('to') || ymd(addDays(today, 6)), min: ymd(today) });
  const length = el('select', {}, LENGTHS.map((m) => el('option', { value: m, selected: String(m) === (params.get('minutes') || '60') }, fmtMinutes(m))));
  const timeFrom = el('input', { type: 'time', value: params.get('time_from') || '' });
  const timeUntil = el('input', { type: 'time', value: params.get('time_until') || '' });
  const results = el('div');
  const field = (label, input) => el('label', { class: 'field' }, el('span', {}, label), input);
  const form = el('form', { class: 'find-form' },
    field('What', q), field('Kind', kind), field('Places at least', places), field('From', from), field('To', to),
    field('For', length), field('Between (optional)', timeFrom), field('and', timeUntil),
    el('button', { class: 'btn btn-primary', type: 'submit' }, 'Find free time'));
  const search = async () => {
    const args = new URLSearchParams({ q: q.value, kind: kind.value, capacity: places.value || 1, from: from.value,
      to: to.value || from.value, minutes: length.value, time_from: timeFrom.value, time_until: timeUntil.value });
    results.replaceChildren(el('p', { class: 'hint' }, 'Looking…'));
    try {
      const { slots } = await api('GET', `/free?${args}`);
      drawSlots(results, slots, Number(length.value));
    } catch (err) { results.replaceChildren(el('p', { class: 'empty' }, err.message)); }
  };
  form.addEventListener('submit', (e) => { e.preventDefault(); search(); });
  $('main').replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Find a free slot')),
    el('div', { class: 'card' }, form),
    results);
  if (state.resources.length) search();
}

function drawSlots(box, slots, minutes) {
  if (!slots.length) {
    box.replaceChildren(el('p', { class: 'empty' }, 'Nothing free for that long then. Try other days, a shorter time, or any kind.'));
    return;
  }
  const byDay = new Map();
  for (const s of slots) {
    const key = ymd(new Date(s.start));
    if (!byDay.has(key)) byDay.set(key, []);
    byDay.get(key).push(s);
  }
  const today = ymd(new Date());
  box.replaceChildren(...[...byDay.entries()].map(([day, list]) => el('div', { class: 'day-group' },
    el('h3', { class: day === today ? 'today' : '' }, `${fmtLongDay(fromYmd(day))}${day === today ? ' · today' : ''}`),
    list.map((s) => {
      const r = resourceById(s.resource_id);
      const start = new Date(s.start);
      const end = addMin(start, minutes);
      return el('div', { class: 'slot' },
        el('span', { class: 'dot', style: `background:${s.resource.colour}` }),
        el('span', { class: 'what' }, el('b', {}, s.resource.name), el('span', { class: 'hint' }, [s.resource.kind, s.resource.location].filter(Boolean).join(' · '))),
        el('span', { class: 'when' }, `free ${fmtSpan(s.start, s.end)}`),
        el('button', { class: 'btn', type: 'button', onclick: () => go('calendar', { id: s.resource_id, d: day }) }, 'Calendar'),
        el('button', { class: 'btn btn-primary', type: 'button', onclick: () => openBooking({ resource: r, start, end }) },
          `Book ${hm(start)}–${hm(end)}`));
    }))));
}

/* --- my bookings ---------------------------------------------------------------- */

async function showMine(params) {
  await loadResources();
  const past = params.get('past') === '1';
  const { bookings } = await api('GET', `/bookings/mine${past ? '?past=31' : ''}`);
  const now = new Date();
  const byDay = new Map();
  for (const b of bookings) {
    const key = ymd(new Date(b.start));
    if (!byDay.has(key)) byDay.set(key, []);
    byDay.get(key).push(b);
  }
  const today = ymd(now);
  $('main').replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'My bookings'),
      el('span', { class: 'actions' },
        el('label', { class: 'checks' }, el('input', { type: 'checkbox', checked: past, onchange: (e) => go('mine', { past: e.target.checked ? '1' : '' }) }),
          ' The past month too'),
        BK.embed ? el('a', { class: 'btn', href: `${BK.base}/#calendar`, target: '_top' }, 'Open the calendar ↗')
          : el('a', { class: 'btn btn-primary', href: '#find' }, 'Find a free slot'))),
    ...(bookings.length ? [] : [el('p', { class: 'empty' }, 'Nothing booked. Bookings you make, and those you are tagged in, show here.')]),
    ...[...byDay.entries()].map(([day, list]) => el('div', { class: 'day-group' },
      el('h3', { class: day === today ? 'today' : '' }, `${fmtLongDay(fromYmd(day))}${day === today ? ' · today' : ''}`),
      list.map((b) => el('div', { class: 'entry', style: new Date(b.end) < now ? 'opacity:.6' : '' },
        el('span', { class: 'dot', style: `background:${b.resource.colour}` }),
        el('span', { class: 'when' }, fmtSpan(b.start, b.end)),
        el('span', { class: 'what' }, el('b', {}, b.resource.name, b.resource.location ? el('span', { class: 'hint' }, ` · ${b.resource.location}`) : null),
          el('span', {}, b.title || ''),
          el('span', { class: 'hint', style: 'display:block' }, b.mine ? (b.people.length ? `With ${b.people.join(', ')}` : 'Just you')
            : `Booked by ${b.booked_by}${b.people.length > 1 ? `, with ${b.people.filter((p) => p !== BK.person.username).join(', ')}` : ''}`)),
        el('button', { class: 'btn', type: 'button', onclick: () => openBooking({ booking: b, resource: resourceById(b.resource_id) }) }, b.can_edit ? 'Change' : 'See'))))));
}

/* --- rooms and equipment (lab admins) ---------------------------------------------------- */

async function showManage() {
  if (!BK.person.can_add) {
    $('main').replaceChildren(el('p', { class: 'empty' }, 'Lab admins add and change the rooms and equipment people book.'));
    return;
  }
  const all = (await loadResources(true)).filter((r) => r.can_manage);
  state.choices = state.choices || await api('GET', '/resources/choices');
  const shareText = (r) => {
    if (r.everyone) return 'Everyone';
    const names = r.shares.map((s) => (s.type === 'lab' ? state.choices.labs.find((l) => l.id === s.id)?.name
      : `${state.choices.chair_groups.find((g) => g.id === s.id)?.name || '?'} (chair group)`));
    return [r.owner_lab, ...names].filter(Boolean).join(', ');
  };
  const act = async (promise, done) => {
    try { await promise; toast(done); showManage(); } catch (err) { toast(err.message, 'error'); }
  };
  $('main').replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Rooms & equipment'),
      el('button', { class: 'btn btn-primary', type: 'button', onclick: () => editResource(null) }, '＋ Add a room or piece of equipment')),
    el('p', { class: 'hint' }, 'What your labs’ people book. Add anything, share it with other labs and chair groups, set its rules. '
      + 'Retire what is gone: its bookings stay in people’s notebooks.'),
    all.length ? el('div', { class: 'card table-scroll' }, el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, ['', 'Name', 'Kind', 'Belongs to · shared with', 'Rules', 'Bookings', ''].map((h) => el('th', {}, h)))),
      el('tbody', {}, all.map((r) => el('tr', { class: r.retired_at ? 'retired' : '' },
        el('td', {}, el('span', { class: 'dot', style: `background:${r.colour}` })),
        el('td', {}, el('b', {}, r.name), r.location ? el('div', { class: 'hint' }, r.location) : null,
          r.retired_at ? el('span', { class: 'badge retired' }, 'retired') : null),
        el('td', {}, r.kind),
        el('td', {}, shareText(r)),
        el('td', { class: 'hint' }, rulesSummary(r)),
        el('td', {}, r.bookings),
        el('td', { style: 'white-space:nowrap' },
          el('button', { class: 'btn btn-small', type: 'button', onclick: () => editResource(r) }, 'Change'), ' ',
          r.retired_at
            ? el('button', { class: 'btn btn-small', type: 'button', onclick: () => act(api('POST', `/resources/${r.id}/retire`, { retired: false }), `${r.name} can be booked again.`) }, 'Bring back')
            : el('button', { class: 'btn btn-small', type: 'button', title: 'No longer booked; its bookings are kept',
              onclick: () => act(api('POST', `/resources/${r.id}/retire`, { retired: true }), `${r.name} is retired.`) }, 'Retire'), ' ',
          r.bookings ? null : el('button', { class: 'btn btn-small btn-danger', type: 'button', onclick: (ev) => {
            if (!ev.target.classList.contains('really')) { ev.target.classList.add('really'); ev.target.textContent = 'Really remove?'; return; }
            act(api('DELETE', `/resources/${r.id}`), `${r.name} is removed.`);
          } }, 'Remove'))))))) : el('p', { class: 'empty' }, 'Nothing yet: add the first room or piece of equipment.'));
}

function timeOptions(selected, from = 0, to = DAY_MIN) {
  const out = [];
  for (let m = from; m <= to; m += 15) {
    const v = m === DAY_MIN ? '24:00' : `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
    out.push(el('option', { value: v, selected: v === selected }, v));
  }
  return out;
}

function editResource(r) {
  const dlg = $('dialog');
  const c = state.choices;
  const field = (label, input, hint) => el('label', { class: 'field' }, el('span', {}, label), input, hint ? el('span', { class: 'hint' }, hint) : null);
  const v = r || { name: '', kind: '', location: '', description: '', colour: '#2f8f46', capacity: 1, step_minutes: 30, min_minutes: 30,
    max_minutes: null, advance_days: null, open_from: '08:00', open_until: '18:00', weekdays: '12345',
    owner_lab_id: c.own_labs[0]?.id, everyone: false, shares: null };
  const kindList = el('datalist', { id: 'kind-ideas' }, [...new Set([...state.kinds, ...KIND_IDEAS])].map((k) => el('option', { value: k })));
  const name = el('input', { type: 'text', required: true, maxlength: 120, value: v.name, placeholder: 'e.g. Confocal (Zeiss LSM 880)' });
  const kind = el('input', { type: 'text', required: true, maxlength: 60, value: v.kind, list: 'kind-ideas', placeholder: 'e.g. Microscope' });
  const location = el('input', { type: 'text', maxlength: 120, value: v.location, placeholder: 'e.g. Kruyt 2.14' });
  const description = el('textarea', { maxlength: 2000, placeholder: 'What it is, what to know before booking it' }, v.description);
  const colour = el('input', { type: 'color', value: v.colour });
  const owner = el('select', {}, c.own_labs.map((l) => el('option', { value: l.id, selected: l.id === v.owner_lab_id }, l.name)));
  const everyone = el('input', { type: 'checkbox', checked: v.everyone });
  const shared = new Set((v.shares || []).map((s) => `${s.type}:${s.id}`));
  if (!r) {
    const group = c.labs.find((l) => l.id === v.owner_lab_id)?.chair_group_id;
    if (group) shared.add(`chair_group:${group}`);
  }
  const box = (type, item, label) => el('label', {}, el('input', { type: 'checkbox', value: `${type}:${item.id}`, checked: shared.has(`${type}:${item.id}`) }), ` ${label}`);
  const groups = el('div', { class: 'checks' }, c.chair_groups.map((g) => box('chair_group', g, g.name)));
  const labsBox = el('div', { class: 'checks' }, c.labs.map((l) => box('lab', l, l.name)));
  const capacity = el('input', { type: 'number', min: 1, max: 500, value: v.capacity });
  const step = el('select', {}, [5, 10, 15, 20, 30, 60].map((m) => el('option', { value: m, selected: m === v.step_minutes }, `${m} min`)));
  const shortest = el('input', { type: 'number', min: 5, step: 5, value: v.min_minutes });
  const longest = el('input', { type: 'number', min: 5, step: 5, value: v.max_minutes ?? '', placeholder: 'no limit' });
  const ahead = el('input', { type: 'number', min: 1, value: v.advance_days ?? '', placeholder: 'no limit' });
  const opens = el('select', {}, timeOptions(v.open_from, 0, DAY_MIN - 15));
  const closes = el('select', {}, timeOptions(v.open_until, 15, DAY_MIN));
  const days = el('div', { class: 'checks' }, WEEKDAYS.map(([d, n]) => el('label', {}, el('input', { type: 'checkbox', value: d, checked: v.weekdays.includes(d) }), ` ${n}`)));
  const roundTheClock = el('input', { type: 'checkbox', checked: Boolean(r && r.always_open) });
  const hours = el('div', { class: 'row' }, field('Opens', opens), field('Closes', closes));
  const syncHours = () => { hours.hidden = roundTheClock.checked; days.hidden = roundTheClock.checked; };
  roundTheClock.addEventListener('change', syncHours);
  syncHours();
  const error = el('div', { class: 'error', hidden: true });
  const form = el('form', { method: 'dialog' },
    el('h2', {}, r ? `Change ${r.name}` : 'Add a room or piece of equipment'), error,
    field('Name', name),
    el('div', { class: 'row' }, field('Kind', kind), field('Where', location), el('label', { class: 'field', style: 'flex:0 0 4.5rem' }, el('span', {}, 'Colour'), colour)),
    kindList,
    field('About it', description),
    el('fieldset', {}, el('legend', {}, 'Who books it'),
      field('Belongs to', owner, 'Its lab’s lab admins manage it and its bookings.'),
      el('label', { class: 'checks' }, everyone, ' Everyone in the suite'),
      c.chair_groups.length ? field('Chair groups', groups) : null,
      field('Other labs', labsBox)),
    el('fieldset', {}, el('legend', {}, 'Rules'),
      el('div', { class: 'row' }, field('How many at once', capacity, 'Seats, shelves, blocks'), field('Booked in steps of', step)),
      el('div', { class: 'row' }, field('Shortest booking (min)', shortest), field('Longest booking (min)', longest), field('Book ahead up to (days)', ahead)),
      el('label', { class: 'checks' }, roundTheClock, ' Round the clock, every day (bookings may run over days, like a growth chamber’s)'),
      hours, days),
    el('div', { class: 'foot' },
      el('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'Cancel'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, r ? 'Save' : 'Add')));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const shares = [...form.querySelectorAll('.checks input[value*=":"]:checked')].map((i) => {
      const [type, id] = i.value.split(':');
      return { type, id };
    }).filter((s) => !(s.type === 'lab' && s.id === owner.value));
    const body = {
      name: name.value, kind: kind.value, location: location.value, description: description.value, colour: colour.value,
      owner_lab_id: owner.value, everyone: everyone.checked, shares,
      capacity: Number(capacity.value), step_minutes: Number(step.value), min_minutes: Number(shortest.value),
      max_minutes: longest.value ? Number(longest.value) : null, advance_days: ahead.value ? Number(ahead.value) : null,
      open_from: roundTheClock.checked ? '00:00' : opens.value, open_until: roundTheClock.checked ? '24:00' : closes.value,
      weekdays: roundTheClock.checked ? '1234567' : [...days.querySelectorAll('input:checked')].map((i) => i.value).join(''),
    };
    try {
      await api(r ? 'PUT' : 'POST', r ? `/resources/${r.id}` : '/resources', body);
      dlg.close();
      toast(r ? 'Saved.' : `${body.name} can be booked now.`);
      showManage();
    } catch (err) { error.textContent = err.message; error.hidden = false; error.scrollIntoView({ block: 'nearest' }); }
  });
  dlg.replaceChildren(form);
  dlg.showModal();
  name.focus();
}

window.addEventListener('hashchange', route);
route();
