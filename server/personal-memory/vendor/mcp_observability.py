"""Bounded protocol metadata; arguments, content and credentials are never stored."""
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')


class Observer:
    def __init__(self, path=None, clock=time.time, timer=time.monotonic):
        self.path = Path(path) if path else None
        self.clock, self.timer = clock, timer
        self.session = uuid4().hex
        self.pending = {}
        self.lock = threading.Lock()
        self.max_bytes = 2_000_000
        self.state = {'session': self.session}

    def _emit(self, kind, **fields):
        if not self.path: return
        event = {'kind': kind, 'at': datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
                 'session': self.session, **fields}
        try:
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if kind in ('connected', 'disconnected', 'tools'):
                    if kind == 'tools':
                        self.state.update(tools=fields['tools'], tools_at=event['at'])
                    else:
                        self.state.update(lifecycle=kind, lifecycle_at=event['at'])
                    try:
                        checkpoint = self.path.with_suffix('.state.json')
                        temporary = checkpoint.with_name(checkpoint.name + '.' + self.session + '.tmp')
                        temporary.write_text(json.dumps(self.state), encoding='utf-8')
                        temporary.replace(checkpoint)
                    except OSError:
                        pass
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    self.path.replace(self.path.with_name(self.path.name + '.1'))
                with self.path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        except OSError:
            pass  # Telemetry failure must not interrupt the MCP stream.

    def connected(self):
        self._emit('connected')

    def _finish(self, key, status):
        call_id, tool, started = self.pending.pop(key)
        self._emit('call_finished', call_id=call_id, tool=tool, status=status,
                   duration_ms=max(0, round((self.timer() - started) * 1000)))

    def disconnected(self):
        for key in list(self.pending): self._finish(key, 'interrupted')
        self._emit('disconnected')

    def observe(self, raw, incoming):
        try: message = json.loads(raw)
        except (TypeError, ValueError): return
        if not isinstance(message, dict): return
        ident = message.get('id')
        key = (type(ident).__name__, ident) if type(ident) in (str, int) else None
        if incoming and message.get('method') == 'tools/call' and key is not None:
            params = message.get('params')
            tool = params.get('name') if isinstance(params, dict) else None
            tool = tool if isinstance(tool, str) and NAME.fullmatch(tool) else 'unknown'
            if key in self.pending: self._finish(key, 'interrupted')
            if len(self.pending) >= 256: self._finish(next(iter(self.pending)), 'interrupted')
            call_id = uuid4().hex
            self.pending[key] = (call_id, tool, self.timer())
            self._emit('call_started', call_id=call_id, tool=tool)
        elif not incoming:
            result = message.get('result')
            if isinstance(result, dict) and isinstance(result.get('tools'), list):
                names = [item['name'] for item in result['tools'] if isinstance(item, dict)
                         and isinstance(item.get('name'), str) and NAME.fullmatch(item['name'])]
                self._emit('tools', tools=list(dict.fromkeys(names))[:128])
            if key in self.pending and ('result' in message or 'error' in message):
                failed = 'error' in message or (isinstance(result, dict) and result.get('isError') is True)
                self._finish(key, 'error' if failed else 'success')
