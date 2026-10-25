"""Lightweight planner HTTP + device WebSocket process (no embedding model)."""
import argparse
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler
from local_http import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from planner_store import PlannerStore, client_operation_id

WEB = Path(__file__).resolve().parent / 'planner_web'

def open_backup_read_lease(database):
    """Keep WAL sidecars readable by the separate read-only backup mount.

    Opening happens in the writer service's writable filesystem, using SQL
    mode=ro. No read transaction remains open, so checkpoints are not blocked.
    """
    connection=sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    try:connection.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
    except Exception:
        connection.close();raise
    return connection

def bounded_json(raw):
    """Bound nesting before CPython's recursive decoder touches untrusted JSON."""
    if isinstance(raw,bytes):raw=raw.decode('utf-8')
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>65536:raise ValueError('Invalid JSON size')
    depth=0;quoted=False;escaped=False
    for char in raw:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '[{':
            depth+=1
            if depth>32:raise ValueError('JSON nesting exceeds 32 levels')
        elif char in ']}':depth-=1
    try:return json.loads(raw)
    except RecursionError:raise ValueError('Invalid JSON nesting')

def host_name(value):
    try: return urlsplit('//'+value).hostname
    except ValueError: return None

def authorize_device(path,headers,token,device,allowed_hosts):
    if path!='/planner/ws' or len(token)<64: return False
    try:
        if not hmac.compare_digest(headers.get('Authorization',''), 'Bearer '+token): return False
        if not hmac.compare_digest(headers.get('Device-Id',''),device): return False
        origin=headers.get('Origin')
        if origin:
            parsed=urlsplit(origin)
            if parsed.scheme!='https' or parsed.hostname not in allowed_hosts: return False
        return True
    except (TypeError,ValueError): return False

def process_device_message(store,device,raw):
    if not isinstance(raw,str) or len(raw.encode())>65536: raise ValueError('Message too large or binary')
    value=bounded_json(raw)
    if not isinstance(value,dict): raise ValueError('Object required')
    if value.get('type')=='ack':
        if set(value)-{'type','revision','ids'}: raise ValueError('Unsupported ACK fields')
        store.ack(device,value.get('revision'),value.get('ids'))
        return None
    if value.get('type')!='action': raise ValueError('Unsupported command')
    op_id=value.get('op_id','')
    try:
        if set(value)-{'type','op_id','action','task_id','occurrence_id','expected_revision','seconds','at'}: raise ValueError('Unsupported action fields')
        result=store.action(device,**{k:v for k,v in value.items() if k!='type'})
        return {'type':'result',**result}
    except (ValueError,KeyError,TypeError):
        with store.connection() as c:revision=c.execute('SELECT revision FROM planner_meta').fetchone()[0]
        return {'type':'result','op_id':op_id if isinstance(op_id,str) and len(op_id)<=64 else '', 'ok':False,'revision':revision,'error':'Invalid action or stale task; refresh and retry'}

def command(store,value):
    if not isinstance(value,dict): raise ValueError('Object required')
    value=dict(value); op=value.pop('op',None)
    if op=='create': return store.create(**value)
    if op=='update': return store.update(**value)
    if op=='complete':
        return store.action('browser',op_id=client_operation_id('web',value.pop('request_id')),action='complete',**value)
    if op=='cancel':
        return store.update(value['task_id'],{'status':'cancelled'},value['expected_revision'],value['request_id'])
    if op=='snooze':
        # Web/MCP action IDs are isolated from the device operation namespace.
        return store.action('browser',op_id=client_operation_id('web',value.pop('request_id')),action='snooze',**value)
    raise ValueError('Unsupported operation')

