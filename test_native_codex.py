"""Check the production TUI launcher against the installed CLI, without login."""
import os
from pathlib import Path
try:
    import pty
except ImportError:
    pty = None
import select
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herdr_accounts import Accounts


@unittest.skipUnless(shutil.which("codex") and pty is not None, "local Codex/PTY required")
class NativeCodexCompatibility(unittest.TestCase):
    def test_tui_accepts_private_remote_connection_arguments(self):
        with tempfile.TemporaryDirectory(prefix="herdr-native-cli-") as folder:
            root = Path(folder)
            accounts = Accounts(root / "accounts")
            home = root / "codex"
            home.mkdir()
            env = accounts.environment(home)
            env.update(HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                       ALL_PROXY="http://127.0.0.1:9", NO_PROXY="localhost,127.0.0.1", TERM="xterm-256color")
            endpoint = root / "not-running.sock"
            master, slave = pty.openpty()
            original = subprocess.Popen
            def attached(argv, *, env):
                return original(argv, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            process = None
            output = bytearray()
            try:
                with patch("herdr_accounts.subprocess.Popen", side_effect=attached):
                    process = accounts.start_tui(SimpleNamespace(endpoint=endpoint), [], env)
                os.close(slave)
                slave = None
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        try:
                            chunk = os.read(master, 16384)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output.extend(chunk)
                    elif process.poll() is not None:
                        break
                text = output.decode(errors="replace")
                self.assertNotIn("--no-daemon cannot be used with --remote", text)
                self.assertIn("connect", text.lower(), "The real CLI must reach its private connection attempt")
            finally:
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
                os.close(master)
                if slave is not None:
                    os.close(slave)


if __name__ == "__main__":
    unittest.main()
