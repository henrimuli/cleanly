# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Lifetime statistics and cleaning history, kept in a small JSON file
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

MAX_HISTORY = 100


def default_data_dir():
    """%APPDATA%\\Cleanly on Windows, ~/.config/cleanly elsewhere"""
    override = os.environ.get('CLEANLY_DATA_DIR')
    if override:
        return override
    appdata = os.environ.get('APPDATA')
    if os.name == 'nt' and appdata:
        return os.path.join(appdata, 'Cleanly')
    return os.path.join(os.path.expanduser('~'), '.config', 'cleanly')


def _empty():
    return {
        'bytes_freed': 0,
        'items_removed': 0,
        'cleanings': 0,
        'last_scan': None,
        'history': [],
    }


class Stats:
    """Read and update stats.json"""

    def __init__(self, data_dir=None):
        self.path = os.path.join(data_dir or default_data_dir(), 'stats.json')
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        data = _empty()
        try:
            with open(self.path, encoding='utf-8') as f:
                data.update(json.load(f))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.warning('Could not read %s; starting fresh', self.path,
                           exc_info=True)
        return data

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    def record_scan(self, summary):
        with self._lock:
            self.data['last_scan'] = summary
            self._save()

    def record_clean(self, summary):
        with self._lock:
            self.data['bytes_freed'] += summary.get('bytes', 0)
            self.data['items_removed'] += summary.get('items', 0)
            self.data['cleanings'] += 1
            self.data['history'].insert(0, {
                'time': summary.get('finished'),
                'bytes': summary.get('bytes', 0),
                'items': summary.get('items', 0),
            })
            del self.data['history'][MAX_HISTORY:]
            self._save()

    def to_dict(self):
        with self._lock:
            return json.loads(json.dumps(self.data))
