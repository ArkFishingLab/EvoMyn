import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from backup_manager import BackupManager

class BackupManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pem=rsa.generate_private_key(public_exponent=65537,key_size=3072).public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.calls=[];self.gate=None
        parent=self
        class Client:
            def __init__(self,token,repository):
                parent.assertEqual(token,'github_pat_test_secret_123456789');self.repository=repository
            def check(self):parent.calls.append('check');return {'repository':self.repository}
            def upload(self,path,metadata):
                parent.calls.append('upload')
                if parent.gate:parent.gate.wait(3)
                return {'release_id':1,'url':'https://github.com/a/b/releases/tag/backup','verified':True}
            def prune(self,daily,monthly):parent.calls.append('prune');return 0
        def bundle(state,config,output,pem):
            output.write_bytes(b'ENCRYPTED');return {'size':9,'sha256':'a'*64,'key_fingerprint':'f'*64}
        self.manager=BackupManager(self.root/'backup',self.root/'state',self.root/'config',client_factory=Client,bundle_factory=bundle)
    def tearDown(self):
        if self.gate:self.gate.set()
        self.manager.wait(5);self.tmp.cleanup()
    def configured(self,**extra):
        return self.manager.save({'repository':'https://github.com/a/b','token':'github_pat_test_secret_123456789','public_key':self.pem,**extra})
    def test_defaults_disabled_and_secrets_write_only_persisted(self):
        self.assertFalse(self.manager.state()['config']['enabled']);self.assertEqual(self.calls,[])
        state=self.configured();raw=json.dumps(state)
        self.assertNotIn('github_pat_test_secret',raw);self.assertNotIn('PRIVATE KEY',raw)
        self.assertEqual(state['config']['repository'],'a/b');self.assertTrue(state['config']['token_configured'])
        self.assertIsNone(state['next_run'])
        self.manager.save({'token':'','time':'04:15'})
        self.assertEqual(self.manager.check()['repository'],'a/b')
        saved=json.loads((self.root/'backup/settings.json').read_text())
        self.assertEqual(saved['token'],'github_pat_test_secret_123456789')
    def test_reject_unsafe_repository_or_incomplete_enable(self):
        for repo in ['https://other.invalid/a/b','a/b/../c','a/b?x=1','a/b#token']:
            with self.assertRaises(ValueError):self.manager.save({'repository':repo})
        for change in [{'enabled':True},{'enabled':'false'},{'time':'25:00'},{'keep_daily':0},{'keep_monthly':True},{'unexpected':'field'}]:
            with self.assertRaises(ValueError):self.manager.save(change)
    def test_one_job_prunes_only_after_verified_upload_and_preserves_file(self):
        self.configured();self.gate=threading.Event()
        self.manager.start()
        with self.assertRaises(RuntimeError):self.manager.start()
        with self.assertRaises(RuntimeError):self.manager.save({'time':'05:00'})
        self.gate.set();self.manager.wait(5)
        state=self.manager.state();self.assertFalse(state['running'])
        self.assertEqual(state['history'][0]['status'],'success')
        self.assertTrue(state['history'][0]['local_available'])
        self.assertEqual(self.calls,['upload','prune'])
        self.assertTrue(self.manager.download(state['history'][0]['id']).is_file())
        with self.assertRaises(ValueError):self.manager.download('../settings.json')
    def test_failure_never_leaks_transport_error_or_calls_prune(self):
        self.configured()
        def failing(*_):raise OSError('github_pat_test_secret_123456789 private path and body')
        self.manager.bundle_factory=failing
        self.manager.start();self.manager.wait(5)
        result=self.manager.state();self.assertEqual(result['history'][0]['status'],'failed')
        self.assertNotIn('github_pat_test_secret',json.dumps(result));self.assertEqual(self.calls,[])
    def test_shanghai_daily_schedule_once_and_survives_restart(self):
        self.configured(enabled=True)
        before=datetime(2026,10,16,18,59,tzinfo=timezone.utc)
        due=datetime(2026,10,16,19,0,tzinfo=timezone.utc)
        self.assertFalse(self.manager.tick(before));self.assertTrue(self.manager.tick(due));self.manager.wait(5)
        self.assertFalse(self.manager.tick(due));self.assertEqual(self.calls,['upload','prune'])
        restarted=BackupManager(self.root/'backup',self.root/'state',self.root/'config',client_factory=lambda *_:None)
        self.assertFalse(restarted.tick(due))
        self.assertEqual(restarted.state()['last_success']['status'],'success')

if __name__=='__main__':unittest.main()
