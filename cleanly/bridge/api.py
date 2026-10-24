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
import os

from cleanly import APP_NAME, APP_VERSION
from cleanly.core import exclusions, scheduler
from cleanly.core.engine import Busy
from cleanly.core.settings import validate

logger = logging.getLogger(__name__)


def _ok(**kwargs):
    return dict(ok=True, **kwargs)


def _error(message):
    return {'ok': False, 'error': message}


class Api:
    """Bridge between the web UI and the engine"""

    def __init__(self, engine, stats, settings, scheduler_mod=scheduler):
        self._engine = engine
        self._stats = stats
        self._settings = settings
        self._scheduler = scheduler_mod
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

    # ---------- History ----------

    def get_history(self):
        stats = self._stats.to_dict()
        return {'history': stats['history'],
                'last_background': stats['last_background']}

    # ---------- Settings and scheduled scans ----------

    def get_settings(self):
        return {'settings': self._settings.load(),
                'scheduled': self._scheduler.is_installed()}

    def save_settings(self, data):
        """Validate, update the scheduled task, then save"""
        try:
            data = validate(data)
        except ValueError as e:
            return _error(str(e))
        if data['schedule'] != self._settings.load()['schedule'] or \
                (data['schedule']['frequency'] != 'off') != \
                self._scheduler.is_installed():
            try:
                self._scheduler.apply(data['schedule'])
            except (RuntimeError, OSError) as e:
                logger.warning('could not update the scheduled task',
                               exc_info=True)
                return _error('Could not update the schedule: %s' % e)
        return _ok(settings=self._settings.save(data))

    # ---------- Paths never to clean ----------

    def _choose_path(self, path_type):
        """Ask the user for a file or folder; None if they cancel"""
        import webview  # pylint: disable=import-outside-toplevel
        dialog = (webview.FileDialog.FOLDER if path_type == 'folder'
                  else webview.FileDialog.OPEN)
        chosen = self._window.create_file_dialog(dialog)
        return chosen[0] if chosen else None

    def get_exclusions(self):
        return _ok(paths=exclusions.list_paths())

    def choose_exclusion(self, path_type):
        """Open a file or folder picker and add the choice"""
        if path_type not in exclusions.PATH_TYPES:
            return _error('Unknown path type')
        path = self._choose_path(path_type)
        if not path:
            return _ok(paths=exclusions.list_paths(), cancelled=True)
        return self.add_exclusion(path_type, path)

    def add_exclusion(self, path_type, path):
        try:
            return _ok(paths=exclusions.add_path(path_type, path))
        except ValueError as e:
            return _error(str(e))

    def exclude_found(self, path):
        """Never clean a file or folder listed in the scan results"""
        path = str(path)
        path_type = 'folder' if os.path.isdir(path) else 'file'
        return self.add_exclusion(path_type, path)

    def remove_exclusion(self, path):
        return _ok(paths=exclusions.remove_path(str(path)))

    # ---------- Cookies to keep ----------

    def get_kept_cookies(self):
        return _ok(domains=exclusions.list_kept_cookies())

    def set_kept_cookies(self, domains):
        if not isinstance(domains, list):
            return _error('Expected a list of websites')
        try:
            return _ok(domains=exclusions.save_kept_cookies(domains))
        except ValueError as e:
            return _error(str(e))

    def get_cookie_sites(self):
        """Sites with cookies in the browsers, for picking ones to keep"""
        try:
            return _ok(sites=exclusions.list_cookie_sites())
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning('could not list cookies', exc_info=True)
            return _error(str(e))
