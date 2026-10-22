import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from backup_manager import BackupManager
from backup_server import create_server

class BackupHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.manager=BackupManager(root/'backup',root/'state',root/'config')
        self.server=create_server(self.manager,port=0,secure_cookie=False)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        with urlopen(self.base+'/api/session') as r:
            self.cookie=r.headers['Set-Cookie'].split(';')[0];self.csrf=json.load(r)['csrf']
        self.headers={'Cookie':self.cookie,'Origin':self.base,'Content-Type':'application/json','X-CSRF-Token':self.csrf}
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def post(self,path,payload,headers=None):
        return urlopen(Request(self.base+path,data=json.dumps(payload).encode(),headers=self.headers if headers is None else headers))
    def test_default_status_and_authorized_configuration(self):
        with urlopen(self.base+'/api/state') as r:self.assertFalse(json.load(r)['config']['enabled'])
        with self.post('/api/config',{'repository':'a/b','token':'github_pat_hidden_secret_123456'}) as r:
            body=r.read();self.assertNotIn(b'github_pat_hidden_secret',body)
            self.assertTrue(json.loads(body)['config']['token_configured'])
        with urlopen(self.base+'/api/state') as r:self.assertNotIn(b'github_pat_hidden_secret',r.read())
    def test_all_mutations_require_csrf_cookie_and_exact_origin(self):
        for headers in [{},{**self.headers,'Origin':'https://other.invalid'},{**self.headers,'X-CSRF-Token':'wrong'},{**self.headers,'Cookie':'backup_session=wrong'}]:
            for path in ['/api/config','/api/run','/api/check']:
                with self.assertRaises(HTTPError) as error:self.post(path,{},headers)
                self.assertEqual(error.exception.code,403)
        self.assertEqual(self.manager.state()['config']['repository'],'')
    def test_host_private_paths_and_incomplete_manual_run(self):
        with self.assertRaises(HTTPError) as error:urlopen(Request(self.base+'/api/state',headers={'Host':'other.invalid'}))
        self.assertEqual(error.exception.code,403)
        for path in ['/settings.json','/history.json','/.env','/api/download/../settings.json']:
            with self.assertRaises(HTTPError):urlopen(self.base+path)
        with self.assertRaises(HTTPError) as error:self.post('/api/run',{})
        self.assertEqual(error.exception.code,400)
    def test_json_limits_and_download_tool(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/config',{'extra':'x'*65536})
        self.assertEqual(error.exception.code,413)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base+'/api/config',data=('['*2000+'0'+']'*2000).encode(),headers=self.headers))
        self.assertEqual(error.exception.code,400)
        with urlopen(self.base+'/restore-tool.py') as r:
            self.assertIn('attachment',r.headers['Content-Disposition']);self.assertIn(b'--key',r.read())

if __name__=='__main__':unittest.main()
