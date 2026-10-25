"""Archive viewer with opt-in same-origin editing; no model imports."""
import argparse
import hmac
import importlib.util
import json
import mimetypes
import os
import queue
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
_category_file = next(path for path in (ROOT.parent / 'app/archive_categories.py', ROOT.parent / 'vendor/archive_categories.py', ROOT.parent / 'archive_categories.py') if path.is_file())
_category_spec = importlib.util.spec_from_file_location('viewer_category_catalog', _category_file)
_category_module = importlib.util.module_from_spec(_category_spec)
_category_spec.loader.exec_module(_category_module)
CategoryCatalog = _category_module.CategoryCatalog
_http_spec = importlib.util.spec_from_file_location('viewer_local_http', _category_file.with_name('local_http.py'))
_http_module = importlib.util.module_from_spec(_http_spec)
_http_spec.loader.exec_module(_http_module)
ThreadingHTTPServer = _http_module.ThreadingHTTPServer
_attachment_file = next(path for path in (ROOT.parent / 'app/attachment_files.py', ROOT.parent / 'vendor/attachment_files.py', ROOT.parent / 'attachment_files.py') if path.is_file())
_attachment_spec = importlib.util.spec_from_file_location('viewer_attachment_files', _attachment_file)
_attachment_module = importlib.util.module_from_spec(_attachment_spec)
_attachment_spec.loader.exec_module(_attachment_module)
STATIC = ROOT / 'static'
ASSETS = {'favicon.svg', 'brand-fonts.css', 'style.css', 'personal-native.css', 'backup.css', 'backup.mjs',
          'personal.mjs', 'personal-shared.mjs', 'personal-model.mjs', 'categories.mjs', 'categories.css',
          'editor-model.mjs', 'record-editor.mjs', 'record-editor.css', 'attachments.mjs'}
CHINA = timezone(timedelta(hours=8))
MAX_ATTACHMENT_BYTES = _attachment_module.MAX_ATTACHMENT_BYTES


class IndexWorker:
    """Coalesce local edits; pending revisions remain durable if the app exits."""
    def __init__(self, store):
        self.store = store
        self.queue = queue.Queue()
        self.pending = set()
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name='archive-editor-index', daemon=True)
        self.thread.start()

    def schedule(self, record_id):
        with self.lock:
            if self.stopped.is_set() or record_id in self.pending: return
            self.pending.add(record_id)
            self.queue.put(record_id)

    def run(self):
        while not self.stopped.is_set():
            try: record_id = self.queue.get(timeout=0.2)
            except queue.Empty: continue
            with self.lock: self.pending.discard(record_id)
            try: self.store._index(record_id)
            except Exception: pass  # Pending writes can be retried through MCP.
            finally: self.queue.task_done()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)


def public_record(record):
    result = {key: value for key, value in record.items() if key not in ('file_path', 'memory_id', 'index_error')}
    # Use an existing managed entry's URL for the primary file when it is listed.
    # Historical primary files may be separate from subsequently added attachments.
    if record.get('file_path') and record.get('href') == '/api/files/' + quote(record.get('id', ''), safe=''):
        primary = next((item for item in record.get('attachments', []) if isinstance(item, dict)
                        and item.get('file_path') == record['file_path'] and item.get('href')), None)
        if primary: result['href'] = primary['href']
    if 'attachments' in result:
        result['attachments'] = [{key: item[key] for key in ('id', 'name', 'size', 'sha256', 'href') if key in item}
                                 for item in result['attachments'] if isinstance(item, dict)]
    return result


def attachment_filename(value):
    """Decode the browser header once, and accept one portable file basename."""
    if not value or re.search(r'%(?![0-9a-fA-F]{2})', value):
        raise ValueError('附件名称不正确。')
    name = unquote(value, errors='strict')
    if (not name or len(name.encode('utf-8')) > 240 or name in ('.', '..')
            or name[-1] in '. ' or any(ord(char) < 32 or ord(char) == 127 or char in '/\\<>:"|?*' for char in name)
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.IGNORECASE)):
        raise ValueError('附件名称不正确。')
    return name


