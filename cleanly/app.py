# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Start the Cleanly window
"""

import logging
import os
import sys

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


def main():
    from bleachbit.Bootstrap import bootstrap
    bootstrap()

    import webview

    from cleanly.bridge.api import Api
    from cleanly.core.engine import Engine
    from cleanly.core.stats import Stats

    stats = Stats()
    engine = Engine(stats)
    engine.load()
    api = Api(engine, stats)

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
