"""Loopback onboarding; credentials are write-only and never rendered."""
import html
from http.cookies import SimpleCookie
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from dotenv import dotenv_values, set_key
from filelock import FileLock


class Setup:
    def __init__(self, root, controller, client_config=None):
        self.root = Path(root).resolve()
        self.controller = controller
        if client_config is None:
            from launcher import Runtime
            client_config = Runtime(self.root).client_config
        self.client_config = client_config
        self.sessions = {}
        self.lock = threading.Lock()

    def respond(self, handler, status, body, kind='text/html; charset=utf-8', cookie=None, location=None, filename=None):
        if isinstance(body, str): body = body.encode('utf-8')
        handler.send_response(status)
        for name, value in [('Content-Type', kind), ('Content-Length', str(len(body))),
                            ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                            ('Referrer-Policy', 'same-origin'), ('X-Frame-Options', 'DENY'),
                            ('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]:
            handler.send_header(name, value)
        if cookie: handler.send_header('Set-Cookie', cookie)
        if location: handler.send_header('Location', location)
        if filename: handler.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        handler.end_headers()
        if handler.command != 'HEAD': handler.wfile.write(body)

    @staticmethod
    def endpoint(value):
        if len(value) > 4096 or any(ord(char) <= 32 for char in value): raise ValueError()
        parsed = urlsplit(value)
        if parsed.scheme != 'wss' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535: raise ValueError()
        parsed.hostname.encode('idna')
        return value

    def session(self):
        ident, token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
            if len(self.sessions) >= 128: self.sessions.pop(next(iter(self.sessions)))
            self.sessions[ident] = (token, now + 1200)
        return token, 'memory_setup=' + ident + '; Path=/setup/; HttpOnly; SameSite=Strict'

    def valid_csrf(self, handler, token):
        try:
            cookies = SimpleCookie(handler.headers.get('Cookie', ''))
            ident = cookies['memory_setup'].value
        except (KeyError, ValueError): return False
        with self.lock:
            saved = self.sessions.get(ident)
            return bool(saved and saved[1] > time.monotonic() and secrets.compare_digest(saved[0], token))

    def save_endpoint(self, endpoint):
        app = self.root / 'app'
        app.mkdir(parents=True, exist_ok=True)
        target = app / '.env'
        with FileLock(str(self.root / 'configuration.lock'), timeout=5):
            if target.is_symlink(): raise ValueError()
            previous = target.read_text('utf-8-sig') if target.exists() else ''
            if len(previous.encode('utf-8')) > 65536: raise ValueError()
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=app, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(previous)
            try:
                os.chmod(temporary, 0o600)
                set_key(temporary, 'MCP_ENDPOINT', endpoint)
                temporary.replace(target)
            finally: temporary.unlink(missing_ok=True)

    def page(self, token, configured, saved=False, restart_failed=False):
        escape = html.escape
        json_config = escape(self.client_config('json'))
        toml_config = escape(self.client_config('toml'))
        notice = ('<p class="notice" role="status">配置已保存。' +
                  ('请在能力页重试小智连接。' if restart_failed else '') + '</p>') if saved else ''
        return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>接入配置 · EvoMyn</title><style>
:root{color-scheme:light;font-family:"Segoe UI Variable","PingFang SC","Microsoft YaHei UI",sans-serif;color:#24242a;background:#fff}*{box-sizing:border-box}body{margin:0}main{max-width:1000px;padding:62px 42px 80px;margin:auto}nav{display:flex;justify-content:space-between;font-size:13px;color:#777}a{color:inherit;text-underline-offset:5px}h1{font-size:42px;letter-spacing:-1px;font-weight:500;margin:60px 0 14px}p{font-size:14px;line-height:1.9;color:#686872}.intro{max-width:540px;margin-bottom:54px}.section{border-top:1px solid #e7e7eb;display:grid;grid-template-columns:230px 1fr;gap:40px;padding:34px 0}h2{font-size:20px;font-weight:500;margin:0 0 12px}.number{font-size:11px;color:#9b9ba3;display:block;margin-bottom:15px}.body>p:first-child{margin-top:0}.clients{display:flex;gap:24px;margin:24px 0;font-size:14px}.client{border-bottom:1px solid #bbb;padding-bottom:7px;text-decoration:none}details{margin:16px 0;font-size:13px;color:#686872}summary{cursor:pointer}pre{font-size:12px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f7f8;padding:20px;color:#333}label{display:block;font-size:13px;margin:24px 0 9px}input[type=password]{border:1px solid #d9d9df;border-radius:2px;width:100%;padding:14px;font:inherit;font-size:14px;background:#fff}input:focus-visible,button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid #73737e;outline-offset:4px}.check{display:flex;align-items:center;gap:8px;color:#777;font-size:12px}button{margin-top:16px;background:#29292f;color:#fff;border:0;padding:13px 24px;font:inherit;font-size:13px;border-radius:2px;cursor:pointer}.state{font-size:12px;color:#797983}.notice{border-left:2px solid #748c77;padding-left:15px;margin:28px 0}.footer{border-top:1px solid #e7e7eb;padding-top:24px;margin-top:30px;font-size:12px;color:#8b8b94}@media(max-width:650px){main{padding:30px 24px}h1{font-size:34px;margin-top:42px}.intro{margin-bottom:36px}.section{grid-template-columns:1fr;gap:8px}.number{margin-bottom:9px}.clients{gap:20px}}
</style><main><nav><a href="/memory/">EvoMyn</a><a href="/memory/mcp/">能力管理 ↗</a></nav>
<h1>让记忆，接入你的工具。</h1><p class="intro">同一份个人档案，可以在 Codex、Claude Code 或小智中使用。记录保存在这台电脑，由你选择如何连接。</p>''' + notice + '''
<section class="section"><div><span class="number">01 / LOCAL</span><h2>本地客户端</h2><p>标准 MCP · stdio</p></div><div class="body"><p>下载配置，填入客户端的 MCP 设置。每个客户端按需启动服务，共享本地记忆库。</p>
<div class="clients"><a class="client" href="/setup/clients/codex.toml">Codex 配置 ↓</a><a class="client" href="/setup/clients/claude.json">Claude Code 配置 ↓</a></div>
<details><summary>查看 Codex 配置</summary><pre>''' + toml_config + '''</pre></details><details><summary>查看通用 MCP / Claude Code 配置</summary><pre>''' + json_config + '''</pre></details><p>能力开关更改后，请在对应客户端重新连接 MCP。下载的配置只包含本机程序路径。</p></div></section>
<section class="section"><div><span class="number">02 / CLOUD</span><h2>小智云端</h2><p class="state">''' + ('已配置接入点' if configured else '尚未配置 · 可选') + '''</p></div><div class="body"><p>从小智控制台复制 MCP 接入点，保存后自动连接。接入点作为凭证保存在本机，不会在页面回显。</p>
<ol><li>打开 <a href="https://xiaozhi.me/" target="_blank" rel="noopener noreferrer">小智控制台 ↗</a>，使用圆盘绑定的账号登录。</li><li>进入「智能体」，选择圆盘正在使用的角色，打开「配置角色」。</li><li>找到「MCP 设置」或「编辑功能」，点击「MCP 接入点」，复制完整的 <code>wss://</code> 地址及其全部参数。</li></ol><p class="state">这里不是看板地址；请粘贴控制台生成的接入点。菜单名称可能随控制台版本调整。</p>
<form method="post" action="/setup/save"><input type="hidden" name="csrf" value="''' + token + '''"><label for="endpoint">MCP 接入点</label><input id="endpoint" name="endpoint" type="password" placeholder="wss://…" autocomplete="new-password" spellcheck="false" maxlength="4096"><p class="state">留空保留现有配置。</p><label class="check"><input type="checkbox" name="disable" value="1">停用小智云端连接</label><button type="submit">保存配置</button></form></div></section>
<p class="footer">圆盘和局域网日志网关为可选模块。首次语义索引可能下载模型；原始记录会先保存。</p></main></html>'''

    def handle(self, handler):
        path = urlsplit(handler.path).path
        allowed = {'127.0.0.1:' + str(handler.server.server_port), 'localhost:' + str(handler.server.server_port)}
        host = handler.headers.get('Host', '')
        if len(handler.headers.get_all('Host', [])) != 1 or host not in allowed:
            return self.respond(handler, 403, 'Forbidden')
        if handler.command in ('GET', 'HEAD'):
            if path == '/setup/':
                token, cookie = self.session()
                configured = bool(dotenv_values(self.root / 'app/.env').get('MCP_ENDPOINT'))
                query = parse_qs(urlsplit(handler.path).query)
                return self.respond(handler, 200, self.page(token, configured,
                    saved=query.get('saved') == ['1'], restart_failed=query.get('restart') == ['failed']), cookie=cookie)
            formats = {'/setup/clients/claude.json': ('json', 'application/json', 'evomyn-mcp.json'),
                       '/setup/clients/codex.toml': ('toml', 'text/plain; charset=utf-8', 'evomyn-mcp.toml')}
            if path in formats:
                kind, media, filename = formats[path]
                return self.respond(handler, 200, self.client_config(kind), media, filename=filename)
            return self.respond(handler, 404, 'Not found')
        if handler.command != 'POST' or path != '/setup/save':
            return self.respond(handler, 405, 'Method not allowed')
        if handler.headers.get('Origin') != 'http://' + host:
            return self.respond(handler, 403, 'Forbidden')
        try:
            if 'Transfer-Encoding' in handler.headers or len(handler.headers.get_all('Content-Length', [])) != 1: raise ValueError()
            length = int(handler.headers['Content-Length'])
            if not 0 <= length <= 8192: raise ValueError()
            if handler.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded': raise ValueError()
            values = parse_qs(handler.rfile.read(length).decode('utf-8'), keep_blank_values=True,
                              max_num_fields=8, encoding='utf-8', errors='strict')
            if any(len(value) != 1 for value in values.values()) or set(values) - {'csrf', 'endpoint', 'disable'}: raise ValueError()
            if not self.valid_csrf(handler, values.get('csrf', [''])[0]):
                return self.respond(handler, 403, 'Forbidden')
            disable = values.get('disable') == ['1']
            value = values.get('endpoint', [''])[0]
            action = None
            if disable:
                self.save_endpoint('')
                action = 'stop'
            elif value:
                self.save_endpoint(self.endpoint(value))
                action = 'restart'
        except (ValueError, UnicodeError):
            return self.respond(handler, 400, '请输入有效的 wss:// 接入点；配置未更改。')
        except Exception:
            return self.respond(handler, 503, '暂时无法保存配置，请稍后重试。')
        failed = False
        if action:
            try: self.controller.command(action)
            except Exception: failed = True
        return self.respond(handler, 303, '', location='/setup/?saved=1' + ('&restart=failed' if failed else ''))
