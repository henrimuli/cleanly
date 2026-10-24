// SPDX-License-Identifier: GPL-3.0-or-later
// Number and time formatting

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/** 1536 -> "1.5 KB" (decimal units, as Windows Explorer shows sizes) */
export function bytes(n) {
  if (!n || n < 0) return '0 B';
  let i = 0;
  let value = n;
  while (value >= 1000 && i < UNITS.length - 1) {
    value /= 1000;
    i += 1;
  }
  const digits = i === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[i]}`;
}

export function count(n) {
  return (n || 0).toLocaleString();
}

export function plural(n, one, many) {
  return `${count(n)} ${n === 1 ? one : many}`;
}

/** Seconds since the epoch -> "3 hours ago" */
export function ago(epochSeconds) {
  if (!epochSeconds) return 'never';
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (seconds < 45) return 'just now';
  const units = [['year', 31536000], ['month', 2592000], ['week', 604800],
    ['day', 86400], ['hour', 3600], ['minute', 60]];
  for (const [name, size] of units) {
    const value = Math.floor(seconds / size);
    if (value >= 1) return `${value} ${name}${value === 1 ? '' : 's'} ago`;
  }
  return '1 minute ago';
}

export function date(epochSeconds) {
  if (!epochSeconds) return '';
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}
