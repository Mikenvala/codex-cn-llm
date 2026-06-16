#!/usr/bin/env python3
"""Debug filter: logs all SSE data to see actual Responses API format."""
import argparse, http.server, json, socketserver, urllib.request, urllib.error, socket, datetime

LOG = "/tmp/codex-filter-debug.log"
MODE = "debug"  # always log all

def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except: pass

def is_minimax(body):
    try:
        obj = json.loads(body)
        m = obj.get("model","")
        return bool(m) and isinstance(m, str) and m.lower().startswith("minimax")
    except: return False

class Handler(http.server.BaseHTTPRequestHandler):
    backend = ""; timeout = 300
    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","*")
        self.end_headers()
    def log_message(self, *a): pass

    def _handle(self, method):
        cl = int(self.headers.get("Content-Length",0))
        body = self.rfile.read(cl) if cl else b""
        url = self.backend + self.path
        is_mm = is_minimax(body) if body else False
        log(f"REQ {method} {self.path} mm={is_mm} body={len(body)}")
        try:
            req = urllib.request.Request(url, data=body if method=="POST" else None, method=method)
            for h in ("Content-Type","Authorization","Accept","User-Agent"):
                if h in self.headers: req.add_header(h, self.headers[h])
            if method=="POST" and body: req.add_header("Content-Length",str(len(body)))
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            ct = resp.headers.get("Content-Type","")
            log(f"RESP {resp.status} ct={ct[:100]}")
            self.send_response(resp.status)
            for h in ("Content-Type","Transfer-Encoding"):
                if h in resp.headers: self.send_header(h, resp.headers[h])
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Cache-Control","no-cache")
            self.send_header("Connection","keep-alive")
            self.end_headers()
            # Log ALL chunks, pass through unchanged
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    log("EOF")
                    break
                log(f"CHUNK {len(chunk)}b: {chunk[:300]!r}")
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception as e:
            log(f"ERR: {e}")
            try:
                self.send_response(502); self.send_header("Content-Type","application/json")
                self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                self.wfile.write(json.dumps({"error":str(e)}).encode()); self.wfile.flush()
            except: pass

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--backend", type=str, required=True)
    a = p.parse_args()
    Handler.backend = a.backend.rstrip("/")
    log(f"DEBUG START port={a.port} backend={Handler.backend}")
    try:
        urllib.request.urlopen(urllib.request.Request(Handler.backend+"/v1/models"), timeout=5)
        print(f"Backend: {Handler.backend}")
    except Exception as e:
        print(f"WARN: {e}")
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", a.port), Handler)
    srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    print(f"DEBUG filter: http://127.0.0.1:{a.port}")
    print(f"Log: {LOG}")
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__": main()
