# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.


"""
Test cases for the Cleanly core: categories, engine, stats and bridge
"""

import os
import tempfile
import threading
from unittest import mock

from tests import common
from tests.TestCleaner import actions_to_cleaner
from bleachbit.Cleaner import Cleaner, backends

from cleanly.bridge.api import Api
from cleanly.core import categories as cat
from cleanly.core.engine import Busy, Engine
from cleanly.core.stats import Stats

MAPPING = {
    'exclude': ['*.passwords'],
    'disk': [
        {'id': 'temp', 'label': 'Temp', 'mode': 'basic',
         'match': ['system.tmp', '*.tmp']},
        {'id': 'bin', 'label': 'Bin', 'mode': 'basic', 'default': False,
         'match': ['system.recycle_bin']},
        {'id': 'recent', 'label': 'Recent', 'mode': 'full',
         'match': ['*.mru']},
    ],
    'browsers': {
        'ids': ['browser'],
        'options': {'cache': 'basic', 'cookies': 'full'},
        'labels': {'cache': 'Cache'},
    },
}


def _fake_cleaner(cleaner_id, name, option_ids, warnings=()):
    cleaner = Cleaner(cleaner_id, name, 'description')
    for option_id in option_ids:
        cleaner.add_option(option_id, option_id, '')
        if option_id in warnings:
            cleaner.set_warning(option_id, 'careful')
    return cleaner


class CategoriesTestCase(common.BleachbitTestCase):
    """Test grouping engine options into categories"""

    def _build(self):
        fake = {
            'system': _fake_cleaner('system', 'System', ['tmp', 'recycle_bin']),
            'app': _fake_cleaner('app', 'App', ['tmp', 'mru', 'unmapped']),
            'risky': _fake_cleaner('risky', 'Risky', ['tmp'], warnings=['tmp']),
            'browser': _fake_cleaner('browser', 'Browser',
                                     ['cache', 'cookies', 'passwords', 'other']),
            'empty': _fake_cleaner('empty', 'Empty', ['unmapped']),
        }
        return {c.id: c for c in cat.build_categories(fake, MAPPING)}

    def test_grouping(self):
        cats = self._build()
        self.assertEqual(cats['temp'].options, [
                         ('app', 'tmp'), ('system', 'tmp')])
        self.assertEqual(cats['recent'].options, [('app', 'mru')])
        # browsers get one row each, with only mapped options
        self.assertEqual(cats['browser'].kind, 'browser')
        self.assertEqual(cats['browser'].options,
                         [('browser', 'cache'), ('browser', 'cookies')])
        self.assertNotIn('empty', cats)

    def test_warnings_and_excludes_left_out(self):
        options = {o for c in self._build().values() for o in c.options}
        self.assertNotIn(('risky', 'tmp'), options)
        self.assertNotIn(('browser', 'passwords'), options)
        self.assertNotIn(('app', 'unmapped'), options)

    def test_modes(self):
        cats = self._build()
        self.assertTrue(cats['temp'].is_selected_in(cat.BASIC))
        self.assertFalse(cats['recent'].is_selected_in(cat.BASIC))
        self.assertTrue(cats['recent'].is_selected_in(cat.FULL))
        # off by default in every mode
        self.assertFalse(cats['bin'].is_selected_in(cat.FULL))
        browser = cats['browser']
        self.assertEqual(browser.options_for(
            cat.BASIC), [('browser', 'cache')])
        self.assertEqual(len(browser.options_for(cat.FULL)), 2)

    def test_browser_label(self):
        self.assertEqual(cat.browser_option_label('cache', MAPPING), 'Cache')
        self.assertEqual(cat.browser_option_label('site_data', MAPPING),
                         'Site data')

    def test_shipped_mapping_loads(self):
        mapping = cat.load_mapping()
        ids = [c['id'] for c in mapping['disk']]
        self.assertEqual(len(ids), len(set(ids)))
        for category in mapping['disk']:
            self.assertIn(category.get('mode', cat.BASIC), cat.MODES)
        for mode in mapping['browsers']['options'].values():
            self.assertIn(mode, cat.MODES)


