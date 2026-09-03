#!/usr/bin/env python3
"""
relay-gateway: Multi-provider OpenAI-compatible API gateway.
Routes /v1/chat/completions by model name to different upstream providers.
Supports config hot-reload, auth.json key resolution, byte-transparent proxying.

Usage: python relay_gateway.py <config.json>
"""

import json, os, socket, ssl, sys, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

AUTH_PATH = os.path.join(os.path.expanduser("~"), ".codex", "auth.json")

def log(msg):
    sys.stderr.write(f"{time.strftime('%Y/%m/%d %H:%M:%S')} {msg}\n")
    sys.stderr.flush()

class Gateway:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config_mtime = 0
        self.providers = {}
        self.models = {}
        self.port = 4447
        self._auth_cache = {}
        self._auth_mtime = 0
        self._load_config()

    def _load_config(self):
        try:
            mtime = os.path.getmtime(self.config_path)
            if mtime == self.config_mtime:
                return
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.port = cfg.get("port", 4447)
            self.providers = cfg.get("providers", {})
            self.models = cfg.get("models", {})
            self.config_mtime = mtime
        except Exception:
            pass

    def _load_auth(self):
        try:
            mtime = os.path.getmtime(AUTH_PATH)
            if mtime != self._auth_mtime:
                with open(AUTH_PATH, "r", encoding="utf-8") as f:
                    self._auth_cache = json.load(f)
                self._auth_mtime = mtime
        except Exception:
            pass
        return self._auth_cache

    def resolve_key(self, api_key_env):
        if not api_key_env:
            return ""
        auth = self._load_auth()
        key = auth.get(api_key_env, "")
        if key:
            return key
        return os.environ.get(api_key_env, "")

    def route_model(self, model):
        provider_name = self.models.get(model)
        if not provider_name:
            return None, None
        provider = self.providers.get(provider_name, {})
        if not provider:
            return provider_name, None
        return provider_name, provider


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        gw = self.server.gateway
        gw._load_config()
        if self.path == "/v1/models":
            self._handle_models(gw)
        elif self.path == "/v1/chat/completions":
            self._handle_chat(gw)
        else:
            self.send_error(404, "page not found")

    def _handle_models(self, gw):
        models_data = []
        for model_name, provider_name in gw.models.items():
            models_data.append({
                "id": model_name, "object": "model",
                "created": 0, "owned_by": provider_name,
            })
        body = json.dumps({"data": models_data, "object": "list"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_chat(self, gw):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        model = ""
        try:
            req = json.loads(body)
            model = req.get("model", "")
        except Exception:
            pass

        provider_name, provider = gw.route_model(model)
        if not provider:
            self._send_json_error(404, "model not routed: " + model)
            return

        base_url = provider.get("base_url", "")
        api_key_env = provider.get("api_key_env", "")
        api_key = gw.resolve_key(api_key_env)
        if not api_key:
            self._send_json_error(401, "No api key for provider " + provider_name)
            return

        parsed = urlparse(base_url)
        host = parsed.hostname
        is_ssl = parsed.scheme == "https"
        port = parsed.port or (443 if is_ssl else 80)
        upstream_path = parsed.path.rstrip("/") + "/chat/completions"
        stream = False
        try:
            stream = req.get("stream", False)
        except Exception:
            pass

        start = time.time()
        sock = None
        try:
            sock = socket.create_connection((host, port), timeout=300)
            if is_ssl:
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=host)

            req_line = f"POST {upstream_path} HTTP/1.1\r\n"
            req_headers = (
                f"Host: {host}\r\n"
                "Content-Type: application/json\r\n"
                f"Authorization: Bearer {api_key}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            )
            sock.sendall(req_line.encode() + req_headers.encode() + body)

            self.close_connection = True

            resp_buf = b""
            while b"\r\n\r\n" not in resp_buf:
                byte = sock.recv(1)
                if not byte:
                    raise ConnectionError("upstream closed before sending headers")
                resp_buf += byte

            header_end = resp_buf.index(b"\r\n\r\n") + 4
            resp_headers_raw = resp_buf[:header_end - 4]
            initial_body = resp_buf[header_end:]

            status_line = resp_headers_raw.split(b"\r\n")[0]
            parts = status_line.split(b" ", 2)
            status_code = int(parts[1])
            status_text = parts[2].decode("utf-8", errors="replace") if len(parts) > 2 else "OK"

            client_sock = self.connection
            our_resp = f"HTTP/1.1 {status_code} {status_text}\r\n".encode()
            for line in resp_headers_raw.split(b"\r\n")[1:]:
                our_resp += line + b"\r\n"
            our_resp += b"Connection: close\r\n\r\n"
            client_sock.sendall(our_resp)

            if initial_body:
                client_sock.sendall(initial_body)

            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                client_sock.sendall(chunk)

            dur = time.time() - start
            log(f"route {model} -> {provider_name} (stream={stream}) status={status_code} dur={dur:.3f}s")

        except Exception as e:
            dur = time.time() - start
            log(f"route {model} -> {provider_name} (stream={stream}) upstream ERROR after {dur:.3f}s: {e}")
            try:
                self._send_json_error(502, f"upstream error: {e}")
            except Exception:
                pass
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def _send_json_error(self, status, message):
        body = json.dumps({"error": {"message": message, "type": "gateway_error"}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self._handle, args=(request, client_address))
        t.daemon = True
        t.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main():
    if len(sys.argv) < 2:
        print("Usage: relay_gateway.py <config.json>", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    if not os.path.isfile(config_path):
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    gw = Gateway(config_path)
    port = gw.port
    server = ThreadedHTTPServer(("127.0.0.1", port), GatewayHandler)
    server.gateway = gw

    log(f"gateway listening on 127.0.0.1:{port} ({len(gw.models)} models routed, hot-reload on)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("gateway shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
