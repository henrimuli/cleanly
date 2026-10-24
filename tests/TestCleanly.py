# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.


"""
Test cases for the Cleanly core: categories, engine, stats, settings,
scheduled scans, exclusions and the bridge
"""

import datetime
import json
import os
import tempfile
import threading
from unittest import mock
from xml.dom.minidom import parseString

from tests import common
from tests.TestCleaner import actions_to_cleaner
from bleachbit.Cleaner import Cleaner, backends

from cleanly.bridge.api import Api
from cleanly.core import background, exclusions, scheduler
from cleanly.core import categories as cat
from cleanly.core.engine import Busy, Engine
from cleanly.core.settings import DEFAULTS, Settings, validate
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


class _EngineFixture(common.BleachbitTestCase):
    """An engine with one fake cleaner that finds two files"""

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

    def _wait(self, start, on_progress=lambda _p: None):
        done = threading.Event()
        result = {}

        def on_done(r):
            result.update(r)
            done.set()
        start(on_progress, on_done)
        self.assertTrue(done.wait(30))
        return result


class EngineTestCase(_EngineFixture):
    """Test scanning and cleaning through the engine"""

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

    def test_scan_progress(self):
        events = []
        self._wait(self.engine.scan, events.append)
        fractions = [e['fraction'] for e in events]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[0], 0)
        self.assertEqual(fractions[-1], 1)
        self.assertEqual(events[-1]['items'], 2)
        self.assertEqual(events[0]['message'], 'app: name1')
        report = os.path.join(os.path.dirname(self.stats.path),
                              'scan-timings.json')
        self.assertExists(report)

    def test_scan_skips_running_app(self):
        with mock.patch.object(backends['app'], 'is_process_running',
                               return_value=True):
            result = self._wait(self.engine.scan)
        self.assertEqual(result['skipped_running'],
                         [backends['app'].get_name()])
        self.assertEqual(result['categories'][0]['items'], 0)

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
            api = Api(self.engine, self.stats,
                      Settings(tempfile.mkdtemp(dir=self.tempdir)))
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
        api = Api(engine, Stats(os.path.join(self.tempdir, 'stats_api')),
                  Settings(os.path.join(self.tempdir, 'stats_api')))
        self.assertFalse(api.start_clean([])['ok'])
        self.assertIsNone(api.get_scan())
        self.assertFalse(api.get_overview()['has_scan'])

        window = mock.Mock()
        api._attach(window)  # pylint: disable=protected-access
        api._emit('scan-done', {'a': 1})  # pylint: disable=protected-access
        window.evaluate_js.assert_called_once_with(
            'window.cleanly && window.cleanly.emit("scan-done", {"a": 1})')

    def test_save_settings_applies_schedule(self):
        data_dir = tempfile.mkdtemp(dir=self.tempdir)
        fake_scheduler = mock.Mock()
        fake_scheduler.is_installed.return_value = False
        api = Api(mock.Mock(), Stats(data_dir), Settings(data_dir),
                  fake_scheduler)
        weekly = {'schedule': {'frequency': 'weekly', 'time': '08:15',
                               'weekday': 'FRI'}}
        res = api.save_settings(weekly)
        self.assertTrue(res['ok'])
        fake_scheduler.apply.assert_called_once_with(weekly['schedule'])
        self.assertEqual(Settings(data_dir).load()['schedule'],
                         weekly['schedule'])

        # a failed schedule change is reported and not saved
        fake_scheduler.is_installed.return_value = True
        fake_scheduler.apply.side_effect = RuntimeError('Access is denied.')
        res = api.save_settings({'schedule': {'frequency': 'daily'}})
        self.assertFalse(res['ok'])
        self.assertIn('Access is denied.', res['error'])
        self.assertEqual(Settings(data_dir).load()['schedule']['frequency'],
                         'weekly')

        self.assertFalse(api.save_settings({'notify': 'yes'})['ok'])

    def test_choose_exclusion_cancelled(self):
        data_dir = tempfile.mkdtemp(dir=self.tempdir)
        api = Api(mock.Mock(), Stats(data_dir), Settings(data_dir))
        with mock.patch.object(api, '_choose_path', return_value=None):
            res = api.choose_exclusion('folder')
        self.assertTrue(res['cancelled'])
        self.assertFalse(api.choose_exclusion('drive')['ok'])


class SettingsTestCase(common.BleachbitTestCase):
    """Test settings validation and storage"""

    def test_defaults_and_roundtrip(self):
        settings = Settings(tempfile.mkdtemp(dir=self.tempdir))
        self.assertEqual(settings.load(), DEFAULTS)
        saved = settings.save({'auto_clean': True,
                               'schedule': {'frequency': 'daily'}})
        self.assertTrue(saved['auto_clean'])
        self.assertEqual(saved['schedule']['time'], '10:00')
        self.assertEqual(settings.load(), saved)

    def test_invalid(self):
        for bad in ({'schedule': {'frequency': 'hourly'}},
                    {'schedule': {'time': '25:00'}},
                    {'schedule': {'time': '9:00'}},
                    {'schedule': {'weekday': 'MONDAY'}},
                    {'auto_clean': 1},
                    {'notify_min_bytes': -5},
                    []):
            with self.assertRaises(ValueError, msg=bad):
                validate(bad)

    def test_corrupt_file(self):
        data_dir = tempfile.mkdtemp(dir=self.tempdir)
        self.write_file(os.path.join(data_dir, 'settings.json'), b'[1, 2]')
        self.assertEqual(Settings(data_dir).load(), DEFAULTS)


