// SPDX-License-Identifier: GPL-3.0-or-later
// Cleanly front end: state, views and actions

import { connect, on } from './bridge.js';
import { h, icon } from './dom.js';
import * as fmt from './format.js';

const PRIVACY_OPTIONS = ['cookies', 'history', 'url_history', 'session', 'form_history', 'forms', 'site_data', 'site_preferences'];
const BROWSER_COLORS = ['#3B82F6', '#14B8A6', '#F97316', '#A855F7', '#EF4444', '#EAB308', '#22C55E'];

const state = {
  api: null,
  info: { name: 'Cleanly', version: '' },
  stats: null,
  scan: null,
  job: null, // {kind: 'scan'|'clean', fraction, message}
  mode: 'basic',
  selected: new Set(),
  view: 'home',
  tab: 'disk',
  expanded: new Set(),
  drawer: null, // {category, items} or {picker: true, ...}
  settings: null, // {settings, scheduled}
  exclusions: null,
  keptCookies: null,
  cookieInput: '',
  history: null,
  dialog: null,
  lastClean: null,
  toast: null,
};

// ---------- Selection ----------

function optionAllowed(category, option, mode) {
  if (category.kind !== 'browser') return true;
  return mode === 'full' ? ['basic', 'full'].includes(option.mode) : option.mode === 'basic';
}

function applyMode(mode) {
  state.mode = mode;
  if (mode === 'custom' || !state.scan) return;
  state.selected = new Set();
  for (const c of state.scan.categories) {
    if (!c.selected[mode]) continue;
    for (const o of c.options) {
      if (o.items > 0 && optionAllowed(c, o, mode)) state.selected.add(o.id);
    }
  }
}

function setChecked(ids, checked) {
  for (const id of ids) {
    if (checked) state.selected.add(id);
    else state.selected.delete(id);
  }
  state.mode = 'custom';
  render();
}

function categoryState(c) {
  const ids = c.options.filter(o => o.items > 0).map(o => o.id);
  const n = ids.filter(id => state.selected.has(id)).length;
  return { ids, checked: n > 0 && n === ids.length, indeterminate: n > 0 && n < ids.length };
}

function selectionTotals(kind) {
  let bytes = 0;
  let items = 0;
  let rows = 0;
  for (const c of visibleCategories(kind)) {
    let any = false;
    for (const o of c.options) {
      if (!state.selected.has(o.id)) continue;
      bytes += o.bytes;
      items += o.items;
      any = true;
    }
    if (any) rows += 1;
  }
  return { bytes, items, rows };
}

function visibleCategories(kind) {
  if (!state.scan) return [];
  return state.scan.categories
    .filter(c => (!kind || c.kind === kind) && (c.items > 0 || c.running))
    .sort((a, b) => b.bytes - a.bytes);
}

// ---------- Actions ----------

async function refreshOverview() {
  const overview = await state.api.get_overview();
  state.stats = overview.stats;
}

async function startScan() {
  const res = await state.api.start_scan();
  if (!res.ok) return showToast(res.error);
  state.job = { kind: 'scan', fraction: 0, message: 'Getting ready\u2026', items: 0, bytes: 0 };
  render();
}

async function cancelJob() {
  await state.api.cancel();
}

function selectedOperations() {
  return [...state.selected];
}

function confirmClean() {
  const ops = selectedOperations();
  if (!ops.length) return;
  const reasons = [];
  const privacy = ops.filter(id => PRIVACY_OPTIONS.includes(id.split('.')[1]));
  if (privacy.length) reasons.push('Cookies, history or open tabs are selected. You may be signed out of websites and lose open tabs.');
  if (ops.includes('system.recycle_bin')) reasons.push('The Recycle Bin will be emptied. Those files cannot be restored afterwards.');
  const running = state.scan.categories.filter(c => c.running && c.options.some(o => state.selected.has(o.id)));
  if (running.length) reasons.push(`${running.map(c => c.label).join(', ')} ${running.length === 1 ? 'is' : 'are'} open and will be skipped. Close ${running.length === 1 ? 'it' : 'them'} first to clean ${running.length === 1 ? 'it' : 'them'}.`);
  if (!reasons.length) return startClean();
  state.dialog = { title: 'Before you clean', reasons };
  render();
}

async function startClean() {
  state.dialog = null;
  const res = await state.api.start_clean(selectedOperations());
  if (!res.ok) return showToast(res.error);
  state.job = { kind: 'clean', fraction: 0, message: 'Getting ready\u2026', items: 0, bytes: 0 };
  state.lastClean = null;
  state.view = 'result';
  render();
}

async function openDrawer(category) {
  state.drawer = { category, items: null };
  render();
  const res = await state.api.get_items(category.id);
  if (state.drawer && state.drawer.category === category) {
    state.drawer.items = res.ok ? res.items : [];
    render();
  }
}

function showToast(message) {
  state.toast = message;
  render();
  setTimeout(() => { state.toast = null; render(); }, 3500);
}

function go(view) {
  state.view = view;
  state.drawer = null;
  render();
  if (view === 'settings') loadSettings();
  if (view === 'history') loadHistory();
}

// ---------- Settings, exclusions, cookies, history ----------

async function loadSettings() {
  const [settings, exclusions, cookies] = await Promise.all([
    state.api.get_settings(), state.api.get_exclusions(), state.api.get_kept_cookies()]);
  state.settings = settings;
  state.exclusions = exclusions.ok ? exclusions.paths : [];
  state.keptCookies = cookies.ok ? cookies.domains : [];
  await refreshOverview();
  render();
}

async function loadHistory() {
  state.history = await state.api.get_history();
  render();
}

