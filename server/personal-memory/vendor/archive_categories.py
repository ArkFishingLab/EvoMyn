"""Model-free, durable memory category catalog shared by MCP and the dashboard."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import unicodedata
from uuid import uuid4

from filelock import FileLock

DEFAULT_CATEGORIES = {
    'background': ('个人', '关于自己、履历与个人积累'),
    'people': ('人脉', '认识的人，以及一起经历的事'),
    'journal': ('日志', '按日回看，留住事情的经过'),
    'resource': ('资料', '与人物、经历和事件关联的文件'),
}
LEGACY_DEFAULTS = [('people', '人脉'), ('journal', '日志'), ('background', '个人'),
                   ('event', '事件'), ('resource', '资料')]
MIGRATION = 'personal-first-four-defaults-v1'
TABLE = 'personal_archive_categories'


def label_value(value):
    if not isinstance(value, str): raise ValueError('请输入分类名称。')
    if any(unicodedata.category(char).startswith('C') for char in value):
        raise ValueError('分类名称不能包含换行或控制字符。')
    value = unicodedata.normalize('NFKC', value).strip()
    if not 1 <= len(value) <= 24: raise ValueError('分类名称需要 1～24 个字符。')
    return value


class CategoryCatalog:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.lock = FileLock(str(self.database.parent / 'archive.lock'), timeout=60)

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(self.database.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            if write: conn.commit()
        finally:
            conn.close()

    @staticmethod
    def exists(conn):
        return conn.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', TABLE)).fetchone() is not None

    def initialize(self):
        with self.lock, self.connection(write=True) as conn:
            self._initialize(conn)

    def _initialize(self, conn):
        if not self.exists(conn):
            conn.execute('''CREATE TABLE personal_archive_categories (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, label_key TEXT NOT NULL UNIQUE,
                position INTEGER NOT NULL)''')
            conn.executemany('INSERT INTO personal_archive_categories VALUES(?,?,?,?)',
                [(key, label, label.casefold(), index) for index, (key, (label, _)) in enumerate(DEFAULT_CATEGORIES.items())])
        conn.execute('CREATE TABLE IF NOT EXISTS personal_archive_category_migrations (id TEXT PRIMARY KEY)')
        if not conn.execute('SELECT 1 FROM personal_archive_category_migrations WHERE id=?', (MIGRATION,)).fetchone():
            rows = conn.execute('SELECT id,label,position FROM personal_archive_categories ORDER BY position,id').fetchall()
            untouched = [(row['id'], row['label'], row['position']) for row in rows] == [
                (key, label, index) for index, (key, label) in enumerate(LEGACY_DEFAULTS)]
            if untouched and 'event' not in self._counts(conn):
                conn.execute('DELETE FROM personal_archive_categories WHERE id=?', ('event',))
            if untouched:
                order = [*DEFAULT_CATEGORIES, 'event']
                conn.executemany('UPDATE personal_archive_categories SET position=? WHERE id=?', enumerate(order))
            conn.execute('INSERT INTO personal_archive_category_migrations VALUES (?)', (MIGRATION,))
        # Pre-catalog databases (and historical imports) may contain categories
        # absent from the catalog. Register them without rewriting any payload.
        existing = {row['id'] for row in conn.execute('SELECT id FROM personal_archive_categories')}
        for entry in self._entries(conn):
            if entry['id'] not in existing:
                conn.execute('INSERT INTO personal_archive_categories VALUES(?,?,?,(SELECT COALESCE(MAX(position),-1)+1 FROM personal_archive_categories))',
                    (entry['id'], entry['label'], entry['label'].casefold()))

    @staticmethod
    def _counts(conn):
        counts = {}
        for row in conn.execute('SELECT payload FROM personal_archive_records'):
            key = json.loads(row['payload']).get('category')
            if isinstance(key, str) and key: counts[key] = counts.get(key, 0) + 1
        return counts

    def _entries(self, conn, counts=None):
        entries = ([dict(row) for row in conn.execute('SELECT id,label FROM personal_archive_categories ORDER BY position,id')]
            if self.exists(conn) else [{'id': key, 'label': value[0]} for key, value in DEFAULT_CATEGORIES.items()])
        keys = {entry['id'] for entry in entries}
        labels = {entry['label'].casefold() for entry in entries}
        for key in sorted(self._counts(conn) if counts is None else counts):
            if key in keys: continue
            base = dict(LEGACY_DEFAULTS).get(key, key)
            label, suffix = base, 2
            while label.casefold() in labels:
                label = f'{base} ({suffix})'
                suffix += 1
            entries.append({'id': key, 'label': label})
            labels.add(label.casefold())
        return entries

    def list(self):
        with self.connection() as conn:
            counts = self._counts(conn)
            entries = self._entries(conn, counts)
        return [{**entry, 'builtin': entry['id'] in DEFAULT_CATEGORIES,
                 'subtitle': DEFAULT_CATEGORIES.get(entry['id'], ('', '此分类下的记忆'))[1],
                 'count': counts.get(entry['id'], 0)} for entry in entries]

    def labels(self):
        with self.connection() as conn:
            return {row['id']: row['label'] for row in self._entries(conn)}

    def create(self, label):
        label = label_value(label)
        key = 'custom-' + uuid4().hex[:16]
        with self.lock, self.connection(write=True) as conn:
            self._initialize(conn)
            if conn.execute('SELECT COUNT(*) FROM personal_archive_categories').fetchone()[0] >= 32:
                raise ValueError('最多可设置 32 个分类。')
            try:
                conn.execute('INSERT INTO personal_archive_categories VALUES(?,?,?,(SELECT COALESCE(MAX(position),-1)+1 FROM personal_archive_categories))',
                    (key, label, label.casefold()))
            except sqlite3.IntegrityError:
                raise ValueError('已有同名分类，请换个名称。') from None
        return {'id': key, 'label': label, 'builtin': False,
                'subtitle': '此分类下的记忆', 'count': 0}

    def rename(self, key, label):
        label = label_value(label)
        with self.lock, self.connection(write=True) as conn:
            self._initialize(conn)
            try:
                result = conn.execute('UPDATE personal_archive_categories SET label=?,label_key=? WHERE id=?', (label, label.casefold(), key))
            except sqlite3.IntegrityError:
                raise ValueError('已有同名分类，请换个名称。') from None
            if result.rowcount != 1: raise ValueError('分类不存在，请刷新后重试。')

    def reorder(self, order):
        if not isinstance(order, list) or any(not isinstance(key, str) for key in order):
            raise ValueError('分类顺序不正确，请刷新后重试。')
        with self.lock, self.connection(write=True) as conn:
            self._initialize(conn)
            keys = {row[0] for row in conn.execute('SELECT id FROM personal_archive_categories')}
            if len(order) != len(keys) or set(order) != keys:
                raise ValueError('分类已发生变化，请刷新后重试。')
            conn.executemany('UPDATE personal_archive_categories SET position=? WHERE id=?', enumerate(order))

    def delete(self, key):
        with self.lock, self.connection(write=True) as conn:
            self._initialize(conn)
            if key in DEFAULT_CATEGORIES: raise ValueError('默认分类可改名和排序，不能删除。')
            if not conn.execute('SELECT 1 FROM personal_archive_categories WHERE id=?', (key,)).fetchone():
                raise ValueError('分类不存在，请刷新后重试。')
            if any(json.loads(row['payload']).get('category') == key for row in conn.execute('SELECT payload FROM personal_archive_records')):
                raise ValueError('此分类还有记忆，不能删除。')
            conn.execute('DELETE FROM personal_archive_categories WHERE id=?', (key,))
