"""Local HTTP listeners whose startup never waits for reverse DNS."""
from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
from socketserver import TCPServer


class ThreadingHTTPServer(_ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves the listener's name through getfqdn(), which can
        # stall for tens of seconds on macOS/offline DNS. These services use
        # explicit Host validation and do not need a canonical DNS name.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]