async function updateSettings(change) {
  const next = structuredClone(state.settings.settings);
  change(next);
  const previous = state.settings;
  state.settings = { ...previous, settings: next };
  render();
  const res = await state.api.save_settings(next);
  if (!res.ok) {
    state.settings = previous;
    showToast(res.error);
    return;
  }
  state.settings = await state.api.get_settings();
  render();
}

async function addExclusion(pathType) {
  const res = await state.api.choose_exclusion(pathType);
  if (!res.ok) return showToast(res.error);
  state.exclusions = res.paths;
  render();
}

async function removeExclusion(path) {
  const res = await state.api.remove_exclusion(path);
  if (res.ok) state.exclusions = res.paths;
  render();
}

async function excludeFound(item) {
  const res = await state.api.exclude_found(item.path);
  if (!res.ok) return showToast(res.error);
  item.kept = true;
  state.exclusions = res.paths;
  showToast('Added to Never clean. Re-scan to update the totals.');
}

async function saveKeptCookies(domains) {
  const res = await state.api.set_kept_cookies(domains);
  if (!res.ok) return showToast(res.error);
  state.keptCookies = res.domains;
  render();
  return true;
}

async function addCookieFromInput() {
  const value = state.cookieInput.trim();
  if (!value) return;
  if (await saveKeptCookies([...state.keptCookies, value])) state.cookieInput = '';
  render();
}

async function openCookiePicker() {
  state.drawer = { picker: true, sites: null, chosen: new Set(state.keptCookies), filter: '' };
  render();
  const res = await state.api.get_cookie_sites();
  if (!state.drawer || !state.drawer.picker) return;
  if (!res.ok) {
    state.drawer = null;
    showToast(`Could not read cookies: ${res.error}`);
    return;
  }
  state.drawer.sites = [...new Set([...res.sites, ...state.keptCookies])].sort();
  render();
}

// ---------- Events from Python ----------

function onProgress(p) {
  if (!state.job) return;
  Object.assign(state.job, p);
  render();
}
on('scan-progress', onProgress);
on('clean-progress', onProgress);
on('scan-done', async result => {
  state.job = null;
  if (result.error) showToast(`Scan failed: ${result.error}`);
  else if (!result.cancelled) {
    state.scan = result;
    applyMode(state.mode === 'custom' ? 'basic' : state.mode);
  }
  await refreshOverview();
  render();
});
on('clean-done', async result => {
  state.job = null;
  state.scan = null;
  state.selected = new Set();
  state.lastClean = result;
  await refreshOverview();
  render();
});

// ---------- Shared pieces ----------

function checkbox({ checked, indeterminate, onchange, label, disabled }) {
  const el = h('input', { type: 'checkbox', class: 'check', 'aria-label': label, disabled, onclick: e => e.stopPropagation(), onchange });
  el.checked = !!checked;
  el.indeterminate = !!indeterminate;
  return el;
}

const RING_RADIUS = 46;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;
let ringNode = null;

/**
 * Progress ring with the percentage inside. The same element is reused
 * across renders so the band grows smoothly instead of jumping.
 */
function ring(job) {
  if (!ringNode) {
    const span = document.createElement('span');
    span.innerHTML = `<svg class="ring" viewBox="0 0 112 112" role="progressbar" aria-valuemin="0" aria-valuemax="100">
      <circle class="track" cx="56" cy="56" r="${RING_RADIUS}"/>
      <circle class="bar" cx="56" cy="56" r="${RING_RADIUS}" stroke-dasharray="${RING_LENGTH}" stroke-dashoffset="${RING_LENGTH}"/>
      <text class="pct" x="56" y="56" text-anchor="middle" dominant-baseline="central">0%</text></svg>`;
    ringNode = span.firstElementChild;
  }
  const fraction = Math.min(1, Math.max(0, job.fraction || 0));
  const percent = Math.floor(fraction * 100);
  // Before the first step finishes, a short spinning arc shows activity
  const waiting = fraction === 0;
  ringNode.classList.toggle('spin', waiting);
  ringNode.querySelector('.bar').setAttribute('stroke-dashoffset',
    waiting ? RING_LENGTH * 0.85 : RING_LENGTH * (1 - fraction));
  ringNode.querySelector('.pct').textContent = `${percent}%`;
  ringNode.setAttribute('aria-valuenow', String(percent));
  return ringNode;
}

function jobDetails(job) {
  const found = job.kind === 'scan' ? 'found' : 'removed';
  return [
    h('p', { class: 'muted job-step' }, job.message || '\u00a0'),
    h('p', { class: 'faint' }, job.items ? `${fmt.plural(job.items, 'item', 'items')} ${found} \u00b7 ${fmt.bytes(job.bytes)}` : '\u00a0'),
  ];
}

function lastScanTime() {
  return state.scan ? state.scan.finished : state.stats && state.stats.last_scan && state.stats.last_scan.time;
}

function rescanButton() {
  return h('button', { class: 'btn btn-outline', onclick: startScan, disabled: !!state.job },
    state.scan ? 'Re-scan' : 'Scan', icon('refresh'));
}

// ---------- Views ----------

const VIEWS = {
  home: { title: 'Welcome', render: homeView, scanBar: true },
  clean: { title: 'Clean junk', render: cleanView, scanBar: true, back: true },
  apps: { title: 'Apps', render: appsView, back: true },
  disks: { title: 'Disks', render: disksView, back: true },
  settings: { title: 'Settings', render: settingsView, back: true },
  history: { title: 'History', render: historyView, back: true },
  result: { title: () => (state.job ? 'Cleaning' : 'All done'), render: resultView, back: true },
};

