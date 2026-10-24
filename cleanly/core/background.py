# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
The scheduled background scan: Cleanly.exe --background-scan

Runs without a window. It scans, then either cleans the Basic
categories (when auto-clean is on) or tells the user how much junk it
found. Apps that are open are skipped, as in a normal scan.
"""

import logging
import threading
import time

from bleachbit.FileUtilities import bytes_to_human

from cleanly.core import notify as notify_mod

logger = logging.getLogger(__name__)

# Longest a background scan or clean may take, in seconds
JOB_TIMEOUT = 50 * 60


def _wait(start):
    """Run an Engine job to completion and return its result"""
    done = threading.Event()
    result = {}

    def on_done(r):
        result.update(r)
        done.set()
    start(lambda _progress: None, on_done)
    if not done.wait(JOB_TIMEOUT):
        raise TimeoutError('The background job took too long')
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result


def run(engine, stats, settings, notify=notify_mod.notify):
    """Scan, maybe clean, notify; return the summary that was recorded"""
    started = time.time()
    if not engine.categories:
        engine.load()
    _wait(engine.scan)
    found = engine.last_scan.summary()
    summary = {
        'time': started,
        'found_bytes': found['bytes'],
        'found_items': found['items'],
        'cleaned_bytes': 0,
        'cleaned_items': 0,
        'notified': False,
    }

    if settings['auto_clean']:
        operations = engine.last_scan.basic_operations()
        if operations:
            cleaned = _wait(lambda p, d: engine.clean(
                operations, p, d, source='scheduled'))
            summary['cleaned_bytes'] = cleaned['bytes']
            summary['cleaned_items'] = cleaned['items']
        if settings['notify'] and summary['cleaned_bytes']:
            summary['notified'] = notify(
                'Freed %s in the background.' %
                bytes_to_human(summary['cleaned_bytes']))
    elif settings['notify'] and found['bytes'] >= settings['notify_min_bytes']:
        summary['notified'] = notify(
            '%s of junk found. Open Cleanly to review and clean it.' %
            bytes_to_human(found['bytes']))

    stats.record_background(summary)
    logger.info('background scan: %s', summary)
    return summary
