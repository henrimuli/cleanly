// SPDX-License-Identifier: GPL-3.0-or-later
// Fake API used when the UI is opened in a normal browser (design and tests)

const MB = 1000 * 1000;

function disk(id, label, description, items, size, opts = {}) {
  return {
    id, label, description, kind: 'disk', mode: opts.mode || 'basic',
    default: opts.default !== false, running: false,
    options: [{ id: `${id}.x`, bytes: size, items }],
    bytes: size, items,
    selected: {
      basic: opts.default !== false && (opts.mode || 'basic') === 'basic',
      full: opts.default !== false,
    },
  };
}

function browser(id, label, running, parts) {
  const options = parts.map(([opt, optLabel, mode, items, size]) => ({
    id: `${id}.${opt}`, label: optLabel, mode, items, bytes: size,
  }));
  return {
    id, label, description: 'Web browser', kind: 'browser', mode: 'basic',
    default: true, running, options,
    bytes: options.reduce((s, o) => s + o.bytes, 0),
    items: options.reduce((s, o) => s + o.items, 0),
    selected: { basic: true, full: true },
  };
}

function fakeScan() {
  const now = Date.now() / 1000;
  return {
    started: now - 6,
    finished: now,
    errors: [],
    skipped_running: ['Google Chrome', 'Discord'],
    categories: [
      disk('recycle_bin', 'Recycle Bin', 'Files you deleted that are still kept in the Recycle Bin.', 6, 571.6 * MB, { default: false }),
      disk('windows_temp', 'Windows temp files', 'Temporary files Windows created and no longer needs.', 622, 42.0 * MB),
      disk('program_temp', 'Program temp files', 'Temporary files left behind by installed programs.', 197, 18.1 * MB),
      disk('program_logs', 'Program log files', 'Diagnostic logs written by installed programs.', 376, 17.1 * MB),
      disk('windows_logs', 'Windows log files', 'Diagnostic logs written by Windows.', 386, 13.8 * MB),
      disk('program_downloads', 'Program download files', 'Installers and updates that programs downloaded and already used.', 7, 6.3 * MB),
      disk('windows_cache', 'Windows cache files', 'Thumbnail and other caches Windows can rebuild.', 1, 0.45 * MB),
      disk('crash_reports', 'Crash reports and memory dumps', 'Reports saved after programs or Windows crashed.', 0, 0),
      disk('recent_activity', 'Recent activity', 'Lists of recently opened files, searches and commands.', 214, 0.9 * MB, { mode: 'full' }),
      disk('system_caches', 'System caches', 'Prefetch, MUICache and DNS cache.', 133, 24.2 * MB, { mode: 'full' }),
      // Open while scanning, so it was skipped
      browser('google_chrome', 'Google Chrome', true, [
        ['cache', 'Cache', 'basic', 0, 0],
        ['cookies', 'Cookies', 'full', 0, 0],
      ]),
      browser('microsoft_edge', 'Microsoft Edge', false, [
        ['cache', 'Cache', 'basic', 5410, 96.4 * MB],
        ['cookies', 'Cookies', 'full', 1, 0.5 * MB],
        ['history', 'Browsing history', 'full', 216, 3.1 * MB],
      ]),
      browser('firefox', 'Firefox', false, [
        ['cache', 'Cache', 'basic', 0, 0],
      ]),
    ],
  };
}