function homeView() {
  const disk = visibleCategories('disk');
  const browsers = visibleCategories('browser');
  const totals = selectionTotals();
  const job = state.job;

  let hero;
  if (job) {
    hero = h('section', { class: 'card hero' },
      ring(job),
      h('div', { class: 'hero-body' },
        h('div', { class: 'big' }, job.kind === 'scan' ? 'Scanning your PC\u2026' : 'Cleaning\u2026'),
        jobDetails(job),
        job.kind === 'scan' && h('div', { class: 'actions' },
          h('button', { class: 'btn btn-outline', onclick: cancelJob }, 'Cancel'))));
  } else if (state.scan) {
    hero = h('section', { class: 'card hero' },
      h('div', { class: 'hero-badge' }, icon('spark')),
      h('div', { class: 'hero-body' },
        h('div', { class: 'big' }, h('span', { class: 'num' }, fmt.bytes(totals.bytes)), ' ready to clean'),
        h('p', { class: 'muted' }, `${fmt.plural(totals.items, 'item', 'items')} in ${fmt.plural(totals.rows, 'category', 'categories')}, chosen with ${state.mode === 'custom' ? 'your custom' : state.mode === 'full' ? 'Full' : 'Basic'} settings.`),
        h('div', { class: 'actions' },
          h('button', { class: 'btn btn-primary btn-lg', onclick: confirmClean, disabled: !totals.items }, icon('spark'), 'Clean now'),
          h('button', { class: 'btn btn-outline btn-lg', onclick: () => go('clean') }, 'Review items'))));
  } else {
    hero = h('section', { class: 'card hero' },
      h('div', { class: 'hero-body' },
        h('div', { class: 'big' }, 'Free up space in one click'),
        h('p', { class: 'muted' }, 'Cleanly looks for temporary files, logs, caches and browser leftovers. Nothing is deleted until you choose to clean.'),
        h('div', { class: 'actions' },
          h('button', { class: 'btn btn-primary btn-lg', onclick: startScan }, icon('refresh'), 'Scan now'))));
  }

  const sum = list => list.reduce((s, c) => s + c.bytes, 0);
  const tile = (iconName, title, value, note, view, soon) =>
    h('button', { class: 'card tile', onclick: () => go(view) },
      h('div', { class: 'card-head' }, icon(iconName), h('h3', null, title)),
      soon ? h('span', { class: 'soon' }, 'Coming soon') : h('div', { class: 'value' }, value),
      h('p', { class: 'muted' }, note));

  const runningBrowsers = browsers.filter(b => b.running);
  const tiles = h('div', { class: 'tiles' },
    tile('files', 'Junk files', state.scan ? fmt.bytes(sum(disk)) : '—',
      state.scan ? `Found in ${fmt.plural(disk.length, 'category', 'categories')}` : 'Scan to see what can go', 'clean'),
    tile('globe', 'Browsers', state.scan ? fmt.bytes(sum(browsers)) : '—',
      runningBrowsers.length ? `${runningBrowsers.map(b => b.label).join(', ')} open: close to scan` : state.scan ? `${fmt.plural(browsers.length, 'browser', 'browsers')} with junk` : 'Caches, history and cookies', 'clean'),
    tile('apps', 'Apps', '', 'Find and uninstall apps you no longer use.', 'apps', true),
    tile('disk', 'Disks', '', 'Optimize drives and check their health.', 'disks', true));

  const stats = state.stats || { bytes_freed: 0, items_removed: 0, cleanings: 0, history: [] };
  const side = h('aside', { class: 'home-side' },
    h('section', { class: 'card' },
      h('div', { class: 'card-head' }, icon('stats'), h('h3', null, 'Your results')),
      h('div', { class: 'stat' }, h('div', { class: 'value' }, fmt.bytes(stats.bytes_freed)), h('div', { class: 'label' }, 'space freed')),
      h('div', { class: 'stat' }, h('div', { class: 'value' }, fmt.count(stats.items_removed)), h('div', { class: 'label' }, 'items removed')),
      h('div', { class: 'stat' }, h('div', { class: 'value' }, fmt.count(stats.cleanings)), h('div', { class: 'label' }, stats.cleanings === 1 ? 'cleaning' : 'cleanings'))),
    h('section', { class: 'card' },
      h('div', { class: 'card-head' }, icon('clock'), h('h3', null, 'Recent cleanings'),
        stats.history.length > 0 && h('button', { class: 'link-btn', onclick: () => go('history') }, 'See all')),
      stats.history.length
        ? stats.history.slice(0, 5).map(e => h('div', { class: 'history-row' }, h('span', { class: 'muted' }, fmt.date(e.time)), h('span', null, fmt.bytes(e.bytes))))
        : h('p', { class: 'muted' }, 'Nothing yet.')));

  return h('div', { class: 'home' }, h('div', { class: 'home-main' }, hero, tiles), side);
}

function needScanPanel() {
  const job = state.job;
  if (job) {
    return h('div', { class: 'center-panel' },
      ring(job),
      h('h2', null, job.kind === 'scan' ? 'Scanning your PC\u2026' : 'Cleaning\u2026'),
      jobDetails(job),
      job.kind === 'scan' && h('button', { class: 'btn btn-outline', onclick: cancelJob }, 'Cancel'));
  }
  return h('div', { class: 'center-panel' },
    h('div', { class: 'icon-circle' }, icon('files')),
    h('h2', null, 'Scan first'),
    h('p', { class: 'muted' }, 'A scan finds what can be cleaned. Nothing is deleted until you press Clean.'),
    h('button', { class: 'btn btn-primary btn-lg', onclick: startScan }, 'Scan now'));
}

