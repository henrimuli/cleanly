# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Paths never to clean, and cookies to keep

Both live in the engine's own storage, so every cleaner obeys them: the
keep list of paths in bleachbit.ini, and cookie_keep_list.json.
"""

import json
import os
import re

import bleachbit
from bleachbit.Cookie import (COOKIE_KEEP_LIST_FILENAME, list_unique_cookies,
                              load_keep_list)
from bleachbit.Options import options

PATH_TYPES = ('file', 'folder')

# A host name such as example.com or sub.example.co.uk
_DOMAIN_RE = re.compile(
    r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))


def list_paths():
    """[{'type': 'file'|'folder', 'path': ...}]"""
    return [{'type': t, 'path': p} for t, p in options.get_whitelist_paths()]


def add_path(path_type, path):
    """Never clean path; return the updated list"""
    if path_type not in PATH_TYPES:
        raise ValueError('Unknown path type: %s' % path_type)
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError('Choose a full path')
    path = os.path.normpath(path)
    current = options.get_whitelist_paths()
    if not any(_same_path(p, path) for _t, p in current):
        options.set_whitelist_paths(current + [(path_type, path)])
    return list_paths()


def remove_path(path):
    """Allow path to be cleaned again; return the updated list"""
    current = options.get_whitelist_paths()
    options.set_whitelist_paths(
        [(t, p) for t, p in current if not _same_path(p, path)])
    return list_paths()


def normalize_domain(domain):
    """'.Example.com ' -> 'example.com'; ValueError if it is not a domain"""
    if not isinstance(domain, str):
        raise ValueError('Not a domain')
    domain = domain.strip().lstrip('.').lower()
    if domain.startswith(('http://', 'https://')):
        domain = domain.split('://', 1)[1]
    domain = domain.split('/', 1)[0]
    if not _DOMAIN_RE.match(domain):
        raise ValueError('"%s" is not a website address' % domain)
    return domain


def list_kept_cookies():
    return sorted(load_keep_list())


def save_kept_cookies(domains):
    """Replace the cookie keep list; return it sorted"""
    clean = sorted({normalize_domain(d) for d in domains})
    os.makedirs(bleachbit.options_dir, exist_ok=True)
    path = os.path.join(bleachbit.options_dir, COOKIE_KEEP_LIST_FILENAME)
    tmp = '%s.%d.tmp' % (path, os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, path)
    return clean


def list_cookie_sites():
    """Sites that have cookies in the browsers, without the leading dot"""
    sites = set()
    for host in list_unique_cookies():
        try:
            sites.add(normalize_domain(host))
        except ValueError:
            continue  # e.g. localhost or an IP address
    return sorted(sites)
