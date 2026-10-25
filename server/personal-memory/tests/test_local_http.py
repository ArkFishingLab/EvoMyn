"""Local listeners must start even when reverse DNS is unavailable."""
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(next(path for path in (ROOT / 'vendor', ROOT / 'app') if path.is_dir())))
from local_http import ThreadingHTTPServer


class LocalHTTPTests(unittest.TestCase):
    def test_listen_and_serve_without_reverse_dns(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.end_headers()

            def log_message(self, *_):
                pass

        with patch('socket.getfqdn', side_effect=AssertionError('Unexpected reverse DNS')):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.addCleanup(server.server_close)
            self.assertEqual(server.server_name, '127.0.0.1')
            self.assertEqual(server.server_port, server.socket.getsockname()[1])
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with build_opener(ProxyHandler({})).open(
                        f'http://127.0.0.1:{server.server_port}/', timeout=2) as response:
                    self.assertEqual(response.status, 204)
            finally:
                server.shutdown()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
