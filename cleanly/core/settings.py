# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Cleanly's own preferences, kept in settings.json in the data folder

The engine keeps its own preferences (such as paths never to clean) in
bleachbit.ini; see cleanly.core.exclusions.
"""

import copy
import json
import logging
import os
import re
import threading

from cleanly.core.stats import default_data_dir

logger = logging.getLogger(__name__)

FREQUENCIES = ('off', 'daily', 'weekly')
WEEKDAYS = ('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')
MB = 1000 * 1000

DEFAULTS = {
    'schedule': {
        'frequency': 'off',
        'time': '10:00',
        'weekday': 'MON',
    },
    # Show a notification when a background scan finds at least this much
    'notify': True,
    'notify_min_bytes': 100 * MB,
    # Clean Basic categories after a background scan, without asking
    'auto_clean': False,
}

_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def validate(data):
    """Return a complete, valid copy of data, filling in defaults

    Raises ValueError for a value that is present but invalid.
    """
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        raise ValueError('Settings must be an object')
    schedule = data.get('schedule', {})
    if not isinstance(schedule, dict):
        raise ValueError('schedule must be an object')
    frequency = schedule.get('frequency', result['schedule']['frequency'])
    if frequency not in FREQUENCIES:
        raise ValueError('Unknown frequency: %s' % frequency)
    time_ = schedule.get('time', result['schedule']['time'])
    if not isinstance(time_, str) or not _TIME_RE.match(time_):
        raise ValueError('Time must look like 09:30')
    weekday = schedule.get('weekday', result['schedule']['weekday'])
    if weekday not in WEEKDAYS:
        raise ValueError('Unknown weekday: %s' % weekday)
    result['schedule'] = {'frequency': frequency, 'time': time_,
                          'weekday': weekday}
    for key in ('notify', 'auto_clean'):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError('%s must be true or false' % key)
            result[key] = data[key]
    if 'notify_min_bytes' in data:
        value = data['notify_min_bytes']
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError('notify_min_bytes must be a positive number')
        result['notify_min_bytes'] = value
    return result


class Settings:
    """Read and write settings.json"""

    def __init__(self, data_dir=None):
        self.path = os.path.join(data_dir or default_data_dir(),
                                 'settings.json')
        self._lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                return validate(json.load(f))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.warning('Could not read %s; using defaults', self.path,
                           exc_info=True)
        return copy.deepcopy(DEFAULTS)

    def save(self, data):
        """Validate and save; return the saved settings"""
        data = validate(data)
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = '%s.%d.tmp' % (self.path, os.getpid())
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, self.path)
        return data
