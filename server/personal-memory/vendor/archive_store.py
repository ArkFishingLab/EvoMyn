"""Durable categorized records in the same database as native Mnemosyne memories."""
import json
import sqlite3
import re
from calendar import monthrange
from contextlib import contextmanager, closing
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from runtime import ROOT, DATA_DIR, MODEL
from filelock import FileLock
from mnemosyne import Mnemosyne
from archive_categories import CategoryCatalog, DEFAULT_CATEGORIES
from attachment_files import import_attachment, cleanup_imports, resolve_attachment

CATEGORIES = {key: value[0] for key, value in DEFAULT_CATEGORIES.items()}
CHINA = timezone(timedelta(hours=8))

class ArchiveConflict(ValueError):
    """The caller's record snapshot is no longer current."""
    status_code = 409

def now():
    return datetime.now(CHINA).isoformat(timespec='seconds')

def date_bounds(value):
    """Bounds are for matching only; the user's original precision stays in date."""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}(?:-[0-9]{2}){0,2}', value):
        raise ValueError('发生时间需要 YYYY、YYYY-MM 或 YYYY-MM-DD。')
    parts = [int(part) for part in value.split('-')]
    year = parts[0]
    if len(parts) == 1:
        return date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
    month = parts[1]
    if len(parts) == 2:
        return date(year, month, 1).isoformat(), date(year, month, monthrange(year, month)[1]).isoformat()
    exact = date(*parts).isoformat()
    return exact, exact

def period_bounds(record):
    start, end = record.get('date', ''), record.get('date_end', '')
    if not start:
        if end: raise ValueError('时间段需要开始时间。')
        return None
    lower, upper = date_bounds(start)
    if end:
        upper = now()[:10] if end == 'ongoing' else date_bounds(end)[1]
    if upper < lower: raise ValueError('结束时间早于开始时间。')
    return lower, upper

