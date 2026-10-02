"""Loopback-only local web application. Keys stay in server memory."""
from __future__ import annotations
import argparse
import json
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .engine import RelationshipAgent
from .providers import build_model_client
from .storage import Store
from .academic import AcademicSearch

ASSETS = Path(__file__).parent / "web"


class Application:
    def __init__(self, root, client=None):
        self.store = Store(root)
        self.store.recover_interrupted()
        self.client = client or build_model_client()
        self.academic = AcademicSearch()
        self._api_keys = {}
        self._api_request_count = 0
        if self.client.mode == "api":
            self._api_keys[(self.client.base_url.rstrip("/"), self.client.protocol)] = self.client.api_key
            self._api_request_count = self.client.request_count
        self.token = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.active = set()
        self.lock = threading.Lock()

    def public_config(self):
        c = self.client
        return {"mode": c.mode, "model": c.model, "protocol": c.protocol,
                "base_url": c.base_url, "has_key": bool(getattr(c, "api_key", "")), "academic": self.academic.public_config(),
                "local_requests_remaining": max(0, c.request_limit - c.request_count) if c.mode == "api" else None}

    def configure(self, payload):
        with self.lock:
            if self.active:
                raise ValueError("请等待当前任务完成 / Wait for the active run")
            mode = payload.get("mode", "mock")
            url = payload.get("base_url", "")
            key = payload.get("api_key", "")
            if not all(isinstance(payload.get(k, ""), str) and len(payload.get(k, "")) <= 2000 for k in ("mode", "model", "protocol", "base_url", "api_key")):
                raise ValueError("Invalid settings")
            protocol = payload.get("protocol")
            if mode == "api" and not key:
                key = self._api_keys.get((url.rstrip("/"), protocol), "")
            if mode == "api" and not key:
                raise ValueError("请为此服务地址输入对应的 API Key / Enter this provider's API key")
            if self.client.mode == "api":
                self._api_request_count = self.client.request_count
            client = build_model_client(mode, model=payload.get("model"), base_url=url,
                                         protocol=protocol, api_key=key)
            if 'academic' in payload:
                self.academic.configure(payload['academic'])
            if mode == "api":
                client.request_count = self._api_request_count
                self._api_keys[(client.base_url.rstrip("/"), client.protocol)] = key
            self.client = client
        return self.public_config()

    def submit(self, session_id=None, message=None, kind="analysis", resume=None):
        with self.lock:
            if self.active:
                raise ValueError("已有任务运行中 / Another run is in progress")
            agent = RelationshipAgent(self.client, self.store, self.academic)
            if resume:
                run = self.store.run(resume)
                if run["config"] != agent.config():
                    raise ValueError("恢复需使用原模型配置 / Restore the original model configuration first")
                run_id = resume
                if run["status"] == "complete":
                    return run_id
                self.store.checkpoint(run_id, run["state"])
            else:
                run_id = agent.start(session_id, message, kind)
            self.active.add(run_id)

        def work():
            try:
                agent.execute(run_id)
            except Exception:
                pass  # Sanitized failure is persisted by the engine.
            finally:
                with self.lock:
                    self.active.discard(run_id)
        self.executor.submit(work)
        return run_id


class Handler(BaseHTTPRequestHandler):
    server_version = "RelationshipAgent/0.2"

    @property
    def app(self):
        return self.server.app

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def check_host(self):
        host = self.headers.get("Host", "")
        valid = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in valid:
            raise PermissionError("Invalid host")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            raise PermissionError("Cross-origin access rejected")

    def do_GET(self):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in files:
                name, mime = files[path]
                return self.send(200, (ASSETS / name).read_bytes(), mime)
            if path == "/api/bootstrap":
                return self.send(200, {"token": self.app.token, "config": self.app.public_config(), "sessions": self.app.store.sessions()})
            if path.startswith("/api/sessions/"):
                sid = path.rsplit("/", 1)[-1]
                return self.send(200, {"session": self.app.store.session(sid),
                                       "runs": [self.public_run(r) for r in self.app.store.runs(sid)]})
            if path.startswith("/api/runs/"):
                rid = path.rsplit("/", 1)[-1]
                return self.send(200, self.public_run(self.app.store.run(rid)))
            self.send(404, {"error": "Not found"})
        except PermissionError as exc:
            self.send(403, {"error": str(exc)})
        except ValueError as exc:
            self.send(404, {"error": str(exc)})

    def public_run(self, run):
        return {k: run[k] for k in ("id", "session_id", "kind", "input", "status", "result", "error", "created")} | {"trace": self.app.store.traces(run["id"])}

    def do_POST(self):
        try:
            self.check_host()
            if not secrets.compare_digest(self.headers.get("X-Local-Token", ""), self.app.token):
                raise PermissionError("Invalid local token")
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 40_000:
                raise ValueError("Request size limit is 40 KB")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            path = urlsplit(self.path).path
            if path == "/api/settings":
                return self.send(200, self.app.configure(payload))
            if path == "/api/sessions":
                title, lang = payload.get("title", ""), payload.get("language", "zh")
                if not isinstance(title, str):
                    raise ValueError("Invalid title")
                return self.send(201, self.app.store.create_session(title, self.app.client.mode, lang))
            if path in {"/api/message", "/api/analyze", "/api/feedback", "/api/chat", "/api/knowledge"}:
                kind = {"/api/message": "auto", "/api/chat": "chat", "/api/feedback": "feedback", "/api/analyze": "analysis", "/api/knowledge": "knowledge"}[path]
                rid = self.app.submit(payload.get("session_id"), payload.get("message"), kind)
                return self.send(202, {"run_id": rid})
            if path == "/api/resume":
                return self.send(202, {"run_id": self.app.submit(resume=payload.get("run_id"))})
            self.send(404, {"error": "Not found"})
        except PermissionError as exc:
            self.send(403, {"error": str(exc)})
        except (ValueError, TypeError, RuntimeError) as exc:
            self.send(400, {"error": str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "Invalid request"})

    def log_message(self, *args):
        pass  # No relationship content or keys in access logs.


def create_server(root, port=8765, client=None):
    app = Application(root, client)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    return server


def main():
    parser = argparse.ArgumentParser(description="Local Relationship Agent web app")
    parser.add_argument("--mode", choices=("mock", "api"), default="mock")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--protocol", choices=("anthropic", "chat-completions"))
    parser.add_argument("--api-key-env", default="GLM_API_KEY")
    parser.add_argument("--memory-dir", default=str(Path.cwd() / "memory" / "v2"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    client = build_model_client(args.mode, model=args.model, base_url=args.base_url, protocol=args.protocol, api_key_env=args.api_key_env)
    server = create_server(args.memory_dir, args.port, client)
    print(f"Relationship Agent: http://127.0.0.1:{server.server_port}  ({client.mode})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.app.executor.shutdown(wait=True)
