"""Private local Codex app-server transport. RPC credentials never leave this module."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time


AUTH_OPTIONS = ["-c", 'cli_auth_credentials_store="file"',
                "-c", 'forced_login_method="chatgpt"']


class NativeError(Exception):
    pass


class NativeRPC:
    """The native Unix endpoint speaks uncompressed RFC 6455, not JSONL."""
    LIMIT = 64 * 1024 * 1024

    def __init__(self, endpoint, timeout=15):
        self.timeout = timeout
        self.serial = 0
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.stream = None
        try:
            self.socket.settimeout(timeout)
            self.socket.connect(str(endpoint))
            self.stream = self.socket.makefile("rb")
            key = base64.b64encode(os.urandom(16)).decode()
            self.socket.sendall(("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: "
                + key + "\r\n\r\n").encode())
            status = self.stream.readline(4096)
            headers = {}
            size = 0
            while True:
                line = self.stream.readline(4096)
                size += len(line)
                if not line or size > 16384:
                    raise NativeError("Codex no completó la conexión privada.")
                if line == b"\r\n":
                    break
                name, value = line.decode().split(":", 1)
                headers[name.lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            if status.split()[:2] != [b"HTTP/1.1", b"101"] or headers.get("sec-websocket-accept") != expected:
                raise NativeError("Codex rechazó la conexión privada.")
            self.call("initialize", {"clientInfo": {"name": "herdr_accounts", "version": "0.1"},
                                     "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def send(self, message, opcode=1):
        data = message if isinstance(message, bytes) else json.dumps(message).encode()
        length = len(data)
        if length > self.LIMIT:
            raise NativeError("El mensaje nativo supera el límite de lectura.")
        mask = os.urandom(4)
        header = bytes([0x80 | opcode, 0x80 | (length if length < 126 else 126 if length < 65536 else 127)])
        if length >= 126:
            header += struct.pack("!H" if length < 65536 else "!Q", length)
        self.socket.sendall(header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(data)))

    def read_exact(self, size):
        data = self.stream.read(size)
        if len(data) != size:
            raise NativeError("Se cerró la conexión con Codex.")
        return data

    def receive(self, deadline):
        fragments = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeError("Codex tardó demasiado en responder.")
            self.socket.settimeout(remaining)
            first, second = self.read_exact(2)
            opcode = first & 15
            length = second & 127
            if length in (126, 127):
                length = struct.unpack("!H" if length == 126 else "!Q",
                                      self.read_exact(2 if length == 126 else 8))[0]
            if second & 128 or first & 112 or length > self.LIMIT or len(fragments) + length > self.LIMIT:
                raise NativeError("Codex devolvió una trama no válida.")
            data = self.read_exact(length)
            if opcode == 8:
                raise NativeError("Se cerró la conexión con Codex.")
            if opcode == 9:
                self.send(data, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1, 2):
                raise NativeError("Codex devolvió una trama no válida.")
            fragments.extend(data)
            if first & 128:
                return json.loads(fragments)

    def call(self, method, params=None):
        self.serial += 1
        serial = self.serial
        self.send({"id": serial, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            reply = self.receive(deadline)
            # This connection never approves tools or responds to host-auth requests.
            if reply.get("id") != serial or "method" in reply:
                continue
            if "error" in reply:
                raise NativeError("Codex rechazó la operación nativa.")
            return reply.get("result")

    def close(self):
        if self.stream:
            self.stream.close()
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class NativeServer:
    def __init__(self, binary, env, cwd=None):
        self.binary, self.env, self.cwd = binary, env, cwd
        self.directory = tempfile.TemporaryDirectory(prefix="herdr-codex-", dir="/tmp")
        self.endpoint = Path(self.directory.name) / "rpc.sock"
        fd = os.open(Path(self.directory.name) / "server.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.log = os.fdopen(fd, "wb")
        self.process = None

    def start(self):
        try:
            self.process = subprocess.Popen([self.binary, "--no-daemon", *AUTH_OPTIONS,
                "app-server", "--listen", "unix://" + str(self.endpoint)], env=self.env,
                cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                start_new_session=True)
            deadline = time.monotonic() + 15
            while not self.endpoint.exists():
                if self.process.poll() is not None or time.monotonic() > deadline:
                    raise NativeError("No se pudo iniciar el servidor privado de Codex.")
                time.sleep(0.05)
            return self
        except BaseException:
            self.close()
            raise

    def connect(self):
        return NativeRPC(self.endpoint)

    def verify(self, payload, provider=False):
        with self.connect() as rpc:
            if provider:
                rpc.call("account/rateLimits/read")
            auth = rpc.call("getAuthStatus", {"includeToken": True, "refreshToken": False})
        expected = payload.get("auth", {}).get("tokens", {}).get("access_token")
        if not expected or auth.get("authMethod") != "chatgpt" or auth.get("authToken") != expected:
            raise NativeError("La identidad efectiva de Codex no coincide con la Cuenta.")

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.log.close()
        self.directory.cleanup()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.close()