export function createMockApi(emit) {
  let scan = null;
  const stats = {
    bytes_freed: 444.4 * 1000 * MB, items_removed: 991608, cleanings: 38,
    last_scan: null,
    last_background: { time: Date.now() / 1000 - 3600 * 20, found_bytes: 412 * MB, found_items: 3120, cleaned_bytes: 0, cleaned_items: 0, notified: true },
    history: [
      { time: Date.now() / 1000 - 86400 * 2, bytes: 812 * MB, items: 2311, source: 'manual', categories: ['Windows temp files', 'Program cache files', 'Google Chrome'] },
      { time: Date.now() / 1000 - 86400 * 9, bytes: 1.3 * 1000 * MB, items: 5120, source: 'scheduled', categories: ['Windows temp files', 'Program log files', 'Windows log files'] },
    ],
  };
  let timer = null;
  let settings = {
    schedule: { frequency: 'weekly', time: '10:00', weekday: 'SUN' },
    notify: true, notify_min_bytes: 100 * MB, auto_clean: false,
  };
  let exclusions = [
    { type: 'folder', path: 'C:\\Users\\Alex\\AppData\\Local\\Temp\\ProjectBuild' },
    { type: 'file', path: 'C:\\Users\\Alex\\Documents\\notes.log' },
  ];
  let keptCookies = ['github.com', 'mail.google.com'];
  const cookieSites = ['amazon.com', 'bbc.co.uk', 'github.com', 'google.com', 'mail.google.com',
    'netflix.com', 'news.ycombinator.com', 'reddit.com', 'stackoverflow.com', 'wikipedia.org', 'youtube.com'];

  function run(kind, steps, done) {
    let i = 0;
    const names = ['System: Temporary files', 'Microsoft Edge: Cache', 'Firefox: Cache',
      'Discord: Cache', 'VS Code: Logs', 'Windows Explorer: Thumbnails'];
    emit(`${kind}-progress`, { fraction: 0, message: names[0], items: 0, bytes: 0 });
    timer = setInterval(() => {
      i += 1;
      emit(`${kind}-progress`, {
        fraction: i / steps,
        message: names[i % names.length],
        items: i * 1367,
        bytes: i * 48 * MB,
      });
      if (i >= steps) {
        clearInterval(timer);
        timer = null;
        done();
      }
    }, 350);
  }

  return {
    async get_app_info() { return { name: 'Cleanly', version: '0.1.0 (preview data)' }; },
    async get_overview() { return { stats, busy: !!timer, has_scan: !!scan }; },
    async get_scan() { return scan; },
    async start_scan() {
      if (timer) return { ok: false, error: 'busy' };
      run('scan', 14, () => {
        scan = fakeScan();
        stats.last_scan = { time: scan.finished, bytes: 97.8 * MB, items: 1600 };
        emit('scan-done', scan);
      });
      return { ok: true };
    },
    async start_clean(operations) {
      if (timer) return { ok: false, error: 'busy' };
      const chosen = new Set(operations);
      let total = 0;
      let items = 0;
      const skipped = new Set();
      for (const c of scan.categories) {
        for (const o of c.options) {
          if (!chosen.has(o.id)) continue;
          if (c.running) { skipped.add(c.label); continue; }
          total += o.bytes;
          items += o.items;
        }
      }
      run('clean', 10, () => {
        stats.bytes_freed += total;
        stats.items_removed += items;
        stats.cleanings += 1;
        stats.history.unshift({ time: Date.now() / 1000, bytes: total, items });
        scan = null;
        emit('clean-done', {
          started: Date.now() / 1000 - 2, finished: Date.now() / 1000,
          bytes: total, items, skipped_running: [...skipped], errors: [],
        });
      });
      return { ok: true };
    },
    async cancel() {
      if (timer) { clearInterval(timer); timer = null; }
      emit('scan-done', { cancelled: true });
      return { ok: true };
    },
    async get_items(categoryId) {
      const c = scan && scan.categories.find(x => x.id === categoryId);
      if (!c) return { ok: false, error: 'Unknown category' };
      const n = Math.min(c.items, 40);
      const base = c.kind === 'browser'
        ? `C:\\Users\\Alex\\AppData\\Local\\${c.label.replace(' ', '\\')}\\User Data\\Default\\Cache\\Cache_Data`
        : 'C:\\Users\\Alex\\AppData\\Local\\Temp';
      const items = Array.from({ length: n }, (_, i) => ({
        path: `${base}\\f_${(0x1a2b + i * 7).toString(16)}.tmp`,
        size: Math.round(c.bytes / Math.max(1, c.items)),
      }));
      return { ok: true, items };
    },
    async get_history() { return { history: stats.history, last_background: stats.last_background }; },
    async get_settings() { return { settings: structuredClone(settings), scheduled: settings.schedule.frequency !== 'off' }; },
    async save_settings(data) {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(data.schedule.time)) return { ok: false, error: 'Time must look like 09:30' };
      settings = structuredClone(data);
      return { ok: true, settings };
    },
    async get_exclusions() { return { ok: true, paths: exclusions }; },
    async choose_exclusion(type) {
      const path = type === 'folder' ? 'C:\\Users\\Alex\\Downloads\\Keep' : 'C:\\Users\\Alex\\Desktop\\important.tmp';
      return this.add_exclusion(type, path);
    },
    async add_exclusion(type, path) {
      if (!exclusions.some(e => e.path === path)) exclusions = [...exclusions, { type, path }];
      return { ok: true, paths: exclusions };
    },
    async exclude_found(path) { return this.add_exclusion('file', path); },
    async remove_exclusion(path) {
      exclusions = exclusions.filter(e => e.path !== path);
      return { ok: true, paths: exclusions };
    },
    async get_kept_cookies() { return { ok: true, domains: keptCookies }; },
    async set_kept_cookies(domains) {
      const clean = [];
      for (const d of domains) {
        const v = d.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^\./, '').split('/')[0];
        if (!/^([a-z0-9-]+\.)+[a-z]{2,}$/.test(v)) return { ok: false, error: `"${v}" is not a website address` };
        clean.push(v);
      }
      keptCookies = [...new Set(clean)].sort();
      return { ok: true, domains: keptCookies };
    },
    async get_cookie_sites() {
      await new Promise(r => setTimeout(r, 400));
      return { ok: true, sites: cookieSites };
    },
  };
}
