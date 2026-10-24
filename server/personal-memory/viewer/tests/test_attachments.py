"""Managed uploads use isolated stores and never touch the installed archive."""
import json
import socket
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import test_record_editor as editor_tests
viewer = editor_tests.viewer


class AttachmentUploadTests(unittest.TestCase):
    setUp = editor_tests.RecordEditorTests.setUp
    tearDown = editor_tests.RecordEditorTests.tearDown
    get = editor_tests.RecordEditorTests.get
    post = editor_tests.RecordEditorTests.post
    create = editor_tests.RecordEditorTests.create
    def upload(self, record, data=b'attachment bytes', name='笔记.txt', headers=None, revision=None):
        merged = {'Content-Type': 'application/octet-stream', 'Origin': self.base,
                  'X-CSRF-Token': self.csrf, 'X-File-Name': quote(name)}
        merged.update(headers or {})
        path = f"/api/attachments?record_id={quote(record['id'])}&revision={revision or record['revision']}"
        try:
            with urlopen(Request(self.base + path, data=data, headers=merged), timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_upload_roundtrip_preserves_names_and_hides_private_paths(self):
        original = self.create()
        first_status, first = self.upload(original)
        self.assertEqual(first_status, 200)
        first = first['record']
        self.assertEqual(first['revision'], original['revision'] + 1)
        self.assertEqual(first['attachments'][0]['name'], '笔记.txt')
        status, second = self.upload(first, b'other bytes')
        self.assertEqual(status, 200)
        second = second['record']
        self.assertEqual(len(second['attachments']), 2)
        self.assertNotEqual(second['attachments'][0]['id'], second['attachments'][1]['id'])
        for attachment, expected in zip(second['attachments'], [b'attachment bytes', b'other bytes']):
            self.assertNotIn('file_path', attachment)
            with urlopen(self.base + attachment['href']) as response:
                self.assertEqual(response.read(), expected)
                self.assertIn('attachment;', response.headers['Content-Disposition'])
                self.assertIn('sandbox', response.headers['Content-Security-Policy'])
        self.assertNotIn(self.tmp.name, json.dumps(self.get('/api/records')))

    def test_upload_refuses_csrf_cross_origin_bad_names_and_stale_revision(self):
        record = self.create()
        for headers in [{'Origin': 'https://other.test'}, {'X-CSRF-Token': ''}, {'Host': 'other.test'}, {'Sec-Fetch-Site': 'cross-site'}]:
            self.assertEqual(self.upload(record, headers=headers)[0], 403)
        for name in ['../escape.txt', r'a\b.txt', 'file:stream', '.', 'CON.txt', 'bad\x00name']:
            self.assertEqual(self.upload(record, name=name)[0], 400)
        self.assertEqual(self.upload(record)[0], 200)
        self.assertEqual(self.upload(record)[0], 409)
        self.assertEqual(len(self.store.get(record['id'])['attachments']), 1)

    def test_upload_bounds_and_framing_are_checked_before_reading_body(self):
        record = self.create()
        for framing, expected in [('Content-Length: 52428801\r\n', 413),
                                  ('Content-Length: 2\r\nTransfer-Encoding: chunked\r\n', 400),
                                  ('Content-Length: 2\r\nContent-Length: 2\r\n', 400)]:
            raw = (f"POST /api/attachments?record_id={record['id']}&revision=1 HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{self.server.server_port}\r\nOrigin: {self.base}\r\n"
                   f"X-CSRF-Token: {self.csrf}\r\nX-File-Name: note.txt\r\nContent-Type: application/octet-stream\r\n{framing}\r\n").encode()
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as conn:
                conn.sendall(raw)
                self.assertIn(f' {expected} '.encode(), conn.recv(1024).split(b'\r\n')[0])

    def test_bad_filename_is_rejected_before_reading_the_body(self):
        record = self.create()
        raw = (f"POST /api/attachments?record_id={record['id']}&revision=1 HTTP/1.1\r\n"
               f"Host: 127.0.0.1:{self.server.server_port}\r\nOrigin: {self.base}\r\n"
               f"X-CSRF-Token: {self.csrf}\r\nX-File-Name: ..%2Fescape.txt\r\n"
               "Content-Type: application/octet-stream\r\nContent-Length: 99999\r\n\r\n").encode()
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as conn:
            conn.sendall(raw)
            self.assertIn(b' 400 ', conn.recv(1024).split(b'\r\n')[0])

    def test_read_only_viewer_never_accepts_uploads(self):
        server = viewer.create_server(self.store.db_path, port=0)
        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(f'http://127.0.0.1:{server.server_port}/api/attachments', data=b'x'))
            self.assertEqual(error.exception.code, 405)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_temporary_upload_is_removed_when_store_rejects_the_write(self):
        record = self.create()
        captured = []
        def rejected(_record_id, paths, **kwargs):
            captured.extend(Path(path) for path in paths)
            self.assertEqual(captured[0].read_bytes(), b'attachment bytes')
            raise ValueError('fixture rejected')
        with patch.object(self.store, 'add_attachments', side_effect=rejected):
            self.assertEqual(self.upload(record)[0], 400)
        self.assertTrue(captured)
        self.assertFalse(captured[0].exists())
        self.assertFalse(captured[0].parent.exists())

    def test_empty_attachment_is_a_valid_file(self):
        status, result = self.upload(self.create(), data=b'')
        self.assertEqual(status, 200)
        self.assertEqual(result['record']['attachments'][0]['size'], 0)

    def test_legacy_primary_stays_downloadable_after_adding_managed_attachments(self):
        record = self.create()
        resource = Path(self.tmp.name) / 'resources/legacy.txt'
        resource.parent.mkdir(exist_ok=True)
        resource.write_bytes(b'legacy bytes')
        # Simulate a pre-feature record in this test's isolated database.
        legacy = self.store.get(record['id'])
        legacy['file_path'] = str(resource)
        legacy['href'] = '/api/files/' + record['id']
        legacy.pop('attachments', None)
        with closing(sqlite3.connect(self.store.db_path)) as conn:
            conn.execute('UPDATE personal_archive_records SET payload=? WHERE id=?', (json.dumps(legacy), record['id']))
            conn.commit()
        status, result = self.upload(record)
        self.assertEqual(status, 200)
        public = result['record']
        self.assertEqual(public['href'], legacy['href'])
        self.assertEqual(len(public['attachments']), 1)
        self.assertNotEqual(public['href'], public['attachments'][0]['href'])
        with urlopen(self.base + public['href']) as response:
            self.assertEqual(response.read(), b'legacy bytes')
        self.assertNotIn('file_path', public)
        self.assertNotIn(str(resource), json.dumps(public))

    def test_public_managed_primary_uses_the_matching_attachment_url(self):
        resource = Path(self.tmp.name) / 'primary.txt'
        resource.write_bytes(b'primary bytes')
        saved = self.store.save({'category':'resource', 'title':'Primary', 'body':'Fixture', 'file_path':str(resource)}, index=False)
        public = next(item for item in self.get('/api/records')['records'] if item['id'] == saved['id'])
        self.assertEqual(public['href'], public['attachments'][0]['href'])
