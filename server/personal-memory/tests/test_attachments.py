import hashlib
import json
import os
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from test_device_archive import isolated_store


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = isolated_store(self.root)
        self.source = self.root / '原始资料.txt'
        self.source.write_bytes(b'original attachment')

    def record(self, **extra):
        return self.store.save(dict(category='resource', title='资料', body='测试', **extra), index=False)

    def files(self):
        return sorted(p for p in (self.root / 'resources').rglob('*') if p.is_file())

    def test_primary_import_survives_source_removal_and_edit_without_copy(self):
        one = self.record(file_path=str(self.source))
        managed = Path(one['file_path'])
        self.assertNotEqual(managed, self.source)
        self.assertTrue(managed.is_relative_to(self.root / 'resources'))
        self.assertEqual(managed.name, self.source.name)
        self.source.unlink()
        two = self.store.update(one['id'], {'body': 'edited'}, index=False)
        self.assertEqual(two['attachments'], one['attachments'])
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.store.attachment(one['id']).read_bytes(), b'original attachment')

    def test_append_duplicates_unique_ids_history_and_resolver(self):
        from attachment_files import resolve_attachment
        one = self.record()
        two = self.store.add_attachments(one['id'], [str(self.source), str(self.source)], 1, index=False)
        self.assertEqual(two['revision'], 2)
        self.assertEqual(len(two['attachments']), 2)
        first, second = two['attachments']
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['file_path'], second['file_path'])
        self.assertEqual(first['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(first['size'], self.source.stat().st_size)
        self.assertEqual(first['href'], f"/api/files/{one['id']}/{first['id']}")
        self.assertEqual(resolve_attachment(self.store.db_path, self.root / 'resources', one['id'], first['id']), Path(first['file_path']))
        self.assertEqual(len(self.store.history(one['id'])), 2)
        self.assertEqual(self.store.history(one['id'])[0].get('attachments', []), [])

    def test_stale_invalid_and_failed_transaction_leave_no_files(self):
        one = self.record()
        for paths, revision in [([str(self.source)], 0), ([str(self.source), str(self.root / 'missing')], 1), ([], 1), ([str(self.source)] * 21, 1)]:
            with self.assertRaises((ValueError, OSError)):
                self.store.add_attachments(one['id'], paths, revision, index=False)
            self.assertEqual(self.files(), [])
        with self.store.connection() as conn:
            conn.execute("CREATE TRIGGER refuse_attachment BEFORE UPDATE ON personal_archive_records BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_attachments(one['id'], [str(self.source)], 1, index=False)
        self.assertEqual(self.files(), [])
        self.assertTrue(self.source.exists())

    def test_reject_metadata_spoof_and_database_sidecars(self):
        one = self.record(file_path=str(self.source))
        for changes in [{'attachments': [{**one['attachments'][0], 'id': 'spoof'}]}, {'attachments': []}]:
            with self.assertRaises(ValueError): self.store.update(one['id'], changes, index=False)
        for suffix in ['', '-wal', '-shm', '-journal']:
            from attachment_files import checked_file
            target = Path(str(self.store.db_path) + suffix)
            with self.assertRaises(ValueError): checked_file(target, self.store.db_path)

    def test_bounds_and_symlinks(self):
        import attachment_files
        one = self.record()
        with patch.object(attachment_files, 'MAX_ATTACHMENT_BYTES', 2):
            with self.assertRaises(ValueError): self.store.add_attachments(one['id'], [str(self.source)], index=False)
        linked = self.root / 'linked.txt'
        try: linked.symlink_to(self.source)
        except OSError: return
        with self.assertRaises(ValueError): self.store.add_attachments(one['id'], [str(linked)], index=False)

    def test_resolver_rejects_external_legacy_and_linked_managed_root(self):
        from attachment_files import resolve_attachment
        one = self.record()
        with self.store.connection() as conn:
            payload = {**one, 'file_path': str(self.source)}
            conn.execute('UPDATE personal_archive_records SET payload=? WHERE id=?', (json.dumps(payload), one['id']))
        with self.assertRaises((KeyError, ValueError)):
            resolve_attachment(self.store.db_path, self.root / 'resources', one['id'], 'legacy')

    def test_replacement_retains_history_files_and_legacy_managed_record(self):
        from attachment_files import resolve_attachment
        one = self.record(file_path=str(self.source))
        second = self.root / '第二份.txt'
        second.write_bytes(b'second')
        two = self.store.update(one['id'], {'file_path': str(second)}, index=False)
        self.assertEqual(len(two['attachments']), 2)
        self.assertTrue(Path(one['file_path']).is_file())
        self.assertEqual(self.store.history(one['id'])[0]['file_path'], one['file_path'])
        # Old payloads without an attachments array resolve only managed files.
        with self.store.connection() as conn:
            legacy = {**one}
            legacy.pop('attachments')
            conn.execute('UPDATE personal_archive_records SET payload=? WHERE id=?', (json.dumps(legacy), one['id']))
        self.assertEqual(resolve_attachment(self.store.db_path, self.root / 'resources', one['id'], 'legacy'), Path(one['file_path']))

    def test_reparse_resource_root_and_linked_parent_are_rejected(self):
        root = self.root / 'resources'
        root.mkdir()
        one = self.record()
        actual_lstat = Path.lstat
        def linked_info(path, *args, **kwargs):
            info = actual_lstat(path, *args, **kwargs)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == root else info
        with patch.object(Path, 'lstat', linked_info):
            with self.assertRaises(ValueError):
                self.store.add_attachments(one['id'], [str(self.source)], index=False)
        self.assertEqual(self.files(), [])

    def test_resolver_rejects_spoofed_external_metadata_and_missing_ids(self):
        from attachment_files import resolve_attachment
        one = self.record()
        with self.store.connection() as conn:
            payload = {**one, 'attachments': [{'id': 'spoof', 'file_path': str(self.source)}]}
            conn.execute('UPDATE personal_archive_records SET payload=? WHERE id=?', (json.dumps(payload), one['id']))
        with self.assertRaises(ValueError):
            resolve_attachment(self.store.db_path, self.root / 'resources', one['id'], 'spoof')
        for record_id, attachment_id in [(one['id'], '../spoof'), ('missing', 'spoof')]:
            with self.assertRaises(KeyError):
                resolve_attachment(self.store.db_path, self.root / 'resources', record_id, attachment_id)

    def test_disk_flush_failure_leaves_no_partial_files(self):
        one = self.record()
        with patch('attachment_files.os.fsync', side_effect=OSError('fixture disk error')):
            with self.assertRaises(OSError):
                self.store.add_attachments(one['id'], [str(self.source)], index=False)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.store.get(one['id'])['revision'], 1)
        self.assertEqual(len(self.store.history(one['id'])), 1)

    def test_save_stale_and_transaction_failure_cleanup_primary(self):
        one = self.record()
        with self.assertRaises(ValueError):
            self.store.update(one['id'], {'file_path': str(self.source)}, expected_revision=0, index=False)
        self.assertEqual(self.files(), [])
        with self.store.connection() as conn:
            conn.execute("CREATE TRIGGER refuse_primary BEFORE UPDATE ON personal_archive_records BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.update(one['id'], {'file_path': str(self.source)}, index=False)
        self.assertEqual(self.files(), [])


if __name__ == '__main__': unittest.main()