const MODE_HINTS = {
  basic: 'Safe everyday cleaning: temp files, logs and caches.',
  full: 'Also clears history, cookies and recent activity.',
  custom: 'You choose exactly what to clean.',
};

function cleanView() {
  if (!state.scan || state.job) return needScanPanel();
  const disk = visibleCategories('disk');
  const browsers = visibleCategories('browser');
  const kind = state.tab === 'browsers' ? 'browser' : 'disk';
  const totals = selectionTotals(kind);
  const all = selectionTotals();

  const tabs = h('div', { class: 'tabs', role: 'tablist' },
    h('button', { class: 'tab', role: 'tab', 'aria-selected': String(state.tab === 'disk'), onclick: () => { state.tab = 'disk'; render(); } },
      icon('files'), 'Disk cleaner', h('span', { class: 'count' }, fmt.bytes(disk.reduce((s, c) => s + c.bytes, 0)))),
    h('button', { class: 'tab', role: 'tab', 'aria-selected': String(state.tab === 'browsers'), onclick: () => { state.tab = 'browsers'; render(); } },
      icon('globe'), 'Browser cleaner', h('span', { class: 'count' }, fmt.bytes(browsers.reduce((s, c) => s + c.bytes, 0)))));

  const toolbar = h('div', { class: 'toolbar' },
    h('span', { class: 'muted' }, 'Cleaning mode'),
    h('div', { class: 'segmented', role: 'group', 'aria-label': 'Cleaning mode' },
      ['basic', 'full', 'custom'].map(mode => h('button', {
        'aria-pressed': String(state.mode === mode),
        onclick: () => { applyMode(mode); render(); },
      }, mode[0].toUpperCase() + mode.slice(1)))),
    h('span', { class: 'mode-hint' }, MODE_HINTS[state.mode]));

  const body = kind === 'disk' ? diskTable(disk) : browserTable(browsers);
  const footer = h('div', { class: 'footer' },
    h('div', { class: 'summary' },
      h('div', { class: 'strong' }, `${fmt.plural(totals.rows, kind === 'disk' ? 'category' : 'browser', kind === 'disk' ? 'categories' : 'browsers')} selected here`),
      h('div', { class: 'muted' }, `In total you'll free ${fmt.bytes(all.bytes)} (${fmt.plural(all.items, 'item', 'items')})`)),
    h('button', { class: 'btn btn-primary btn-lg', onclick: confirmClean, disabled: !all.items }, icon('spark'), 'Clean'));

  return h('div', null, tabs, toolbar, body, footer);
}

function diskTable(disk) {
  const allCategories = state.scan.categories.filter(c => c.kind === 'disk');
  const cleanCount = allCategories.length - disk.length;
  const allIds = disk.flatMap(c => categoryState(c).ids);
  const nSelected = allIds.filter(id => state.selected.has(id)).length;
  return h('div', null,
    h('div', { class: 'table', role: 'table' },
      h('div', { class: 'row head', role: 'row' },
        checkbox({ checked: nSelected && nSelected === allIds.length, indeterminate: nSelected && nSelected < allIds.length, label: 'Select all', onchange: e => setChecked(allIds, e.target.checked) }),
        h('span', null, 'Name'), h('span', null, 'Items'), h('span', null, 'Size'), h('span')),
      disk.length ? disk.map(c => {
        const s = categoryState(c);
        return h('div', { class: 'row clickable', role: 'row', onclick: () => openDrawer(c), title: 'Show files' },
          checkbox({ ...s, label: c.label, onchange: e => setChecked(s.ids, e.target.checked) }),
          h('div', { class: 'name' },
            h('div', { class: 'title' }, c.label, c.mode === 'full' && h('span', { class: 'badge mode' }, 'Full')),
            h('div', { class: 'desc' }, c.description)),
          h('span', { class: 'cell-num' }, fmt.count(c.items)),
          h('span', { class: 'cell-num' }, fmt.bytes(c.bytes)),
          h('span', { class: 'chev' }, icon('chevron')));
      }) : h('div', { class: 'row' }, h('span'), h('span', { class: 'muted' }, 'No junk files found.'))),
    cleanCount > 0 && h('div', { class: 'clean-note' }, icon('check'), `${fmt.plural(cleanCount, 'other category is', 'other categories are')} already clean.`),
    skippedNote());
}

/** Note naming non-browser apps the last scan skipped because they were open */
function skippedNote() {
  const browserNames = new Set(state.scan.categories.filter(c => c.kind === 'browser').map(c => c.label));
  const apps = (state.scan.skipped_running || []).filter(name => !browserNames.has(name));
  if (!apps.length) return null;
  const one = apps.length === 1;
  return h('div', { class: 'clean-note' }, icon('info'),
    `Not scanned because ${one ? 'it is' : 'they are'} open: ${apps.join(', ')}. Close ${one ? 'it' : 'them'} and scan again to include ${one ? 'it' : 'them'}.`);
}

