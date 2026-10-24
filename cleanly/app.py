# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Start the Cleanly window
"""

import importlib
import logging
import os
import sys
import traceback

from cleanly import APP_NAME

logger = logging.getLogger(__name__)

# Colors that match the front end, so the window does not flash white
WINDOW_BACKGROUND = '#0D1714'


def frontend_dir():
    """Front-end files, from source or from a PyInstaller bundle"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(base, 'cleanly', 'frontend')
    return os.path.join(base, 'frontend')


def unblock_bundle(root):
    """Remove the 'downloaded from the internet' mark from bundled DLLs

    Explorer copies that mark (the Zone.Identifier stream) onto every
    file it extracts from a downloaded zip. The .NET Framework refuses
    to load marked assemblies, which stops pywebview (via pythonnet)
    from starting. Best effort: a read-only install is left alone.
    """
    unblocked = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not filename.lower().endswith(('.dll', '.exe', '.pyd')):
                continue
            stream = os.path.join(dirpath, filename) + ':Zone.Identifier'
            try:
                if os.path.exists(stream):
                    os.remove(stream)
                    unblocked += 1
            except OSError:
                logger.debug('could not unblock %s', filename, exc_info=True)
    return unblocked


def self_check():
    """Load the engine and the WebView2 backend without opening a window

    Used by CI to catch packaging problems. Exit code 0 means OK.
    """
    from cleanly.core.engine import Engine
    categories = Engine().load()
    importlib.import_module('webview')
    if os.name == 'nt':
        # Loads pythonnet and the WebView2 assemblies
        importlib.import_module('webview.platforms.winforms')
        # Notifications for scheduled scans
        importlib.import_module('plyer.platforms.win.notification')
    if not categories:
        raise RuntimeError('No cleaning categories found')
    return 0


def use_own_engine_settings():
    """Keep the engine's settings in %APPDATA%\\Cleanly\\engine

    Otherwise Cleanly would share bleachbit.ini (and its keep list) with
    a BleachBit installation. Must run before bleachbit is imported.
    """
    from cleanly.core.stats import default_data_dir
    os.environ.setdefault('BLEACHBIT_TEST_OPTIONS_DIR',
                          os.path.join(default_data_dir(), 'engine'))


def background_scan():
    """Scheduled scan without a window; see cleanly.core.background"""
    from cleanly.core import background
    from cleanly.core.engine import Engine
    from cleanly.core.settings import Settings
    from cleanly.core.stats import Stats

    stats = Stats()
    try:
        background.run(Engine(stats), stats, Settings().load())
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception('background scan failed')
        return 1
    return 0


def main():
    if os.name == 'nt' and hasattr(sys, '_MEIPASS'):
        unblock_bundle(sys._MEIPASS)  # pylint: disable=protected-access

    use_own_engine_settings()
    from bleachbit.Bootstrap import bootstrap
    bootstrap()

    from cleanly.core.scheduler import BACKGROUND_ARG
    if BACKGROUND_ARG in sys.argv:
        sys.exit(background_scan())

    if '--self-check' in sys.argv:
        # A windowed build has no console, and an unhandled exception
        # would open a dialog box and hang CI, so report through a file.
        try:
            sys.exit(self_check())
        except Exception:  # pylint: disable=broad-exception-caught
            with open('cleanly-self-check.log', 'w', encoding='utf-8') as f:
                traceback.print_exc(file=f)
            sys.exit(1)

    import webview

    from cleanly.bridge.api import Api
    from cleanly.core.engine import Engine
    from cleanly.core.settings import Settings
    from cleanly.core.stats import Stats

    stats = Stats()
    engine = Engine(stats)
    engine.load()
    api = Api(engine, stats, Settings())

    window = webview.create_window(
        APP_NAME,
        url=os.path.join(frontend_dir(), 'index.html'),
        js_api=api,
        width=1120,
        height=740,
        min_size=(960, 640),
        background_color=WINDOW_BACKGROUND,
    )
    api._attach(window)  # pylint: disable=protected-access
    # Serve the front end over pywebview's local HTTP server: browsers do
    # not load ES modules from file:// URLs.
    webview.start(http_server=True, debug='--debug' in sys.argv)


if __name__ == '__main__':
    main()
