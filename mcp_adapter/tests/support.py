import json
import hashlib
from urllib.parse import urlencode
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FixtureStudio:
    def __init__(self):
        self.routes = {}
        self.requests = []
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.respond()
            def do_POST(self):
                self.respond()
            def do_PUT(self):
                self.respond()
            def respond(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                request = dict(method=self.command, path=self.path, headers=dict(self.headers), body=raw)
                fixture.requests.append(request)
                response = fixture.routes.get((self.command, self.path), (404, {'error': 'missing fixture route'}))
                if callable(response):
                    response = response(request)
                if response is None:
                    self.close_connection = True
                    return
                status, body, *extra = response
                headers = extra[0] if extra else {}
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02), daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def guidance(self):
        raw = b'---\r\nname: h3-continuity-video\r\ndescription: H3 authoring\r\n---\r\nRead the host.\r\n'
        uri = 'skill://h3-continuity-video/SKILL.md'
        entry = dict(uri=uri, digest='sha256:' + hashlib.sha256(raw).hexdigest(), size=len(raw), mime_type='text/markdown')
        self.catalog = dict(agent_api_version=1, catalog_sha256='a' * 64, skills=[dict(uri=uri,
            frontmatter=dict(name='h3-continuity-video', description='H3 authoring'), resources=[entry])], resources=[entry], coverage={})
        self.routes[('GET', '/h3c/agent/catalog')] = (200, self.catalog)
        self.routes[('GET', '/h3c/agent/resource?' + urlencode({'uri': uri, 'digest': entry['digest']}))] = (200, raw)
        self.routes[('GET', '/h3c/api/v1/capabilities')] = (200, {'profiles': [], 'operations': [], 'readiness': {}})
        return uri, raw
