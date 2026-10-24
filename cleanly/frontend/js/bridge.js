// SPDX-License-Identifier: GPL-3.0-or-later
// Connects the UI to Python (pywebview) or, in a plain browser, to a mock

const listeners = {};

// Python delivers events by calling window.cleanly.emit(name, payload)
window.cleanly = {
  emit(name, payload) {
    for (const fn of listeners[name] || []) fn(payload);
  },
};

export function on(name, fn) {
  (listeners[name] ||= []).push(fn);
}

function waitForPywebview(timeoutMs) {
  return new Promise(resolve => {
    if (window.pywebview && window.pywebview.api) return resolve(true);
    const timer = setTimeout(() => resolve(false), timeoutMs);
    window.addEventListener('pywebviewready', () => {
      clearTimeout(timer);
      resolve(true);
    }, { once: true });
  });
}

/** Resolve to an object with the same methods as cleanly/bridge/api.py */
export async function connect() {
  // index.html?mock opens the UI in an ordinary browser with fake data,
  // for design work and screenshot tests. The app itself never uses it.
  if (new URLSearchParams(location.search).has('mock')) {
    const { createMockApi } = await import('./mock.js');
    return createMockApi(window.cleanly.emit);
  }
  if (await waitForPywebview(15000)) return window.pywebview.api;
  throw new Error('Could not connect to the Cleanly engine');
}
