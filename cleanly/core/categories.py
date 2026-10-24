# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Group engine cleaner options into friendly categories

The engine knows about options such as 'vlc.mru' or 'system.tmp'.
Cleanly shows categories such as 'Program temp files' instead, and
browsers as one row each. The mapping lives in categories.json.
"""

import fnmatch
import json
import os

BASIC = 'basic'
FULL = 'full'
CUSTOM = 'custom'
MODES = (BASIC, FULL, CUSTOM)

_MAPPING_PATH = os.path.join(os.path.dirname(__file__), 'categories.json')


def load_mapping(path=_MAPPING_PATH):
    """Load the category mapping from JSON"""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _matches(operation, patterns):
    return any(fnmatch.fnmatchcase(operation, pattern) for pattern in patterns)


class Category:
    """A group of engine options shown as one row"""

    def __init__(self, id_, label, description, kind, mode, default=True):
        self.id = id_
        self.label = label
        self.description = description
        self.kind = kind  # 'disk' or 'browser'
        self.mode = mode  # lowest mode that selects it by default
        self.default = default
        # engine options: list of (cleaner_id, option_id)
        self.options = []
        # browser categories only: option_id -> mode
        self.option_modes = {}
        self.running = False

    def is_selected_in(self, mode):
        """Whether this category is checked by default in the given mode"""
        if not self.default:
            return False
        if mode == FULL:
            return self.mode in (BASIC, FULL)
        return self.mode == BASIC

    def options_for(self, mode):
        """Engine options to run for this category in the given mode"""
        if self.kind != 'browser' or mode == CUSTOM:
            return list(self.options)
        allowed = (BASIC,) if mode == BASIC else (BASIC, FULL)
        return [(cid, oid) for (cid, oid) in self.options
                if self.option_modes.get(oid) in allowed]

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
            'kind': self.kind,
            'mode': self.mode,
            'default': self.default,
            'running': self.running,
            'options': ['%s.%s' % option for option in self.options],
        }


def build_categories(backends, mapping=None):
    """Build the category list from the registered engine backends

    backends: dict of cleaner_id -> Cleaner, as in bleachbit.Cleaner.backends

    Options with a warning are left out: they stay available in the
    expert view rather than in one-click cleaning.

    Returns a list of Category, disk categories first, then browsers.
    """
    if mapping is None:
        mapping = load_mapping()
    excluded = mapping.get('exclude', [])
    browser_cfg = mapping.get('browsers', {})
    browser_ids = browser_cfg.get('ids', [])
    browser_option_modes = browser_cfg.get('options', {})

    disk = [Category(c['id'], c['label'], c.get('description', ''), 'disk',
                     c.get('mode', BASIC), c.get('default', True))
            for c in mapping.get('disk', [])]
    disk_patterns = [c.get('match', []) for c in mapping.get('disk', [])]
    browsers = []

    for cleaner_id in sorted(backends):
        cleaner = backends[cleaner_id]
        if cleaner_id in browser_ids:
            category = Category(cleaner_id, cleaner.get_name(),
                                cleaner.get_description() or '', 'browser',
                                BASIC)
        else:
            category = None
        for option_id, _name in cleaner.get_options():
            operation = '%s.%s' % (cleaner_id, option_id)
            if _matches(operation, excluded) or cleaner.get_warning(option_id):
                continue
            if category is not None:
                if option_id in browser_option_modes:
                    category.options.append((cleaner_id, option_id))
                    category.option_modes[option_id] = \
                        browser_option_modes[option_id]
                continue
            for disk_category, patterns in zip(disk, disk_patterns):
                if _matches(operation, patterns):
                    disk_category.options.append((cleaner_id, option_id))
                    break
        if category is not None and category.options:
            browsers.append(category)

    browsers.sort(key=lambda c: c.label.lower())
    return [c for c in disk if c.options] + browsers


def browser_option_label(option_id, mapping=None):
    """Friendly label for a browser option such as 'cache'"""
    if mapping is None:
        mapping = load_mapping()
    labels = mapping.get('browsers', {}).get('labels', {})
    return labels.get(option_id, option_id.replace('_', ' ').capitalize())
