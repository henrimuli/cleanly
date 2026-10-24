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
      browser('google_chrome', 'Google Chrome', true, [
        ['cache', 'Cache', 'basic', 12109, 470.2 * MB],
        ['crash_reports', 'Crash reports', 'basic', 21, 7.0 * MB],
        ['cookies', 'Cookies', 'full', 1, 1.2 * MB],
        ['history', 'Browsing history', 'full', 3, 9.8 * MB],
        ['session', 'Open tabs and session', 'full', 4, 0.6 * MB],
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
    history: [
      { time: Date.now() / 1000 - 86400 * 2, bytes: 812 * MB, items: 2311 },
      { time: Date.now() / 1000 - 86400 * 9, bytes: 1.3 * 1000 * MB, items: 5120 },
    ],
  };
  let timer = null;

  function run(kind, steps, done) {
    let i = 0;
    const names = ['System', 'Google Chrome', 'Microsoft Edge', 'Firefox', 'Discord', 'VS Code'];
    timer = setInterval(() => {
      i += 1;
      emit(`${kind}-progress`, { fraction: i / steps });
      emit(`${kind}-progress`, { message: `Please wait.  ${kind === 'scan' ? 'Previewing' : 'Cleaning'} ${names[i % names.length]}.` });
      if (i >= steps) {
        clearInterval(timer);
        timer = null;
        done();
      }
    }, 180);
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
  };
}
