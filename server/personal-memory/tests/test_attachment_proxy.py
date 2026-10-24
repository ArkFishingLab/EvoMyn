"""Exercise the actual front-door handler without loading private runtime state."""
import ast
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class AttachmentProxyTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'local/dashboard.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Dashboard')
        namespace = dict(BaseHTTPRequestHandler=BaseHTTPRequestHandler, os=os, urlsplit=urlsplit,
                         Request=Request, urlopen=urlopen, HTTPError=HTTPError, URLError=URLError,
                         PLANNER_OWNER='device', tempfile=tempfile, time=time)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
        class Target(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                body = json.dumps({'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                    'name':self.headers.get('X-File-Name'), 'site':self.headers.get('Sec-Fetch-Site')}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        self.target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        self.front = ThreadingHTTPServer(('127.0.0.1', 0), namespace['Dashboard'])
        self.environment = patch.dict(os.environ, {'ARCHIVE_PORT':str(self.target.server_port),'DASHBOARD_PORT':str(self.front.server_port)})
        self.environment.start()
        self.threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (self.target,self.front)]
        for thread in self.threads: thread.start()
        self.url = 'http://127.0.0.1:' + str(self.front.server_port)

    def tearDown(self):
        for server in (self.front,self.target): server.shutdown();server.server_close()
        for thread in self.threads: thread.join()
        self.environment.stop()

    def test_real_front_door_forwards_binary_upload_over_old_json_limit(self):
        raw = b'attachment\x00' * 200000
        request = Request(self.url+'/memory/api/attachments?record_id=resource-a&revision=1', data=raw,
            headers={'Content-Type':'application/octet-stream','X-File-Name':'%E7%AC%94%E8%AE%B0.txt',
                     'X-CSRF-Token':'fixture','Origin':self.url,'Sec-Fetch-Site':'same-origin'})
        with urlopen(request) as response: result=json.load(response)
        self.assertEqual(result, {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'name':'%E7%AC%94%E8%AE%B0.txt','site':'same-origin'})

    def test_other_mutations_keep_their_existing_small_limit(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/memory/api/records', data=b'x'*65537))
        self.assertEqual(error.exception.code,413)

    def test_unauthorized_uploads_are_rejected_without_waiting_for_the_body(self):
        good = {'Origin':self.url,'X-CSRF-Token':'fixture','X-File-Name':'note.txt','Content-Type':'application/octet-stream'}
        for changes, expected in [({'Origin':'https://other.test'},403),({'X-CSRF-Token':''},403),
                                  ({'X-File-Name':''},403),({'Sec-Fetch-Site':'cross-site'},403),
                                  ({'Content-Type':'text/plain'},415)]:
            headers = {**good, **changes}
            raw = ('POST /memory/api/attachments?record_id=resource-a&revision=1 HTTP/1.1\r\n'
                   f'Host: 127.0.0.1:{self.front.server_port}\r\nContent-Length: 2097152\r\n' +
                   ''.join(f'{key}: {value}\r\n' for key,value in headers.items()) + '\r\n').encode()
            with socket.create_connection(('127.0.0.1',self.front.server_port),timeout=2) as connection:
                connection.sendall(raw)
                self.assertIn(f' {expected} '.encode(),connection.recv(1024).split(b'\r\n')[0])


if __name__ == '__main__': unittest.main()