def create_server(database, port=8768, host='127.0.0.1', resource_root=None,
                  allowed_hosts=('127.0.0.1', 'localhost'), record_store=None):
    device_owns_planner = os.environ.get('PLANNER_OWNER', 'pc') == 'device'
    database = Path(database).resolve()
    if record_store is not None and Path(record_store.db_path).resolve() != database:
        raise ValueError('Editor and viewer databases must match')
    catalog = CategoryCatalog(database)
    category_csrf = secrets.token_urlsafe(32)
    resource_root = Path(resource_root or database.parent.parent / 'resources').absolute()
    index_worker = None

    def read_rows():
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            return conn.execute('SELECT payload,revision,index_revision,index_error FROM personal_archive_records ORDER BY occurrence_date DESC,id').fetchall()

    def records():
        result = []
        for row in read_rows():
            record = public_record(json.loads(row['payload']))
            record['revision'] = row['revision']
            record['index_status'] = 'indexed' if row['revision'] == row['index_revision'] and not row['index_error'] else 'pending'
            result.append(record)
        return result

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def write_headers(self, length, kind, code=200, filename=None):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            if filename:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(filename))
                csp = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"
            else:
                csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            self.send_header('Content-Security-Policy', csp)
            self.end_headers()

        def respond(self, value, kind='application/json; charset=utf-8', code=200):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.write_headers(len(body), kind, code)
            if self.command != 'HEAD':
                self.wfile.write(body)

        def do_GET(self):
            if self.headers.get('Host', '').split(':')[0].lower() not in allowed_hosts:
                self.respond({'error': 'Invalid host'}, code=403)
                return
            path = urlsplit(self.path).path
            try:
                if path == '/api/records':
                    items = records()
                    self.respond({'mode': 'personal', 'engine': 'Mnemosyne', 'as_of': datetime.now(CHINA).date().isoformat(), 'records': items, 'categories': catalog.list(), 'pending_index': sum(x['index_status'] == 'pending' for x in items)})
                elif path == '/api/categories':
                    self.respond({'categories': catalog.list(), 'csrf': category_csrf})
                elif path == '/api/editor':
                    self.respond({'enabled': record_store is not None, 'csrf': category_csrf if record_store is not None else ''})
                elif path == '/api/dashboard':
                    count = len(read_rows())
                    self.respond({'database_ok': True, 'read_only': record_store is None, 'record_management': record_store is not None, 'category_management': os.access(database, os.W_OK) and os.access(database.parent, os.W_OK), 'native_counts': {'personal_archive_records': count}, 'source': json.loads((ROOT / 'SOURCE.json').read_text(encoding='utf-8'))})
                elif path == '/api/status':
                    items = records()
                    self.respond({'engine': 'Mnemosyne', 'read_only': record_store is None, 'records': len(items), 'pending_index': sum(x['index_status'] == 'pending' for x in items)})
                elif path.startswith('/api/files/'):
                    parts = path[len('/api/files/'):].split('/')
                    if not 1 <= len(parts) <= 2: raise FileNotFoundError()
                    record_id = unquote(parts[0])
                    try: file = _attachment_module.resolve_attachment(database, resource_root, record_id, unquote(parts[1]) if len(parts) == 2 else 'legacy')
                    except (ValueError, OSError, KeyError): raise FileNotFoundError() from None
                    with file.open('rb') as stream:
                        self.write_headers(os.fstat(stream.fileno()).st_size, mimetypes.guess_type(file.name)[0] or 'application/octet-stream', filename=file.name)
                        if self.command != 'HEAD':
                            while block := stream.read(65536):
                                self.wfile.write(block)
                else:
                    if path in ('/', '/index.html'):
                        file = ROOT / 'index.html'
                    elif path.startswith('/static/') and path[len('/static/'):] in ASSETS:
                        file = STATIC / path[len('/static/'):]
                    elif path.startswith('/static/fonts/') and path[len('/static/fonts/'):] in {p.name for p in (STATIC / 'fonts').glob('*.woff2')}:
                        file = STATIC / 'fonts' / path[len('/static/fonts/'):]
                    else:
                        raise FileNotFoundError()
                    kind = 'text/javascript' if file.suffix == '.mjs' else mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                    content = file.read_bytes()
                    if file.name == 'index.html' and device_owns_planner:
                        content = content.replace('<a href="/memory/planner/">计划</a>'.encode('utf-8'), b'')
                        content = content.replace('<a href="/memory/planner/"><!--i18n-->计划</a>'.encode('utf-8'), b'')
                    self.respond(content, kind + ('; charset=utf-8' if kind.startswith('text/') else ''))
            except (FileNotFoundError, KeyError):
                self.respond({'error': 'Not found'}, code=404)
            except (sqlite3.Error, json.JSONDecodeError):
                self.respond({'error': 'Memory database unavailable'}, code=503)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_HEAD(self):
            self.do_GET()

        def reject_write(self):
            self.close_connection = True
            self.respond({'error': 'Read-only viewer. Record information through your voice assistant.'}, code=405)

        def do_POST(self):
            path = urlsplit(self.path).path
            editing = path == '/api/records' and record_store is not None
            uploading = path == '/api/attachments' and record_store is not None
            if path != '/api/categories' and not editing and not uploading: return self.reject_write()
            try:
                host_header = self.headers.get('Host', '')
                origin = urlsplit(self.headers.get('Origin', ''))
                valid = (all(len(self.headers.get_all(name, [])) == 1 for name in ('Host', 'Origin', 'X-CSRF-Token'))
                    and urlsplit('//' + host_header).hostname in allowed_hosts
                    and origin.scheme in ('http', 'https') and origin.netloc == host_header
                    and self.headers.get('Sec-Fetch-Site') != 'cross-site'
                    and hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), category_csrf))
            except (ValueError, TypeError): valid = False
            if not valid:
                self.close_connection = True
                return self.respond({'error': '请刷新页面后重试。'}, code=403)
            if len(self.headers.get_all('Content-Length', [])) != 1 or self.headers.get_all('Transfer-Encoding'):
                self.close_connection = True
                return self.respond({'error': '请求长度不正确。'}, code=400)
            try: length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.close_connection = True
                return self.respond({'error': '请求长度不正确。'}, code=400)
            if not (0 <= length <= MAX_ATTACHMENT_BYTES if uploading else 0 < length <= (65536 if editing else 4096)):
                self.close_connection = True
                return self.respond({'error': '请求内容过大或为空。'}, code=413)
            if uploading: return self.upload_attachment(length)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.close_connection = True
                return self.respond({'error': '请使用 JSON 请求。'}, code=415)
            try:
                self.connection.settimeout(15)
                value = json.loads(self.rfile.read(length))
                if editing: return self.edit_record(value)
                shapes = {'create': {'action', 'label'}, 'rename': {'action', 'id', 'label'},
                          'reorder': {'action', 'order'}, 'delete': {'action', 'id'}}
                if not isinstance(value, dict) or not isinstance(value.get('action'), str) or set(value) != shapes.get(value['action']):
                    raise ValueError('分类操作不正确。')
                if 'id' in value and not isinstance(value['id'], str): raise ValueError('分类编号不正确。')
                action = value['action']
                if action == 'create': catalog.create(value['label'])
                elif action == 'rename': catalog.rename(value['id'], value['label'])
                elif action == 'reorder': catalog.reorder(value['order'])
                elif action == 'delete': catalog.delete(value['id'])
                self.respond({'categories': catalog.list()})
            except (json.JSONDecodeError, UnicodeError, RecursionError):
                self.respond({'error': '请求格式不正确。'}, code=400)
            except ValueError as error:
                self.respond({'error': str(error)}, code=400)
            except (sqlite3.Error, OSError):
                self.respond({'error': '分类未能保存，请稍后重试。'}, code=503)

        def upload_attachment(self, length):
            try:
                if len(self.headers.get_all('X-File-Name', [])) != 1: raise ValueError('附件名称不正确。')
                filename = attachment_filename(self.headers.get('X-File-Name'))
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True, strict_parsing=True)
                if set(query) != {'record_id', 'revision'} or any(len(value) != 1 for value in query.values()):
                    raise ValueError('附件请求不正确。')
                record_id = query['record_id'][0]
                if not 0 < len(record_id) <= 120 or not query['revision'][0].isascii() or not query['revision'][0].isdigit():
                    raise ValueError('记录版本不正确。')
                revision = int(query['revision'][0])
                if revision < 1: raise ValueError('记录版本不正确。')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/octet-stream':
                    self.close_connection = True
                    return self.respond({'error': '请使用文件上传请求。'}, code=415)
                # A total deadline and per-read timeout bound slow or incomplete uploads.
                deadline = time.monotonic() + 60
                # macOS exposes its system temp directory through /var ->
                # /private/var. Resolve that OS-owned base before creating our
                # private upload directory; user-supplied links remain rejected.
                with tempfile.TemporaryDirectory(prefix='evomyn-upload-', dir=Path(tempfile.gettempdir()).resolve()) as folder:
                    file = Path(folder) / filename
                    with file.open('xb') as stream:
                        remaining = length
                        while remaining:
                            budget = deadline - time.monotonic()
                            if budget <= 0: raise TimeoutError()
                            self.connection.settimeout(min(15, budget))
                            block = self.rfile.read1(min(65536, remaining))
                            if not block: raise TimeoutError()
                            stream.write(block)
                            remaining -= len(block)
                    record = record_store.add_attachments(record_id, [str(file)], expected_revision=revision, index=False)
                index_worker.schedule(record['id'])
                self.respond({'record': public_record(record)})
            except KeyError:
                self.close_connection = True
                self.respond({'error': '记录已被更新或删除，请刷新后重试。'}, code=409)
            except (ValueError, UnicodeError) as error:
                self.close_connection = True
                self.respond({'error': str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else '附件名称不正确。'}, code=409 if getattr(error, 'status_code', None) == 409 else 400)
            except TimeoutError:
                self.close_connection = True
                self.respond({'error': '附件上传超时，请重试。'}, code=408)
            except Exception:
                self.close_connection = True
                self.respond({'error': '附件未能保存，请稍后重试。'}, code=503)

        def edit_record(self, value):
            try:
                shapes = {'create': {'action', 'record'}, 'update': {'action', 'id', 'revision', 'changes'},
                          'delete': {'action', 'id', 'revision'}}
                if not isinstance(value, dict) or not isinstance(value.get('action'), str) or set(value) != shapes.get(value['action']):
                    raise ValueError('记忆操作不正确。')
                action = value['action']
                if action != 'create':
                    if not isinstance(value['id'], str) or not 0 < len(value['id']) <= 120:
                        raise ValueError('记录编号不正确。')
                    if type(value['revision']) is not int or value['revision'] < 1:
                        raise ValueError('记录版本不正确。')
                if action == 'delete':
                    result = record_store.delete(value['id'], expected_revision=value['revision'])
                    for record_id in result['updated_links']: index_worker.schedule(record_id)
                    return self.respond({'deleted': result['deleted']})
                fields = value['record'] if action == 'create' else value['changes']
                allowed = {'category', 'title', 'body', 'date', 'date_end', 'tags', 'href'}
                if not isinstance(fields, dict) or not fields or not set(fields) <= allowed:
                    raise ValueError('只能编辑分类、标题、正文、时间、标签和链接。')
                for key in ('category', 'title', 'body', 'date', 'date_end', 'href'):
                    if key in fields and (not isinstance(fields[key], str) or '\x00' in fields[key]):
                        raise ValueError('文字字段格式不正确。')
                if 'tags' in fields and (not isinstance(fields['tags'], list) or any(not isinstance(item, str) for item in fields['tags'])):
                    raise ValueError('标签必须是字符串数组。')
                if action == 'create':
                    record = record_store.save(fields, expected_revision=0, index=False)
                else:
                    record = record_store.update(value['id'], fields, expected_revision=value['revision'], index=False)
                index_worker.schedule(record['id'])
                self.respond({'record': public_record(record)})
            except KeyError:
                self.respond({'error': '记录已被更新或删除，请刷新后重试。'}, code=409)
            except ValueError as error:
                self.respond({'error': str(error)}, code=409 if getattr(error, 'status_code', None) == 409 else 400)
            except Exception:
                self.respond({'error': '记忆未能保存，请稍后重试。'}, code=503)

        do_PUT = do_PATCH = do_DELETE = reject_write

    class Server(ThreadingHTTPServer):
        def server_close(self):
            super().server_close()
            if index_worker is not None: index_worker.close()

    server = Server((host, port), Handler)
    if record_store is not None: index_worker = IndexWorker(record_store)
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default=os.environ.get('ARCHIVE_DATABASE', '/state/data/mnemosyne.db'))
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    server = create_server(args.database, host=args.host, port=args.port)
    print('Personal memory viewer ready (read-only)', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
