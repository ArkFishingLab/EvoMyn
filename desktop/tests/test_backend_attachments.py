"""Native attachment resolution never imports models or accepts external paths."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'desktop/backend'))
from attachments import attachment_path


class AttachmentResolutionTests(unittest.TestCase):
    def test_resolve_managed_attachment_and_reject_outside_or_deleted_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app').mkdir()
            shutil.copyfile(ROOT / 'server/personal-memory/vendor/attachment_files.py', root / 'app/attachment_files.py')
            data = root / 'state/data'; data.mkdir(parents=True)
            resources = root / 'state/resources'; resources.mkdir()
            file = resources / '中文资料.pdf'; file.write_bytes(b'isolated attachment')
            with closing(sqlite3.connect(data / 'mnemosyne.db')) as connection:
                connection.execute('CREATE TABLE personal_archive_records(id TEXT PRIMARY KEY,payload TEXT)')
                connection.execute('INSERT INTO personal_archive_records VALUES(?,?)', ('resource-a', json.dumps({'attachments':[{'id':'a'*32,'file_path':str(file)}]})))
                connection.commit()
            self.assertEqual(attachment_path(root, 'resource-a', 'a'*32)['path'], str(file))
            with self.assertRaises(KeyError): attachment_path(root, 'deleted', 'a'*32)
            outside = root / 'outside.txt'; outside.write_text('private fixture')
            with closing(sqlite3.connect(data / 'mnemosyne.db')) as connection:
                connection.execute('UPDATE personal_archive_records SET payload=?', (json.dumps({'file_path':str(outside)}),))
                connection.commit()
            with self.assertRaises(ValueError): attachment_path(root, 'resource-a', 'legacy')


if __name__ == '__main__': unittest.main()
