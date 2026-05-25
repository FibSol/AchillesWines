"""Local server: serves a collector page (GET /) and receives JSON (POST /).
Navigate browser to http://localhost:9977/ — the page reads window.name and
POSTs it back. Same-origin so no CORS/PNA restrictions apply.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys, pathlib

OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("ct_received.json")

_PAGE = b"""<!DOCTYPE html><html><body>
<p id="status">Sending...</p>
<script>
(async () => {
  const data = window.name;
  if (!data || data.length < 5) { document.getElementById('status').textContent = 'ERROR: window.name empty'; return; }
  try {
    const r = await fetch('/', { method:'POST', headers:{'Content-Type':'application/json'}, body: data });
    const t = await r.text();
    document.getElementById('status').textContent = 'Done: ' + t;
  } catch(e) { document.getElementById('status').textContent = 'Error: ' + e.message; }
})();
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(_PAGE)))
        self.end_headers()
        self.wfile.write(_PAGE)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        OUT.write_bytes(data)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        msg = f"ok {len(data)} bytes -> {OUT.name}".encode()
        self.wfile.write(msg)
        print(f"Received {len(data)} bytes -> {OUT}", flush=True)
    def log_message(self, *_): pass

print(f"Listening on http://localhost:9977  output -> {OUT}", flush=True)
HTTPServer(("localhost", 9977), Handler).serve_forever()
