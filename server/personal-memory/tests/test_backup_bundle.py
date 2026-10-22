import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

VENDOR = Path(__file__).resolve().parents[1] / 'vendor'
sys.path.insert(0, str(VENDOR))
import backup_bundle
import restore_backup


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = cls.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.private = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        (self.state / 'data').mkdir(parents=True)
        (self.state / 'resources').mkdir()
        self.config = self.root / 'config'
        self.config.mkdir()
        self.db = sqlite3.connect(self.state / 'data/mnemosyne.db')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE personal_archive_records (id TEXT)')
        self.db.execute('CREATE TABLE planner_tasks (id TEXT)')
        self.db.execute("INSERT INTO personal_archive_records VALUES ('record-a')")
        self.db.execute("INSERT INTO planner_tasks VALUES ('task-a')")
        self.db.commit()
        self.addCleanup(self.db.close)
        (self.state / 'resources/note.txt').write_text('attachment content')
        (self.state / 'backup-state').mkdir()
        (self.state / 'backup-state/token').write_text('never-include-this')
        (self.config / 'compose.yaml').write_text('services: {}')
        (self.config / 'other-secret').write_text('never-include-this')
        self.keyfile = self.root / 'key.pem'
        self.keyfile.write_bytes(self.private)

    def test_round_trip_snapshot_allowlist_and_metadata(self):
        encrypted = self.root / 'backup.pmbak'
        metadata = backup_bundle.create_bundle(self.state, self.config, encrypted, self.public)
        self.assertEqual(metadata['archive_records'], 1)
        self.assertEqual(metadata['planner_tasks'], 1)
        self.assertEqual(metadata['sha256'], hashlib.sha256(encrypted.read_bytes()).hexdigest())
        self.assertEqual(metadata['size'], encrypted.stat().st_size)
        self.assertNotIn(b'attachment content', encrypted.read_bytes())
        restored = self.root / 'restored.tar.gz'
        restore_backup.decrypt_bundle(self.keyfile, encrypted, restored)
        with tarfile.open(restored, 'r:gz') as archive:
            self.assertEqual(set(archive.getnames()), {'manifest.json', 'state/data/mnemosyne.db', 'state/resources/note.txt', 'config/compose.yaml'})
            snapshot = self.root / 'snapshot.db'
            snapshot.write_bytes(archive.extractfile('state/data/mnemosyne.db').read())
            with closing(sqlite3.connect(snapshot)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('SELECT * FROM planner_tasks').fetchall(), [('task-a',)])

    def test_tampering_never_exposes_plaintext_and_existing_output_is_untouched(self):
        encrypted = self.root / 'backup.pmbak'
        backup_bundle.create_bundle(self.state, self.config, encrypted, self.public)
        data = bytearray(encrypted.read_bytes())
        data[-20] ^= 1
        encrypted.write_bytes(data)
        restored = self.root / 'restored.tar.gz'
        with self.assertRaises(ValueError):
            restore_backup.decrypt_bundle(self.keyfile, encrypted, restored)
        self.assertFalse(restored.exists())
        self.assertFalse(list(self.root.glob('.restore-*')))
        restored.write_text('keep')
        with self.assertRaises(ValueError):
            restore_backup.decrypt_bundle(self.keyfile, encrypted, restored)
        self.assertEqual(restored.read_text(), 'keep')

    def test_weak_key_and_output_overwrite_rejected(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(ValueError):
            backup_bundle.public_key_fingerprint(pem)
        existing = self.root / 'existing'
        existing.write_text('keep')
        with self.assertRaises(ValueError):
            backup_bundle.create_bundle(self.state, self.config, existing, self.public)
        self.assertEqual(existing.read_text(), 'keep')

    def test_symlink_resource_is_rejected(self):
        link = self.state / 'resources/link'
        try:
            link.symlink_to(self.keyfile)
        except OSError:
            self.skipTest('Windows symlink privilege unavailable')
        with self.assertRaises(ValueError):
            backup_bundle.create_bundle(self.state, self.config, self.root / 'backup', self.public)

    def test_rejects_output_in_resources_and_cleans_failed_archive(self):
        output = self.state / 'resources/backup.pmbak'
        with self.assertRaises(ValueError):
            backup_bundle.create_bundle(self.state, self.config, output, self.public)
        self.assertFalse(output.exists())

    def test_each_backup_has_independent_encryption(self):
        first, second = self.root / 'one', self.root / 'two'
        backup_bundle.create_bundle(self.state, self.config, first, self.public)
        backup_bundle.create_bundle(self.state, self.config, second, self.public)
        self.assertNotEqual(first.read_bytes(), second.read_bytes())

    def test_all_regular_resource_names_are_preserved(self):
        (self.state / 'resources/token').write_text('user document named token')
        (self.state / 'resources/models').mkdir()
        (self.state / 'resources/models/backups').write_text('user document named backups')
        encrypted, restored = self.root / 'backup', self.root / 'restored.tar.gz'
        backup_bundle.create_bundle(self.state, self.config, encrypted, self.public)
        restore_backup.decrypt_bundle(self.keyfile, encrypted, restored)
        with tarfile.open(restored, 'r:gz') as archive:
            self.assertEqual(archive.extractfile('state/resources/token').read(), b'user document named token')
            self.assertEqual(archive.extractfile('state/resources/models/backups').read(), b'user document named backups')
            self.assertNotIn('state/backup-state/token', archive.getnames())

    def test_snapshot_integrity_failure_rejects_backup_before_output_creation(self):
        self.db.execute('CREATE TABLE integrity_probe (value INTEGER CHECK(value > 0))')
        self.db.execute('PRAGMA ignore_check_constraints=ON')
        self.db.execute('INSERT INTO integrity_probe VALUES (-1)')
        self.db.execute('PRAGMA ignore_check_constraints=OFF')
        self.db.commit()
        self.assertNotEqual(self.db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        output = self.root / 'corrupt-backup'
        with self.assertRaisesRegex(ValueError, 'integrity'):
            backup_bundle.create_bundle(self.state, self.config, output, self.public)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.snapshot-*')))


if __name__ == '__main__':
    unittest.main()
