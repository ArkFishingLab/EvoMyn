import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from planner_server import open_backup_read_lease

class BackupWalLeaseTests(unittest.TestCase):
    def test_idle_read_lease_keeps_sidecars_without_holding_a_read_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'db.sqlite'
            with sqlite3.connect(db) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('CREATE TABLE records(id INTEGER)')
                writer.commit()
            writer.close()
            lease=open_backup_read_lease(db)
            try:
                self.assertFalse(lease.in_transaction)
                writer=sqlite3.connect(db)
                writer.execute('INSERT INTO records VALUES(1)');writer.commit()
                self.assertEqual(writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
                writer.close()
                self.assertTrue(Path(str(db)+'-wal').exists())
                self.assertTrue(Path(str(db)+'-shm').exists())
                with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as reader:
                    self.assertEqual(reader.execute('SELECT count(*) FROM records').fetchone()[0],1)
                reader.close()
            finally:lease.close()

if __name__=='__main__':unittest.main()
