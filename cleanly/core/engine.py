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


class _Collector:
    """Receives the Worker callbacks and records results per option"""

    def __init__(self, on_progress):
        self.on_progress = on_progress
        self.results = {}  # 'cleaner.option' -> OptionResult
        self.errors = []
        self.done = threading.Event()

    def on_command_result(self, operation_option, ret):
        self.results.setdefault(operation_option, OptionResult()).add(ret)

    def append_text(self, text, tag=None):
        if tag == 'error':
            self.errors.append(text.strip())

    def update_progress_bar(self, status):
        if isinstance(status, (int, float)):
            self.on_progress({'fraction': float(status)})
        elif isinstance(status, str):
            self.on_progress({'message': status})

    def update_total_size(self, _size):
        pass

    def update_item_size(self, _op, _opid, _size):
        pass

    def worker_done(self, _worker, _really_delete):
        self.done.set()


def _to_operations(option_list):
    """[(cleaner_id, option_id)] -> {cleaner_id: [option_id]}"""
    operations = {}
    for cleaner_id, option_id in option_list:
        operations.setdefault(cleaner_id, [])
        if option_id not in operations[cleaner_id]:
            operations[cleaner_id].append(option_id)
    return operations


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
        collector = _Collector(on_progress)
        operations = _to_operations(option_list)
        if not operations:
            collector.worker_done(None, really_delete)
            return collector
        self._worker = Worker.Worker(collector, really_delete, operations)
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

    def _refresh_running(self):
        for category in self.categories:
            if category.kind == 'browser':
                try:
                    category.running = backends[category.id].is_process_running(
                    )
                except Exception:
                    logger.debug('running check failed for %s', category.id,
                                 exc_info=True)
                    category.running = False

    def scan(self, on_progress, on_done):
        """Preview every category option in a background thread

        Every option is scanned whatever the cleaning mode, so switching
        mode in the UI only changes which rows are checked.
        """
        option_list = [option for category in self.categories
                       for option in category.options]

        def do_scan():
            started = time.time()
            try:
                collector = self._run(False, option_list, on_progress)
                if self._cancelled:
                    on_done({'cancelled': True})
                    return
                self._refresh_running()
                self.last_scan = ScanResult(self.categories, collector,
                                            started, time.time())
                if self.stats:
                    self.stats.record_scan(self.last_scan.summary())
                on_done(self.last_scan.to_dict())
            except Exception as e:
                logger.exception('scan failed')
                on_done({'error': str(e)})
        return self._start_job(do_scan)

    def clean(self, operations, on_progress, on_done):
        """Clean the given 'cleaner.option' strings in a background thread"""
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

    def __init__(self, categories, collector, started, finished):
        self.categories = categories
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
