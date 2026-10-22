"""Fixed local capability groups shared by the dashboard and Xiaozhi bridge."""
import json
import os
from pathlib import Path
from uuid import uuid4

MANIFEST = (
    {'id': 'archive', 'name': '记忆档案', 'description': '保存、检索和整理个人记忆',
     'source': '项目内置', 'author': 'EvoMyn', 'version': '1.0', 'license': '项目内置', 'url': None,
     'builtin': True, 'setup': '无需配置，使用现有个人记忆库。',
     'tools': ('archive_status', 'archive_record', 'archive_update', 'archive_list', 'archive_get',
               'archive_search', 'archive_history', 'archive_backup', 'archive_retry_index')},
    {'id': 'planner', 'name': '计划提醒', 'description': '管理待办、日程和提醒',
     'source': '项目内置', 'author': 'EvoMyn', 'version': '1.0', 'license': '项目内置', 'url': None,
     'builtin': True, 'setup': '无需配置，沿用现有圆盘提醒连接。关闭不取消已设提醒。',
     'tools': ('planner_get_context', 'planner_create', 'planner_list', 'planner_get', 'planner_delivery',
               'planner_update', 'planner_complete', 'planner_cancel', 'planner_snooze')},
    {'id': 'worldtime', 'name': '世界时间', 'description': '查询各地时间，换算不同时区',
     'source': 'Model Context Protocol', 'author': 'MCP Contributors', 'version': '2026.10.10',
     'license': 'MIT', 'url': 'https://github.com/modelcontextprotocol/servers/tree/main/src/time',
     'builtin': False, 'setup': '无需账号或密钥。默认北京时间，支持 IANA 时区。',
     'tools': ('worldtime_now', 'worldtime_convert')},
)


def planner_owner():
    owner = os.environ.get('PLANNER_OWNER', 'pc')
    if owner not in ('pc', 'device'):
        raise ValueError('PLANNER_OWNER must be pc or device')
    return owner


class Packages:
    def __init__(self, path):
        self.path = Path(path)
        self.owner = planner_owner()
        self.error = False

    def _load(self):
        self.error = False
        try:
            with self.path.open('rb') as stream:
                value = json.loads(stream.read(8192))
            if not isinstance(value, dict) or not {'archive', 'planner'} <= set(value) <= {item['id'] for item in MANIFEST}:
                raise ValueError('Invalid packages')
            if any(type(enabled) is not bool for enabled in value.values()): raise ValueError('Invalid switch')
            return {**{item['id']: False for item in MANIFEST}, **value}
        except FileNotFoundError:
            return {item['id']: item['builtin'] for item in MANIFEST}
        except (OSError, ValueError, RecursionError):
            self.error = True
            return {item['id']: False for item in MANIFEST}

    def list(self):
        return [item for item in self.catalog() if item['installed']]

    def catalog(self):
        enabled = self._load()
        result = []
        for item in MANIFEST:
            if item['id'] == 'planner' and self.owner == 'device':
                result.append({**item, 'owner': 'device', 'external': True, 'tools': (),
                    'enabled': False, 'installed': True, 'source': '圆盘设备',
                    'description': '计划和提醒由圆盘本地保存与执行，PC 仅接收完成日志。',
                    'setup': '使用圆盘 self.planner.* 工具管理；PC 计划能力已下线。',
                    'adaptation': '设备自主管理', 'requires_key': False})
                continue
            installed = item['builtin'] or self.installed(item['id'], item['version'])
            result.append({**item, 'installed': installed, 'enabled': enabled[item['id']] and installed,
                           'adaptation': '已适配', 'requires_key': False})
        return result

    def installed(self, ident, version):
        try:
            receipt = json.loads((self.path.parent / 'packages' / ident / 'installed.json').read_text(encoding='utf-8'))
            return receipt == {'version': version, 'verified': True} and self.python(ident).is_file()
        except (OSError, ValueError): return False

    def python(self, ident):
        return self.path.parent / 'packages' / ident / '.venv/Scripts/python.exe'

    def set(self, ident, enabled):
        if not isinstance(ident, str) or ident not in {item['id'] for item in MANIFEST} or type(enabled) is not bool:
            raise ValueError('Invalid package switch')
        if ident == 'planner' and enabled and self.owner == 'device':
            raise ValueError('Planner is owned by the device; use 圆盘 self.planner.* tools')
        if enabled and not any(item['id'] == ident and item['installed'] for item in self.catalog()):
            raise ValueError('Package must be installed first')
        value = self._load()
        value[ident] = enabled
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(value), encoding='utf-8')
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _disabled(self):
        disabled = {tool for item in self.catalog() if not item['enabled'] for tool in item['tools']}
        if self.owner == 'device':
            disabled.update(tool for item in MANIFEST if item['id'] == 'planner' for tool in item['tools'])
        return disabled

    def blocked_response(self, raw):
        try: message = json.loads(raw)
        except (TypeError, ValueError): return None
        if not isinstance(message, dict) or message.get('method') != 'tools/call': return None
        params = message.get('params')
        name = params.get('name') if isinstance(params, dict) else None
        if not isinstance(name, str) or name not in self._disabled(): return None
        if type(message.get('id')) not in (str, int): return None
        message_text = '该功能包已关闭，请在 MCP 管理页开启后重试。'
        if self.owner == 'device' and name.startswith('planner_'):
            message_text = '计划提醒已迁移到圆盘，请使用设备 self.planner.* 工具；PC 仅接收完成日志。'
        return json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': {'isError': True,
            'content': [{'type': 'text', 'text': message_text}]}}, ensure_ascii=False)

    def filter_response(self, raw):
        try: message = json.loads(raw)
        except (TypeError, ValueError): return raw
        if not isinstance(message, dict): return raw
        result = message.get('result')
        if not isinstance(result, dict) or not isinstance(result.get('tools'), list): return raw
        disabled = self._disabled()
        result['tools'] = [tool for tool in result['tools'] if isinstance(tool, dict)
                           and isinstance(tool.get('name'), str) and tool['name'] not in disabled]
        return json.dumps(message, ensure_ascii=False)
