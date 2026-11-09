#!/usr/bin/env python3
"""Offline public-CLI fixture. All credentials below are deliberately fictitious."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socketserver
import struct
import sys
import threading
import time


args = sys.argv[1:]
auth_file = Path(os.environ["CODEX_HOME"]) / "auth.json"


def send_frame(stream, data, masked=False):
    data = json.dumps(data).encode()
    size = len(data)
    header = bytes([0x81, (0x80 if masked else 0) | (size if size < 126 else 126 if size < 65536 else 127)])
    if size >= 126:
        header += struct.pack("!H" if size < 65536 else "!Q", size)
    if masked:
        mask = os.urandom(4)
        data = mask + bytes(value ^ mask[i % 4] for i, value in enumerate(data))
    stream.write(header + data)
    stream.flush()


def read_frame(stream):
    head = stream.read(2)
    if not head or head[0] & 15 == 8:
        return None
    size = head[1] & 127
    if size in (126, 127):
        size = struct.unpack("!H" if size == 126 else "!Q", stream.read(2 if size == 126 else 8))[0]
    mask = stream.read(4) if head[1] & 128 else None
    data = stream.read(size)
    if mask:
        data = bytes(value ^ mask[i % 4] for i, value in enumerate(data))
    return json.loads(data)


def serve():
    endpoint = args[args.index("--listen") + 1].removeprefix("unix://")
    cached = json.loads(auth_file.read_text())
    lock = threading.Lock()
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            headers = {}
            while True:
                line = self.rfile.readline()
                if line == b"\r\n":
                    break
                if not line:
                    return
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] +
                "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())
            self.wfile.flush()
            while True:
                try:
                    request = read_frame(self.rfile)
                except (ConnectionError, ValueError, struct.error):
                    return
                if request is None:
                    return
                if "id" not in request:
                    continue
                method = request["method"]
                error = None
                with lock:
                    if method == "initialize":
                        result = {"userAgent": "codex/fixture", "codexHome": str(auth_file.parent)}
                    elif method == "getAuthStatus":
                        result = {"authMethod": "chatgpt", "authToken": cached["tokens"]["access_token"]}
                    elif method == "account/rateLimits/read":
                        state_path = os.environ.get("HERDR_TEST_PROVIDER_STATE")
                        state = json.loads(Path(state_path).read_text()) if state_path else {}
                        if cached["tokens"]["account_id"] in state.get("rejected", []):
                            error = {"code": -32000, "message": "Fixture account refused"}
                        result = {"rateLimits": {}}
                    else:
                        error = {"code": -32601, "message": "Fixture method unsupported"}
                        result = None
                send_frame(self.wfile, {"id": request["id"], **({"error": error} if error else {"result": result})})
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    with Server(endpoint, Handler) as server:
        server.serve_forever()


if "app-server" in args:
    serve()
elif "login" in args:
    if "status" in args:
        sys.exit(0 if auth_file.exists() else 1)
    mode = os.environ.get("HERDR_TEST_LOGIN", "success")
    if mode == "wait":
        print("LOGIN_WAITING", flush=True)
        time.sleep(60)
    if mode == "fail":
        print("fake login failed", file=sys.stderr)
        sys.exit(1)
    account = os.environ.get("HERDR_TEST_ACCOUNT", "demo")
    claims = {"email": account + "@example.invalid", "https://api.openai.com/auth": {
        "chatgpt_account_id": account + "-account", "chatgpt_plan_type": "plus"}}
    token = "fixture." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".fixture"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token,
        "account_id": account + "-account", "access_token": "FIXTURE_SECRET_" + account}}))
else:
    print(json.dumps({"args": args, "codex_home": os.environ.get("CODEX_HOME"),
        "sqlite_home": os.environ.get("CODEX_SQLITE_HOME"),
        "api_key": os.environ.get("OPENAI_API_KEY"), "group": os.environ.get("HERDR_ACCOUNT_GROUP")}))
