"""Bounded physical USB diagnostics; responses and boot logs remain local."""
import argparse
import json
from pathlib import Path
import time
import serial


class RoundPort:
    def __init__(self, *, port='COM3', log=None):
        self.port = serial.Serial()
        self.port.port = port
        self.port.baudrate = 115200
        self.port.timeout = .2
        self.port.dtr = False
        self.port.rts = False
        self.log = Path(log).open('ab') if log else None
        self.port.open()
        self.number = 1000

    def __enter__(self): return self

    def __exit__(self, *_):
        self.port.close()
        if self.log: self.log.close()

    def read(self):
        line = self.port.readline()
        if self.log:
            self.log.write(line)
            self.log.flush()
        marker = b'ROUND_REPLY '
        if marker not in line: return None
        try: return json.loads(line.split(marker, 1)[1])
        except (ValueError, UnicodeError): return None

    def request(self, value, *, mcp=False, timeout=15):
        self.number += 1
        value = {**value, 'id': self.number}
        data = (('ROUND_MCP ' if mcp else 'ROUND_CTL ') + json.dumps(value, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
        if len(data) > 16000: raise ValueError('Diagnostic frame exceeds firmware limit')
        # A short chunk interval also supports devices with the older polling console.
        for offset in range(0, len(data), 128):
            self.port.write(data[offset:offset + 128])
            time.sleep(.012)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.read()
            if isinstance(response, dict) and response.get('id') == self.number:
                if mcp:
                    if 'error' in response: raise RuntimeError(response['error'])
                    result = response.get('result', {})
                    content = result.get('content', [])
                    if result.get('isError'): raise RuntimeError(content)
                    if content and 'text' in content[0]:
                        text = content[0]['text']
                        try: return json.loads(text)
                        except ValueError: return text
                return response
        raise TimeoutError('Device did not reply to physical diagnostic request')

    def control(self, op, **arguments): return self.request({'op': op, **arguments})

    def tool(self, name, **arguments):
        return self.request({'jsonrpc': '2.0', 'method': 'tools/call',
            'params': {'name': name, 'arguments': arguments}}, mcp=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mcp', action='store_true')
    args = parser.parse_args()
    with RoundPort(log=args.output.with_suffix('.serial.log')) as device:
        response = device.request(json.loads(args.request.read_text('utf-8')), mcp=args.mcp)
    args.output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Device response saved; keys:', ', '.join(response) if isinstance(response, dict) else type(response).__name__)
