import concurrent.futures
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
from test_device_archive import isolated_store


class ArchiveCategoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_store(self.tmp.name)

    def catalog(self):
        from archive_categories import CategoryCatalog
        return CategoryCatalog(self.store.db_path)

    def legacy_catalog(self, *, labels=None, order=None):
        entries = [('people', '人脉'), ('journal', '日志'), ('background', '个人'),
                   ('event', '事件'), ('resource', '资料')]
        labels = labels or {}
        order = order or [key for key, _ in entries]
        with self.store.connection() as conn:
            conn.execute('DROP TABLE IF EXISTS personal_archive_category_migrations')
            conn.execute('DELETE FROM personal_archive_categories')
            conn.executemany('INSERT INTO personal_archive_categories VALUES (?,?,?,?)',
                [(key, labels.get(key, label), labels.get(key, label).casefold(), order.index(key))
                 for key, label in entries])

    def test_fresh_defaults_have_four_categories_in_personal_first_order(self):
        entries = self.catalog().list()
        self.assertEqual([item['id'] for item in entries], ['background', 'people', 'journal', 'resource'])
        self.assertEqual([item['label'] for item in entries], ['个人', '人脉', '日志', '资料'])
        self.assertTrue(all(item['builtin'] for item in entries))

    def test_untouched_legacy_catalog_migrates_once_without_changing_records(self):
        self.legacy_catalog()
        record = self.store.save(dict(category='background', title='履历', body='旧内容'))
        before, history = self.store.get(record['id']), self.store.history(record['id'])
        self.store = isolated_store(self.tmp.name)
        self.assertEqual([x['id'] for x in self.catalog().list()], ['background', 'people', 'journal', 'resource'])
        self.assertEqual(self.store.get(record['id']), before)
        self.assertEqual(self.store.history(record['id']), history)
        order = ['people', 'journal', 'background', 'resource']
        self.catalog().reorder(order)
        self.store = isolated_store(self.tmp.name)
        self.assertEqual([x['id'] for x in self.catalog().list()], order)

    def test_renamed_or_reordered_legacy_defaults_keep_user_order(self):
        for labels, order in [({'people': '朋友'}, ['people', 'journal', 'background', 'event', 'resource']),
                              ({}, ['resource', 'event', 'background', 'journal', 'people']),
                              ({}, ['journal', 'people', 'background', 'event', 'resource'])]:
            with self.subTest(labels=labels, order=order):
                self.legacy_catalog(labels=labels, order=order)
                self.store = isolated_store(self.tmp.name)
                entries = self.catalog().list()
                actual = [x['id'] for x in entries]
                self.assertEqual(actual, order)
                self.assertEqual(next(x['label'] for x in entries if x['id'] == 'people'), labels.get('people', '人脉'))

    def test_occupied_legacy_event_becomes_deletable_only_when_empty(self):
        self.legacy_catalog()
        record = self.store.save(dict(category='event', title='旧事件', body='保留正文'))
        before, history = self.store.get(record['id']), self.store.history(record['id'])
        self.store = isolated_store(self.tmp.name)
        entries = self.catalog().list()
        self.assertEqual([x['id'] for x in entries], ['background', 'people', 'journal', 'resource', 'event'])
        self.assertFalse(next(x for x in entries if x['id'] == 'event')['builtin'])
        self.assertEqual(self.store.get(record['id']), before)
        self.assertEqual(self.store.history(record['id']), history)
        with self.assertRaises(ValueError): self.catalog().delete('event')
        self.store.delete(record['id'], 1)
        self.catalog().delete('event')
        self.assertNotIn('event', self.catalog().labels())

    def test_empty_renamed_event_is_preserved_as_regular_category(self):
        self.legacy_catalog(labels={'event': '项目'})
        self.store = isolated_store(self.tmp.name)
        event = next(x for x in self.catalog().list() if x['id'] == 'event')
        self.assertEqual(event['label'], '项目')
        self.assertFalse(event['builtin'])
        self.catalog().delete('event')

    def test_pre_catalog_records_keep_event_and_unknown_categories_editable(self):
        self.legacy_catalog()
        event = self.store.save(dict(category='event', title='旧事件', body='原始内容'))
        other = self.catalog().create('旧分类')
        unknown = self.store.save(dict(category=other['id'], title='旧记忆', body='保留内容'))
        with self.store.connection() as conn:
            conn.execute('DROP TABLE personal_archive_categories')
        # Reading a pre-catalog database must not hide historical categories.
        self.assertEqual(self.catalog().labels()['event'], '事件')
        self.assertIn(other['id'], self.catalog().labels())
        self.assertEqual(next(x for x in self.catalog().list() if x['id'] == 'event')['count'], 1)
        self.store = isolated_store(self.tmp.name)
        self.assertEqual(self.store.update(event['id'], {'body': '补充'})['revision'], 2)
        self.assertEqual(self.store.update(unknown['id'], {'body': '补充'})['revision'], 2)

    def test_default_personal_label_keeps_legacy_record_unchanged(self):
        record = self.store.save(dict(category='background', title='履历', body='用户提供的事实'))
        before = self.store.get(record['id'])
        # Simulate a pre-catalog database without touching any record payload.
        with self.store.connection() as conn:
            conn.execute('DROP TABLE personal_archive_categories')
        self.store = isolated_store(self.tmp.name)
        entries = self.catalog().list()
        self.assertEqual([item['label'] for item in entries], ['个人', '人脉', '日志', '资料'])
        self.assertEqual(next(x for x in entries if x['id'] == 'background')['count'], 1)
        self.assertEqual(isolated_store(self.tmp.name).get(record['id']), before)

    def test_custom_category_persists_and_accepts_archive_writes_and_updates(self):
        item = self.catalog().create('读书')
        record = self.store.save(dict(category=item['id'], title='阅读笔记', body='内容'))
        again = isolated_store(self.tmp.name)
        self.assertEqual(again.list(category=item['id'])[0]['id'], record['id'])
        self.assertEqual(again.update(record['id'], {'body': '补充内容'})['revision'], 2)
        with patch('importlib.metadata.version', return_value='isolated-test'):
            self.assertEqual(next(x for x in again.status()['categories'] if x['id'] == item['id'])['label'], '读书')
        with self.assertRaises(ValueError):
            again.save(dict(category='not-registered', title='未知', body='不能直接使用'))

    def test_rename_and_order_do_not_rewrite_records_or_history(self):
        record = self.store.save(dict(category='background', title='个人资料', body='正文'))
        catalog = self.catalog()
        catalog.rename('background', '关于我')
        order = [x['id'] for x in catalog.list()][::-1]
        catalog.reorder(order)
        self.assertEqual([x['id'] for x in self.catalog().list()], order)
        self.assertEqual(next(x for x in self.catalog().list() if x['id'] == 'background')['label'], '关于我')
        self.assertEqual(self.store.get(record['id'])['revision'], 1)
        self.assertEqual(len(self.store.history(record['id'])), 1)

    def test_delete_protects_records_defaults_and_unknown_ids(self):
        catalog = self.catalog()
        empty = catalog.create('空分类')
        catalog.delete(empty['id'])
        self.assertNotIn(empty['id'], [x['id'] for x in self.catalog().list()])
        with self.assertRaises(ValueError):
            self.store.save(dict(category=empty['id'], title='已删除', body='正文'))
        used = catalog.create('已有记忆')
        record = self.store.save(dict(category=used['id'], title='保留', body='正文'))
        with self.assertRaises(ValueError): catalog.delete(used['id'])
        with self.assertRaises(ValueError): catalog.delete('journal')
        with self.assertRaises(ValueError): catalog.delete('unknown')
        self.assertEqual(self.store.get(record['id'])['body'], '正文')

    def test_name_validation_permutation_validation_and_concurrent_duplicates(self):
        catalog = self.catalog()
        for label in ['', '  ', '人脉', 'a' * 25, 'bad\nname', ['not a name']]:
            with self.subTest(label=label), self.assertRaises(ValueError): catalog.create(label)
        item = catalog.create(' Work ')
        self.assertEqual(item['label'], 'Work')
        with self.assertRaises(ValueError): catalog.create('ｗｏｒｋ')
        with self.assertRaises(ValueError): catalog.rename(item['id'], '资料')
        with self.assertRaises(ValueError): catalog.reorder(['journal'])
        with self.assertRaises(ValueError): catalog.reorder([x['id'] for x in catalog.list()] * 2)
        def attempt(_):
            try: return self.catalog().create('并发分类')['id']
            except ValueError: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(sum(value is not None for value in pool.map(attempt, range(3))), 1)

    def test_catalog_is_in_sqlite_backup_and_refresh_is_model_free(self):
        item = self.catalog().create('项目')
        backup = self.store.backup()
        from archive_categories import CategoryCatalog
        self.assertEqual(next(x for x in CategoryCatalog(backup).list() if x['id'] == item['id'])['label'], '项目')


if __name__ == '__main__': unittest.main()
