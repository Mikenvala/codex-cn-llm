#!/usr/bin/env python3
"""MiniMax think-filter proxy for Codex relay.
State-machine strips <think>/<thought> tags across SSE streaming events.
Also injects Chinese-only instruction, disables thinking mode, and strips reasoning fields.
"""
import argparse, http.server, json, re, socketserver, urllib.request, urllib.error, socket, datetime, os

LOG = os.environ.get("CODEX_FILTER_LOG", "/tmp/codex-filter.log")
CN = "请始终用中文回答。"

RE_TO = re.compile(r'<\s*think(?:\s[^>]*)?\s*>', re.IGNORECASE)
RE_TC = re.compile(r'</\s*think\s*>', re.IGNORECASE)
RE_TTO = re.compile(r'<\s*thought(?:\s[^>]*)?\s*>', re.IGNORECASE)
RE_TTC = re.compile(r'</\s*thought\s*>', re.IGNORECASE)

def L(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

def is_mm(body):
    try:
        obj = json.loads(body if isinstance(body, str) else body.decode())
        m = obj.get("model", "")
        return bool(m) and m.lower().startswith("minimax")
    except Exception:
        return False

def inject_cn(body):
    try:
        obj = json.loads(body if isinstance(body, str) else body.decode())
        m = obj.get("model", "")
        if not (m and m.lower().startswith("minimax")):
            return body
        # Disable reasoning to reduce silent thinking delay
        if "thinking" not in obj:
            obj["thinking"] = {"type": "disabled"}
        if "instructions" in obj:
            if CN not in obj["instructions"]:
                obj["instructions"] = CN + "\n" + obj["instructions"]
        elif "messages" not in obj:
            obj["instructions"] = CN
        if "messages" in obj:
            if not any(m.get("role") == "system" for m in obj["messages"]):
                obj["messages"].insert(0, {"role": "system", "content": CN})
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    except Exception:
        return body


class ThinkState:
    """Tracks <think>/<thought> nesting depth across SSE events.
    Handles partial tags spanning multiple SSE events.
    """

    def __init__(self):
        self.d = 0
        self.td = 0
        self.buf = ""

    def feed(self, text):
        if not text:
            return ""
        text = self.buf + text
        self.buf = ""
        out = []
        i = 0
        n = len(text)
        while i < n:
            m1 = RE_TO.match(text, i)
            m2 = RE_TTO.match(text, i)
            c1 = RE_TC.match(text, i)
            c2 = RE_TTC.match(text, i)
            if m1:
                if self.d == 0 and self.td == 0:
                    out.append(text[i:m1.start()])
                self.d += 1
                i = m1.end()
            elif m2:
                if self.d == 0 and self.td == 0:
                    out.append(text[i:m2.start()])
                self.td += 1
                i = m2.end()
            elif c1 and self.d > 0:
                self.d -= 1
                i = c1.end()
            elif c2 and self.td > 0:
                self.td -= 1
                i = c2.end()
            elif self.d > 0 or self.td > 0:
                # Inside think/thought – still check for partial close tags
                if text[i] == '<':
                    tail = text[i:]
                    is_close = False
                    for prefix in ('</think', '</thought'):
                        lo = prefix.lower()
                        tl = tail.lower()
                        if tl.startswith(lo[:min(len(lo), len(tl))]) and (
                            len(tl) < len(lo) or tl[:len(lo)] == lo
                        ):
                            is_close = True
                            break
                    if is_close:
                        self.buf = tail
                        break
                i += 1
            elif text[i] == '<':
                tail = text[i:]
                is_prefix = False
                for prefix in ('<think', '<thought', '</think', '</thought'):
                    lo = prefix.lower()
                    tl = tail.lower()
                    if tl.startswith(lo[:min(len(lo), len(tl))]) and (
                        len(tl) < len(lo) or tl[:len(lo)] == lo
                    ):
                        is_prefix = True
                        break
                if is_prefix:
                    self.buf = tail
                    break
                else:
                    out.append(text[i])
                    i += 1
            else:
                out.append(text[i])
                i += 1
        return "".join(out)


def clean(obj, ts):
    """Recursively clean think content and reasoning fields from JSON."""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in ('reasoning_content', 'reasoning', 'thinking'):
                del obj[k]
        for k, v in obj.items():
            if isinstance(v, str) and v:
                obj[k] = ts.feed(v)
            elif isinstance(v, (dict, list)):
                clean(v, ts)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and v:
                obj[i] = ts.feed(v)
            elif isinstance(v, (dict, list)):
                clean(v, ts)


class Handler(http.server.BaseHTTPRequestHandler):
    backend = ""
    timeout = 300

    def do_GET(self):
        self._do("GET")

    def do_POST(self):
        self._do("POST")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, *a):
        pass

    def _do(self, method):
        cl = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(cl) if cl else b""
        url = self.backend + self.path
        mm = is_mm(body) if body else False
        L(f"REQ {method} {self.path} mm={mm} body_len={len(body)}")
        if mm and body:
            body = inject_cn(body)
        try:
            req = urllib.request.Request(url, data=body if method == "POST" else None, method=method)
            for h in ("Content-Type", "Authorization", "Accept"):
                if h in self.headers:
                    req.add_header(h, self.headers[h])
            if method == "POST" and body:
                req.add_header("Content-Length", str(len(body)))
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            ct = resp.headers.get("Content-Type", "")
            L(f"RESP {resp.status} ct={ct[:80]}")
            self.send_response(resp.status)
            for h in ("Content-Type", "Transfer-Encoding"):
                if h in resp.headers:
                    self.send_header(h, resp.headers[h])
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            if mm:
                self._stream_filtered(resp)
            else:
                self._stream_passthrough(resp)
        except urllib.error.HTTPError as e:
            L(f"ERR HTTP {e.code}")
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(e.read())
                self.wfile.flush()
            except Exception:
                pass

    def _stream_passthrough(self, resp):
        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
            self.wfile.flush()
        except Exception as e:
            L(f"PASSTHROUGH ERR {e}")

    def _stream_filtered(self, resp):
        buf = b""
        n_lines = 0
        ts = ThinkState()
        try:
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    L(f"EOF total_lines={n_lines}")
                    break
                buf += chunk
                while b"\n" in buf:
                    idx = buf.index(b"\n")
                    lb = buf[:idx + 1]
                    buf = buf[idx + 1:]
                    n_lines += 1
                    try:
                        line = lb.decode("utf-8")
                    except Exception:
                        self.wfile.write(lb)
                        continue
                    x = line.rstrip("\r\n")
                    if x.startswith("event:"):
                        self.wfile.write(lb)
                        continue
                    if x.startswith("data:"):
                        ds = x[5:]
                        if ds.strip() in ("", "[DONE]"):
                            self.wfile.write(lb)
                        else:
                            try:
                                obj = json.loads(ds)
                                clean(obj, ts)
                                cleaned_line = f"data: {json.dumps(obj, ensure_ascii=False, separators=(',', ':'))}\n"
                                self.wfile.write(cleaned_line.encode())
                            except json.JSONDecodeError:
                                self.wfile.write(lb)
                        continue
                    self.wfile.write(lb)
                self.wfile.flush()
            if buf:
                self.wfile.write(buf)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            L(f"CLOSE {e}")
        except Exception as e:
            L(f"STREAM ERR {e}")
        finally:
            try:
                self.wfile.flush()
            except Exception:
                pass


def main():
    p = argparse.ArgumentParser(description="MiniMax think-filter proxy for Codex")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--backend", type=str, required=True)
    a = p.parse_args()
    Handler.backend = a.backend.rstrip("/")
    L(f"START port={a.port} backend={Handler.backend}")
    try:
        urllib.request.urlopen(urllib.request.Request(Handler.backend + "/v1/models"), timeout=5)
        print(f"\u2713 Backend OK: {Handler.backend}")
    except Exception as e:
        print(f"\u26a0 Backend warning: {e}")
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", a.port), Handler)
    srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    print(f"\u2713 Filter ready: http://127.0.0.1:{a.port}")
    print(f"  Log: {LOG}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        L("STOP")
        srv.shutdown()


if __name__ == "__main__":
    main()
