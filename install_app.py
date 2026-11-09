#!/usr/bin/env python3
"""Install a personal mod/layout into an explicitly selected Herdr App home."""
import argparse
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-home", required=True)
    parser.add_argument("--base-layout", required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    app = Path(args.app_home).expanduser().resolve()
    mod = app / "mods" / "codex-accounts"
    mod.mkdir(parents=True, exist_ok=True)
    for source in (project / "mod").iterdir():
        shutil.copyfile(source, mod / source.name)
    config = {"python": sys.executable, "controller": str(project / "herdr_accounts.py"),
              "accounts_home": str(app / "accounts")}
    (mod / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    layout = json.loads(Path(args.base_layout).expanduser().read_text())

    def add_button(node):
        if node.get("id") == "tabs":
            original = dict(node)
            original["size"] = {"weight": 1}
            node.clear()
            node.update(id="accounts-tab-bar", type="row", size={"px": 42},
                        children=[original, {"id": "codex-accounts-button", "type": "block",
                                  "size": {"px": 230}, "content": {"mod": "codex-accounts"}}])
            return True
        return any(add_button(child) for child in node.get("children", []))

    if not add_button(layout):
        raise SystemExit("El layout base no contiene una barra de pestañas compatible.")
    layouts = app / "layouts"
    layouts.mkdir(parents=True, exist_ok=True)
    target = layouts / "codex-accounts.json"
    target.write_text(json.dumps(layout, indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    main()