function browserTable(browsers) {
  if (!browsers.length) {
    return h('div', { class: 'table' }, h('div', { class: 'row' }, h('span'), h('span', { class: 'muted' }, 'No browser junk found.')));
  }
  return h('div', { class: 'table', role: 'table' },
    browsers.map((c, i) => {
      const s = categoryState(c);
      const open = state.expanded.has(c.id);
      const toggle = () => { open ? state.expanded.delete(c.id) : state.expanded.add(c.id); render(); };
      const avatar = h('span', { class: 'avatar', style: `background:${BROWSER_COLORS[i % BROWSER_COLORS.length]}` }, c.label[0]);
      if (c.running) {
        return h('div', { class: 'row', role: 'row' },
          checkbox({ checked: false, disabled: true, label: c.label }),
          h('div', { class: 'browser-name' }, avatar,
            h('div', { class: 'name' },
              h('div', { class: 'title' }, c.label, h('span', { class: 'badge warn' }, 'Open')),
              h('div', { class: 'desc' }, `Not scanned while it is open. Close ${c.label} and scan again.`))),
          h('span', { class: 'cell-num' }, '\u2014'),
          h('span', { class: 'cell-num' }, '\u2014'),
          h('span'));
      }
      const row = h('div', { class: `row clickable${open ? ' open' : ''}`, role: 'row', onclick: toggle, 'aria-expanded': String(open) },
        checkbox({ ...s, label: c.label, onchange: e => setChecked(s.ids, e.target.checked) }),
        h('div', { class: 'browser-name' }, avatar,
          h('div', { class: 'name' },
            h('div', { class: 'title' }, c.label),
            h('div', { class: 'desc' }, `${fmt.plural(c.options.filter(o => o.items > 0).length, 'kind of data', 'kinds of data')} found`))),
        h('span', { class: 'cell-num' }, fmt.count(c.items)),
        h('span', { class: 'cell-num' }, fmt.bytes(c.bytes)),
        h('span', { class: 'chev' }, icon('chevron')));
      if (!open) return row;
      const subs = h('div', { class: 'sub-rows' },
        c.options.filter(o => o.items > 0).map(o => h('div', { class: 'row' },
          checkbox({ checked: state.selected.has(o.id), label: o.label, onchange: e => setChecked([o.id], e.target.checked) }),
          h('div', { class: 'name' }, h('div', { class: 'title' }, o.label, o.mode === 'full' && h('span', { class: 'badge mode' }, 'Full'))),
          h('span', { class: 'cell-num' }, fmt.count(o.items)),
          h('span', { class: 'cell-num' }, fmt.bytes(o.bytes)),
          h('span'))),
        h('div', { class: 'row' }, h('span'),
          h('div', null, h('button', { class: 'btn btn-ghost', onclick: () => openDrawer(c) }, 'View files')),
          h('span'), h('span'), h('span')));
      return [row, subs];
    }));
}

function resultView() {
  const job = state.job;
  if (job && job.kind === 'clean') {
    return h('div', { class: 'center-panel' },
      ring(job),
      h('h2', null, 'Cleaning\u2026'),
      jobDetails(job));
  }
  const r = state.lastClean;
  if (!r) return needScanPanel();
  if (r.error) {
    return h('div', { class: 'center-panel' }, h('h2', null, 'Cleaning stopped'), h('p', { class: 'muted' }, r.error),
      h('button', { class: 'btn btn-outline', onclick: () => go('home') }, 'Back to home'));
  }
  return h('div', { class: 'center-panel' },
    h('div', { class: 'icon-circle' }, icon('check')),
    h('div', { class: 'big' }, 'You freed ', h('span', { class: 'num' }, fmt.bytes(r.bytes))),
    h('p', { class: 'muted' }, `${fmt.plural(r.items, 'item', 'items')} removed.`),
    r.skipped_running && r.skipped_running.length > 0 && h('div', { class: 'notice' },
      `${r.skipped_running.join(', ')} ${r.skipped_running.length === 1 ? 'was' : 'were'} open, so ${r.skipped_running.length === 1 ? 'it was' : 'they were'} skipped. Close ${r.skipped_running.length === 1 ? 'it' : 'them'} and clean again.`),
    r.errors && r.errors.length > 0 && h('div', { class: 'notice' },
      `${fmt.plural(r.errors.length, 'item', 'items')} could not be cleaned, usually because a program was using ${r.errors.length === 1 ? 'it' : 'them'}.`),
    h('div', { class: 'actions', style: 'display:flex;gap:10px;margin-top:8px' },
      h('button', { class: 'btn btn-primary', onclick: () => go('home') }, 'Back to home'),
      h('button', { class: 'btn btn-outline', onclick: () => { go('home'); startScan(); } }, 'Scan again')));
}

function placeholder(iconName, title, text, plans) {
  return h('div', { class: 'center-panel' },
    h('div', { class: 'icon-circle' }, icon(iconName)),
    h('h2', null, title),
    h('p', { class: 'muted' }, text),
    h('ul', { class: 'plan-list' }, plans.map(p => h('li', null, p))));
}

function appsView() {
  return placeholder('apps', 'Apps are coming soon', 'This is where you will manage what is installed on your PC.', [
    'See every installed app with its size and when you last used it',
    'Spot apps you have not opened in months',
    'Uninstall them and review leftover files',
    'Choose which apps start with Windows',
  ]);
}

function disksView() {
  return placeholder('disk', 'Disk tools are coming soon', 'This is where you will look after your drives.', [
    'Analyze and optimize drives with Windows’ own tools (defragments hard drives, trims SSDs)',
    'Check drive health',
    'Find large files that take up space',
  ]);
}

function readTheme() {
  try { return localStorage.getItem('theme') || 'system'; } catch { return 'system'; }
}

function setTheme(theme) {
  try { localStorage.setItem('theme', theme); } catch { /* storage unavailable */ }
  applyTheme(theme);
  render();
}

function applyTheme(theme) {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
}

const WEEKDAYS = [['MON', 'Monday'], ['TUE', 'Tuesday'], ['WED', 'Wednesday'],
  ['THU', 'Thursday'], ['FRI', 'Friday'], ['SAT', 'Saturday'], ['SUN', 'Sunday']];

function settingRow(title, hint, control) {
  return h('div', { class: 'setting-row' },
    h('div', { class: 'grow' }, h('div', null, title), hint && h('div', { class: 'hint' }, hint)),
    control);
}

