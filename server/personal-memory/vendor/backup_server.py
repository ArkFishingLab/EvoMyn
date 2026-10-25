"""Same-origin backup administration. Expose only behind authenticated TLS Nginx."""
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler
from local_http import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from backup_manager import BackupManager

def load_json(raw):
    text=raw.decode('utf-8');depth=0;quoted=False;escaped=False
    for char in text:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '[{':
            depth+=1
            if depth>32:raise ValueError('JSON too deep')
        elif char in ']}':depth-=1
    value=json.loads(text)
    if not isinstance(value,dict):raise ValueError('Object required')
    return value

def create_server(manager,host='127.0.0.1',port=8780,allowed_hosts=('localhost','127.0.0.1'),secure_cookie=True):
    sessions={};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def valid_host(self):
            try:return urlsplit('//'+self.headers.get('Host','')).hostname in allowed_hosts
            except ValueError:return False
        def headers_for(self,code,length,kind,download=None,cookie=None):
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(length))
            for key,value in {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"sandbox; default-src 'none'; frame-ancestors 'none'; base-uri 'none'"}.items():self.send_header(key,value)
            if cookie:self.send_header('Set-Cookie',cookie)
            if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers()
        def respond(self,value,code=200,cookie=None):
            raw=json.dumps(value,ensure_ascii=False).encode('utf-8');self.headers_for(code,len(raw),'application/json; charset=utf-8',cookie=cookie)
            if self.command!='HEAD':self.wfile.write(raw)
        def file(self,path,name,kind):
            with path.open('rb') as stream:
                self.headers_for(200,os.fstat(stream.fileno()).st_size,kind,download=name)
                if self.command!='HEAD':
                    while block:=stream.read(65536):self.wfile.write(block)
        def do_GET(self):
            if not self.valid_host():return self.respond({'error':'Invalid host'},403)
            path=urlsplit(self.path).path
            try:
                if path=='/api/session':
                    sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
                    with lock:
                        for key in list(sessions):
                            if sessions[key][1]<time.time():del sessions[key]
                        if len(sessions)>=1000:sessions.pop(next(iter(sessions)))
                        sessions[sid]=(csrf,time.time()+28800)
                    return self.respond({'csrf':csrf},cookie='backup_session='+sid+'; Path=/memory/backup/; HttpOnly; SameSite=Strict; Max-Age=28800'+('; Secure' if secure_cookie else ''))
                if path=='/api/state':return self.respond(manager.state())
                if path=='/api/status':return self.respond({'ok':True,'service':'backup'})
                if path.startswith('/api/download/'):
                    job_id=path[len('/api/download/'):]
                    return self.file(manager.download(job_id),'memory-'+job_id+'.mbackup','application/octet-stream')
                if path=='/restore-tool.py':return self.file(Path(__file__).with_name('restore_backup.py'),'restore_backup.py','text/plain; charset=utf-8')
                return self.respond({'error':'Not found'},404)
            except (FileNotFoundError,ValueError):return self.respond({'error':'备份文件不存在或已过期'},404)
            except (BrokenPipeError,ConnectionResetError):pass
            except (OSError,TypeError):return self.respond({'error':'备份服务暂时不可用'},503)
        def authorized(self):
            try:
                if not self.valid_host():return False
                origin=urlsplit(self.headers.get('Origin',''))
                cookie=dict(piece.strip().split('=',1) for piece in self.headers.get('Cookie','').split(';') if '=' in piece)
                with lock:session=sessions.get(cookie.get('backup_session',''))
                return bool(session and session[1]>=time.time() and hmac.compare_digest(session[0],self.headers.get('X-CSRF-Token','')) and origin.scheme==('https' if secure_cookie else 'http') and origin.netloc==self.headers.get('Host'))
            except (ValueError,TypeError):return False
        def do_POST(self):
            if not self.authorized():
                self.close_connection=True;return self.respond({'error':'请刷新会话后重试'},403)
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.respond({'error':'Invalid length'},400)
            if not 0<length<=65536:
                self.close_connection=True;return self.respond({'error':'请求内容过大或为空'},413)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.respond({'error':'JSON required'},415)
            path=urlsplit(self.path).path
            if path not in ('/api/config','/api/check','/api/run'):return self.respond({'error':'Not found'},404)
            try:
                value=load_json(self.rfile.read(length))
                if path=='/api/config':return self.respond(manager.save(value))
                if value:raise ValueError('请使用已保存的设置进行操作')
                if path=='/api/check':return self.respond(manager.check())
                return self.respond(manager.start(),202)
            except (UnicodeError,json.JSONDecodeError,RecursionError):return self.respond({'error':'请求格式不正确'},400)
            except ValueError as error:return self.respond({'error':str(error)[:180]},400)
            except RuntimeError as error:return self.respond({'error':str(error)[:180]},409)
            except OSError:return self.respond({'error':'设置未能保存，请检查服务器空间'},503)
        def do_HEAD(self):self.do_GET()
        def do_DELETE(self):self.respond({'error':'不支持此操作'},405)
        do_PUT=do_PATCH=do_DELETE
    return ThreadingHTTPServer((host,port),Handler)

def main():
    manager=BackupManager(os.getenv('BACKUP_HOME','/backup'),os.getenv('BACKUP_SOURCE','/state'),os.getenv('BACKUP_CONFIG','/config'))
    hosts=set(os.getenv('BACKUP_ALLOWED_HOSTS','127.0.0.1,localhost').split(','))
    server=create_server(manager,host='0.0.0.0',port=int(os.getenv('BACKUP_PORT','8780')),allowed_hosts=hosts)
    stop=threading.Event();threading.Thread(target=manager.schedule_forever,args=(stop,),daemon=True).start()
    print('Backup administration ready; configuration stays under user control',flush=True)
    try:server.serve_forever()
    finally:stop.set();server.server_close()

if __name__=='__main__':main()
