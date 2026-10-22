import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../static/personal-model.mjs';
const { selectRecords, relatedRecords, summarize, safeResourceUrl } = model;

test('category catalog uses renamed personal default and preserves custom and legacy records', () => {
  assert.equal(model.categories.background.label, '个人');
  const extra = [...records, { id:'c1', category:'custom-reading', title:'读书笔记', body:'内容', date:'', fields:{} },
    { id:'old1', category:'legacy-topic', title:'旧分类', body:'保留', date:'', fields:{} }];
  const catalog = model.categoryMap([{id:'custom-reading',label:'读书'}, {id:'background',label:'关于我'}], extra);
  assert.equal(catalog.background.label, '关于我');
  assert.equal(catalog['custom-reading'].label, '读书');
  assert.equal(catalog['legacy-topic'].label, 'legacy-topic');
  const summary = summarize(extra, catalog);
  assert.equal(summary.counts['custom-reading'], 1);
  assert.equal(summary.counts['legacy-topic'], 1);
  assert.equal(selectRecords(extra, {category:'custom-reading'})[0].id, 'c1');
});

const records = [
  { id: 'p1', category: 'people', title: '林老师', body: '讨论博士毕业', fields: { 单位: '示例大学' }, tags: ['研究'], date: '2026-09-01', links: [] },
  { id: 'j1', category: 'journal', title: '一次讨论', body: '整理毕业材料', fields: {}, tags: [], date: '2026-10-01', created_at: '2026-10-14', links: ['p1', 'e1', 'missing'] },
  { id: 'e1', category: 'event', title: '博士毕业', body: '待核实要求', fields: { 状态: '进行中' }, tags: [], date: '2026-09-03', links: ['j1'] },
];

test('search covers Chinese fields and combines category with query', () => {
  assert.deepEqual(selectRecords(records, { category: 'people', query: '示例大学' }).map(r => r.id), ['p1']);
  assert.equal(selectRecords(records, { category: 'journal', query: '示例大学' }).length, 0);
});
test('date filtering uses occurrence date, includes both boundaries, and returns all matching records', () => {
  const days = Array.from({ length: 25 }, (_, i) => ({ ...records[1], id: `day${i}`, date: '2026-10-01' }));
  assert.equal(selectRecords(days, { from: '2026-10-01', to: '2026-10-01' }).length, 25);
  assert.equal(selectRecords(records, { from: '2026-10-14' }).length, 0);
});

test('partial dates and periods show known precision and filter by overlap', () => {
  assert.equal(typeof model.formatRecordDate, 'function');
  const dates = [
    {id:'year',date:'2023'}, {id:'month',date:'2024-09'},
    {id:'study',date:'2017-09',date_end:'2021-06'}, {id:'ongoing',date:'2025-02',date_end:'ongoing'}, {id:'unknown',date:''}
  ];
  assert.equal(model.formatRecordDate(dates[0]), '2023年');
  assert.equal(model.formatRecordDate(dates[1]), '2024年9月');
  assert.equal(model.formatRecordDate(dates[2]), '2017年9月 — 2021年6月');
  assert.equal(model.formatRecordDate(dates[3]), '2025年2月 — 至今');
  assert.equal(model.formatRecordDate(dates[4]), '日期未记录');
  assert.equal(model.formatRecordDate({date:'2026-10-14'}), '2026-10-14');
  assert.deepEqual(selectRecords(dates,{from:'2020-01-01',to:'2020-12-31'}).map(r=>r.id), ['study']);
  assert.deepEqual(selectRecords(dates,{from:'2023-07-01',to:'2023-07-31'}).map(r=>r.id), ['year']);
  assert.deepEqual(selectRecords(dates,{from:'2026-10-01',to:'2026-10-14'}).map(r=>r.id), ['ongoing']);
  assert.equal(selectRecords(dates,{from:'2024-10-01',to:'2024-10-31'}).length,0);
  assert.equal(selectRecords(dates,{from:'9999-01-01',to:'9999-12-31'}).length,0);
});
test('links resolve both explicit outgoing links and incoming references without duplication', () => {
  assert.deepEqual(relatedRecords(records, records[1]).map(r => r.id).sort(), ['e1', 'p1']);
  assert.deepEqual(relatedRecords(records, records[0]).map(r => r.id), ['j1']);
});
test('blank search keeps the complete collection and unknown categories return an empty result', () => {
  assert.equal(selectRecords(records, { query: '  ' }).length, 3);
  assert.equal(selectRecords(records, { category: 'resource' }).length, 0);
});
test('summary counts each category and distinguishes completed from active events', () => {
  const result = summarize([...records, { ...records[2], id: 'e2', fields: { 状态: '已完成' } }]);
  assert.equal(result.counts.event, 2);
  assert.equal(result.activeEvents, 1);
  assert.equal(result.counts.background, 0);
});
test('resource links support HTTP and only bundled attachments when preview opens from a file', () => {
  const fileBase = 'file:///C:/archive/preview.html';
  assert.equal(safeResourceUrl('dist/files/note.md', fileBase)?.href, 'file:///C:/archive/dist/files/note.md');
  assert.equal(safeResourceUrl('https://example.com/document', fileBase)?.protocol, 'https:');
  assert.equal(safeResourceUrl('files/note.md', 'http://127.0.0.1:8768/')?.pathname, '/files/note.md');
  for (const href of ['javascript:alert(1)', 'data:text/html,hello', 'file:///C:/private.txt', 'dist/files/../../private.txt']) {
    assert.equal(safeResourceUrl(href, fileBase), null);
  }
});
