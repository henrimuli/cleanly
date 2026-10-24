# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
#
# PyInstaller build for Cleanly (Windows). Run from the repository root:
#   pyinstaller --noconfirm cleanly.spec
# Output: dist/Cleanly/Cleanly.exe

from PyInstaller.utils.hooks import collect_submodules


def _engine_module(name):
    """Engine modules only: the GTK user interface is not shipped"""
    leaf = name.rsplit('.', 1)[-1]
    return not (leaf.startswith('Gui') or leaf in ('GUI', 'FontCheckDialog'))


datas = [
    ('cleanly/frontend', 'cleanly/frontend'),
    ('cleanly/core/categories.json', 'cleanly/core'),
    # bleachbit/__init__.py looks for these next to the executable
    ('cleaners/*.xml', 'cleaners'),
    ('share/protected_path.xml', 'share'),
    ('COPYING', '.'),
    # .NET settings read by the WebView2 backend
    ('cleanly/Cleanly.exe.config', '.'),
]

a = Analysis(
    ['cleanly/__main__.py'],
    pathex=['.'],
    datas=datas,
    hiddenimports=collect_submodules('bleachbit', filter=_engine_module),
    excludes=['gi', 'gtk', 'cairo', 'tkinter'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Cleanly',
    icon='cleanly/frontend/assets/cleanly.ico',
    console=False,
    # Keep files beside Cleanly.exe, where the engine expects cleaners/
    contents_directory='.',
)
coll = COLLECT(exe, a.binaries, a.datas, name='Cleanly')
