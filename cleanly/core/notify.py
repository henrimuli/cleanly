# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Windows notifications for background scans
"""

import logging
import os
import sys

from cleanly import APP_NAME

logger = logging.getLogger(__name__)


def icon_path():
    """cleanly.ico, from source or from a PyInstaller bundle"""
    if hasattr(sys, '_MEIPASS'):
        base = os.path.join(
            sys._MEIPASS, 'cleanly')  # pylint: disable=protected-access
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, 'frontend', 'assets', 'cleanly.ico')
    return path if os.path.exists(path) else None


def notify(message, title=APP_NAME):
    """Show a notification; return whether it was shown"""
    try:
        # pylint: disable-next=import-outside-toplevel
        from plyer import notification
        notification.notify(title=title, message=message, app_name=APP_NAME,
                            app_icon=icon_path(), timeout=10)
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning('Could not show a notification', exc_info=True)
        return False
