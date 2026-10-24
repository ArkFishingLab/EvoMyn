import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'tests'))
from test_device_archive import isolated_store

spec = importlib.util.spec_from_file_location('editor_viewer', BASE / 'viewer/server.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


class RecordEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = isolated_store(self.tmp.name)
        self.server = viewer.create_server(self.store.db_path, port=0, record_store=self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.csrf = self.get('/api/editor')['csrf']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as response: return json.load(response)

    def post(self, value, headers=None):
        merged = {'Content-Type': 'application/json', 'Origin': self.base, 'X-CSRF-Token': self.csrf}
        merged.update(headers or {})
        try:
            with urlopen(Request(self.base + '/api/records', data=json.dumps(value).encode(), headers=merged), timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def create(self):
        status, value = self.post({'action': 'create', 'record': {'category': 'journal', 'title': '练习', 'body': '今天完成一幅画', 'date': '2026-10'}})
        self.assertEqual(status, 200)
        return value['record']

    def test_crud_is_durable_and_exposes_revisions_without_internal_details(self):
        self.assertEqual(self.get('/api/editor')['enabled'], True)
        dashboard = self.get('/api/dashboard')
        self.assertTrue(dashboard['record_management'])
        self.assertFalse(dashboard['read_only'])
        record = self.create()
        self.assertEqual(record['revision'], 1)
        self.assertNotIn('index_error', record)
        status, value = self.post({'action': 'update', 'id': record['id'], 'revision': 1, 'changes': {'body': '完成两幅画'}})
        self.assertEqual(status, 200)
        self.assertEqual(value['record']['revision'], 2)
        self.assertEqual(isolated_store(self.tmp.name).get(record['id'])['body'], '完成两幅画')
        status, value = self.post({'action': 'delete', 'id': record['id'], 'revision': 2})
        self.assertEqual((status, value), (200, {'deleted': record['id']}))
        self.assertEqual(self.get('/api/records')['records'], [])

    def test_stale_update_and_delete_cannot_overwrite_external_edits(self):
        record = self.create()
        self.store.update(record['id'], {'body': 'MCP edited'}, index=False)
        for action in ('update', 'delete'):
            value = {'action': action, 'id': record['id'], 'revision': 1}
            if action == 'update': value['changes'] = {'body': 'stale'}
            self.assertEqual(self.post(value)[0], 409)
        self.assertEqual(self.store.get(record['id'])['body'], 'MCP edited')
        self.store.delete(record['id'], expected_revision=2)
        self.assertEqual(self.post({'action': 'update', 'id': record['id'], 'revision': 2, 'changes': {'body': 'stale'}})[0], 409)

    def test_post_requires_same_origin_token_and_strict_public_fields(self):
        value = {'action': 'create', 'record': {'category': 'journal', 'title': 'x', 'body': 'y'}}
        for headers in ({'Origin': 'https://other.test'}, {'X-CSRF-Token': ''}, {'Host': 'other.test'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.post(value, headers)[0], 403)
        for changes in ({'file_path': '/secret'}, {'id': 'chosen'}, {'memory_id': 'index'}, {'fields': {}}, {'category': 'missing'}, {'body': ''}):
            self.assertEqual(self.post({**value, 'record': {**value['record'], **changes}})[0], 400)
        for malformed in ([], {'action': []}, {'action': 'create'}, {'action': 'delete', 'id': 'x', 'revision': True}):
            self.assertEqual(self.post(malformed)[0], 400)
        self.assertEqual(self.store.list(), [])

    def test_bounded_payload_and_ambiguous_framing_are_rejected(self):
        self.assertEqual(self.post({'action': 'create', 'record': {'category': 'journal', 'title': 'x', 'body': 'x' * 70000}})[0], 413)
        for extra in ('Content-Length: 2\r\n', 'Transfer-Encoding: chunked\r\n'):
            request = (f'POST /api/records HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\nOrigin: {self.base}\r\nX-CSRF-Token: {self.csrf}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n{extra}\r\n{{}}').encode()
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as conn:
                conn.sendall(request)
                self.assertIn(b' 400 ', conn.recv(1024).split(b'\r\n')[0])

    def test_save_returns_while_model_work_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        def remember(*args, **kwargs):
            entered.set()
            release.wait(5)
            return 'fixture-index'
        self.store.mem.remember = remember
        try:
            start = time.monotonic()
            record = self.create()
            self.assertLess(time.monotonic() - start, 2)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.store.get(record['id'])['index_status'], 'pending')
            status, _ = self.post({'action': 'update', 'id': record['id'], 'revision': 1, 'changes': {'body': 'while indexing'}})
            self.assertEqual(status, 200)
        finally:
            release.set()

    def test_edit_preserves_attachment_metadata_but_never_returns_local_path(self):
        resource = Path(self.tmp.name) / 'resources/file.txt'
        resource.parent.mkdir()
        resource.write_text('fixture')
        one = self.store.save({'category': 'resource', 'title': '文档', 'body': '原文', 'file_path': str(resource), 'fields': {'用途': '参考'}}, index=False)
        managed_path = one['file_path']
        status, response = self.post({'action': 'update', 'id': one['id'], 'revision': 1, 'changes': {'body': '修改正文', 'category': 'people'}})
        self.assertEqual(status, 200)
        self.assertNotIn('file_path', response['record'])
        self.assertNotIn('memory_id', response['record'])
        self.assertEqual(self.store.get(one['id'])['file_path'], managed_path)
        self.assertEqual(Path(managed_path).read_text(), 'fixture')
        self.assertEqual(resource.read_text(), 'fixture')
        self.assertEqual(response['record']['fields'], {'用途': '参考'})
        self.assertEqual(response['record']['category'], 'people')
        with urlopen(self.base + '/api/files/' + one['id'], timeout=5) as download:
            self.assertEqual(download.read(), b'fixture')
        self.assertEqual(self.post({'action': 'update', 'id': one['id'], 'revision': 2, 'changes': {'category': 'missing'}})[0], 400)
        self.assertEqual(self.store.get(one['id'])['category'], 'people')


if __name__ == '__main__': unittest.main()