class SchedulerTestCase(common.BleachbitTestCase):
    """Test the Task Scheduler definition"""

    COMMAND = (r'C:\Program Files\Cleanly\Cleanly.exe', '--background-scan',
               r'C:\Program Files\Cleanly')

    def _parse(self, schedule):
        xml = scheduler.build_task_xml(schedule, self.COMMAND,
                                       today=datetime.date(2026, 10, 24))
        # minidom rejects the UTF-16 declaration on a str
        return parseString(xml.split('\n', 1)[1])

    def _text(self, dom, tag):
        return dom.getElementsByTagName(tag)[0].firstChild.data

    def test_daily(self):
        dom = self._parse({'frequency': 'daily', 'time': '09:30',
                           'weekday': 'MON'})
        self.assertEqual(self._text(dom, 'StartBoundary'),
                         '2026-10-24T09:30:00')
        self.assertEqual(self._text(dom, 'DaysInterval'), '1')
        self.assertEqual(self._text(dom, 'Command'), self.COMMAND[0])
        self.assertEqual(self._text(dom, 'Arguments'), '--background-scan')
        self.assertEqual(self._text(dom, 'StartWhenAvailable'), 'true')
        self.assertEqual(self._text(dom, 'RunLevel'), 'LeastPrivilege')

    def test_weekly(self):
        dom = self._parse({'frequency': 'weekly', 'time': '18:00',
                           'weekday': 'SAT'})
        self.assertEqual(len(dom.getElementsByTagName('Saturday')), 1)
        self.assertEqual(self._text(dom, 'WeeksInterval'), '1')

    def test_escapes_paths(self):
        xml = scheduler.build_task_xml(
            {'frequency': 'daily', 'time': '09:30', 'weekday': 'MON'},
            (r'C:\A&B\Cleanly.exe', '--background-scan', r'C:\A&B'))
        self.assertIn(r'C:\A&amp;B\Cleanly.exe', xml)

    def test_off_has_no_task(self):
        with self.assertRaises(ValueError):
            scheduler.build_task_xml({'frequency': 'off', 'time': '09:30',
                                      'weekday': 'MON'}, self.COMMAND)

    def test_command_from_source(self):
        exe, args, workdir = scheduler.task_command()
        self.assertTrue(args.endswith('--background-scan'))
        self.assertIn('-m cleanly', args)
        self.assertTrue(os.path.isfile(
            os.path.join(workdir, 'cleanly', '__init__.py')))
        self.assertTrue(exe)


class BackgroundTestCase(_EngineFixture):
    """Test the scheduled background scan"""

    def _settings(self, **changes):
        data = json.loads(json.dumps(DEFAULTS))
        data.update(changes)
        return data

    def test_notifies_when_junk_found(self):
        notify = mock.Mock(return_value=True)
        summary = background.run(self.engine, self.stats,
                                 self._settings(notify_min_bytes=1), notify)
        self.assertEqual(summary['found_items'], 2)
        self.assertTrue(summary['notified'])
        self.assertIn('junk found', notify.call_args[0][0])
        # nothing deleted without auto-clean
        for path in self.files:
            self.assertExists(path)
        self.assertEqual(self.stats.to_dict()['last_background'], summary)

    def test_quiet_below_threshold(self):
        notify = mock.Mock()
        summary = background.run(self.engine, self.stats, self._settings(),
                                 notify)
        notify.assert_not_called()
        self.assertFalse(summary['notified'])

    def test_auto_clean(self):
        notify = mock.Mock(return_value=True)
        summary = background.run(self.engine, self.stats,
                                 self._settings(auto_clean=True), notify)
        self.assertEqual(summary['cleaned_items'], 2)
        for path in self.files:
            self.assertNotExists(path)
        self.assertIn('Freed', notify.call_args[0][0])
        entry = self.stats.to_dict()['history'][0]
        self.assertEqual(entry['source'], 'scheduled')
        self.assertEqual(entry['categories'], ['Temp'])


class ExclusionsTestCase(common.BleachbitTestCase):
    """Test paths never to clean and cookies to keep"""

    def test_paths(self):
        folder = os.path.join(self.tempdir, 'keep')
        before = exclusions.list_paths()
        exclusions.add_path('folder', folder)
        exclusions.add_path('folder', folder + os.sep)  # no duplicate
        paths = exclusions.list_paths()
        self.assertEqual(len(paths), len(before) + 1)
        self.assertIn({'type': 'folder', 'path': folder}, paths)
        self.assertEqual(exclusions.remove_path(folder), before)
        with self.assertRaises(ValueError):
            exclusions.add_path('folder', 'relative/path')
        with self.assertRaises(ValueError):
            exclusions.add_path('drive', folder)

    def test_cookies(self):
        saved = exclusions.save_kept_cookies(
            ['.Example.com', 'https://mail.example.org/inbox', 'example.com'])
        self.assertEqual(saved, ['example.com', 'mail.example.org'])
        self.assertEqual(exclusions.list_kept_cookies(), saved)
        for bad in ('localhost', 'not a site', '127.0.0.1', ''):
            with self.assertRaises(ValueError, msg=bad):
                exclusions.normalize_domain(bad)
        exclusions.save_kept_cookies([])
        self.assertEqual(exclusions.list_kept_cookies(), [])
