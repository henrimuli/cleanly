# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Scan and clean through the BleachBit engine, off the UI thread

A scan is the engine's preview (nothing is deleted). Its results are
grouped by category so the UI can show rows such as
'Program temp files: 197 items, 18.1 MB'.
"""

import logging
import threading
import time

from bleachbit import Worker
from bleachbit.Cleaner import backends, register_cleaners

from cleanly.core import categories as cat

logger = logging.getLogger(__name__)

# Paths kept per option for the review drawer. Counts stay exact.
MAX_PATHS_PER_OPTION = 200


class Busy(RuntimeError):
    """Another scan or clean is already running"""


class OptionResult:
    """What one engine option found or removed"""

    def __init__(self):
        self.bytes = 0
        self.items = 0
        self.paths = []

    def add(self, ret):
        if isinstance(ret.get('size'), int):
            self.bytes += ret['size']
        self.items += ret.get('n_deleted', 0) + ret.get('n_special', 0)
        path = ret.get('path')
        if path and len(self.paths) < MAX_PATHS_PER_OPTION:
            self.paths.append({'path': path, 'size': ret.get('size')})

    def to_dict(self, with_paths=False):
        d = {'bytes': self.bytes, 'items': self.items}
        if with_paths:
            d['paths'] = list(self.paths)
        return d


def _to_operations(option_list):
    """[(cleaner_id, option_id)] -> {cleaner_id: [option_id]}"""
    operations = {}
    for cleaner_id, option_id in option_list:
        operations.setdefault(cleaner_id, [])
        if option_id not in operations[cleaner_id]:
            operations[cleaner_id].append(option_id)
    return operations


def _option_label(cleaner_id, option_id):
    """'Google Chrome: Cache' for progress messages"""
    cleaner = backends[cleaner_id]
    cleaner_name = cleaner.get_name() or cleaner_id
    for oid, name in cleaner.get_options():
        if oid == option_id:
            return '%s: %s' % (cleaner_name, name)
    return cleaner_name


class _Collector:
    """Receives the Worker callbacks and records results per option

    Progress counts finished options, so it moves steadily from 0 to 1,
    and reports the running totals so a long option never looks stuck.
    """

    # Seconds between progress events while one option is running
    PROGRESS_INTERVAL = 0.1

    def __init__(self, on_progress, operations):
        self.on_progress = on_progress
        self.results = {}  # 'cleaner.option' -> OptionResult
        self.errors = []
        self.done = threading.Event()
        # The Worker runs the options in this order
        self.order = [(cid, oid) for cid, oids in operations.items()
                      for oid in oids]
        self.finished = 0
        self.items = 0
        self.bytes = 0
        self.timings = {}  # 'cleaner.option' -> seconds
        self._option_started = time.time()
        self._last_emit = 0

    def _emit(self, force=False):
        now = time.time()
        if not force and now - self._last_emit < self.PROGRESS_INTERVAL:
            return
        self._last_emit = now
        total = len(self.order) or 1
        message = ''
        if self.finished < len(self.order):
            message = _option_label(*self.order[self.finished])
        self.on_progress({
            'fraction': min(1.0, self.finished / total),
            'message': message,
            'items': self.items,
            'bytes': self.bytes,
        })

    def start(self):
        self._option_started = time.time()
        self._emit(force=True)

    def on_command_result(self, operation_option, ret):
        result = self.results.setdefault(operation_option, OptionResult())
        before_items, before_bytes = result.items, result.bytes
        result.add(ret)
        self.items += result.items - before_items
        self.bytes += result.bytes - before_bytes
        self._emit()

    def append_text(self, text, tag=None):
        if tag == 'error':
            self.errors.append(text.strip())

    def update_progress_bar(self, _status):
        # Progress comes from finished options instead (see _emit)
        pass

    def update_total_size(self, _size):
        pass

    def update_item_size(self, op, opid, _size):
        if opid == -1:  # the whole cleaner is done
            return
        now = time.time()
        self.timings['%s.%s' % (op, opid)] = now - self._option_started
        self._option_started = now
        self.finished += 1
        self._emit(force=True)

    def worker_done(self, _worker, _really_delete):
        self.done.set()

    def slowest(self, n=25):
        """The n slowest options, for diagnosing slow scans"""
        ranked = sorted(self.timings.items(), key=lambda kv: kv[1],
                        reverse=True)
        return [{'option': op, 'seconds': round(sec, 2)}
                for op, sec in ranked[:n]]


class Engine:
    """Owns the registered cleaners, categories and the running job"""

    def __init__(self, stats=None):
        self.stats = stats
        self.categories = []
        self.last_scan = None
        self._lock = threading.Lock()
        self._worker = None
        self._cancelled = False

    def load(self):
        """Register the cleaners and build categories"""
        for _ in register_cleaners():
            pass
        self.categories = cat.build_categories(backends)
        return self.categories

    def get_category(self, category_id):
        for category in self.categories:
            if category.id == category_id:
                return category
        raise KeyError(category_id)

    def _known_operations(self):
        return {'%s.%s' % option
                for category in self.categories for option in category.options}

    def _run(self, really_delete, option_list, on_progress):
        """Run the Worker to completion; return the collector"""
        operations = _to_operations(option_list)
        collector = _Collector(on_progress, operations)
        if not operations:
            collector.worker_done(None, really_delete)
            return collector
        self._worker = Worker.Worker(collector, really_delete, operations)
        collector.start()
        try:
            for ret in self._worker.run():
                if not ret:
                    break
        finally:
            self._worker = None
        return collector

    def _start_job(self, target, *args):
        if not self._lock.acquire(blocking=False):
            raise Busy('A scan or clean is already running')
        self._cancelled = False

        def job():
            try:
                target(*args)
            finally:
                self._lock.release()
        thread = threading.Thread(target=job, daemon=True)
        thread.start()
        return thread

    def is_busy(self):
        return self._lock.locked()

    def cancel(self):
        self._cancelled = True
        worker = self._worker
        if worker is not None:
            worker.abort()

    @staticmethod
    def _running_cleaners(option_list):
        """Cleaner ids among option_list whose application is open"""
        running = set()
        for cleaner_id in {cid for cid, _oid in option_list}:
            try:
                if backends[cleaner_id].is_process_running():
                    running.add(cleaner_id)
            except Exception:
                logger.debug('running check failed for %s', cleaner_id,
                             exc_info=True)
        return running

    def scan(self, on_progress, on_done):
        """Preview every category option in a background thread

        Every option is scanned whatever the cleaning mode, so switching
        mode in the UI only changes which rows are checked.

        Applications that are open are skipped: they lock their files
        (browsers hold their databases, and each locked database makes
        the preview wait), and they could not be cleaned anyway.
        """
        option_list = [option for category in self.categories
                       for option in category.options]

        def do_scan():
            started = time.time()
            try:
                running = self._running_cleaners(option_list)
                for category in self.categories:
                    category.running = (category.kind == 'browser'
                                        and category.id in running)
                collector = self._run(
                    False, [o for o in option_list if o[0] not in running],
                    on_progress)
                if self._cancelled:
                    on_done({'cancelled': True})
                    return
                self.last_scan = ScanResult(self.categories, collector,
                                            started, time.time(), running)
                if self.stats:
                    self.stats.record_scan(self.last_scan.summary())
                    self.stats.save_report('scan-timings.json', {
                        'seconds': round(time.time() - started, 1),
                        'slowest': collector.slowest(),
                    })
                on_done(self.last_scan.to_dict())
            except Exception as e:
                logger.exception('scan failed')
                on_done({'error': str(e)})
        return self._start_job(do_scan)

    def _category_labels(self, results):
        """Labels of the categories that had results, for the history"""
        found = {op for op, r in results.items() if r.items or r.bytes}
        return [c.label for c in self.categories
                if any('%s.%s' % o in found for o in c.options)]

    def clean(self, operations, on_progress, on_done, source='manual'):
        """Clean the given 'cleaner.option' strings in a background thread

        source: 'manual' or 'scheduled', recorded in the history
        """
        known = self._known_operations()
        unknown = [op for op in operations if op not in known]
        if unknown:
            raise ValueError('Unknown operations: %s' % ', '.join(unknown))
        option_list = [tuple(op.split('.', 1)) for op in operations]
        skipped = sorted({cid for cid, _oid in option_list
                          if backends[cid].is_process_running()})
        option_list = [o for o in option_list if o[0] not in skipped]

        def do_clean():
            started = time.time()
            try:
                collector = self._run(True, option_list, on_progress)
                total_bytes = sum(r.bytes for r in collector.results.values())
                total_items = sum(r.items for r in collector.results.values())
                summary = {
                    'started': started,
                    'finished': time.time(),
                    'bytes': total_bytes,
                    'items': total_items,
                    'skipped_running': [backends[cid].get_name()
                                        for cid in skipped],
                    'errors': collector.errors,
                    'categories': self._category_labels(collector.results),
                    'source': source,
                }
                if self.stats:
                    self.stats.record_clean(summary)
                # The earlier scan is stale now
                self.last_scan = None
                on_done(summary)
            except Exception as e:
                logger.exception('clean failed')
                on_done({'error': str(e)})
        return self._start_job(do_clean)

    def get_items(self, category_id):
        """Files found for one category in the last scan"""
        if self.last_scan is None:
            return []
        return self.last_scan.items_for(self.get_category(category_id))


class ScanResult:
    """Scan results grouped by category"""

    def __init__(self, categories, collector, started, finished,
                 running=()):
        self.categories = categories
        self.running = sorted(running)
        self.results = collector.results
        self.errors = collector.errors
        self.started = started
        self.finished = finished

    def _result(self, cleaner_id, option_id):
        return self.results.get('%s.%s' % (cleaner_id, option_id),
                                OptionResult())

    def category_dict(self, category):
        d = category.to_dict()
        options = []
        total_bytes = total_items = 0
        for cleaner_id, option_id in category.options:
            r = self._result(cleaner_id, option_id)
            total_bytes += r.bytes
            total_items += r.items
            entry = {'id': '%s.%s' % (cleaner_id, option_id),
                     'bytes': r.bytes, 'items': r.items}
            if category.kind == 'browser':
                entry['label'] = cat.browser_option_label(option_id)
                entry['mode'] = category.option_modes.get(option_id)
            options.append(entry)
        d['options'] = options
        d['bytes'] = total_bytes
        d['items'] = total_items
        d['selected'] = {mode: category.is_selected_in(mode)
                         for mode in (cat.BASIC, cat.FULL)}
        return d

    def basic_operations(self):
        """Operations Basic mode selects that found something

        The same choice the UI makes by default, used by auto-clean.
        """
        operations = []
        for category in self.categories:
            if category.running or not category.is_selected_in(cat.BASIC):
                continue
            for cleaner_id, option_id in category.options_for(cat.BASIC):
                if self._result(cleaner_id, option_id).items:
                    operations.append('%s.%s' % (cleaner_id, option_id))
        return operations

    def items_for(self, category):
        items = []
        for cleaner_id, option_id in category.options:
            items.extend(self._result(cleaner_id, option_id).paths)
        return items

    def to_dict(self):
        categories = [self.category_dict(c) for c in self.categories]
        return {
            'started': self.started,
            'finished': self.finished,
            'categories': categories,
            'errors': self.errors,
            'skipped_running': [backends[cid].get_name()
                                for cid in self.running if cid in backends],
        }

    def summary(self):
        """Totals of what Basic mode would clean"""
        total_bytes = total_items = 0
        for category in self.categories:
            if not category.is_selected_in(cat.BASIC):
                continue
            for cleaner_id, option_id in category.options_for(cat.BASIC):
                r = self._result(cleaner_id, option_id)
                total_bytes += r.bytes
                total_items += r.items
        return {'time': self.finished, 'bytes': total_bytes,
                'items': total_items}