function toggle(checked, label, onchange, disabled) {
  const el = h('input', { type: 'checkbox', class: 'switch', role: 'switch', 'aria-label': label, disabled, onchange: e => onchange(e.target.checked) });
  el.checked = !!checked;
  return el;
}

function scheduleCard() {
  if (!state.settings) return h('section', { class: 'card' }, h('h3', null, 'Scheduled scans'), h('p', { class: 'muted' }, 'Loading\u2026'));
  const st = state.settings.settings;
  const sched = st.schedule;
  const on = sched.frequency !== 'off';
  const bg = state.stats && state.stats.last_background;
  let lastRun = 'No background scan has run yet.';
  if (bg) {
    lastRun = `Last background scan ${fmt.ago(bg.time)}: ${bg.cleaned_bytes ? `freed ${fmt.bytes(bg.cleaned_bytes)}` : `found ${fmt.bytes(bg.found_bytes)}`}.`;
  }
  return h('section', { class: 'card' },
    h('div', { class: 'card-head' }, icon('clock'), h('h3', null, 'Scheduled scans')),
    h('p', { class: 'lead' }, 'Cleanly can scan in the background, even when it is closed. Nothing keeps running between scans, and scans wait if your laptop is on battery.'),
    settingRow('How often', null,
      h('div', { class: 'segmented', role: 'group', 'aria-label': 'How often' },
        [['off', 'Off'], ['daily', 'Daily'], ['weekly', 'Weekly']].map(([value, label]) =>
          h('button', { 'aria-pressed': String(sched.frequency === value), onclick: () => updateSettings(n => { n.schedule.frequency = value; }) }, label)))),
    on && settingRow('When', 'If your PC is off then, the scan runs the next time it is on.',
      h('div', { class: 'button-row' },
        sched.frequency === 'weekly' && h('select', { class: 'field', 'aria-label': 'Day', onchange: e => updateSettings(n => { n.schedule.weekday = e.target.value; }) },
          WEEKDAYS.map(([value, label]) => h('option', { value, selected: sched.weekday === value }, label))),
        h('input', { class: 'field', type: 'time', value: sched.time, 'aria-label': 'Time', onchange: e => { if (e.target.value) updateSettings(n => { n.schedule.time = e.target.value; }); } }))),
    settingRow('Notify me', `When a scan finds at least ${fmt.bytes(st.notify_min_bytes)} of junk, or after an automatic clean.`,
      toggle(st.notify, 'Notify me', v => updateSettings(n => { n.notify = v; }), !on)),
    settingRow('Clean automatically', 'Cleans what Basic mode would: temp files, logs and caches. History, cookies and the Recycle Bin are never cleaned automatically.',
      toggle(st.auto_clean, 'Clean automatically', v => updateSettings(n => { n.auto_clean = v; }), !on)),
    h('p', { class: 'faint', style: 'margin-top:8px;font-size:12.5px' }, on && !state.settings.scheduled ? 'The scheduled task is missing. Choose a schedule again to recreate it.' : lastRun));
}

function exclusionsCard() {
  const list = state.exclusions;
  return h('section', { class: 'card' },
    h('div', { class: 'card-head' }, icon('shield'), h('h3', null, 'Never clean')),
    h('p', { class: 'lead' }, 'Files and folders here are never cleaned by any category. You can also add items from the file list in Clean junk.'),
    h('div', { class: 'list' },
      list === null ? h('div', { class: 'list-empty' }, 'Loading\u2026')
        : list.length === 0 ? h('div', { class: 'list-empty' }, 'Nothing added yet.')
          : list.map(item => h('div', { class: 'list-row' },
            icon(item.type === 'folder' ? 'folder' : 'files'),
            h('span', { class: 'p', title: item.path }, h('bdi', null, item.path)),
            h('button', { class: 'icon-btn', 'aria-label': `Remove ${item.path}`, title: 'Remove', onclick: () => removeExclusion(item.path) }, icon('close'))))),
    h('div', { class: 'button-row' },
      h('button', { class: 'btn btn-outline', onclick: () => addExclusion('folder') }, icon('folder'), 'Add folder'),
      h('button', { class: 'btn btn-outline', onclick: () => addExclusion('file') }, icon('files'), 'Add file')));
}

function cookiesCard() {
  const kept = state.keptCookies;
  return h('section', { class: 'card' },
    h('div', { class: 'card-head' }, icon('globe'), h('h3', null, 'Cookies to keep')),
    h('p', { class: 'lead' }, 'Cookies keep you signed in to websites. When cookies are cleaned, the ones for these sites stay.'),
    kept === null ? h('p', { class: 'muted' }, 'Loading\u2026')
      : kept.length === 0 ? h('p', { class: 'muted', style: 'margin-bottom:12px' }, 'No sites yet: cleaning cookies signs you out everywhere.')
        : h('div', { class: 'chips' }, kept.map(domain => h('span', { class: 'chip' }, domain,
          h('button', { class: 'icon-btn', 'aria-label': `Stop keeping ${domain}`, onclick: () => saveKeptCookies(kept.filter(d => d !== domain)) }, icon('close'))))),
    h('form', { class: 'button-row', onsubmit: e => { e.preventDefault(); addCookieFromInput(); } },
      h('input', { class: 'field', 'data-key': 'cookie-input', placeholder: 'example.com', 'aria-label': 'Website to keep', value: state.cookieInput, oninput: e => { state.cookieInput = e.target.value; } }),
      h('button', { class: 'btn btn-outline', type: 'submit' }, 'Add'),
      h('button', { class: 'btn btn-ghost', type: 'button', onclick: openCookiePicker }, 'Choose from your browsers')));
}

