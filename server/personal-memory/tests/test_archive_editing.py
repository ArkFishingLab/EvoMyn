import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_device_archive import isolated_store, DeviceArchive, EventConflict, EVENT


class ArchiveEditingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_store(self.tmp.name)

    def record(self, **extra):
        return dict(category='journal', title='今天', body='完成一次练习', date='2026-10', **extra)

    def test_deferred_write_and_edit_preserve_metadata_and_revision_history(self):
        self.store.mem.remember = Mock(side_effect=AssertionError('must defer model'))
        one = self.store.save(self.record(fields={'课程': '画画'}, steps=[{'text': '复盘', 'done': False}]), index=False)
        two = self.store.update(one['id'], {'body': '第二次练习'}, expected_revision=1, index=False)
        self.assertEqual(two['revision'], 2)
        self.assertEqual(two['fields'], one['fields'])
        self.assertEqual(two['steps'], one['steps'])
        self.assertEqual(two['index_status'], 'pending')
        self.assertEqual([r['body'] for r in self.store.history(one['id'])], ['完成一次练习', '第二次练习'])
        self.store.mem.remember.assert_not_called()
        with self.assertRaises(ValueError): self.store.update(one['id'], {'body': 'stale'}, expected_revision=1, index=False)
        self.assertEqual(self.store.get(one['id'])['body'], '第二次练习')

    def test_reclassification_preserves_identity_history_links_and_counts(self):
        one = self.store.save(self.record(fields={'课程': '画画'}), index=False)
        linked = self.store.save(self.record(links=[one['id']]), index=False)
        custom = self.store.categories.create('学习')['id']
        for revision, category in enumerate(['people', custom], 1):
            updated = self.store.update(one['id'], {'category': category}, expected_revision=revision, index=False)
            self.assertEqual(updated['id'], one['id'])
            self.assertEqual(updated['created_at'], one['created_at'])
            self.assertEqual(updated['fields'], one['fields'])
            self.assertEqual([r['id'] for r in self.store.list(category=category)], [one['id']])
            self.assertEqual(next(c['count'] for c in self.store.categories.list() if c['id'] == category), 1)
        self.assertEqual([r['category'] for r in self.store.history(one['id'])], ['journal', 'people', custom])
        self.assertEqual(self.store.get(linked['id'])['links'], [one['id']])
        self.assertEqual([r['id'] for r in self.store.list(category='journal')], [linked['id']])
        for changes, revision in [({'category': 'missing'}, 3), ({'category': 'journal'}, 1)]:
            with self.assertRaises(ValueError):
                self.store.update(one['id'], changes, expected_revision=revision, index=False)
        self.assertEqual(self.store.get(one['id'])['category'], custom)
        self.assertEqual(len(self.store.history(one['id'])), 3)

    def test_reclassification_keeps_registered_attachment(self):
        attachment = Path(self.tmp.name) / 'resource.txt'
        attachment.write_text('fixture')
        one = self.store.save({'category': 'resource', 'title': '资料', 'body': '附件', 'file_path': str(attachment)}, index=False)
        two = self.store.update(one['id'], {'category': 'background'}, expected_revision=1, index=False)
        self.assertEqual(two['href'], one['href'])
        self.assertEqual(self.store.attachment(one['id']), Path(one['file_path']))
        self.assertEqual(self.store.attachment(one['id']).read_text(), attachment.read_text())

    def test_delete_checks_revision_removes_history_and_unlinks_atomically(self):
        one = self.store.save(self.record(), index=False)
        two = self.store.save(self.record(links=[one['id']]), index=False)
        with self.assertRaises(ValueError): self.store.delete(one['id'], expected_revision=2)
        self.assertEqual(self.store.get(two['id'])['links'], [one['id']])
        result = self.store.delete(one['id'], expected_revision=1)
        self.assertEqual(result['deleted'], one['id'])
        with self.assertRaises(KeyError): self.store.get(one['id'])
        self.assertEqual(self.store.history(one['id']), [])
        linked = self.store.get(two['id'])
        self.assertEqual(linked['links'], [])
        self.assertEqual(linked['revision'], 2)
        self.assertEqual(linked['index_status'], 'pending')
        with self.assertRaises(ValueError): self.store.save({**one, 'body': 'resurrect'}, index=False)
        tombstone = self.store.tombstone(one['id'])
        self.assertEqual(set(tombstone), {'id', 'deleted_at', 'event_digest'})
        self.assertNotIn('完成一次练习', json.dumps(tombstone))

    def test_delete_keeps_attachment_and_existing_backup(self):
        attachment = Path(self.tmp.name) / 'resource.txt'
        attachment.write_text('fixture')
        one = self.store.save({'category': 'resource', 'title': '资料', 'body': '附件', 'file_path': str(attachment)}, index=False)
        backup = self.store.backup()
        self.store.delete(one['id'], expected_revision=1)
        self.assertTrue(attachment.is_file())
        self.assertTrue(backup.is_file())
        with self.assertRaises(KeyError): self.store.attachment(one['id'])

    def test_failed_relationship_cleanup_rolls_back_entire_deletion(self):
        one = self.store.save(self.record(), index=False)
        two = self.store.save(self.record(links=[one['id']]), index=False)
        with self.store.connection() as conn:
            conn.execute("CREATE TRIGGER refuse_cleanup BEFORE UPDATE ON personal_archive_records BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.delete(one['id'], expected_revision=1)
        self.assertIsNone(self.store.tombstone(one['id']))
        self.assertEqual(self.store.get(one['id'])['revision'], 1)
        self.assertEqual(len(self.store.history(one['id'])), 1)
        self.assertEqual(self.store.get(two['id'])['links'], [one['id']])

    def test_delete_invalidates_native_index_and_ignores_stale_recall(self):
        self.store.mem.remember = lambda *a, **kw: 'old-index'
        self.store.mem.invalidate = Mock()
        self.store.mem.recall = lambda *a, **kw: [{'id': 'old-index', 'score': 1}]
        one = self.store.save(self.record())
        self.assertEqual(one['index_status'], 'indexed')
        self.store.delete(one['id'], expected_revision=1)
        self.store.mem.invalidate.assert_called_once_with('old-index')
        self.assertEqual(self.store.search('今天'), [])

    def test_deleted_device_completion_replay_is_acknowledged_without_recreation(self):
        archive = DeviceArchive(store=self.store)
        first = archive.receive(EVENT, 'dev1')
        self.store.update(first['record_id'], {'fields': {'note': 'edited'}})
        self.store.delete(first['record_id'], expected_revision=2)
        replay = DeviceArchive(store=isolated_store(self.tmp.name)).receive(EVENT, 'dev1')
        self.assertTrue(replay['ok'])
        self.assertEqual(replay['index_status'], 'deleted')
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.history(first['record_id']), [])
        with self.assertRaises(EventConflict): archive.receive({**EVENT, 'note': 'changed'}, 'dev1')

    def test_device_index_runs_after_releasing_archive_lock(self):
        observed = []
        def remember(*args, **kwargs):
            observed.append(self.store.lock.is_locked)
            return 'device-index'
        self.store.mem.remember = remember
        DeviceArchive(store=self.store).receive(EVENT, 'dev1')
        self.assertEqual(observed, [False])

    def test_stale_index_result_cannot_mark_new_revision_indexed(self):
        one = self.store.save(self.record(), index=False)
        def remember(*args, **kwargs):
            self.store.update(one['id'], {'body': 'newer'}, expected_revision=1, index=False)
            return 'stale-index'
        self.store.mem.remember = remember
        self.store.mem.invalidate = Mock()
        self.store._index(one['id'])
        current = self.store.get(one['id'])
        self.assertEqual(current['revision'], 2)
        self.assertEqual(current['index_status'], 'pending')
        self.assertIsNone(current['memory_id'])
        self.store.mem.invalidate.assert_called_once_with('stale-index')

    def test_delete_during_index_cannot_restore_record_or_search_hit(self):
        one = self.store.save(self.record(), index=False)
        def remember(*args, **kwargs):
            self.store.delete(one['id'], expected_revision=1)
            return 'deleted-index'
        self.store.mem.remember = remember
        self.store.mem.invalidate = Mock()
        self.store.mem.recall = lambda *a, **kw: [{'id': 'deleted-index', 'score': 1}]
        self.store._index(one['id'])
        self.assertEqual(self.store.search('今天'), [])
        self.store.mem.invalidate.assert_called_once_with('deleted-index')

    def test_old_index_failure_does_not_attach_error_to_new_revision(self):
        one = self.store.save(self.record(), index=False)
        def remember(*args, **kwargs):
            self.store.update(one['id'], {'body': 'newer'}, expected_revision=1, index=False)
            raise RuntimeError('old snapshot failed')
        self.store.mem.remember = remember
        self.store._index(one['id'])
        current = self.store.get(one['id'])
        self.assertEqual(current['revision'], 2)
        self.assertNotIn('index_error', current)

    def test_delete_does_not_call_shared_native_connection_during_model_work(self):
        self.store.mem.remember = lambda *a, **kw: 'old-index'
        one = self.store.save(self.record())
        entered, release = threading.Event(), threading.Event()
        def remember(*args, **kwargs):
            entered.set()
            release.wait(5)
            return 'new-index'
        self.store.mem.remember = remember
        self.store.mem.invalidate = Mock()
        worker = threading.Thread(target=self.store._index, args=(one['id'],))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.store.delete(one['id'], expected_revision=1)
            self.store.mem.invalidate.assert_not_called()
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.store.mem.invalidate.assert_called_once_with('new-index')


if __name__ == '__main__': unittest.main()
