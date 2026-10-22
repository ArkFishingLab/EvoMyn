"""Independent, transactional planner. Standard library only; never imports Mnemosyne."""
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
CHINA = timezone(timedelta(hours=8))

def tzinfo(name):
    if name == 'Asia/Shanghai': return CHINA
    try: return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError): raise ValueError('Unknown timezone')

def clip(value, size):
    return value.encode('utf-8')[:size].decode('utf-8', errors='ignore')

def client_operation_id(namespace,request_id):
    """Stable, bounded IDs for online clients; device IDs pass through untouched."""
    if namespace not in ('web','mcp') or not isinstance(request_id,str) or not re.fullmatch(r'[\x21-\x7e]{1,128}',request_id):
        raise ValueError('Unique ASCII request_id required (1–128 characters)')
    return namespace+'-'+hashlib.sha256(request_id.encode('ascii')).hexdigest()[:48]

class PlannerStore:
    def __init__(self, database=None, clock=time.time):
        self.db_path = Path(database or Path(os.getenv('PERSONAL_ARCHIVE_HOME', '/state')) / 'data/mnemosyne.db').resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connection() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS planner_meta (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
            INSERT OR IGNORE INTO planner_meta VALUES(1,0);
            CREATE TABLE IF NOT EXISTS planner_tasks (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                status TEXT NOT NULL, due_at INTEGER, repeat TEXT NOT NULL, timezone TEXT NOT NULL,
                remind INTEGER NOT NULL, revision INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS planner_links (
                task_id TEXT NOT NULL REFERENCES planner_tasks(id), archive_id TEXT NOT NULL REFERENCES personal_archive_records(id),
                PRIMARY KEY(task_id,archive_id));
            CREATE TABLE IF NOT EXISTS planner_history (task_id TEXT NOT NULL REFERENCES planner_tasks(id), revision INTEGER NOT NULL,
                payload TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(task_id,revision));
            CREATE TABLE IF NOT EXISTS planner_requests (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS planner_occurrences (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES planner_tasks(id),
                task_revision INTEGER NOT NULL, at INTEGER NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS planner_occurrence_time ON planner_occurrences(at);
            CREATE TABLE IF NOT EXISTS planner_sent (device TEXT NOT NULL, revision INTEGER NOT NULL, ids TEXT NOT NULL, PRIMARY KEY(device,revision));
            CREATE TABLE IF NOT EXISTS planner_acks (device TEXT NOT NULL, revision INTEGER NOT NULL, occurrence_id TEXT NOT NULL REFERENCES planner_occurrences(id),
                at INTEGER NOT NULL, PRIMARY KEY(device,revision,occurrence_id));
            ''')
            c.execute('BEGIN IMMEDIATE')
            columns={r[1] for r in c.execute('PRAGMA table_info(planner_tasks)')}
            for column in ('start_at','end_at','remind_at'):
                if column not in columns:c.execute('ALTER TABLE planner_tasks ADD COLUMN '+column+' INTEGER')
            if 'acted_at' not in {r[1] for r in c.execute('PRAGMA table_info(planner_occurrences)')}:
                c.execute('ALTER TABLE planner_occurrences ADD COLUMN acted_at INTEGER')
            if 'parent_occurrence_id' not in {r[1] for r in c.execute('PRAGMA table_info(planner_occurrences)')}:
                c.execute('ALTER TABLE planner_occurrences ADD COLUMN parent_occurrence_id TEXT REFERENCES planner_occurrences(id)')

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=10000')
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally: c.close()

    def context(self):
        now = int(self.clock())
        return {'server_time':now, 'utc':datetime.fromtimestamp(now,UTC).isoformat(), 'local_date':datetime.fromtimestamp(now,CHINA).date().isoformat(), 'timezone':'Asia/Shanghai'}

    @staticmethod
    def parse_time(value, zone):
        if value is None: return None
        if isinstance(value, bool): raise ValueError('Time must be an exact datetime or UTC seconds')
        if isinstance(value, int): stamp = value
        elif isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?',value):
            try:
                dt = datetime.fromisoformat(value.replace('Z','+00:00'))
                zoneobj = tzinfo(zone)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=zoneobj)
                    if dt.replace(fold=0).utcoffset() != dt.replace(fold=1).utcoffset(): raise ValueError('Ambiguous or nonexistent local time; provide UTC offset')
                stamp = int(dt.timestamp())
            except (OverflowError, ValueError): raise ValueError('Invalid exact datetime')
        else: raise ValueError('Exact YYYY-MM-DDTHH:MM datetime required; clarify vague dates/times')
        if not 946684800 <= stamp <= 4102444799: raise ValueError('Datetime outside 2000–2099')
        return stamp

    def _get(self, c, task_id):
        row = c.execute('SELECT * FROM planner_tasks WHERE id=?',(task_id,)).fetchone()
        if not row: raise KeyError('Task not found')
        task = dict(row)
        task['remind'] = bool(task['remind'])
        task['archive_links'] = [r[0] for r in c.execute('SELECT archive_id FROM planner_links WHERE task_id=? ORDER BY archive_id',(task_id,))]
        return task

    def get(self, task_id):
        with self.connection() as c: return self._get(c,task_id)

    def list(self, status=None, kind=None, from_at=None, to_at=None, query=None):
        with self.connection() as c:
            items = [self._get(c,r[0]) for r in c.execute('SELECT id FROM planner_tasks ORDER BY COALESCE(start_at,due_at,remind_at) IS NULL,COALESCE(start_at,due_at,remind_at),created_at,id')]
        def in_range(t):
            anchor=next((t[k] for k in ('start_at','due_at','remind_at') if t[k] is not None),None)
            return (from_at is None or anchor is not None and anchor>=from_at) and (to_at is None or anchor is not None and anchor<=to_at)
        return [t for t in items if (status is None or t['status']==status) and (kind is None or t['kind']==kind) and (query is None or query.casefold() in (t['title']+' '+t['body']).casefold()) and in_range(t)]

    def history(self, task_id):
        with self.connection() as c:
            self._get(c,task_id)
            return [json.loads(r[0]) for r in c.execute('SELECT payload FROM planner_history WHERE task_id=? ORDER BY revision',(task_id,))]

    def occurrence_history(self,task_id):
        """Read-only, bounded instance audit for exactly one existing task."""
        with closing(sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True,timeout=10)) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN')
            if not c.execute('SELECT 1 FROM planner_tasks WHERE id=?',(task_id,)).fetchone():raise KeyError('Task not found')
            return [dict(row) for row in c.execute('SELECT id,status,at,task_revision,parent_occurrence_id,acted_at FROM planner_occurrences WHERE task_id=? ORDER BY COALESCE(acted_at,at) DESC,at DESC,id DESC LIMIT 100',(task_id,))]

    def archive_choices(self):
        """Only existing archive IDs and titles, with no attachment/body metadata."""
        with self.connection() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='personal_archive_records' AND type='table'").fetchone():return []
            result=[]
            for row in c.execute('SELECT id,payload FROM personal_archive_records ORDER BY id'):
                try:title=json.loads(row['payload']).get('title',row['id'])
                except (ValueError,AttributeError,RecursionError):title=row['id']
                result.append({'id':row['id'],'title':clip(title if isinstance(title,str) else row['id'],384)})
            return result

    @staticmethod
    def _bump(c): c.execute('UPDATE planner_meta SET revision=revision+1 WHERE id=1')

    def _request(self, c, request_id, data, operation):
        if not isinstance(request_id,str) or not re.fullmatch(r'[\x21-\x7e]{1,128}',request_id): raise ValueError('Unique ASCII request_id required (1–128 characters)')
        fingerprint = hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        old = c.execute('SELECT * FROM planner_requests WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint: raise ValueError('request_id reused with different arguments')
            return json.loads(old['result'])
        result = operation()
        c.execute('INSERT INTO planner_requests VALUES(?,?,?)',(request_id,fingerprint,json.dumps(result,ensure_ascii=False)))
        return result

    def _validate(self, c, task):
        if task['kind'] not in ('note','task','event'): raise ValueError('kind must be note/task/event')
        if task['status'] not in ('pending','completed','cancelled'): raise ValueError('Invalid status')
        if task['repeat'] not in ('none','daily','weekly'): raise ValueError('repeat must be none/daily/weekly')
        for key,limit in [('title',384),('body',32768)]:
            if not isinstance(task[key],str) or len(task[key].encode())>limit or (key=='title' and not task[key].strip()): raise ValueError(f'Invalid {key} (UTF-8 maximum {limit} bytes)')
        tzinfo(task['timezone'])
        for field in ('due_at','start_at','end_at','remind_at'):
            task[field] = self.parse_time(task.get(field),task['timezone'])
        if task['end_at'] is not None and (task['start_at'] is None or task['end_at']<task['start_at']):raise ValueError('end_at requires start_at and cannot precede it')
        anchor=next((task[k] for k in ('remind_at','start_at','due_at') if task[k] is not None),None)
        if not isinstance(task['remind'],bool): raise ValueError('remind must be boolean')
        if task['repeat']!='none' and anchor is None: raise ValueError('Repeating tasks require an exact datetime')
        if task['remind'] and anchor is None: raise ValueError('Reminder requires an exact datetime; ask user for time')
        links = task['archive_links']
        if not isinstance(links,list) or len(links)>100 or any(not isinstance(x,str) for x in links): raise ValueError('archive_links must be record ID list')
        task['archive_links'] = sorted(set(links))
        for linked in links:
            try: exists = c.execute('SELECT 1 FROM personal_archive_records WHERE id=?',(linked,)).fetchone()
            except sqlite3.OperationalError: exists = None
            if not exists: raise ValueError('Linked archive record does not exist')

    def _save(self,c,task):
        self._validate(c,task)
        keys = ('id','kind','title','body','status','due_at','repeat','timezone','remind','revision','created_at','updated_at','start_at','end_at','remind_at')
        c.execute('INSERT INTO planner_tasks ('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(task[k] for k in keys)) if task['revision']==1 else c.execute('UPDATE planner_tasks SET '+','.join(k+'=?' for k in keys[1:])+' WHERE id=?',tuple(task[k] for k in keys[1:])+(task['id'],))
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='personal_archive_records'").fetchone():
            c.execute('DELETE FROM planner_links WHERE task_id=?',(task['id'],))
        for linked in task['archive_links']: c.execute('INSERT INTO planner_links VALUES(?,?)',(task['id'],linked))
        c.execute('INSERT INTO planner_history VALUES(?,?,?,?)',(task['id'],task['revision'],json.dumps(task,ensure_ascii=False),int(self.clock())))
        self._bump(c)
        return task

    def create(self, title, body='', kind='task', due_at=None, repeat='none', timezone='Asia/Shanghai', remind=False, archive_links=None, request_id=None,start_at=None,end_at=None,remind_at=None):
        args = dict(title=title,body=body,kind=kind,due_at=due_at,repeat=repeat,timezone=timezone,remind=remind,archive_links=archive_links,start_at=start_at,end_at=end_at,remind_at=remind_at)
        with self.connection() as c:
            def operation():
                task = dict(args,id='plan-'+uuid4().hex,status='pending',revision=1,created_at=int(self.clock()),updated_at=int(self.clock()))
                task['archive_links'] = archive_links or []
                return self._save(c,task)
            return self._request(c,'mcp:'+request_id if isinstance(request_id,str) else request_id,{'op':'create',**args},operation)

    def update(self,task_id,changes,expected_revision,request_id):
        if not isinstance(changes,dict) or not changes or set(changes)-{'kind','title','body','status','due_at','repeat','timezone','remind','archive_links','start_at','end_at','remind_at'}: raise ValueError('Invalid task changes')
        with self.connection() as c:
            def operation():
                task = self._get(c,task_id)
                if type(expected_revision) is not int or task['revision'] != expected_revision: raise ValueError('Revision conflict; read task again')
                task.update(changes)
                task['revision'] += 1
                task['updated_at'] = int(self.clock())
                return self._save(c,task)
            return self._request(c,'mcp:'+request_id if isinstance(request_id,str) else request_id,{'op':'update','id':task_id,'changes':changes,'revision':expected_revision},operation)

    def _occurrences(self,c,now):
        for row in c.execute("SELECT * FROM planner_tasks WHERE status='pending' AND (remind=1 OR repeat!='none') AND COALESCE(remind_at,start_at,due_at) IS NOT NULL").fetchall():
            t = dict(row)
            anchor=next(t[k] for k in (('remind_at','start_at','due_at') if t['remind'] else ('start_at','due_at','remind_at')) if t[k] is not None)
            start = datetime.fromtimestamp(anchor,tzinfo(t['timezone']))
            step = {'daily':1,'weekly':7}.get(t['repeat'])
            if step:
                localnow = datetime.fromtimestamp(now-300,tzinfo(t['timezone']))
                n = max(0, (localnow.date()-start.date()).days//step-1)
                dates = (int((start+timedelta(days=k*step)).timestamp()) for k in range(n,n+12))
            else: dates = [anchor]
            for at in dates:
                if now-300 <= at <= now+7*86400:
                    oid=f"{t['id']}:{t['revision']}:{at}"
                    c.execute("INSERT OR IGNORE INTO planner_occurrences (id,task_id,task_revision,at,status,source) VALUES(?,?,?,?,'pending','base')",(oid,t['id'],t['revision'],at))
        return [dict(r) for r in c.execute("SELECT o.*,t.title FROM planner_occurrences o JOIN planner_tasks t ON t.id=o.task_id AND t.revision=o.task_revision WHERE t.status='pending' AND t.remind=1 AND o.status='pending' AND o.at BETWEEN ? AND ? ORDER BY o.at,o.id",(now-300,now+7*86400))]

    def snapshot(self,device):
        now=int(self.clock())
        with self.connection() as c:
            return self._snapshot(c,device,now)

    def _snapshot(self,c,device,now):
        occurrences=self._occurrences(c,now)
        all_tasks=[dict(r) for r in c.execute("SELECT id,title,body,kind,status,revision,repeat,COALESCE(start_at,due_at) AS due_at FROM planner_tasks WHERE status='pending' ORDER BY due_at IS NULL,due_at,id")]
        byid={t['id']:t for t in all_tasks}
        order=list(dict.fromkeys([o['task_id'] for o in occurrences]+[t['id'] for t in all_tasks]))
        tasks=[{**byid[i],'body':clip(byid[i]['body'],768)} for i in order[:32]]
        allowed={t['id'] for t in tasks}
        reminders=[{'id':o['id'],'task_id':o['task_id'],'task_revision':o['task_revision'],'title':o['title'],'at':o['at']} for o in occurrences if o['task_id'] in allowed][:64]
        closed=[dict(r) for r in c.execute("SELECT o.id,o.task_id FROM planner_occurrences o JOIN planner_tasks t ON t.id=o.task_id AND t.revision=o.task_revision WHERE t.status='pending' AND o.status IN ('completed','dismissed','snoozed') AND COALESCE(o.acted_at,o.at)>=? AND o.task_id IN ("+','.join('?' for _ in allowed)+") ORDER BY COALESCE(o.acted_at,o.at) DESC,o.at DESC,o.id LIMIT 129",(now-7*86400,*sorted(allowed)))] if allowed else []
        snap={'type':'snapshot','revision':c.execute('SELECT revision FROM planner_meta').fetchone()[0],'server_time':now,'timezone':'Asia/Shanghai','tasks':tasks,'reminders':reminders,'closed_reminders':[r['id'] for r in closed[:128]],'truncated':len(all_tasks)>len(tasks) or len(occurrences)>len(reminders) or len(closed)>128 or any(len(t['body'].encode())>768 for t in all_tasks)}
        while len(json.dumps(snap,ensure_ascii=False).encode())>65536:
            snap['truncated']=True
            if reminders: reminders.pop()
            elif tasks:
                removed=tasks.pop()['id']
                snap['closed_reminders']=[r['id'] for r in closed[:128] if r['task_id']!=removed and any(t['id']==r['task_id'] for t in tasks)]
        ids=[r['id'] for r in reminders]
        c.execute('INSERT OR REPLACE INTO planner_sent VALUES(?,?,?)',(device,snap['revision'],json.dumps(ids)))
        c.execute('DELETE FROM planner_sent WHERE device=? AND revision<?',(device,snap['revision']-100))
        return snap

    def ack(self,device,revision,ids):
        if type(revision) is not int or not isinstance(ids,list) or len(ids)>64 or any(not isinstance(i,str) for i in ids): raise ValueError('Invalid ACK')
        with self.connection() as c:
            row=c.execute('SELECT ids FROM planner_sent WHERE device=? AND revision=?',(device,revision)).fetchone()
            if not row or set(ids)-set(json.loads(row[0])): raise ValueError('ACK is not for sent occurrences')
            for oid in ids: c.execute('INSERT OR IGNORE INTO planner_acks VALUES(?,?,?,?)',(device,revision,oid,int(self.clock())))
        return {'ok':True}

    def _occurrence_root(self,c,occurrence_id):
        row=c.execute("WITH RECURSIVE parents(id,parent_occurrence_id) AS (SELECT id,parent_occurrence_id FROM planner_occurrences WHERE id=? UNION SELECT o.id,o.parent_occurrence_id FROM planner_occurrences o JOIN parents p ON o.id=p.parent_occurrence_id) SELECT id FROM parents WHERE parent_occurrence_id IS NULL LIMIT 1",(occurrence_id,)).fetchone()
        return row[0] if row else occurrence_id

    def _completion_candidate(self,c,task,now,chosen_date=None):
        if chosen_date is not None:
            if not isinstance(chosen_date,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',chosen_date):raise ValueError('chosen_date requires exact YYYY-MM-DD')
            target=date.fromisoformat(chosen_date)
            if not 2000<=target.year<=2099:raise ValueError('chosen_date outside 2000–2099')
        else:target=datetime.fromtimestamp(now,tzinfo(task['timezone'])).date()
        if task['repeat']=='none' or task['status']!='pending':return None,None
        zone=tzinfo(task['timezone']);step={'daily':1,'weekly':7}[task['repeat']]
        calendar_start=datetime.fromtimestamp(next(task[k] for k in ('start_at','due_at','remind_at') if task[k] is not None),zone)
        alarm_start=datetime.fromtimestamp(next(task[k] for k in (('remind_at','start_at','due_at') if task['remind'] else ('start_at','due_at','remind_at')) if task[k] is not None),zone)
        difference=(target-calendar_start.date()).days
        if difference<0 or chosen_date is not None and difference%step:return None,None
        n=difference//step
        while n>=0:
            at=int((alarm_start+timedelta(days=n*step)).timestamp());oid=f"{task['id']}:{task['revision']}:{at}"
            c.execute("INSERT OR IGNORE INTO planner_occurrences (id,task_id,task_revision,at,status,source) VALUES(?,?,?,?,'pending','base')",(oid,task['id'],task['revision'],at))
            base=c.execute('SELECT status FROM planner_occurrences WHERE id=?',(oid,)).fetchone()
            if base['status']!='completed':
                row=c.execute("WITH RECURSIVE family(id) AS (SELECT ? UNION SELECT o.id FROM planner_occurrences o JOIN family f ON o.parent_occurrence_id=f.id) SELECT o.id,o.task_id,o.task_revision,o.at,o.status,o.source,o.acted_at FROM planner_occurrences o JOIN family f ON f.id=o.id WHERE o.task_id=? AND o.task_revision=? AND o.status!='completed' ORDER BY CASE o.status WHEN 'fired' THEN 0 WHEN 'pending' THEN 1 WHEN 'dismissed' THEN 2 ELSE 3 END,o.at DESC LIMIT 1",(oid,task['id'],task['revision'])).fetchone()
                if row:return {**dict(row),'title':task['title']},(calendar_start+timedelta(days=n*step)).date().isoformat()
            if chosen_date is not None:break
            n-=1
        return None,None

    def delivery(self,task_id,device,occurrence_id=None,chosen_date=None):
        now=int(self.clock())
        with self.connection() as c:
            task=self._get(c,task_id)
            snap=self._snapshot(c,device,now)
            pending=c.execute("SELECT id,task_id,task_revision,at,status FROM planner_occurrences WHERE task_id=? AND task_revision=? AND status='pending' AND at BETWEEN ? AND ? ORDER BY at,id LIMIT 1",(task_id,task['revision'],now-300,now+7*86400)).fetchone() if task['status']=='pending' else None
            next_instance={**dict(pending),'title':task['title']} if pending else None
            requested=next((r for r in snap['reminders'] if r['task_id']==task_id and (occurrence_id is None or r['id']==occurrence_id)),None)
            acked=bool(requested and c.execute('SELECT 1 FROM planner_acks WHERE device=? AND revision=? AND occurrence_id=?',(device,snap['revision'],requested['id'])).fetchone())
            fired=c.execute("SELECT id,task_id,task_revision,at,status,source,acted_at FROM planner_occurrences WHERE task_id=? AND task_revision=? AND status='fired' AND COALESCE(acted_at,at)>=? ORDER BY COALESCE(acted_at,at) DESC,at DESC,id LIMIT 1",(task_id,task['revision'],now-7*86400)).fetchone() if task['status']=='pending' else None
            recent=dict(fired) if fired else None
            candidate,calendar_date=self._completion_candidate(c,task,now,chosen_date)
            current=candidate if chosen_date is not None else recent or candidate or (next_instance if task['repeat']=='none' else None)
            if current and current is not candidate:
                root=self._occurrence_root(c,current['id']);rootrow=c.execute('SELECT at FROM planner_occurrences WHERE id=?',(root,)).fetchone()
                zone=tzinfo(task['timezone'])
                origin=datetime.fromtimestamp(next(task[k] for k in ('start_at','due_at','remind_at') if task[k] is not None),zone)
                alarm=datetime.fromtimestamp(next(task[k] for k in (('remind_at','start_at','due_at') if task['remind'] else ('start_at','due_at','remind_at')) if task[k] is not None),zone)
                elapsed=(datetime.fromtimestamp(rootrow['at'],zone).date()-alarm.date()).days
                calendar_date=(origin+timedelta(days=elapsed if task['repeat']!='none' else 0)).date().isoformat()
            return {'saved':True,'device_scheduled':acked,'occurrence_id':requested['id'] if requested else None,'revision':snap['revision'],'next_occurrence_id':next_instance['id'] if next_instance else None,'next_occurrence':next_instance,'recent_fired_occurrence_id':recent['id'] if recent else None,'current_occurrence_id':current['id'] if current else None,'current_occurrence':current,'current_occurrence_date':calendar_date,'chosen_date':chosen_date,'task':task}

    def action(self,device,op_id,action,task_id,expected_revision,occurrence_id=None,seconds=600,at=None):
        if not isinstance(op_id,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,64}',op_id): raise ValueError('Invalid op_id')
        args=dict(action=action,task_id=task_id,expected_revision=expected_revision,occurrence_id=occurrence_id,seconds=seconds,at=at)
        with self.connection() as c:
            def operation():
                task=self._get(c,task_id)
                if type(expected_revision) is not int or expected_revision!=task['revision']: raise ValueError('Revision conflict; read task again')
                if action not in ('complete','cancel','dismiss','snooze','fired'): raise ValueError('Unsupported action')
                if action=='cancel' or (action=='complete' and task['repeat']=='none'):
                    if task['status']!='pending': raise ValueError('Task is not pending')
                    task.update(status='cancelled' if action=='cancel' else 'completed',revision=task['revision']+1,updated_at=int(self.clock()))
                    self._save(c,task)
                else:
                    self._occurrences(c,int(self.clock()))
                    occ=c.execute('SELECT * FROM planner_occurrences WHERE id=? AND task_id=? AND task_revision=?',(occurrence_id,task_id,expected_revision)).fetchone()
                    if not occ: raise ValueError('Occurrence not found or stale')
                    if task['status']!='pending': raise ValueError('Task is not pending')
                    state=occ['status']
                    no_op=(action=='fired' and state!='pending') or (action=='dismiss' and state in ('completed','dismissed','snoozed')) or (action=='complete' and state=='completed')
                    if no_op:return {'op_id':op_id,'ok':True,'revision':c.execute('SELECT revision FROM planner_meta').fetchone()[0]}
                    if action=='snooze' and state=='completed':raise ValueError('Completed occurrence cannot be snoozed')
                    if action=='snooze':
                        if type(seconds) is not int or not 60<=seconds<=604800: raise ValueError('Snooze seconds must be 60–604800')
                        target=int(self.clock())+seconds if at is None else at
                        if type(target) is not int or abs(target-int(self.clock()))>604800: raise ValueError('Snooze target outside seven days')
                        if c.execute('SELECT 1 FROM planner_occurrences WHERE id=?',('snooze-'+op_id,)).fetchone():
                            raise ValueError('Snooze operation ID collision; already owned by another request')
                        c.execute("INSERT INTO planner_occurrences (id,task_id,task_revision,at,status,source,parent_occurrence_id) VALUES(?,?,?,?,'pending','snooze',?)",('snooze-'+op_id,task_id,expected_revision,target,occurrence_id))
                    # A fired occurrence stays durable for later dismiss/snooze actions.
                    c.execute('UPDATE planner_occurrences SET status=?,acted_at=? WHERE id=?',({'complete':'completed','fired':'fired','dismiss':'dismissed','snooze':'snoozed'}[action],int(self.clock()),occurrence_id))
                    if action=='complete':
                        root=self._occurrence_root(c,occurrence_id)
                        c.execute("WITH RECURSIVE family(id) AS (SELECT ? UNION SELECT o.id FROM planner_occurrences o JOIN family f ON o.parent_occurrence_id=f.id) UPDATE planner_occurrences SET status='completed',acted_at=? WHERE id IN (SELECT id FROM family) AND task_id=? AND task_revision=? AND status!='completed'",(root,int(self.clock()),task_id,expected_revision))
                    self._bump(c)
                return {'op_id':op_id,'ok':True,'revision':c.execute('SELECT revision FROM planner_meta').fetchone()[0]}
            return self._request(c,'device:'+device+':'+op_id,args,operation)