def create_http_server(store,host='127.0.0.1',port=8769,allowed_hosts=('localhost','127.0.0.1'),secure_cookie=True):
    sessions={};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def respond(self,value,code=200,kind='application/json; charset=utf-8',cookie=None):
            body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:self.send_header('Set-Cookie',cookie)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(body)
        def valid_host(self): return host_name(self.headers.get('Host','')) in allowed_hosts
        def do_GET(self):
            if not self.valid_host(): return self.respond({'error':'Invalid host'},403)
            path=urlsplit(self.path).path
            try:
                if path=='/api/session':
                    sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
                    with lock:
                        for key in list(sessions):
                            if sessions[key][1]<time.time():del sessions[key]
                        if len(sessions)>=1000:sessions.pop(next(iter(sessions)))
                        sessions[sid]=(csrf,time.time()+28800)
                    return self.respond({'csrf':csrf,**store.context()},cookie='planner_session='+sid+'; Path=/memory/planner/; HttpOnly; SameSite=Strict; Max-Age=28800'+('; Secure' if secure_cookie else ''))
                if path=='/api/context':return self.respond(store.context())
                if path=='/api/tasks':return self.respond({'tasks':store.list(),**store.context()})
                if path=='/api/archive-choices':return self.respond({'records':store.archive_choices()})
                if path=='/api/status':return self.respond({'ok':True,'service':'planner'})
                if path=='/api/delivery':
                    params=parse_qs(urlsplit(self.path).query)
                    task_id=params.get('task_id',[''])[0]
                    return self.respond(store.delivery(task_id,os.getenv('PLANNER_DEVICE_ID','02:00:00:00:00:01'),chosen_date=params.get('chosen_date',[None])[0]))
                files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
                if path not in files:return self.respond({'error':'Not found'},404)
                name,kind=files[path];return self.respond((WEB/name).read_bytes(),kind=kind+'; charset=utf-8')
            except (ValueError,KeyError):self.respond({'error':'Invalid request'},400)
            except OSError:self.respond({'error':'Service unavailable'},503)
        def do_POST(self):
            try: length=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.respond({'error':'Invalid length'},400)
            if length>65536 or length<0:
                self.close_connection=True;return self.respond({'error':'Too large'},413)
            if not self.valid_host():return self.respond({'error':'Invalid host'},403)
            origin=urlsplit(self.headers.get('Origin',''))
            cookie=dict(piece.strip().split('=',1) for piece in self.headers.get('Cookie','').split(';') if '=' in piece)
            with lock:session=sessions.get(cookie.get('planner_session',''))
            if not session or session[1]<time.time() or not hmac.compare_digest(session[0],self.headers.get('X-CSRF-Token','')) or origin.scheme!=('https' if secure_cookie else 'http') or origin.netloc!=self.headers.get('Host'):
                self.close_connection=True;return self.respond({'error':'Session, origin and CSRF token required'},403)
            if urlsplit(self.path).path!='/api/command':return self.respond({'error':'Not found'},404)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.respond({'error':'JSON required'},415)
            try:return self.respond(command(store,bounded_json(self.rfile.read(length))))
            except (ValueError,KeyError,TypeError):return self.respond({'error':'Invalid input or revision conflict; refresh and retry'},400)
        def do_DELETE(self): self.respond({'error':'History cannot be deleted'},405)
        def do_HEAD(self):self.do_GET()
    return ThreadingHTTPServer((host,port),Handler)

def create_websocket_server(store,host,port,token,device,allowed_hosts):
    from websockets.sync.server import serve
    from websockets.exceptions import ConnectionClosed
    def process_request(connection,request):
        if not authorize_device(request.path,request.headers,token,device,allowed_hosts):return connection.respond(403,'Forbidden\n')
    def handler(ws):
        signature=None
        try:
            while True:
                snap=store.snapshot(device)
                current=json.dumps({k:v for k,v in snap.items() if k!='server_time'},sort_keys=True,ensure_ascii=False)
                if current!=signature:
                    ws.send(json.dumps(snap,ensure_ascii=False,separators=(',',':')));signature=current
                try:raw=ws.recv(timeout=1)
                except TimeoutError:continue
                try:result=process_device_message(store,device,raw)
                except (ValueError,TypeError,json.JSONDecodeError):
                    ws.close(1008,'Invalid message');return
                if result:ws.send(json.dumps(result,separators=(',',':')))
        except ConnectionClosed:pass
    return serve(handler,host,port,process_request=process_request,max_size=65536,max_queue=8,ping_interval=20,ping_timeout=20,compression=None)

def run_websocket(store,host,port,token,device,allowed_hosts):
    with create_websocket_server(store,host,port,token,device,allowed_hosts) as server:server.serve_forever()

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--http-port',type=int,default=8769);p.add_argument('--ws-port',type=int,default=8770)
    args=p.parse_args();token=os.environ.get('PLANNER_DEVICE_TOKEN','');device=os.environ.get('PLANNER_DEVICE_ID','')
    if len(token)<64:raise SystemExit('PLANNER_DEVICE_TOKEN must contain at least 256 bits (64 hex characters)')
    if not device:raise SystemExit('PLANNER_DEVICE_ID is required for the legacy PC reminder service')
    hosts=set(os.getenv('PLANNER_ALLOWED_HOSTS','localhost,127.0.0.1').split(','))
    store=PlannerStore();lease=open_backup_read_lease(store.db_path)
    http=create_http_server(store,args.host,args.http_port,hosts)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:run_websocket(store,args.host,args.ws_port,token,device,hosts)
    finally:lease.close();http.shutdown();http.server_close()

if __name__=='__main__':main()
