import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from planner_store import PlannerStore
from planner_server import create_http_server, authorize_device, process_device_message, command

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=PlannerStore(Path(self.tmp.name)/'db.sqlite')
        self.server=create_http_server(self.store,host='127.0.0.1',port=0,allowed_hosts=['localhost'],secure_cookie=False)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        c.request(method,path,body,{'Host':'localhost',**(headers or {})})
        r=c.getresponse();data=r.read(); result=(r.status,dict(r.getheaders()),data);c.close();return result
    def test_browser_session_csrf_write_and_no_secret(self):
        code,h,b=self.request('GET','/api/session')
        self.assertEqual(code,200)
        csrf=json.loads(b)['csrf'];cookie=h['Set-Cookie'].split(';')[0]
        body=json.dumps(dict(op='create',title='待办',request_id='browser1')).encode()
        self.assertEqual(self.request('POST','/api/command',body,{'Content-Type':'application/json'})[0],403)
        headers={'Cookie':cookie,'X-CSRF-Token':csrf,'Origin':'http://localhost','Content-Type':'application/json'}
        self.assertEqual(self.request('POST','/api/command',body,headers)[0],200)
        self.assertEqual(self.request('GET','/api/tasks')[0],200)
        headers['Origin']='https://evil.example'
        self.assertEqual(self.request('POST','/api/command',body,headers)[0],403)
        code,h,html=self.request('GET','/')
        self.assertEqual(code,200);self.assertNotIn(b'PLANNER_DEVICE_TOKEN',html)
        self.assertEqual(self.request('POST','/api/command',b'x'*65537,headers)[0],413)
    def test_host_validation(self):
        self.assertEqual(self.request('GET','/',headers={'Host':'evil.example'})[0],403)
    def test_json_depth_is_rejected_before_decoder_for_http_and_ws(self):
        deep='['*3000+'0'+']'*3000
        with self.assertRaises(ValueError):process_device_message(self.store,'dev',deep)
        _,h,b=self.request('GET','/api/session')
        headers={'Cookie':h['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(b)['csrf'],'Origin':'http://localhost','Content-Type':'application/json'}
        self.assertEqual(self.request('POST','/api/command',deep,headers)[0],400)
        self.assertEqual(self.request('GET','/api/status')[0],200)
        # Brackets inside JSON string contents do not consume structural depth.
        value=dict(op='create',title='literal brackets',body='['*3000,request_id='brackets')
        self.assertEqual(self.request('POST','/api/command',json.dumps(value),headers)[0],200)
    def test_archive_choices_expose_only_ids_and_titles_and_validate_links(self):
        with self.store.connection() as c:
            c.execute('CREATE TABLE personal_archive_records(id TEXT PRIMARY KEY,payload TEXT)')
            c.execute('INSERT INTO personal_archive_records VALUES(?,?)',('archive1',json.dumps({'title':'<script>标题</script>','body':'PRIVATE_BODY','file_path':'PRIVATE_PATH'})))
        code,h,b=self.request('GET','/api/archive-choices')
        self.assertEqual(code,200)
        self.assertEqual(json.loads(b),{'records':[{'id':'archive1','title':'<script>标题</script>'}]})
        self.assertNotIn(b'PRIVATE',b)
        _,h,b=self.request('GET','/api/session')
        headers={'Cookie':h['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(b)['csrf'],'Origin':'http://localhost','Content-Type':'application/json'}
        value=dict(op='create',title='linked',request_id='linked',archive_links=['archive1'])
        code,_,b=self.request('POST','/api/command',json.dumps(value),headers)
        self.assertEqual(code,200);self.assertEqual(json.loads(b)['archive_links'],['archive1'])
        value.update(request_id='invalid-link',archive_links=['nonexistent'])
        self.assertEqual(self.request('POST','/api/command',json.dumps(value),headers)[0],400)
    def test_web_complete_requires_repeat_instance_and_preserves_series(self):
        # Keep the created instance on today's calendar date, including near midnight.
        self.store.clock=lambda:1792166400
        task=self.store.create(title='daily',due_at=int(self.store.clock())+600,repeat='daily',remind=True,request_id='daily-web')
        current=self.store.delivery(task['id'],'dev')['current_occurrence_id']
        value=dict(op='complete',task_id=task['id'],expected_revision=1,request_id='done-web')
        with self.assertRaises(ValueError):command(self.store,value)
        value['occurrence_id']=current
        result=command(self.store,value);self.assertTrue(result['ok'])
        self.assertEqual(self.store.get(task['id'])['status'],'pending')
        self.assertNotEqual(self.store.delivery(task['id'],'dev')['next_occurrence_id'],current)
    def test_web_delivery_uses_exact_selected_calendar_date(self):
        self.store.clock=lambda:1792166760
        task=self.store.create(title='quiet dates',due_at=1792166400,repeat='daily',request_id='dates')
        code,_,body=self.request('GET','/api/delivery?task_id='+task['id']+'&chosen_date=2026-10-18')
        self.assertEqual(code,200);result=json.loads(body)
        self.assertEqual(result['current_occurrence_date'],'2026-10-18')
        self.assertEqual(result['current_occurrence']['at'],1792252800)
        self.assertEqual(self.request('GET','/api/delivery?task_id='+task['id']+'&chosen_date=tomorrow')[0],400)
    def test_cross_client_collision_returns_result_and_browser_has_namespace(self):
        now=int(self.store.clock())
        a=self.store.create(title='a',due_at=now+600,remind=True,request_id='a')
        b=self.store.create(title='b',due_at=now+700,remind=True,request_id='b')
        snap=self.store.snapshot('dev');occ={r['task_id']:r['id'] for r in snap['reminders']}
        self.store.action('other-client','same','snooze',a['id'],1,occ[a['id']])
        result=process_device_message(self.store,'dev',json.dumps(dict(type='action',op_id='same',action='snooze',task_id=b['id'],occurrence_id=occ[b['id']],expected_revision=1)))
        self.assertFalse(result['ok']);self.assertEqual(result['type'],'result')
        self.assertIsInstance(result['revision'],int)
        result=command(self.store,dict(op='snooze',request_id='same',task_id=b['id'],occurrence_id=occ[b['id']],expected_revision=1))
        self.assertTrue(result['ok']);self.assertTrue(result['op_id'].startswith('web-'))
    def test_device_auth_and_safe_commands(self):
        token='a'*64;device='02:00:00:00:00:01'
        good={'Authorization':'Bearer '+token,'Device-Id':device}
        self.assertTrue(authorize_device('/planner/ws',good,token,device,{'example.com'}))
        for path,headers in [('/wrong',good),('/planner/ws',{**good,'Device-Id':'other'}),('/planner/ws',{**good,'Origin':'https://evil.example'}),('/planner/ws',{})]:
            self.assertFalse(authorize_device(path,headers,token,device,{'example.com'}))
        result=process_device_message(self.store,device,json.dumps({'type':'action','op_id':'bad','action':'delete','task_id':'missing','expected_revision':1}))
        self.assertFalse(result['ok']);self.assertEqual(result['type'],'result')
        with self.assertRaises(ValueError): process_device_message(self.store,device,'x'*65537)
    def test_actual_websocket_push_ack_action_and_reconnect(self):
        from planner_server import create_websocket_server
        from websockets.sync.client import connect
        from websockets.exceptions import InvalidStatus
        token='b'*64;device='dev'
        task=self.store.create(title='real integration',due_at=int(self.store.clock())+600,remind=True,request_id='ws-create')
        initial=self.store.snapshot('seed')['reminders'][0]['id']
        self.store.action('other-client','cross','snooze',task['id'],1,initial)
        wsserver=create_websocket_server(self.store,'127.0.0.1',0,token,device,{'localhost'})
        thread=threading.Thread(target=wsserver.serve_forever,daemon=True);thread.start()
        url='ws://127.0.0.1:'+str(wsserver.socket.getsockname()[1])+'/planner/ws'
        try:
            with self.assertRaises(InvalidStatus):connect(url,proxy=None)
            headers={'Authorization':'Bearer '+token,'Device-Id':device}
            with connect(url,additional_headers=headers,proxy=None) as ws:
                snap=json.loads(ws.recv(timeout=3));occ=snap['reminders'][0]['id']
                ws.send(json.dumps({'type':'action','op_id':'cross','action':'snooze','task_id':task['id'],'occurrence_id':occ,'expected_revision':1}))
                rejected=json.loads(ws.recv(timeout=3));self.assertFalse(rejected['ok']);self.assertEqual(rejected['revision'],snap['revision'])
                ws.send(json.dumps({'type':'ack','revision':snap['revision'],'ids':[occ]}))
                # A subsequent action result confirms all earlier FIFO input was processed.
                ws.send(json.dumps({'type':'action','op_id':'fire1','action':'fired','task_id':task['id'],'occurrence_id':occ,'expected_revision':1}))
                result=json.loads(ws.recv(timeout=3));self.assertTrue(result['ok']);self.assertEqual(result['type'],'result')
                updated=json.loads(ws.recv(timeout=3));self.assertGreater(updated['revision'],snap['revision'])
                self.assertEqual(updated['reminders'],[])
                ws.send(json.dumps({'type':'action','op_id':'snooze1','action':'snooze','task_id':task['id'],'occurrence_id':occ,'expected_revision':1,'seconds':600}))
                self.assertTrue(json.loads(ws.recv(timeout=3))['ok'])
                snoozed=json.loads(ws.recv(timeout=3));self.assertEqual(snoozed['reminders'][0]['id'],'snooze-snooze1')
                ws.send(json.dumps({'type':'ack','revision':snoozed['revision'],'ids':['snooze-snooze1']}))
                ws.send(json.dumps({'type':'action','op_id':'complete1','action':'complete','task_id':task['id'],'expected_revision':1}))
                self.assertTrue(json.loads(ws.recv(timeout=3))['ok']);self.assertEqual(json.loads(ws.recv(timeout=3))['tasks'],[])
            with connect(url,additional_headers=headers,proxy=None) as ws:
                self.assertEqual(json.loads(ws.recv(timeout=3))['tasks'],[])
                ws.send('['*3000+'0'+']'*3000)
                from websockets.exceptions import ConnectionClosed
                with self.assertRaises(ConnectionClosed):ws.recv(timeout=3)
                self.assertEqual(ws.close_code,1008)
            with connect(url,additional_headers=headers,proxy=None) as ws:
                self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
            # A detail-page cancellation has no occurrence ID (notes also qualify).
            note=self.store.create(title='cancel note',request_id='ws-cancel-note')
            with connect(url,additional_headers=headers,proxy=None) as ws:
                initial=json.loads(ws.recv(timeout=3))
                self.assertEqual(initial['tasks'][0]['id'],note['id'])
                command={'type':'action','op_id':'cancel-note','action':'cancel','task_id':note['id'],'expected_revision':1}
                ws.send(json.dumps(command))
                result=json.loads(ws.recv(timeout=3));self.assertTrue(result['ok'])
                self.assertEqual(json.loads(ws.recv(timeout=3))['tasks'],[])
                ws.send(json.dumps(command))
                self.assertEqual(json.loads(ws.recv(timeout=3)),result)
                self.assertEqual(self.store.get(note['id'])['status'],'cancelled')
        finally:
            wsserver.shutdown();thread.join()

if __name__=='__main__':unittest.main()