class ArchiveStore:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.db_path = self.root / 'data' / 'mnemosyne.db'
        self.resources = self.root / 'resources'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.db_path.parent / 'archive.lock'), timeout=60)
        self.index_lock = FileLock(str(self.db_path.parent / 'archive-index.lock'), timeout=60)
        self.mem = Mnemosyne(db_path=self.db_path, session_id='personal-archive', author_type='human')
        with self.connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS personal_archive_records (
                    id TEXT PRIMARY KEY, category TEXT NOT NULL, occurrence_date TEXT NOT NULL,
                    payload TEXT NOT NULL, revision INTEGER NOT NULL,
                    memory_id TEXT, index_revision INTEGER NOT NULL DEFAULT 0,
                    index_error TEXT, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS personal_archive_category_date
                    ON personal_archive_records(category, occurrence_date);
                CREATE TABLE IF NOT EXISTS personal_archive_history (
                    record_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    changed_at TEXT NOT NULL, PRIMARY KEY(record_id, revision)
                );
                CREATE TABLE IF NOT EXISTS personal_archive_tombstones (
                    id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL, event_digest TEXT
                );
            ''')
        self.categories = CategoryCatalog(self.db_path)
        self.categories.initialize()

    @contextmanager
    def connection(self, readonly=False):
        if readonly:
            conn = sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=30)
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            if not readonly: conn.commit()
        finally: conn.close()

    def normalize(self, value):
        if not isinstance(value, dict): raise ValueError('记录必须是一个对象。')
        record = {key: value[key] for key in ('id', 'category', 'title', 'body', 'date', 'date_end', 'fields', 'tags', 'links', 'steps', 'href', 'file_path', 'attachments') if key in value}
        if not isinstance(record.get('category'), str) or record['category'] not in self.categories.labels():
            raise ValueError('分类不存在，请先通过 archive_status 查看可用分类编号。')
        for key in ('title', 'body'):
            if not isinstance(record.get(key), str) or not record[key].strip(): raise ValueError(f'{key} 不能为空。')
        record.setdefault('id', f"{record['category']}-{uuid4().hex[:12]}")
        if not isinstance(record['id'], str) or not record['id'] or len(record['id']) > 120: raise ValueError('记录编号不正确。')
        record.setdefault('date', '')
        record.setdefault('fields', {})
        record.setdefault('tags', [])
        record.setdefault('links', [])
        if not isinstance(record['date'], str) or ('date_end' in record and not isinstance(record['date_end'], str)):
            raise ValueError('时间必须是字符串，未知时间使用空字符串。')
        period_bounds(record)
        if not isinstance(record['fields'], dict): raise ValueError('fields 必须是一个对象。')
        for key in ('tags', 'links'):
            if not isinstance(record[key], list) or any(not isinstance(item, str) for item in record[key]): raise ValueError(f'{key} 必须是字符串数组。')
        record['links'] = list(dict.fromkeys(record['links']))
        for linked_id in record['links']:
            if linked_id == record['id']: raise ValueError('不能关联记录自身。')
            try: self.get(linked_id)
            except KeyError: raise ValueError(f'关联记录不存在：{linked_id}')
        if 'steps' in record and (not isinstance(record['steps'], list) or any(not isinstance(step, dict) or not isinstance(step.get('text'), str) or not isinstance(step.get('done'), bool) for step in record['steps'])): raise ValueError('steps 需要 text 字符串与 done 布尔值。')
        if record.get('file_path'):
            if not isinstance(record['file_path'], str): raise ValueError('file_path 必须是字符串。')
            from urllib.parse import quote
            record['href'] = '/api/files/' + quote(record['id'], safe='')
        elif record.get('href'):
            from urllib.parse import urlsplit
            parsed = urlsplit(record['href'])
            if parsed.scheme not in ('http', 'https') or not parsed.netloc: raise ValueError('资料链接需要 HTTP(S) 地址，或使用 file_path 登记本地文件。')
        return record

    def save(self, value, expected_revision=None, *, index=True):
        return self._save(value, expected_revision, index=index)

    def add_attachments(self, record_id, file_paths, expected_revision=None, *, index=True):
        if not isinstance(file_paths, list) or not 1 <= len(file_paths) <= 20 or any(not isinstance(path, str) or not path for path in file_paths):
            raise ValueError('file_paths 需要 1～20 个文件路径。')
        with self.lock:
            record = self.get(record_id)
            result = self._save(record, record['revision'] if expected_revision is None else expected_revision,
                                index=False, import_paths=file_paths)
        if index:
            self._index(record_id)
            return self.get(record_id)
        return result

    def _save(self, value, expected_revision=None, *, index=True, import_paths=()):
        imported = []
        try:
            result = self._save_transaction(value, expected_revision, imported, import_paths)
        except BaseException:
            cleanup_imports(imported)
            raise
        if index:
            self._index(result['id'])
        return self.get(result['id'])

    def _save_transaction(self, value, expected_revision, imported, import_paths):
        with self.lock:
            record = self.normalize(value)
            stamp = now()
            with self.connection() as conn:
                if conn.execute('SELECT 1 FROM personal_archive_tombstones WHERE id=?', (record['id'],)).fetchone():
                    raise ArchiveConflict('记录已被删除，请刷新后重试。')
                previous = conn.execute('SELECT * FROM personal_archive_records WHERE id=?', (record['id'],)).fetchone()
                if expected_revision is not None and (previous['revision'] if previous else 0) != expected_revision: raise ArchiveConflict('记录已被更新，请重新读取后再修改。')
                original = json.loads(previous['payload']) if previous else {}
                attachments = original.get('attachments', [])
                if 'attachments' in record and record['attachments'] != attachments:
                    raise ValueError('附件元数据不能直接修改；请使用 archive_attach 添加附件。')
                record['attachments'] = list(attachments)
                if record.get('file_path'):
                    unchanged = (record['file_path'] == original.get('file_path') and
                                 Path(record['file_path']).is_relative_to(self.resources))
                    if not unchanged:
                        entry = import_attachment(record['file_path'], self.db_path, self.resources, record['id'])
                        imported.append(entry)
                        record['attachments'].append(entry)
                        record['file_path'] = entry['file_path']
                for path in import_paths:
                    entry = import_attachment(path, self.db_path, self.resources, record['id'])
                    imported.append(entry)
                    record['attachments'].append(entry)
                revision = previous['revision'] + 1 if previous else 1
                record['created_at'] = json.loads(previous['payload'])['created_at'] if previous else stamp
                record['updated_at'] = stamp
                record['revision'] = revision
                payload = json.dumps(record, ensure_ascii=False)
                conn.execute('''INSERT INTO personal_archive_records (id,category,occurrence_date,payload,revision,updated_at)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,category=excluded.category,
                    occurrence_date=excluded.occurrence_date,revision=excluded.revision,updated_at=excluded.updated_at''',
                    (record['id'], record['category'], record['date'], payload, revision, stamp))
                conn.execute('INSERT INTO personal_archive_history VALUES (?,?,?,?)', (record['id'], revision, payload, stamp))
        return record

    def _index(self, record_id):
        # The expensive model call does not hold the archive write lock. A
        # revision check below prevents a completed old job indexing newer text.
        with self.index_lock:
            self._index_current(record_id)

    def _invalidate(self, memory_id, replacement_id=None):
        if not memory_id: return
        try:
            # Mnemosyne owns shared SQLite connections. Do not race its worker
            # or make deletion wait for a slow embedding/model download.
            with self.index_lock.acquire(timeout=0):
                if replacement_id: self.mem.invalidate(memory_id, replacement_id=replacement_id)
                else: self.mem.invalidate(memory_id)
        except Exception:
            # Archive search only exposes current, indexed, active records.
            # Native invalidation is best effort; it is not secure erasure.
            pass

    def _index_current(self, record_id):
        try: record = self.get(record_id)
        except KeyError: return
        old_memory_id = record.get('memory_id')
        text = '\n'.join([
            f"记录编号：{record['id']}；版本：{record['revision']}",
            f"类别：{self.categories.labels().get(record['category'], record['category'])}；发生时间：{record['date']}" + (f" ~ {'至今' if record['date_end'] == 'ongoing' else record['date_end']}" if record.get('date_end') else ''),
            record['title'], record['body'],
            *[f'{key}：{value}' for key, value in record['fields'].items()],
            '标签：' + '、'.join(record['tags']),
            '关联：' + '、'.join(record['links']),
        ])
        try:
            memory_id = self.mem.remember(text, source='personal-archive', scope='global', importance=0.8,
                metadata={'archive_id': record_id, 'topic': record['category'], 'revision': record['revision']}, veracity='stated')
            if not memory_id: raise ValueError('Mnemosyne 拒绝索引此记录；原始记录已保留。')
            with self.lock, self.connection() as conn:
                changed = conn.execute('UPDATE personal_archive_records SET memory_id=?,index_revision=?,index_error=NULL WHERE id=? AND revision=?', (memory_id, record['revision'], record_id, record['revision'])).rowcount
            if not changed:
                self._invalidate(memory_id)
                return
            if old_memory_id and old_memory_id != memory_id:
                self._invalidate(old_memory_id, replacement_id=memory_id)
        except Exception as error:
            with self.lock, self.connection() as conn:
                conn.execute('UPDATE personal_archive_records SET index_error=? WHERE id=? AND revision=?', (str(error)[:500], record_id, record['revision']))

    def retry_index(self):
        with self.connection(readonly=True) as conn:
            ids = [row['id'] for row in conn.execute('SELECT id FROM personal_archive_records WHERE index_revision<revision OR index_error IS NOT NULL')]
        for record_id in ids: self._index(record_id)
        return self.status()

    def get(self, record_id):
        with self.connection(readonly=True) as conn:
            row = conn.execute('SELECT * FROM personal_archive_records WHERE id=?', (record_id,)).fetchone()
        if not row: raise KeyError(record_id)
        record = json.loads(row['payload'])
        record['memory_id'] = row['memory_id']
        record['index_status'] = 'indexed' if row['index_revision'] == row['revision'] and not row['index_error'] else 'pending'
        if row['index_error']: record['index_error'] = row['index_error']
        return record

    def list(self, category=None, from_date=None, to_date=None, query=None, status=None):
        where, params = [], []
        if category:
            if category not in self.categories.labels(): raise ValueError('未知类别。')
            where.append('category=?'); params.append(category)
        for name, value in [('开始日期', from_date), ('结束日期', to_date)]:
            if value:
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
                    raise ValueError(f'{name}需要 YYYY-MM-DD。')
                try: date.fromisoformat(value)
                except ValueError: raise ValueError(f'{name}无效。')
        if from_date and to_date and from_date > to_date: raise ValueError('开始日期晚于结束日期。')
        sql = 'SELECT id FROM personal_archive_records' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY occurrence_date DESC,id'
        with self.connection(readonly=True) as conn: ids = [row['id'] for row in conn.execute(sql, params)]
        records = []
        for record_id in ids:
            try: records.append(self.get(record_id))
            except KeyError: pass  # A concurrent deletion is absent from this view.
        if from_date or to_date:
            records = [record for record in records if (bounds := period_bounds(record)) and
                       (not from_date or bounds[1] >= from_date) and (not to_date or bounds[0] <= to_date)]
        records.sort(key=lambda record: record['id'])
        records.sort(key=lambda record: (period_bounds(record) or ('', ''))[0], reverse=True)
        if status: records = [record for record in records if record['fields'].get('状态') == status]
        if query:
            term = query.strip().lower()
            records = [record for record in records if term in '\n'.join([record['title'], record['body'], *map(str, record['fields'].values()), *record['tags']]).lower()]
        return records

    def update(self, record_id, changes, expected_revision=None, *, index=True):
        record = self.get(record_id)
        if not isinstance(changes, dict) or any(key in changes for key in ('id', 'created_at', 'revision', 'memory_id')): raise ValueError('修改字段不正确。')
        return self.save({**record, **changes}, expected_revision=record['revision'] if expected_revision is None else expected_revision, index=index)

    def tombstone(self, record_id):
        with self.connection(readonly=True) as conn:
            row = conn.execute('SELECT id,deleted_at,event_digest FROM personal_archive_tombstones WHERE id=?', (record_id,)).fetchone()
        return dict(row) if row else None

    def delete(self, record_id, expected_revision):
        """Remove active content/history; retain only a replay-prevention marker."""
        updated = []
        with self.lock, self.connection() as conn:
            row = conn.execute('SELECT * FROM personal_archive_records WHERE id=?', (record_id,)).fetchone()
            if not row or row['revision'] != expected_revision:
                raise ArchiveConflict('记录已被更新或删除，请刷新后重试。')
            original = conn.execute('SELECT payload FROM personal_archive_history WHERE record_id=? AND revision=1', (record_id,)).fetchone()
            digest = json.loads(original['payload']).get('fields', {}).get('event_payload_sha256') if original else None
            if not record_id.startswith('device-journal-') or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest): digest = None
            stamp = now()
            conn.execute('INSERT INTO personal_archive_tombstones VALUES (?,?,?)', (record_id, stamp, digest))
            conn.execute('DELETE FROM personal_archive_history WHERE record_id=?', (record_id,))
            conn.execute('DELETE FROM personal_archive_records WHERE id=?', (record_id,))
            for linked in conn.execute('SELECT id,payload,revision FROM personal_archive_records').fetchall():
                value = json.loads(linked['payload'])
                if record_id not in value.get('links', []): continue
                value['links'] = [item for item in value['links'] if item != record_id]
                value['revision'] = linked['revision'] + 1
                value['updated_at'] = stamp
                payload = json.dumps(value, ensure_ascii=False)
                conn.execute('UPDATE personal_archive_records SET payload=?,revision=?,updated_at=? WHERE id=?', (payload, value['revision'], stamp, linked['id']))
                conn.execute('INSERT INTO personal_archive_history VALUES (?,?,?,?)', (linked['id'], value['revision'], payload, stamp))
                updated.append(linked['id'])
        self._invalidate(row['memory_id'])
        return {'deleted': record_id, 'updated_links': updated}

    def history(self, record_id):
        with self.connection(readonly=True) as conn:
            return [json.loads(row['payload']) for row in conn.execute('SELECT payload FROM personal_archive_history WHERE record_id=? ORDER BY revision', (record_id,))]

    def search(self, query, top_k=10):
        if not query.strip(): return []
        if not 1 <= top_k <= 50: raise ValueError('top_k 必须在 1～50 之间。')
        matches = self.mem.recall(query, top_k=min(100, max(20, top_k * 4)), source='personal-archive')
        records = self.list()
        by_memory = {record['memory_id']: record for record in records if record['index_status'] == 'indexed'}
        hits = []
        for match in matches:
            record = by_memory.get(match['id'])
            if record and not any(hit['id'] == record['id'] for hit in hits):
                hits.append({**record, 'score': match.get('score'), 'retrieval': 'mnemosyne'})
        for record in self.list(query=query):
            if not any(hit['id'] == record['id'] for hit in hits): hits.append({**record, 'retrieval': 'keyword'})
        return hits[:top_k]

    def attachment(self, record_id, attachment_id='legacy'):
        return resolve_attachment(self.db_path, self.resources, record_id, attachment_id)

    def status(self):
        import importlib.metadata
        with self.connection(readonly=True) as conn:
            total = conn.execute('SELECT COUNT(*) FROM personal_archive_records').fetchone()[0]
            pending = conn.execute('SELECT COUNT(*) FROM personal_archive_records WHERE index_revision<revision OR index_error IS NOT NULL').fetchone()[0]
        return {'engine': 'Mnemosyne', 'version': importlib.metadata.version('mnemosyne-memory'), 'records': total, 'pending_index': pending, 'embedding_model': MODEL, 'database': str(self.db_path), 'categories': self.categories.list()}

    def backup(self):
        target = self.root / 'backups' / (datetime.now(CHINA).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6] + '.db')
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.connection(readonly=True) as source, closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
        return target
