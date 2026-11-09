"""Native-core isolation checks with fictitious accounts and private state."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from preview import environment


class PreviewLauncher(unittest.TestCase):
    def test_an_existing_window_cannot_be_mistaken_for_a_reconfigured_preview(self):
        with tempfile.TemporaryDirectory(prefix="herdr-preview-launcher-") as folder:
            root = Path(folder).resolve()
            app = root / "app"
            accounts = app / "accounts"
            accounts.mkdir(parents=True)
            context = accounts / "core.json"
            context.write_text('{"HC_SESSION":"previous-core"}')
            client = root / "herdr-app"
            unexpected = root / "unexpected-open"
            client.write_text("#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\n"
                "if sys.argv[1:] == ['status']:\n    print('{}')\n"
                "    print('Permission denied',file=sys.stderr)\n    sys.exit(int(os.environ['HERDR_TEST_STATUS']))\n"
                "else:\n    Path(" + repr(str(unexpected)) + ").write_text('raised-old-window')\n")
            client.chmod(0o700)
            fake = root / "codex"
            fake.write_text("#!/bin/sh\nexit 1\n")
            fake.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       HERDR_ACCOUNTS_CODEX_BINARY=str(fake))
            for status in ("0", "2"):
                with self.subTest(status=status):
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name("preview.py")),
                        "--app-home", str(app)], env=dict(env, HERDR_TEST_STATUS=status),
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, "must refuse to reuse an unverified running window")
                    self.assertEqual(context.read_text(), '{"HC_SESSION":"previous-core"}')
                    self.assertFalse(unexpected.exists())
                    self.assertFalse((app / "runtime").exists())
                    self.assertIn("ventana", result.stderr.lower())


@unittest.skipUnless(shutil.which("hc") and Path("/bin/zsh").exists(), "Herdr native core required")
class PreviewIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="herdr-preview-check-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.external = self.root / "external/auth.json"
        self.external.parent.mkdir()
        self.external.write_text("external-login-must-not-change")
        binary = self.root / "codex-fixture"
        binary.write_text((Path(__file__).parent / "tests/fixtures/codex.py").read_text())
        binary.chmod(0o700)
        with patch.dict(os.environ, CODEX_HOME=str(self.external.parent)):
            self.env = environment(self.root / "app", str(binary))
        self.controller = Path(__file__).with_name("herdr_accounts.py")
        self.home = self.root / "app/accounts"
        self.prefix = [sys.executable, str(self.controller), "--home", str(self.home), "--codex", str(binary)]
        self.addCleanup(lambda: subprocess.run(["hc", "server", "stop"], env=self.env,
                                              capture_output=True, timeout=10))

    def hc(self, *args):
        result = subprocess.run(["hc", *args], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def account(self, *args):
        result = subprocess.run([*self.prefix, *args], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, "private account operation failed")
        return json.loads(result.stdout)

    def wait_for_screen(self, terminal, text):
        deadline = time.monotonic() + 6
        while True:
            screen = self.hc("read", terminal, "--lines", "35")
            if text in screen:
                return
            self.assertLess(time.monotonic(), deadline, "expected native terminal output did not appear: " + screen[-1500:])
            time.sleep(0.05)

    def test_menu_fallback_and_new_native_shell_preserve_external_login(self):
        pending = self.account("enrol")
        # Real core, exact macOS agent-menu wrapper, real controller login.
        argv = ["/bin/zsh", "-lic", '\"$@\"; exec \"$0\" -li', "/bin/zsh", *pending["command"]]
        terminal = json.loads(self.hc("run", "--bg", "--json", "--cwd", str(self.root), "--", *argv))["address"]
        deadline = time.monotonic() + 6
        while self.account("status")["login"].get("state") != "completed":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        # This is exactly the dangerous transition after the original login.
        probe = "import os,sys;print('HERDR_HOME_MATCH',os.environ.get('CODEX_HOME')==sys.argv[1])"
        self.hc("send", terminal, shlex.join([sys.executable, "-c", probe, str(self.home / "codex")]))
        self.wait_for_screen(terminal, "HERDR_HOME_MATCH True")
        lookup = "import shutil,sys;print('HERDR_COMMAND_MATCH',shutil.which('codex')==sys.argv[1])"
        self.hc("send", terminal, shlex.join([sys.executable, "-c", lookup, str(self.home / "bin/codex")]))
        self.wait_for_screen(terminal, "HERDR_COMMAND_MATCH True")
        self.assertTrue(self.external.read_text() == "external-login-must-not-change")
        self.hc("kill", terminal)

        # Ordinary + Terminal / Cmd-T uses the preview's configured shell too.
        shell = json.loads(self.hc("run", "--bg", "--json", "--cwd", str(self.root)))["address"]
        self.hc("send", shell, "command -v codex")
        self.wait_for_screen(shell, str(self.home / "bin/codex"))
        self.hc("send", shell, "codex exec --model fixture")
        self.wait_for_screen(shell, '"codex_home": "' + str(self.home / "codex") + '"')
        self.assertIn(shell, self.account("status")["managed_terminals"])
        self.assertTrue(self.external.read_text() == "external-login-must-not-change")
        self.hc("kill", shell)


if __name__ == "__main__":
    unittest.main()
