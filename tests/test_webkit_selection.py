"""Exercise ABI selection through the real command without loading native GTK."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


APP = Path(__file__).resolve().parents[1] / "app.py"

GI_STUB = """
import json
import os

selected_api = None


def record(event, value):
    with open(os.environ["TEST_GI_LOG"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps([event, value]) + "\\n")


def require_version(namespace, version):
    global selected_api
    if namespace == "WebKit2":
        record("require", version)
        available = os.environ["TEST_GI_AVAILABLE"].split(",")
        if version not in available:
            raise ValueError("fixture typelib unavailable: " + version)
        selected_api = version
    elif (namespace, version) not in (("Gtk", "3.0"), ("Gdk", "3.0")):
        raise AssertionError("unexpected namespace requirement")
"""

REPOSITORY_STUB = """
import os
from types import SimpleNamespace
from gi import record, selected_api

record("repository", selected_api)
if os.environ["TEST_GI_IMPORT_FAILURE"] == "1":
    raise ImportError("fixture repository import failure")


class NoUI:
    def __init__(self, *args, **kwargs):
        record("unexpected-ui", selected_api)
        raise AssertionError("dependency checks must not construct a GUI")


class WebView(NoUI):
    def run_javascript(self, *args, **kwargs):
        raise AssertionError("dependency checks must not execute JavaScript")


Gtk = SimpleNamespace(
    MAJOR_VERSION=3, MINOR_VERSION=24, MICRO_VERSION=0,
    Application=NoUI, ApplicationWindow=NoUI,
)
WebKit2 = SimpleNamespace(
    get_major_version=lambda: 2,
    get_minor_version=lambda: 36 if selected_api == "4.1" else 28,
    get_micro_version=lambda: 0,
    WebView=WebView,
)
Gdk = SimpleNamespace()
Gio = SimpleNamespace()
GLib = SimpleNamespace()
"""


class WebKitSelectionTests(unittest.TestCase):
    def run_check(self, available, import_failure=False):
        # Each case gets a fresh process: an imported native ABI cannot be
        # safely unloaded to test a different one in the same interpreter.
        with tempfile.TemporaryDirectory(prefix="music-abi-test-") as directory:
            root = Path(directory)
            package = root / "gi"
            package.mkdir()
            (package / "__init__.py").write_text(
                textwrap.dedent(GI_STUB), encoding="utf-8")
            (package / "repository.py").write_text(
                textwrap.dedent(REPOSITORY_STUB), encoding="utf-8")
            log = root / "imports.jsonl"
            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(root),
                "TEST_GI_AVAILABLE": ",".join(available),
                "TEST_GI_IMPORT_FAILURE": "1" if import_failure else "0",
                "TEST_GI_LOG": str(log),
                "DISPLAY": "",
                "WAYLAND_DISPLAY": "",
            })
            result = subprocess.run(
                [sys.executable, "-B", "-S", str(APP), "--check"],
                cwd=str(root), env=env, capture_output=True,
                text=True, encoding="utf-8", timeout=10,
            )
            events = [json.loads(line) for line in
                      log.read_text(encoding="utf-8").splitlines()]
        self.assertNotIn("unexpected-ui", [event[0] for event in events])
        return result, events

    def test_prefers_41_when_both_typelibs_exist(self):
        result, events = self.run_check(["4.0", "4.1"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(API 4.1)", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(events, [["require", "4.1"], ["repository", "4.1"]])

    def test_missing_41_uses_40(self):
        result, events = self.run_check(["4.0"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(API 4.0)", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(events, [
            ["require", "4.1"], ["require", "4.0"], ["repository", "4.0"],
        ])

    def test_no_typelib_fails_before_repository_import(self):
        result, events = self.run_check([])

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("gir1.2-webkit2-4.1", result.stderr)
        self.assertIn("gir1.2-webkit2-4.0", result.stderr)
        self.assertEqual(events, [["require", "4.1"], ["require", "4.0"]])

    def test_repository_import_failure_does_not_try_another_abi(self):
        result, events = self.run_check(["4.0", "4.1"], import_failure=True)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("fixture repository import failure", result.stderr)
        self.assertEqual(events, [["require", "4.1"], ["repository", "4.1"]])


if __name__ == "__main__":
    unittest.main()