function settingsView() {
  const theme = readTheme();
  return h('div', { class: 'settings-list' },
    scheduleCard(),
    exclusionsCard(),
    cookiesCard(),
    h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('h3', null, 'Appearance')),
      h('div', { class: 'toolbar' },
        h('span', { class: 'muted' }, 'Theme'),
        h('div', { class: 'segmented', role: 'group', 'aria-label': 'Theme' },
          ['system', 'dark', 'light'].map(t => h('button', { 'aria-pressed': String(theme === t), onclick: () => setTheme(t) }, t[0].toUpperCase() + t.slice(1)))))),
    h('section', { class: 'card' },
      h('div', { class: 'card-head' }, icon('shield'), h('h3', null, `About ${state.info.name}`)),
      h('p', null, `Version ${state.info.version}`),
      h('p', { class: 'muted', style: 'margin-top:6px' }, 'Cleanly is free and open-source software under the GNU GPL version 3 or later. It is built on the BleachBit cleaning engine by Andrew Ziem and contributors.')));
}

function historyView() {
  const data = state.history;
  if (!data) return h('p', { class: 'muted' }, 'Loading\u2026');
  const stats = state.stats || { bytes_freed: 0, cleanings: 0 };
  if (!data.history.length) {
    return h('div', { class: 'center-panel' },
      h('div', { class: 'icon-circle' }, icon('clock')),
      h('h2', null, 'No cleanings yet'),
      h('p', { class: 'muted' }, 'Each time you clean, it shows up here.'),
      h('button', { class: 'btn btn-primary', onclick: () => go('home') }, 'Go to Home'));
  }
  return h('div', { class: 'history' },
    h('p', { class: 'muted' }, `${fmt.plural(stats.cleanings, 'cleaning', 'cleanings')} so far, ${fmt.bytes(stats.bytes_freed)} freed in total.`),
    data.history.map(e => h('section', { class: 'card history-entry' },
      h('div', null,
        h('div', null, h('strong', null, fmt.date(e.time)), e.source === 'scheduled' && h('span', { class: 'badge mode' }, 'Automatic')),
        h('div', { class: 'faint', style: 'font-size:13px' }, fmt.plural(e.items, 'item removed', 'items removed'))),
      h('div', { class: 'size num' }, fmt.bytes(e.bytes)),
      e.categories && e.categories.length > 0 && h('div', { class: 'what' }, e.categories.join(', ')))));
}

function cookiePickerView(d) {
  const close = () => { state.drawer = null; render(); };
  const filter = d.filter.trim().toLowerCase();
  const sites = d.sites && d.sites.filter(site => site.includes(filter));
  return h('div', { class: 'scrim', onclick: e => { if (e.target === e.currentTarget) close(); } },
    h('aside', { class: 'drawer', role: 'dialog', 'aria-label': 'Choose cookies to keep' },
      h('div', { class: 'drawer-head' },
        h('div', { class: 'grow' },
          h('h2', null, 'Choose cookies to keep'),
          h('p', { class: 'muted' }, 'Sites that have cookies in your browsers. Tick the ones you want to stay signed in to.')),
        h('button', { class: 'icon-btn', onclick: close, 'aria-label': 'Close' }, icon('close'))),
      h('div', { class: 'drawer-tools' },
        h('input', { class: 'field', 'data-key': 'cookie-filter', placeholder: 'Search sites', 'aria-label': 'Search sites', value: d.filter, oninput: e => { d.filter = e.target.value; render(); } })),
      h('div', { class: 'drawer-body', 'data-scroll-key': 'picker' },
        sites === null ? h('p', { class: 'drawer-note' }, 'Reading cookies from your browsers\u2026')
          : sites.length === 0 ? h('p', { class: 'drawer-note' }, filter ? 'No matching sites.' : 'No cookies found. Browsers that are open may be skipped.')
            : sites.map(site => h('label', { class: 'pick-row' },
              checkbox({ checked: d.chosen.has(site), label: site, onchange: e => { e.target.checked ? d.chosen.add(site) : d.chosen.delete(site); render(); } }),
              site))),
      h('div', { class: 'drawer-foot' },
        h('span', { class: 'muted' }, `${fmt.plural(d.chosen.size, 'site', 'sites')} chosen`),
        h('button', { class: 'btn btn-outline', onclick: close }, 'Cancel'),
        h('button', { class: 'btn btn-primary', onclick: async () => { if (await saveKeptCookies([...d.chosen])) close(); } }, 'Save'))));
}

// ---------- Overlays ----------

function drawerView() {
  const d = state.drawer;
  if (!d) return null;
  if (d.picker) return cookiePickerView(d);
  const close = () => { state.drawer = null; render(); };
  const items = d.items;
  return h('div', { class: 'scrim', onclick: e => { if (e.target === e.currentTarget) close(); } },
    h('aside', { class: 'drawer', role: 'dialog', 'aria-label': d.category.label },
      h('div', { class: 'drawer-head' },
        h('div', { class: 'grow' },
          h('h2', null, d.category.label),
          h('p', { class: 'muted' }, `${fmt.plural(d.category.items, 'item', 'items')} · ${fmt.bytes(d.category.bytes)}`)),
        h('button', { class: 'icon-btn', onclick: close, 'aria-label': 'Close' }, icon('close'))),
      h('div', { class: 'drawer-body', 'data-scroll-key': 'drawer' },
        items === null ? h('p', { class: 'drawer-note' }, 'Loading…')
          : items.length === 0 ? h('p', { class: 'drawer-note' }, 'These items are not individual files (for example registry entries or a database clean-up).')
            : items.map(it => h('div', { class: `path-row${it.kept ? ' kept' : ''}`, title: it.path },
              h('span', { class: 'p' }, h('bdi', null, it.path)),
              h('span', { class: 's' }, it.kept ? h('span', { class: 'kept-label' }, 'Never clean') : typeof it.size === 'number' ? fmt.bytes(it.size) : ''),
              it.kept ? h('span') : h('button', { class: 'icon-btn keep', title: 'Never clean this', 'aria-label': `Never clean ${it.path}`, onclick: () => excludeFound(it) }, icon('shield'))))),
      items && items.length > 0 && items.length < d.category.items &&
        h('p', { class: 'drawer-note' }, `Showing the first ${fmt.count(items.length)} of ${fmt.count(d.category.items)} items.`)));
}

