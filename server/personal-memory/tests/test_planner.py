import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
from planner_store import PlannerStore

NOW = 1792166400  # 2026-10-16 16:00 UTC

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PlannerStore(Path(self.tmp.name) / 'db.sqlite', clock=lambda: NOW)
    def tearDown(self): self.tmp.cleanup()
    def create(self, **kw):
        return self.store.create(title='买牛奶', due_at=NOW+600, remind=True, request_id='create1', **kw)
    def test_date_context_and_strict_time(self):
        self.assertEqual(self.store.context()['local_date'], '2026-10-17')
        self.assertEqual(self.store.parse_time('2026-10-17T01:00:00', 'Asia/Shanghai'), NOW+3600)
        for value in ['明天', '2026-10', '2026-10-17', True]:
            with self.assertRaises(ValueError): self.store.parse_time(value, 'Asia/Shanghai')
    def test_device_cancel_without_occurrence_closes_series_and_keeps_history(self):
        task = self.create(repeat='daily')
        other = self.store.create(title='保留事项', request_id='keep')
        self.assertTrue(self.store.snapshot('dev')['reminders'])
        args = dict(op_id='cancel-series', action='cancel', task_id=task['id'], expected_revision=1)
        result = self.store.action('dev', **args)
        self.assertEqual(self.store.action('dev', **args), result)
        self.assertEqual(self.store.get(task['id'])['status'], 'cancelled')
        self.assertEqual(len(self.store.history(task['id'])), 2)
        snap = self.store.snapshot('dev')
        self.assertFalse(snap['reminders'])
        self.assertEqual([t['id'] for t in snap['tasks']], [other['id']])
        with self.assertRaises(ValueError):
            self.store.action('dev', 'stale-cancel', 'cancel', task['id'], 1)
        result = self.store.action('dev', 'cancel-note', 'cancel', other['id'], 1)
        self.assertTrue(result['ok'])
        self.assertEqual(self.store.get(other['id'])['status'], 'cancelled')
    def test_idempotent_create_conflict_and_revision(self):
        first = self.create()
        self.assertEqual(first, self.create())
        with self.assertRaises(ValueError): self.store.create(title='different', request_id='create1')
        with self.assertRaises(ValueError): self.store.update(first['id'], {'title':'new'}, 0, 'bad')
        done = self.store.update(first['id'], {'status':'completed'}, 1, 'done')
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(len(self.store.history(first['id'])), 2)
    def test_existing_archive_fk_and_no_model_import(self):
        with self.assertRaises(ValueError): self.create(archive_links=['unknown'])
        with closing(sqlite3.connect(self.store.db_path)) as c, c:
            c.execute('CREATE TABLE personal_archive_records(id TEXT PRIMARY KEY)')
            c.execute("INSERT INTO personal_archive_records VALUES ('people-existing')")
        self.assertEqual(self.create(archive_links=['people-existing'])['archive_links'], ['people-existing'])
        self.assertNotIn('mnemosyne', sys.modules)
    def test_ack_is_for_actual_current_occurrence_only(self):
        task = self.create()
        snap = self.store.snapshot('dev')
        occurrence = snap['reminders'][0]['id']
        self.assertFalse(self.store.delivery(task['id'], 'dev')['device_scheduled'])
        with self.assertRaises(ValueError): self.store.ack('dev', snap['revision'], ['made-up'])
        self.store.ack('dev', snap['revision'], [occurrence])
        self.assertTrue(self.store.delivery(task['id'], 'dev')['device_scheduled'])
        self.store.update(task['id'], {'due_at':NOW+1200}, 1, 'change')
        self.assertFalse(self.store.delivery(task['id'], 'dev')['device_scheduled'])
    def test_repeat_dismiss_fired_and_offline_snooze(self):
        task = self.create(repeat='daily')
        snap = self.store.snapshot('dev')
        self.assertGreater(len(snap['reminders']), 1)
        occurrence = snap['reminders'][0]['id']
        action = dict(op_id='fire', action='fired', task_id=task['id'], occurrence_id=occurrence, expected_revision=1)
        result=self.store.action('dev', **action)
        self.assertEqual(self.store.action('dev', **action), result)
        self.assertEqual(result['revision'], self.store.snapshot('dev')['revision'])
        self.assertEqual(self.store.get(task['id'])['status'], 'pending')
        self.store.action('dev', op_id='snooze', action='snooze', task_id=task['id'], occurrence_id=occurrence, expected_revision=1, seconds=600, at=NOW-60)
        with closing(sqlite3.connect(self.store.db_path)) as c, c:
            row = c.execute("SELECT at FROM planner_occurrences WHERE source='snooze'").fetchone()
        self.assertEqual(row[0], NOW-60)
        self.store.action('dev', op_id='dismiss', action='dismiss', task_id=task['id'], occurrence_id=occurrence, expected_revision=1)
        self.assertEqual(self.store.get(task['id'])['status'], 'pending')
    def test_device_snapshot_limits_utf8_and_cancellation(self):
        for n in range(40):
            self.store.create(title='提醒'*64, body='字'*1000, due_at=NOW+600+n, repeat='daily', remind=True, request_id=f'c{n}')
        snap = self.store.snapshot('dev')
        self.assertLessEqual(len(json.dumps(snap,ensure_ascii=False).encode()), 65536)
        self.assertLessEqual(len(snap['tasks']),32)
        self.assertLessEqual(len(snap['reminders']),64)
        self.assertTrue(snap['truncated'])
        ids = {t['id']:t['revision'] for t in snap['tasks']}
        self.assertTrue(all(ids[r['task_id']]==r['task_revision'] for r in snap['reminders']))
        self.assertTrue(all(len(t['body'].encode())<=768 for t in snap['tasks']))
        task = snap['tasks'][0]
        self.store.update(task['id'], {'status':'cancelled'}, task['revision'], 'cancel')
        self.assertNotIn(task['id'], {t['id'] for t in self.store.snapshot('dev')['tasks']})
    def test_snooze_delivery_does_not_use_another_repeat_occurrence_ack(self):
        task=self.create(repeat='daily')
        snap=self.store.snapshot('dev');base=snap['reminders'][0]
        self.store.action('dev','long-snooze','snooze',task['id'],1,base['id'],seconds=172800)
        snap=self.store.snapshot('dev')
        tomorrow=snap['reminders'][0]
        self.store.ack('dev',snap['revision'],[tomorrow['id']])
        result=self.store.delivery(task['id'],'dev',occurrence_id='snooze-long-snooze')
        self.assertFalse(result['device_scheduled'])
        self.assertEqual(result['occurrence_id'],'snooze-long-snooze')
    def test_deadline_is_not_alarm_and_event_has_separate_times(self):
        due=self.store.create(title='deadline',due_at=NOW+600,request_id='deadline')
        self.assertFalse(due['remind'])
        self.assertEqual(self.store.snapshot('dev')['reminders'],[])
        event=self.store.create(title='meeting',kind='event',start_at=NOW+3600,end_at=NOW+7200,remind_at=NOW+3000,remind=True,request_id='meeting')
        snap=self.store.snapshot('dev')
        self.assertEqual(snap['reminders'][0]['at'],NOW+3000)
        self.assertEqual(next(t for t in snap['tasks'] if t['id']==event['id'])['due_at'],NOW+3600)
        self.assertEqual([t['id'] for t in self.store.list(kind='event',from_at=NOW+3500,to_at=NOW+3700)],[event['id']])
        with self.assertRaises(ValueError):self.store.update(event['id'],{'end_at':NOW+1000},1,'bad-end')
        self.assertEqual(self.store.get(event['id'])['revision'],1)
    def test_cross_client_snooze_collision_is_controlled_and_atomic(self):
        a=self.create()
        b=self.store.create(title='second',due_at=NOW+700,remind=True,request_id='second')
        before=self.store.snapshot('dev')
        occurrences={r['task_id']:r['id'] for r in before['reminders']}
        original=self.store.action('dev','same','snooze',a['id'],1,occurrences[a['id']])
        revision=self.store.snapshot('dev')['revision']
        with self.assertRaisesRegex(ValueError,'[Cc]ollision|already|conflict'):
            self.store.action('browser','same','snooze',b['id'],1,occurrences[b['id']])
        after=self.store.snapshot('dev')
        self.assertEqual(after['revision'],revision)
        self.assertIn(occurrences[b['id']],{r['id'] for r in after['reminders']})
        self.assertEqual(self.store.action('dev','same','snooze',a['id'],1,occurrences[a['id']]),original)
        with closing(sqlite3.connect(self.store.db_path)) as c:
            self.assertEqual(c.execute("SELECT task_id FROM planner_occurrences WHERE id='snooze-same'").fetchone()[0],a['id'])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM planner_requests WHERE request_id='device:browser:same'").fetchone()[0],0)
    def test_delivery_distinguishes_fired_current_from_next_repeat(self):
        for repeat in ('none','daily'):
            task=self.store.create(title=repeat,due_at=NOW+600,repeat=repeat,remind=True,request_id=repeat)
            first=next(r for r in self.store.snapshot('dev')['reminders'] if r['task_id']==task['id'])
            self.store.action('dev','fire-'+repeat,'fired',task['id'],1,first['id'])
            result=self.store.delivery(task['id'],'dev')
            self.assertEqual(result['recent_fired_occurrence_id'],first['id'])
            self.assertEqual(result['current_occurrence_id'],first['id'])
            if repeat=='none':self.assertIsNone(result['next_occurrence_id'])
            else:self.assertNotEqual(result['next_occurrence_id'],first['id'])
            self.store.action('mcp','later-'+repeat,'snooze',task['id'],1,result['current_occurrence_id'])
            after=self.store.delivery(task['id'],'dev')
            self.assertIsNone(after['recent_fired_occurrence_id'])
            if repeat=='daily':
                self.assertIn(result['next_occurrence_id'],{r['id'] for r in self.store.snapshot('dev')['reminders']})
    def test_delivery_reads_task_snapshot_and_ack_in_one_transaction(self):
        task=self.create();snap=self.store.snapshot('dev')
        self.store.ack('dev',snap['revision'],[snap['reminders'][0]['id']])
        original=self.store.connection
        opened=[]
        def tracked():opened.append(True);return original()
        with patch.object(self.store,'connection',side_effect=tracked):
            result=self.store.delivery(task['id'],'dev')
        self.assertTrue(result['device_scheduled'])
        self.assertEqual(len(opened),1,'delivery must not join independently committed revisions')
    def test_concurrent_edit_cannot_mix_old_task_with_new_occurrence_ack(self):
        task=self.create();snap=self.store.snapshot('dev')
        self.store.ack('dev',snap['revision'],[snap['reminders'][0]['id']])
        original_connection=self.store.connection;original_get=self.store._get
        main=threading.current_thread();entered=threading.Event();workers=[];errors=[]
        def edit_and_ack():
            entered.set()
            try:
                self.store.update(task['id'],{'due_at':NOW+1200},1,'concurrent-edit')
                newer=self.store.snapshot('dev')
                self.store.ack('dev',newer['revision'],[newer['reminders'][0]['id']])
            except BaseException as error:errors.append(error)
        def interleaved_get(c,task_id):
            result=original_get(c,task_id)
            if threading.current_thread() is main and not workers:
                worker=threading.Thread(target=edit_and_ack);workers.append(worker);worker.start()
                self.assertTrue(entered.wait(1))
            return result
        @contextmanager
        def coordinated_connection():
            with original_connection() as c:yield c
            if threading.current_thread() is main and workers:
                workers[0].join(3)
        with patch.object(self.store,'connection',side_effect=coordinated_connection),patch.object(self.store,'_get',side_effect=interleaved_get):
            result=self.store.delivery(task['id'],'dev')
        self.assertFalse(workers[0].is_alive());self.assertEqual(errors,[])
        self.assertTrue(result['device_scheduled'])
        self.assertEqual(result['task']['revision'],result['next_occurrence']['task_revision'])
        self.assertEqual(result['task']['revision'],1)
        self.assertEqual(self.store.get(task['id'])['revision'],2)
    def test_repeat_complete_only_finishes_actual_instance_and_is_idempotent(self):
        task=self.create(repeat='daily')
        before=self.store.snapshot('dev');instances=before['reminders'];first=instances[0]
        with self.assertRaises(ValueError):self.store.action('dev','missing','complete',task['id'],1)
        with self.assertRaises(ValueError):self.store.action('dev','fake','complete',task['id'],1,'made-up')
        result=self.store.action('dev','done-once','complete',task['id'],1,first['id'])
        self.assertEqual(self.store.action('dev','done-once','complete',task['id'],1,first['id']),result)
        after=self.store.snapshot('dev')
        self.assertEqual(self.store.get(task['id'])['status'],'pending')
        self.assertEqual(self.store.get(task['id'])['revision'],1)
        self.assertEqual([r['id'] for r in after['reminders']],[r['id'] for r in instances[1:]])
        self.assertEqual(after['tasks'][0]['repeat'],'daily')
    def test_complete_snoozed_repeat_instance_preserves_future_series(self):
        task=self.create(repeat='daily');before=self.store.snapshot('dev');first=before['reminders'][0]
        self.store.action('dev','later-repeat','snooze',task['id'],1,first['id'])
        self.store.action('dev','done-snooze','complete',task['id'],1,'snooze-later-repeat')
        after=self.store.snapshot('dev')
        self.assertEqual(self.store.get(task['id'])['status'],'pending')
        self.assertEqual([r['id'] for r in after['reminders']],[r['id'] for r in before['reminders'][1:]])
    def test_repeat_without_alarm_has_completable_instance_but_never_rings(self):
        task=self.store.create(title='daily quiet',due_at=NOW+600,repeat='daily',request_id='quiet')
        self.assertEqual(self.store.snapshot('dev')['reminders'],[])
        delivery=self.store.delivery(task['id'],'dev')
        self.assertIsNotNone(delivery['current_occurrence_id'])
        self.assertFalse(delivery['device_scheduled'])
        self.store.action('web','done-quiet','complete',task['id'],1,delivery['current_occurrence_id'])
        after=self.store.delivery(task['id'],'dev')
        self.assertNotEqual(after['current_occurrence_id'],delivery['current_occurrence_id'])
        self.assertEqual(self.store.snapshot('dev')['reminders'],[])
    def test_snapshot_reports_closed_instances_but_not_fired(self):
        task=self.create(repeat='daily');before=self.store.snapshot('dev');ids=[r['id'] for r in before['reminders']]
        self.store.action('dev','closed-complete','complete',task['id'],1,ids[0])
        self.store.action('dev','closed-dismiss','dismiss',task['id'],1,ids[1])
        self.store.action('dev','closed-snooze','snooze',task['id'],1,ids[2])
        self.store.action('dev','open-fired','fired',task['id'],1,ids[3])
        snap=self.store.snapshot('dev')
        self.assertEqual(set(snap['closed_reminders']),set(ids[:3]))
        self.assertNotIn(ids[3],snap['closed_reminders'])
        self.assertLessEqual(len(json.dumps(snap,ensure_ascii=False).encode()),65536)
        self.store.update(task['id'],{'title':'new revision'},1,'new-revision')
        self.assertEqual(self.store.snapshot('dev')['closed_reminders'],[])
    def test_closed_snapshot_is_bounded_recent_first_and_retains_server_history(self):
        task=self.create(repeat='daily')
        with self.store.connection() as c:
            c.executemany("INSERT INTO planner_occurrences (id,task_id,task_revision,at,status,source,acted_at) VALUES(?,?,1,?,'completed','snooze',?)",[(f'snooze-history-{n}',task['id'],NOW+600,NOW-n) for n in range(140)])
        snap=self.store.snapshot('dev')
        self.assertEqual(len(snap['closed_reminders']),128)
        self.assertEqual(snap['closed_reminders'][0],'snooze-history-0')
        self.assertEqual(snap['closed_reminders'][-1],'snooze-history-127')
        self.assertTrue(snap['truncated'])
        self.assertLessEqual(len(json.dumps(snap,ensure_ascii=False).encode()),65536)
        with self.store.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM planner_occurrences WHERE status='completed'").fetchone()[0],140)
    def test_late_receipts_cannot_resurrect_closed_or_completed_instances(self):
        task=self.create(repeat='daily');ids=[r['id'] for r in self.store.snapshot('dev')['reminders']]
        for n,state in enumerate(('complete','dismiss','snooze')):
            self.store.action('web','close-'+state,state,task['id'],1,ids[n])
            rev=self.store.snapshot('dev')['revision']
            self.store.action('dev','late-fire-'+state,'fired',task['id'],1,ids[n])
            self.assertEqual(self.store.snapshot('dev')['revision'],rev)
            self.assertIn(ids[n],self.store.snapshot('dev')['closed_reminders'])
        rev=self.store.snapshot('dev')['revision']
        self.store.action('dev','late-dismiss-complete','dismiss',task['id'],1,ids[0])
        self.assertEqual(self.store.snapshot('dev')['revision'],rev)
        with self.assertRaises(ValueError):self.store.action('dev','bad-resnooze','snooze',task['id'],1,ids[0])
    def test_completing_original_closes_only_its_snooze_descendants(self):
        task=self.create(repeat='daily');ids=[r['id'] for r in self.store.snapshot('dev')['reminders']]
        self.store.action('dev','child1','snooze',task['id'],1,ids[0])
        self.store.action('dev','child2','snooze',task['id'],1,'snooze-child1')
        self.store.action('web','finish-original','complete',task['id'],1,ids[0])
        snap=self.store.snapshot('dev')
        self.assertTrue({ids[0],'snooze-child1','snooze-child2'}<=set(snap['closed_reminders']))
        self.assertEqual([r['id'] for r in snap['reminders']],ids[1:])
    def test_quiet_current_survives_alarm_window_and_selected_date_is_exact(self):
        task=self.store.create(title='quiet',due_at=NOW,repeat='daily',request_id='quiet-current')
        first=self.store.delivery(task['id'],'dev')['current_occurrence_id']
        self.store.clock=lambda:NOW+360
        result=self.store.delivery(task['id'],'dev')
        self.assertEqual(result['current_occurrence_id'],first)
        self.assertEqual(result['current_occurrence_date'],'2026-10-17')
        tomorrow=self.store.delivery(task['id'],'dev',chosen_date='2026-10-18')
        self.assertNotEqual(tomorrow['current_occurrence_id'],first)
        self.assertEqual(tomorrow['current_occurrence_date'],'2026-10-18')
        self.store.action('web','finish-tomorrow','complete',task['id'],1,tomorrow['current_occurrence_id'])
        self.assertEqual(self.store.delivery(task['id'],'dev')['current_occurrence_id'],first)
        with self.assertRaises(ValueError):self.store.delivery(task['id'],'dev',chosen_date='明天')
        with self.assertRaises(ValueError):self.store.delivery(task['id'],'dev',chosen_date='9999-12-31')
    def test_calendar_date_uses_event_day_when_reminder_is_previous_day(self):
        task=self.store.create(title='next-day meeting',kind='event',start_at=NOW+15*3600,remind_at=NOW-600,repeat='daily',remind=True,request_id='previous-day')
        current=self.store.delivery(task['id'],'dev')['current_occurrence_id']
        self.store.action('dev','fire-previous-day','fired',task['id'],1,current)
        self.assertEqual(self.store.delivery(task['id'],'dev')['current_occurrence_date'],'2026-10-17')
        self.assertEqual(self.store.delivery(task['id'],'dev',chosen_date='2026-10-18')['current_occurrence_date'],'2026-10-18')

if __name__ == '__main__': unittest.main()
