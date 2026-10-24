# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
The object pywebview exposes to JavaScript as window.pywebview.api

Every public method is callable from the front end and returns a
JSON-serializable value. Long jobs return at once; their progress and
results arrive as events through window.cleanly.emit(name, payload).

Attributes are private (underscore) on purpose: pywebview exposes
public attributes to JavaScript as well.
"""

import json
import logging

from cleanly import APP_NAME, APP_VERSION
from cleanly.core.engine import Busy

logger = logging.getLogger(__name__)


def _ok(**kwargs):
    return dict(ok=True, **kwargs)


def _error(message):
    return {'ok': False, 'error': message}


class Api:
    """Bridge between the web UI and the engine"""

    def __init__(self, engine, stats):
        self._engine = engine
        self._stats = stats
        self._window = None

    def _attach(self, window):
        self._window = window

    def _emit(self, name, payload=None):
        if self._window is None:
            return
        script = 'window.cleanly && window.cleanly.emit(%s, %s)' % (
            json.dumps(name), json.dumps(payload))
        try:
            self._window.evaluate_js(script)
        except Exception:
            logger.debug('could not deliver event %s', name, exc_info=True)

    def get_app_info(self):
        return {'name': APP_NAME, 'version': APP_VERSION}

    def get_overview(self):
        """Stats and whether a scan is cached or running"""
        last = self._engine.last_scan
        return {
            'stats': self._stats.to_dict(),
            'busy': self._engine.is_busy(),
            'has_scan': last is not None,
        }

    def get_scan(self):
        last = self._engine.last_scan
        return last.to_dict() if last else None

    def start_scan(self):
        try:
            self._engine.scan(
                lambda p: self._emit('scan-progress', p),
                lambda r: self._emit('scan-done', r))
        except Busy as e:
            return _error(str(e))
        return _ok()

    def start_clean(self, operations):
        """operations: list of 'cleaner.option' strings"""
        if not isinstance(operations, list) or not operations:
            return _error('Nothing selected')
        try:
            self._engine.clean(
                [str(op) for op in operations],
                lambda p: self._emit('clean-progress', p),
                lambda r: self._emit('clean-done', r))
        except (Busy, ValueError) as e:
            return _error(str(e))
        return _ok()

    def cancel(self):
        self._engine.cancel()
        return _ok()

    def get_items(self, category_id):
        try:
            return _ok(items=self._engine.get_items(str(category_id)))
        except KeyError:
            return _error('Unknown category')