function dialogView() {
  const d = state.dialog;
  if (!d) return null;
  const close = () => { state.dialog = null; render(); };
  return h('div', { class: 'scrim center', onclick: e => { if (e.target === e.currentTarget) close(); } },
    h('div', { class: 'dialog', role: 'alertdialog', 'aria-label': d.title },
      h('h2', null, d.title),
      h('ul', null, d.reasons.map(r => h('li', null, r))),
      h('div', { class: 'actions' },
        h('button', { class: 'btn btn-outline', onclick: close }, 'Go back'),
        h('button', { class: 'btn btn-primary', onclick: startClean }, 'Clean anyway'))));
}

// ---------- Shell ----------

const NAV = [
  ['home', 'home', 'Home'],
  ['clean', 'clean', 'Clean junk'],
  ['apps', 'apps', 'Apps'],
  ['disks', 'disk', 'Disks'],
];

function navButton([view, iconName, label]) {
  const current = state.view === view || (view === 'clean' && state.view === 'result');
  return h('button', { class: 'nav-btn', 'aria-label': label, 'aria-current': current ? 'page' : null, onclick: () => go(view) },
    icon(iconName), h('span', { class: 'tooltip' }, label));
}

// Overlays already shown, so their opening animation does not replay
const shownOverlays = new WeakSet();
const shownToasts = new Set();

/** Mark an overlay element to animate the first time its state appears */
function entering(key, el) {
  if (!el) return el;
  const seen = typeof key === 'object' ? shownOverlays.has(key) : shownToasts.has(key);
  if (!seen) {
    el.classList.add('enter');
    if (typeof key === 'object') shownOverlays.add(key);
    else {
      shownToasts.clear();
      shownToasts.add(key);
    }
  }
  return el;
}

let lastRenderedView = null;

function render() {
  const root = document.getElementById('app');
  const oldContent = root.querySelector('.content');
  const scrollTop = oldContent ? oldContent.scrollTop : 0;
  // Re-rendering replaces elements, so carry over focus and scrolling
  const focused = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.key;
  const selection = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  const scrolls = {};
  for (const el of root.querySelectorAll('[data-scroll-key]')) scrolls[el.dataset.scrollKey] = el.scrollTop;
  const view = VIEWS[state.view];
  const last = lastScanTime();

  const topbar = h('header', { class: 'topbar' },
    h('div', { class: 'crumbs' },
      view.back && h('button', { class: 'back', onclick: () => go('home'), 'aria-label': 'Back to home' }, icon('back')),
      h('h1', null, typeof view.title === 'function' ? view.title() : view.title)),
    view.scanBar && last && h('span', { class: 'last-scan' }, `Last scan: ${fmt.ago(last)}`),
    view.scanBar && rescanButton());

  const content = h('main', { class: `content${state.view === 'clean' && state.scan && !state.job ? ' has-footer' : ''}` }, view.render());

  const shell = h('div', { class: 'shell' },
    h('nav', { class: 'sidebar', 'aria-label': 'Main' },
      h('img', { class: 'logo', src: 'assets/logo.svg', alt: 'Cleanly' }),
      NAV.map(navButton),
      h('div', { class: 'nav-spacer' }),
      navButton(['history', 'clock', 'History']),
      navButton(['settings', 'settings', 'Settings'])),
    h('div', { class: 'main' }, topbar, content));

  const toast = state.toast && h('div', { class: 'scrim center', style: 'background:none;pointer-events:none;align-items:flex-end;padding-bottom:28px' },
    h('div', { class: 'dialog', style: 'width:auto' }, state.toast));
  root.replaceChildren(shell, entering(state.drawer, drawerView()) || '',
    entering(state.dialog, dialogView()) || '', entering(state.toast, toast) || '');
  const newContent = root.querySelector('.content');
  // A new page starts at the top
  if (newContent && oldContent && lastRenderedView === state.view) newContent.scrollTop = scrollTop;
  lastRenderedView = state.view;
  for (const el of root.querySelectorAll('[data-scroll-key]')) {
    if (el.dataset.scrollKey in scrolls) el.scrollTop = scrolls[el.dataset.scrollKey];
  }
  if (focused) {
    const el = root.querySelector(`[data-key="${focused}"]`);
    if (el) {
      el.focus();
      if (selection && el.setSelectionRange) el.setSelectionRange(...selection);
    }
  }
}

async function start() {
  applyTheme(readTheme());
  try {
    state.api = await connect();
  } catch (e) {
    document.getElementById('app').replaceChildren(h('div', { class: 'center-panel' },
      h('h2', null, 'Cleanly could not start'), h('p', { class: 'muted' }, e.message)));
    return;
  }
  state.info = await state.api.get_app_info();
  await refreshOverview();
  const scan = await state.api.get_scan();
  if (scan) {
    state.scan = scan;
    applyMode('basic');
  }
  render();
  // Keep "Last scan: x ago" fresh
  setInterval(() => { if (!state.job && !state.drawer && !state.dialog) render(); }, 60000);
}

start();
