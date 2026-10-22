"""User-controlled backup configuration and single-worker daily scheduling."""
import copy
import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from backup_bundle import create_bundle, public_key_fingerprint
from backup_github import GitHubClient

CHINA=timezone(timedelta(hours=8))
UTC=timezone.utc
DEFAULTS={'repository':'','token':'','public_key':'','time':'03:00','enabled':False,'keep_daily':30,'keep_monthly':12,'last_scheduled_date':''}

def atomic_json(path,value):
    """Never truncate the last good settings/receipt on a failed write."""
    fd,name=tempfile.mkstemp(prefix='.write-',dir=path.parent)
    try:
        os.chmod(name,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def repository_name(value):
    if not isinstance(value,str):raise ValueError('请填写 GitHub 私有仓库地址')
    value=value.strip().rstrip('/')
    if value.startswith('https://github.com/'):
        parsed=urlsplit(value)
        if parsed.query or parsed.fragment or parsed.netloc!='github.com':raise ValueError('仓库地址格式不正确')
        value=parsed.path.lstrip('/')
    if value.endswith('.git'):value=value[:-4]
    if value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',value):raise ValueError('请使用 owner/repo 格式的 GitHub 仓库')
    if value and value.split('/')[1] in ('.','..'):raise ValueError('仓库地址格式不正确')
    return value

def stamp(value=None):return (value or datetime.now(UTC)).astimezone(UTC).isoformat(timespec='seconds')

class BackupManager:
    def __init__(self,root,state_root,config_root,client_factory=GitHubClient,bundle_factory=create_bundle):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);os.chmod(self.root,0o700)
        self.files=self.root/'files';self.files.mkdir(exist_ok=True);os.chmod(self.files,0o700)
        self.state_root=Path(state_root);self.config_root=Path(config_root)
        self.client_factory=client_factory;self.bundle_factory=bundle_factory
        self.lock=threading.RLock();self.thread=None;self.active=None
        self.config=copy.deepcopy(DEFAULTS)
        settings=self.root/'settings.json';history=self.root/'history.json'
        if settings.exists():self.config.update(json.loads(settings.read_text(encoding='utf-8')))
        self.history=json.loads(history.read_text(encoding='utf-8')) if history.exists() else []
        for item in self.history:
            if item['status']=='running':item.update(status='failed',error='服务重启，上一份备份未完成，请重新备份')
        if history.exists():atomic_json(history,self.history)

    def ready(self,config=None):
        c=config or self.config
        return bool(c['repository'] and c['token'] and c['public_key'])

    def save(self,changes):
        if not isinstance(changes,dict) or set(changes)-{'repository','token','public_key','time','enabled','keep_daily','keep_monthly'}:raise ValueError('备份设置字段不正确')
        with self.lock:
            if self.active:raise RuntimeError('正在备份，请完成后再修改设置')
            c=copy.deepcopy(self.config)
            for key,value in changes.items():
                if key=='repository':c[key]=repository_name(value)
                elif key=='token':
                    if not isinstance(value,str) or len(value)>255 or (value and not re.fullmatch(r'[A-Za-z0-9_.-]{20,255}',value)):raise ValueError('GitHub Token 格式不正确')
                    if value:c[key]=value
                elif key=='public_key':
                    if not isinstance(value,str) or len(value)>8192:raise ValueError('恢复公钥格式不正确')
                    if value:
                        public_key_fingerprint(value);c[key]=value
                elif key=='enabled':
                    if type(value) is not bool:raise ValueError('自动备份开关不正确')
                    c[key]=value
                elif key=='time':
                    if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ValueError('请选择有效的备份时间')
                    c[key]=value
                else:
                    if type(value) is not int or not 1<=value<=(90 if key=='keep_daily' else 24):raise ValueError('版本保留数量超出范围')
                    c[key]=value
            if c['enabled'] and not self.ready(c):raise ValueError('启用前请保存仓库、Token 和恢复公钥')
            atomic_json(self.root/'settings.json',c);self.config=c
            return self.state()

    def _next_run(self,now):
        if not self.config['enabled'] or not self.ready():return None
        local=now.astimezone(CHINA);hour,minute=map(int,self.config['time'].split(':'))
        due=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
        if self.config['last_scheduled_date']==local.date().isoformat():due+=timedelta(days=1)
        elif due<local:due=local
        return stamp(due)

    def state(self):
        with self.lock:
            config={k:self.config[k] for k in ('repository','time','enabled','keep_daily','keep_monthly')}
            config.update(token_configured=bool(self.config['token']),key_fingerprint=public_key_fingerprint(self.config['public_key']) if self.config['public_key'] else '')
            history=copy.deepcopy(self.history)
            for item in history:item['local_available']=self._file(item['id']).is_file() and not self._file(item['id']).is_symlink()
            return {'service_ok':True,'config':config,'running':bool(self.active),'last_success':next((r for r in history if r['status']=='success'),None),'next_run':self._next_run(datetime.now(UTC)),'history':history}

    def check(self):
        with self.lock:
            if self.active:raise RuntimeError('正在备份，请稍后再验证')
            c=copy.deepcopy(self.config)
        if not c['repository'] or not c['token']:raise ValueError('请先保存仓库地址和 GitHub Token')
        try:self.client_factory(c['token'],c['repository']).check()
        except Exception:raise ValueError('连接失败，请检查私有仓库地址、Token 权限和服务器网络') from None
        return {'ok':True,'repository':c['repository'],'message':'私有仓库连接正常'}

    def _file(self,job_id):
        if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('备份编号不正确')
        return self.files/(job_id+'.mbackup')

    def download(self,job_id):
        with self.lock:
            path=self._file(job_id)
            if not any(r['id']==job_id and r['status']!='running' for r in self.history):raise FileNotFoundError()
            if path.is_symlink() or not path.is_file():raise FileNotFoundError()
            return path

    def start(self,trigger='manual'):
        with self.lock:
            if self.active:raise RuntimeError('已有备份正在进行')
            if not self.ready():raise ValueError('请先保存仓库、Token 和恢复公钥')
            job_id=secrets.token_hex(16);config=copy.deepcopy(self.config)
            record={'id':job_id,'created_at':stamp(),'status':'running','trigger':trigger,'repository':config['repository'],'size':0,'sha256':'','url':'','error':''}
            self.history.insert(0,record);self.history=self.history[:100]
            atomic_json(self.root/'history.json',self.history);self.active=job_id
            self.thread=threading.Thread(target=self._work,args=(job_id,config),daemon=True)
            try:self.thread.start()
            except Exception:
                self.active=None;record.update(status='failed',error='备份任务未能启动，请稍后重试');atomic_json(self.root/'history.json',self.history);raise RuntimeError('备份任务未能启动') from None
            return self.state()

    def _work(self,job_id,config):
        result=None;metadata={};warning=''
        try:
            output=self._file(job_id)
            metadata=self.bundle_factory(self.state_root,self.config_root,output,config['public_key'])
            client=self.client_factory(config['token'],config['repository'])
            result=client.upload(output,metadata)
            if not result.get('verified'):raise ValueError('Upload was not verified')
            try:client.prune(config['keep_daily'],config['keep_monthly'])
            except Exception:warning='备份已上传并校验，旧版本清理未完成'
        except Exception:
            result=None
        with self.lock:
            record=next(r for r in self.history if r['id']==job_id)
            record.update(status='success' if result else 'failed',finished_at=stamp(),size=metadata.get('size',0),sha256=metadata.get('sha256',''))
            if result:record.update(url=result.get('url',''),release_id=result.get('release_id'),warning=warning)
            else:record['error']='备份未完成，请检查仓库权限、网络和服务器空间；已有备份保留'
            self.active=None
            # Retain seven local encrypted files for downloads, independently of cloud retention.
            for item in self.history[7:]:
                path=self._file(item['id'])
                if path.is_file() and not path.is_symlink():
                    try:path.unlink()
                    except OSError:pass
            atomic_json(self.root/'history.json',self.history)

    def wait(self,timeout=5):
        if self.thread:self.thread.join(timeout)

    def tick(self,now=None):
        now=now or datetime.now(UTC)
        with self.lock:
            if self.active or not self.config['enabled'] or not self.ready():return False
            local=now.astimezone(CHINA);date=local.date().isoformat()
            hour,minute=map(int,self.config['time'].split(':'))
            if self.config['last_scheduled_date']==date or (local.hour,local.minute)<(hour,minute):return False
            self.config['last_scheduled_date']=date;atomic_json(self.root/'settings.json',self.config)
            self.start('scheduled');return True

    def schedule_forever(self,stop):
        while not stop.is_set():
            try:self.tick()
            except Exception:pass  # Do not log credentials or terminate scheduling on transient disk errors.
            stop.wait(30)
