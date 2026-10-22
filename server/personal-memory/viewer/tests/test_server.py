import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('memory_viewer', Path(__file__).resolve().parents[1] / 'server.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'data' / 'mnemosyne.db'
        self.db.parent.mkdir()
        self.resources = self.root / 'resources'
        self.resources.mkdir()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE personal_archive_records(id TEXT PRIMARY KEY, payload TEXT, revision INTEGER, index_revision INTEGER, index_error TEXT, occurrence_date TEXT)')
            conn.commit()
        self.save('first', '真实记录')
        self.server = viewer.create_server(self.db, port=0, resource_root=self.resources)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def save(self, record_id, title, **extra):
        value = dict(id=record_id, category='journal', title=title, body='正文 <script> 文本', date='', fields={}, tags=[], links=[])
        value.update(extra)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('INSERT INTO personal_archive_records VALUES(?,?,?,?,?,?)', (record_id, json.dumps(value), 1, 1, None, ''))
            conn.commit()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return response, response.read()

    def test_records_are_real_and_later_writes_appear(self):
        _, body = self.get('/api/records')
        self.assertEqual(len(json.loads(body)['records']), 1)
        self.save('second', '后来新增')
        _, body = self.get('/api/records')
        self.assertEqual({x['title'] for x in json.loads(body)['records']}, {'真实记录', '后来新增'})

    def test_read_only_api_rejects_mutations(self):
        for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + '/api/records', data=b'{}', method=method))
            self.assertEqual(error.exception.code, 405)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM personal_archive_records').fetchone()[0], 1)

    def category_request(self, value, csrf=None, origin=None):
        headers = {'Content-Type': 'application/json', 'Origin': origin or self.base}
        if csrf is not None: headers['X-CSRF-Token'] = csrf
        with urlopen(Request(self.base + '/api/categories', data=json.dumps(value).encode(), headers=headers)) as response:
            return json.load(response)

    def test_categories_are_durable_model_free_and_leave_existing_records_untouched(self):
        _, raw = self.get('/api/categories')
        initial = json.loads(raw)
        self.assertEqual(initial['categories'][2]['label'], '个人')
        value = self.category_request({'action': 'create', 'label': '工作项目'}, initial['csrf'])
        item = next(x for x in value['categories'] if x['label'] == '工作项目')
        self.category_request({'action': 'rename', 'id': item['id'], 'label': '项目档案'}, initial['csrf'])
        _, raw = self.get('/api/records')
        payload = json.loads(raw)
        self.assertEqual(len(payload['records']), 1)
        self.assertEqual(next(x for x in payload['categories'] if x['id'] == item['id'])['label'], '项目档案')
        self.assertNotIn('mnemosyne', sys.modules)
        self.category_request({'action': 'delete', 'id': item['id']}, initial['csrf'])
        _, raw = self.get('/api/categories')
        self.assertNotIn(item['id'], [x['id'] for x in json.loads(raw)['categories']])

    def test_category_mutations_require_token_same_origin_and_valid_shape(self):
        _, raw = self.get('/api/categories')
        token = json.loads(raw)['csrf']
        for csrf, origin in [(None, self.base), ('wrong', self.base), (token, 'https://other.invalid')]:
            with self.assertRaises(HTTPError) as error:
                self.category_request({'action': 'create', 'label': '拒绝'}, csrf, origin)
            self.assertEqual(error.exception.code, 403)
        for value in [{'action': 'create', 'label': ''}, {'action': 'rename', 'id': 'missing', 'label': '新名'},
                      {'action': 'reorder', 'order': ['journal']}, {'action': 'drop-all'},
                      {'action': 'create', 'label': '多余字段', 'extra': True}, []]:
            with self.assertRaises(HTTPError) as error:
                self.category_request(value, token)
            self.assertEqual(error.exception.code, 400)

    def test_database_and_source_are_not_static_files(self):
        for path in ['/data/mnemosyne.db', '/static/../server.py', '/static/%2e%2e/server.py', '/.env']:
            with self.assertRaises(HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404)

    def test_registered_resources_are_downloaded_without_active_content(self):
        target = self.resources / 'note.html'
        target.write_text('<script>private()</script>', encoding='utf-8')
        self.save('attachment', '附件', category='resource', file_path=str(target), href='/api/files/attachment')
        response, body = self.get('/api/files/attachment')
        self.assertIn(b'private()', body)
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn('sandbox', response.headers['Content-Security-Policy'])
        _, records = self.get('/api/records')
        self.assertNotIn(str(target), records.decode())

    def test_paths_outside_resource_directory_are_refused(self):
        secret = self.root / '.env'
        secret.write_text('secret', encoding='utf-8')
        self.save('secret', '禁止附件', category='resource', file_path=str(secret))
        with self.assertRaises(HTTPError) as error:
            self.get('/api/files/secret')
        self.assertEqual(error.exception.code, 404)

    def test_host_is_checked_and_database_errors_are_not_empty_success(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base + '/', headers={'Host': 'other.invalid'}))
        self.assertEqual(error.exception.code, 403)
        self.db.unlink()
        with self.assertRaises(HTTPError) as error:
            self.get('/api/records')
        self.assertEqual(error.exception.code, 503)
        self.assertFalse(self.db.exists())

    def test_assets_use_prefix_safe_urls_and_readonly_status(self):
        _, html = self.get('/')
        self.assertIn(b'./static/personal.mjs', html)
        self.assertNotIn(b'href="/static/', html)
        _, script = self.get('/static/personal.mjs')
        self.assertIn(b"api('./api/records')", script)
        _, status = self.get('/api/dashboard')
        self.assertTrue(json.loads(status)['read_only'])


if __name__ == '__main__':
    unittest.main()
