import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from planner_store import PlannerStore
from planner_tools import register_planner_tools

class Registry:
    def __init__(self):self.tools={}
    def tool(self,**kw):
        def decorator(fn):self.tools[fn.__name__]=fn;return fn
        return decorator
class ToolTests(unittest.TestCase):
    def test_get_exposes_bounded_repeat_instance_history_without_other_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PlannerStore(Path(tmp)/'db.sqlite',clock=lambda:1792166400)
            mcp=Registry();register_planner_tools(mcp,store,device='dev')
            created=mcp.tools['planner_create'](title='daily history',due_at=1792166400,repeat='daily',remind=True,request_id='history-create')
            task_id=created['task']['id'];current=created['current_occurrence_id']
            other=store.create(title='other task',due_at=1792166500,repeat='daily',remind=True,request_id='other-history')
            other_ids={r['id'] for r in store.snapshot('dev')['reminders'] if r['task_id']==other['id']}
            mcp.tools['planner_complete'](task_id,1,'history-complete',occurrence_id=current)
            result=mcp.tools['planner_get'](task_id)
            history=result['occurrence_history']
            self.assertTrue(any(r['id']==current and r['status']=='completed' for r in history))
            self.assertTrue(any(r['at']>1792166400 and r['status']=='pending' for r in history))
            self.assertFalse(other_ids & {r['id'] for r in history})
            self.assertEqual(result['task']['status'],'pending')
            self.assertEqual(len(result['history']),1)
            self.assertEqual(set(history[0]),{'id','status','at','task_revision','parent_occurrence_id','acted_at'})
            with store.connection() as c:
                c.executemany("INSERT INTO planner_occurrences (id,task_id,task_revision,at,status,source,acted_at) VALUES(?,?,1,?,'completed','snooze',?)",[(f'snooze-bounded-{n}',task_id,1792166400,1792166400-n) for n in range(120)])
            bounded=store.occurrence_history(task_id)
            self.assertEqual(len(bounded),100)
            self.assertEqual([r['acted_at'] if r['acted_at'] is not None else r['at'] for r in bounded],sorted([r['acted_at'] if r['acted_at'] is not None else r['at'] for r in bounded],reverse=True))
    def test_tools_save_without_promising_scheduling_and_use_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PlannerStore(Path(tmp)/'db.sqlite',clock=lambda:1792166400);mcp=Registry();register_planner_tools(mcp,store,device='dev')
            self.assertEqual(len(mcp.tools),9)
            result=mcp.tools['planner_create'](title='新计划',request_id='test')
            self.assertTrue(result['saved']);self.assertFalse(result['device_scheduled'])
            task=result['task'];self.assertIsNone(task['due_at'])
            dated=mcp.tools['planner_create'](title='only deadline',due_at='2026-10-20T15:00:00+08:00',request_id='dated')
            self.assertFalse(dated['task']['remind'])
            event=mcp.tools['planner_create'](title='meeting',kind='event',start_at='2026-10-20T15:00:00+08:00',end_at='2026-10-20T16:00:00+08:00',remind_at='2026-10-20T14:50:00+08:00',remind=True,request_id='event')
            self.assertEqual(event['task']['start_at']-event['task']['remind_at'],600)
            live=mcp.tools['planner_create'](title='live',due_at=int(store.clock())+600,remind=True,request_id='live')
            snoozed=mcp.tools['planner_snooze'](live['task']['id'],live['occurrence_id'],1,'same')
            self.assertTrue(snoozed['occurrence_id'].startswith('snooze-mcp-'))
            self.assertEqual(mcp.tools['planner_snooze'](live['task']['id'],live['occurrence_id'],1,'same')['occurrence_id'],snoozed['occurrence_id'])
            done=mcp.tools['planner_complete'](task_id=task['id'],expected_revision=1,request_id='done')
            self.assertEqual(done['task']['status'],'completed')
            self.assertEqual(len(mcp.tools['planner_get'](task['id'])['history']),2)
            with self.assertRaises(ValueError):mcp.tools['planner_update'](task['id'],{'title':'stale'},1,'update')
            repeat=mcp.tools['planner_create'](title='daily',due_at=int(store.clock())+600,repeat='daily',remind=True,request_id='daily')
            with self.assertRaises(ValueError):mcp.tools['planner_complete'](repeat['task']['id'],1,'no-instance')
            current=mcp.tools['planner_delivery'](repeat['task']['id'])['current_occurrence_id']
            done=mcp.tools['planner_complete'](repeat['task']['id'],1,'done-instance',occurrence_id=current)
            self.assertEqual(done['task']['status'],'pending')
            self.assertNotEqual(done['next_occurrence_id'],current)
if __name__=='__main__':unittest.main()
