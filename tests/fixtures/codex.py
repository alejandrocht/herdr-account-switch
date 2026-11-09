#!/usr/bin/env python3
"""Offline public-CLI fixture. All credentials below are deliberately fictitious."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socketserver
import socket
import struct
import sys
import threading
import time
import uuid


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
    history_file = auth_file.parent / "fixture_threads.json"
    threads = json.loads(history_file.read_text()) if history_file.exists() else {}
    loaded = set()
    lock = threading.Lock()
    def provider_state():
        path = os.environ.get("HERDR_TEST_PROVIDER_STATE")
        return json.loads(Path(path).read_text()) if path else {}
    def save_provider(state):
        path = Path(os.environ["HERDR_TEST_PROVIDER_STATE"])
        stage = path.with_suffix(".native.tmp")
        stage.write_text(json.dumps(state))
        stage.replace(path)
    def turn(params, started):
        with lock:
            thread = threads[params["threadId"]]
            thread["status"] = {"type": "active"}
        started()
        while provider_state().get("hold_turns"):
            time.sleep(0.02)
        with lock:
            message = params["input"][0]["text"]
            number = len(thread["turns"]) + 1
            items = [{"id": f"user-{number}", "type": "userMessage", "text": message}]
            if message == "write-once":
                work = Path(thread["cwd"]) / "work.txt"
                count = int(work.read_text()) + 1 if work.exists() else 1
                work.write_text(str(count))
                items.append({"id": f"tool-{number}", "type": "commandExecution",
                              "output": "NATIVE_TOOL_RESULT_" + str(count)})
            items.append({"id": f"answer-{number}", "type": "agentMessage", "text": "DONE"})
            thread["turns"].append({"id": f"turn-{number}", "items": items, "status": "completed"})
            thread["status"] = {"type": "idle"}
            history_file.write_text(json.dumps(threads))
            return {"event": "turn", "thread_id": thread["id"],
                    "account": cached["tokens"]["account_id"], "history": thread["turns"]}
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
                params = request.get("params") or {}
                error = None
                if method == "turn/start":
                    result = turn(params, lambda: send_frame(self.wfile,
                        {"method": "turn/started", "params": {"threadId": params["threadId"]}}))
                    send_frame(self.wfile, {"id": request["id"], "result": result})
                    continue
                with lock:
                    if method == "initialize":
                        result = {"userAgent": "codex/fixture", "codexHome": str(auth_file.parent)}
                    elif method == "getAuthStatus":
                        state = provider_state()
                        if state.get("hold_activation") == cached["tokens"]["account_id"] and state.get("live_home") == str(auth_file.parent):
                            state.update(activation_waiting=True, activation_pid=os.getpid())
                            save_provider(state)
                            while provider_state().get("hold_activation"):
                                time.sleep(0.02)
                        if state.get("refresh_live") == cached["tokens"]["account_id"] and state.get("live_home") == str(auth_file.parent) and not cached.get("fixture_rotated"):
                            state.setdefault("revoked_access", []).append(cached["tokens"]["access_token"])
                            save_provider(state)
                            cached["tokens"]["access_token"] += "_rotated"
                            cached["fixture_rotated"] = True
                            auth_file.write_text(json.dumps(cached))
                        stale = state.get("reject_activation") == cached["tokens"]["account_id"] and state.get("live_home") == str(auth_file.parent)
                        result = {"authMethod": "chatgpt", "authToken": "FIXTURE_STALE" if stale else cached["tokens"]["access_token"]}
                    elif method == "account/rateLimits/read":
                        state = provider_state()
                        if cached["tokens"]["account_id"] in state.get("rejected", []) or cached["tokens"]["access_token"] in state.get("revoked_access", []):
                            error = {"code": -32000, "message": "Fixture account refused"}
                        result = {"rateLimits": {}}
                    elif method == "thread/loaded/list":
                        result = {"data": list(loaded)}
                    elif method == "thread/start":
                        thread_id = str(uuid.uuid4())
                        threads[thread_id] = {"id": thread_id, "status": {"type": "idle"},
                            "cwd": params.get("cwd"), "turns": []}
                        loaded.add(thread_id)
                        history_file.write_text(json.dumps(threads))
                        result = {"thread": threads[thread_id]}
                    elif method in ("thread/read", "thread/resume"):
                        thread_id = params["threadId"]
                        state = provider_state()
                        if method == "thread/resume" and state.get("hold_resume") == cached["tokens"]["account_id"]:
                            state["resume_waiting"] = True
                            save_provider(state)
                            while provider_state().get("hold_resume"):
                                time.sleep(0.02)
                        if method == "thread/resume" and state.get("reject_resume") == cached["tokens"]["account_id"]:
                            send_frame(self.wfile, {"id": request["id"], "error": {"code": -32000, "message": "Fixture resume refused"}})
                            continue
                        if method == "thread/resume":
                            loaded.add(thread_id)
                        result = {"thread": threads[thread_id]}
                    else:
                        error = {"code": -32601, "message": "Fixture method unsupported"}
                        result = None
                send_frame(self.wfile, {"id": request["id"], **({"error": error} if error else {"result": result})})
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    with Server(endpoint, Handler) as server:
        server.serve_forever()


def tui():
    endpoint = args[args.index("--remote") + 1].removeprefix("unix://")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(endpoint)
    stream = sock.makefile("rwb")
    key = base64.b64encode(os.urandom(16)).decode()
    stream.write(("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: " + key + "\r\n\r\n").encode())
    stream.flush()
    while stream.readline() != b"\r\n":
        pass
    serial = 0
    def rpc(method, params=None):
        nonlocal serial
        serial += 1
        send_frame(stream, {"id": serial, "method": method, "params": params or {}}, masked=True)
        while True:
            reply = read_frame(stream)
            if reply.get("method") == "turn/started":
                print(json.dumps({"event": "working"}), flush=True)
            elif reply.get("id") == serial:
                return reply["result"]
    rpc("initialize")
    if "resume" in args:
        thread = rpc("thread/resume", {"threadId": args[args.index("resume") + 1]})["thread"]
    else:
        thread = rpc("thread/start", {"cwd": os.getcwd()})["thread"]
    print(json.dumps({"event": "ready", "thread_id": thread["id"], "history": thread["turns"]}), flush=True)
    for line in sys.stdin:
        result = rpc("turn/start", {"threadId": thread["id"], "input": [{"type": "text", "text": line.rstrip("\n")}]})
        print(json.dumps(result), flush=True)
    stream.close()
    sock.close()


if "app-server" in args:
    serve()
elif "--remote" in args:
    tui()
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