class EngineTestCase(common.BleachbitTestCase):
    """Test scanning and cleaning through the engine"""

    def setUp(self):
        super().setUp()
        self.saved_backends = dict(backends)
        self.files = [self.write_file(os.path.join(self.tempdir, name), b'x' * 10)
                      for name in ('a.tmp', 'b.tmp')]
        cleaner = actions_to_cleaner(
            ['<action command="delete" search="file" path="%s"/>' % path
             for path in self.files])
        cleaner.id = 'app'
        backends.clear()
        backends['app'] = cleaner
        mapping = {'disk': [{'id': 'temp', 'label': 'Temp',
                             'match': ['app.option1', 'app.option2']}]}
        self.stats = Stats(tempfile.mkdtemp(dir=self.tempdir))
        self.engine = Engine(self.stats)
        self.engine.categories = cat.build_categories(backends, mapping)

    def tearDown(self):
        backends.clear()
        backends.update(self.saved_backends)
        super().tearDown()

    def _wait(self, start):
        done = threading.Event()
        result = {}

        def on_done(r):
            result.update(r)
            done.set()
        start(lambda _p: None, on_done)
        self.assertTrue(done.wait(30))
        return result

    def test_scan_then_clean(self):
        result = self._wait(self.engine.scan)
        temp = result['categories'][0]
        self.assertEqual(temp['items'], 2)
        # sizes are disk usage, so at least the file contents
        self.assertGreaterEqual(temp['bytes'], 20)
        self.assertEqual(temp['selected'], {'basic': True, 'full': True})
        # preview deletes nothing
        for path in self.files:
            self.assertExists(path)
        items = self.engine.get_items('temp')
        self.assertEqual(sorted(i['path'] for i in items), sorted(self.files))
        self.assertEqual(self.stats.to_dict()['last_scan']['items'], 2)

        summary = self._wait(lambda p, d: self.engine.clean(
            ['app.option1', 'app.option2'], p, d))
        self.assertEqual(summary['items'], 2)
        self.assertEqual(summary['skipped_running'], [])
        for path in self.files:
            self.assertNotExists(path)
        stats = self.stats.to_dict()
        self.assertEqual(stats['cleanings'], 1)
        self.assertEqual(stats['bytes_freed'], temp['bytes'])
        self.assertIsNone(self.engine.last_scan)

    def test_clean_rejects_unknown_operation(self):
        with self.assertRaises(ValueError):
            self.engine.clean(['system.memory'], None, None)

    def test_clean_skips_running_app(self):
        with mock.patch.object(backends['app'], 'is_process_running',
                               return_value=True):
            summary = self._wait(lambda p, d: self.engine.clean(
                ['app.option1'], p, d))
        self.assertEqual(summary['skipped_running'],
                         [backends['app'].get_name()])
        self.assertEqual(summary['items'], 0)
        self.assertExists(self.files[0])

    def test_one_job_at_a_time(self):
        gate = threading.Event()
        self.engine._start_job(gate.wait)  # pylint: disable=protected-access
        try:
            with self.assertRaises(Busy):
                self.engine.scan(None, None)
            api = Api(self.engine, self.stats)
            self.assertFalse(api.start_scan()['ok'])
        finally:
            gate.set()


class StatsTestCase(common.BleachbitTestCase):
    """Test the stats file"""

    def test_persist(self):
        data_dir = os.path.join(self.tempdir, 'stats_persist')
        stats = Stats(data_dir)
        stats.record_clean({'finished': 1, 'bytes': 5, 'items': 2})
        stats.record_clean({'finished': 2, 'bytes': 7, 'items': 1})
        again = Stats(data_dir).to_dict()
        self.assertEqual(again['bytes_freed'], 12)
        self.assertEqual(again['items_removed'], 3)
        self.assertEqual(again['cleanings'], 2)
        self.assertEqual(again['history'][0]['time'], 2)

    def test_corrupt_file(self):
        data_dir = os.path.join(self.tempdir, 'stats_corrupt')
        os.makedirs(data_dir, exist_ok=True)
        self.write_file(os.path.join(data_dir, 'stats.json'), b'{not json')
        self.assertEqual(Stats(data_dir).to_dict()['cleanings'], 0)


class ApiTestCase(common.BleachbitTestCase):
    """Test the pywebview bridge without a window"""

    def test_events_and_validation(self):
        engine = mock.Mock()
        engine.last_scan = None
        engine.is_busy.return_value = False
        api = Api(engine, Stats(os.path.join(self.tempdir, 'stats_api')))
        self.assertFalse(api.start_clean([])['ok'])
        self.assertIsNone(api.get_scan())
        self.assertFalse(api.get_overview()['has_scan'])

        window = mock.Mock()
        api._attach(window)  # pylint: disable=protected-access
        api._emit('scan-done', {'a': 1})  # pylint: disable=protected-access
        window.evaluate_js.assert_called_once_with(
            'window.cleanly && window.cleanly.emit("scan-done", {"a": 1})')
