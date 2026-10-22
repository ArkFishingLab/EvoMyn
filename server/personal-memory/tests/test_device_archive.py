import concurrent.futures
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from filelock import FileLock

VENDOR = Path(__file__).resolve().parents[1] / 'vendor'
sys.path.insert(0, str(VENDOR))
from device_archive import DeviceArchive, EventConflict, validate_event

EVENT = dict(event_id='dev1:task1:done:1', device_id='dev1', task_id='task1',
             title='喝水', body='喝水提醒', scheduled_at=1792166400,
             completed_at=1792166450, note='已喝完一杯')


def isolated_store(root):
    # Exercise the real ArchiveStore persistence/history without loading a model.
    runtime = types.ModuleType('runtime')
    runtime.ROOT = Path(root); runtime.DATA_DIR = Path(root) / 'data'; runtime.MODEL = 'isolated-test'
    mnemosyne = types.ModuleType('mnemosyne')
    class OfflineMemory:
        def __init__(self, **kwargs): pass
        def remember(self, *args, **kwargs): raise RuntimeError('model offline')
    mnemosyne.Mnemosyne = OfflineMemory
    spec = importlib.util.spec_from_file_location('isolated_archive_store', VENDOR / 'archive_store.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'runtime': runtime, 'mnemosyne': mnemosyne}):
        spec.loader.exec_module(module)
    return module.ArchiveStore(root)


class DeviceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = isolated_store(self.tmp.name)
        self.archive = DeviceArchive(store=self.store)
    def tearDown(self): self.tmp.cleanup()

    def test_persists_exact_completion_as_journal_with_pending_index(self):
        result = self.archive.receive(EVENT, 'dev1')
        self.assertTrue(result['ok']); self.assertEqual(result['event_id'], EVENT['event_id'])
        self.assertEqual(result['index_status'], 'pending')
        record = self.store.get(result['record_id'])
        self.assertEqual(record['category'], 'journal')
        self.assertEqual(record['title'], EVENT['title'])
        self.assertEqual(record['body'], EVENT['body'])
        self.assertEqual(record['fields']['note'], EVENT['note'])
        self.assertEqual(record['fields']['completed_at'], EVENT['completed_at'])
        self.assertEqual(record['date'], '2026-10-17')
        self.assertEqual(len(self.store.history(record['id'])), 1)

    def test_retry_after_new_receiver_returns_durable_original_without_revision(self):
        first = self.archive.receive(EVENT, 'dev1')
        again = DeviceArchive(store=isolated_store(self.tmp.name)).receive(dict(reversed(list(EVENT.items()))), 'dev1')
        self.assertEqual(first, again)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(len(self.store.history(first['record_id'])), 1)

    def test_same_event_different_content_conflicts(self):
        first = self.archive.receive(EVENT, 'dev1')
        with self.assertRaises(EventConflict): self.archive.receive({**EVENT, 'note': 'different'}, 'dev1')
        self.assertEqual(len(self.store.history(first['record_id'])), 1)

    def test_exact_replay_uses_immutable_first_history_after_user_edits_fields(self):
        first = self.archive.receive(EVENT, 'dev1')
        self.store.update(first['record_id'], {'fields': {'note': 'corrected'}, 'body': 'user edited body'})
        result = DeviceArchive(store=isolated_store(self.tmp.name)).receive(EVENT, 'dev1')
        self.assertEqual(result['record_id'], first['record_id'])
        self.assertEqual(result['index_status'], self.store.get(first['record_id'])['index_status'])
        self.assertEqual(self.store.get(first['record_id'])['fields'], {'note': 'corrected'})
        self.assertEqual(self.store.get(first['record_id'])['body'], 'user edited body')
        self.assertEqual(len(self.store.history(first['record_id'])), 2)
        with self.assertRaises(EventConflict):
            self.archive.receive({**EVENT, 'note': 'corrected'}, 'dev1')
        self.assertEqual(len(self.store.history(first['record_id'])), 2)

    def test_committed_save_exception_recovers_without_duplicate(self):
        original = self.store.save
        def committed_then_failed(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('response lost after save')
        with patch.object(self.store, 'save', committed_then_failed):
            result = self.archive.receive(EVENT, 'dev1')
        self.assertEqual(result, self.archive.receive(EVENT, 'dev1'))
        self.assertEqual(len(self.store.history(result['record_id'])), 1)

    def test_failed_save_never_acknowledges(self):
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.archive.receive(EVENT, 'dev1')
        self.assertEqual(self.store.list(), [])

    def test_concurrent_receivers_use_store_lock(self):
        receivers = [DeviceArchive(store=isolated_store(self.tmp.name)) for _ in range(4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda receiver: receiver.receive(EVENT, 'dev1'), receivers))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(len(self.store.history(results[0]['record_id'])), 1)

    def test_explicit_archive_root_is_used_without_global_environment_changes(self):
        destination = Path(self.tmp.name) / 'device-isolated'
        module = types.ModuleType('archive_store')
        module.ArchiveStore = isolated_store
        receiver = DeviceArchive(archive_root=destination)
        self.assertIsNone(receiver._store)
        with patch.dict(sys.modules, {'archive_store': module}):
            result = receiver.receive(EVENT, 'dev1')
        self.assertEqual(receiver.store.db_path, destination / 'data/mnemosyne.db')
        self.assertEqual(receiver.store.get(result['record_id'])['title'], EVENT['title'])
        self.assertFalse(self.store.list())

    def test_empty_original_body_archives_title_and_replays_exact_event(self):
        event = {**EVENT, 'body': ''}
        first = self.archive.receive(event, 'dev1')
        record = self.store.get(first['record_id'])
        self.assertEqual(record['body'], EVENT['title'])
        self.assertEqual(record['fields']['body'], '')
        self.assertEqual(self.archive.receive(event, 'dev1'), first)
        self.assertEqual(len(self.store.history(first['record_id'])), 1)
        with self.assertRaises(EventConflict):
            self.archive.receive({**event, 'body': EVENT['title']}, 'dev1')

    def test_whitespace_body_is_preserved_with_title_fallback_and_exact_replay(self):
        event = {**EVENT, 'body': ' \t\r\n\u3000'}
        first = self.archive.receive(event, 'dev1')
        record = self.store.get(first['record_id'])
        self.assertEqual(record['body'], EVENT['title'])
        self.assertEqual(record['fields']['body'], event['body'])
        self.assertEqual(self.archive.receive(event, 'dev1'), first)
        self.assertEqual(len(self.store.history(first['record_id'])), 1)
        with self.assertRaises(EventConflict):
            self.archive.receive({**event, 'body': ' '}, 'dev1')

    def test_strict_bounded_schema(self):
        cases = [[], {**EVENT, 'device_id': 'other'}, {**EVENT, 'file_path': 'x'},
                 {**EVENT, 'completed_at': True}, {**EVENT, 'completed_at': 0},
                 {**EVENT, 'completed_at': 1.5}, {**EVENT, 'scheduled_at': -1},
                 {**EVENT, 'title': '字' * 1000}, {**EVENT, 'note': '\ud800'},
                 {**EVENT, 'event_id': 'a' * 129}, {**EVENT, 'body': None},
                 {**EVENT, 'task_id': {'nested': 'value'}}]
        for value in cases:
            with self.subTest(value=repr(value)[:100]), self.assertRaises(ValueError):
                validate_event(value, 'dev1')
        for scheduled in (None, 0):
            self.assertEqual(validate_event({**EVENT, 'scheduled_at': scheduled}, 'dev1')['scheduled_at'], scheduled)

if __name__ == '__main__': unittest.main()

