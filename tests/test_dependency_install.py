"""Exercise dependency installation with isolated package-manager stand-ins."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install-dependencies.sh"
COMMAND_STAND_IN = r'''
import json
import os
from pathlib import Path
import re
import sys

command = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["MUSIC_TEST_COMMAND_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([command] + args) + "\n")

if command == "sudo":
    if not args or args[0] != "apt-get":
        raise SystemExit("Unexpected privileged command")
    target = Path(sys.argv[0]).parent / "apt-get"
    os.execv(str(target), [str(target)] + args[1:])
elif command == "apt-get":
    if not args or args[0] not in ("update", "install"):
        raise SystemExit("Unexpected package-manager command")
    failure = os.environ.get("MUSIC_TEST_APT_FAILURE")
    raise SystemExit(42 if args[0] == failure else 0)
elif command == "apt-cache":
    if len(args) != 2 or args[0] != "policy":
        raise SystemExit("Unexpected package query")
    candidates = json.loads(os.environ["MUSIC_TEST_CANDIDATES"])
    print("  Candidate: " + candidates.get(args[1], "(none)"))
elif command == "dpkg":
    if len(args) != 4 or args[0] != "--compare-versions" or args[2] != "ge":
        raise SystemExit("Unexpected version comparison")
    # These fixtures use numeric releases with optional distribution suffixes.
    def release(version):
        match = re.match(r"\d+(?:\.\d+)*", version)
        if not match:
            raise SystemExit("Unexpected fixture version")
        parts = tuple(int(part) for part in match.group().split("."))
        return parts + (0,) * (8 - len(parts))
    raise SystemExit(0 if release(args[1]) >= release(args[3]) else 1)
else:
    raise SystemExit("Unexpected command")
'''


class DependencyInstallTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="music-dependencies-")
        self.addCleanup(self.scratch.cleanup)
        self.directory = Path(self.scratch.name)
        self.bin_dir = self.directory / "bin"
        self.bin_dir.mkdir()
        self.log = self.directory / "commands.jsonl"
        self.bash = shutil.which("bash")
        awk = shutil.which("awk")
        if not self.bash or not awk:
            self.skipTest("These shell-script tests require bash and awk")
        # PATH contains no real package manager or privilege escalation tool.
        for command in ("apt-get", "apt-cache", "dpkg", "sudo"):
            target = self.bin_dir / command
            target.write_text("#!" + sys.executable + "\n" + COMMAND_STAND_IN,
                              encoding="utf-8")
            target.chmod(0o755)
        (self.bin_dir / "awk").symlink_to(awk)
        self.candidates = {
            "gir1.2-webkit2-4.1": "2.50.4-1",
            "gir1.2-webkit2-4.0": "2.38.6-1",
            "python3": "3.11.2-1",
            "python3-gi": "3.42.2-3",
            "gir1.2-gtk-3.0": "3.24.38-2",
            "gstreamer1.0-plugins-good": "1.22.0-5",
        }

    def run_installer(self, changes=None, failure=""):
        candidates = dict(self.candidates)
        candidates.update(changes or {})
        env = dict(os.environ)
        env.update({
            "PATH": str(self.bin_dir),
            "MUSIC_TEST_COMMAND_LOG": str(self.log),
            "MUSIC_TEST_CANDIDATES": json.dumps(candidates),
            "MUSIC_TEST_APT_FAILURE": failure,
        })
        # Do not inherit shell startup hooks into the isolated command runner.
        env.pop("BASH_ENV", None)
        result = subprocess.run(
            [self.bash, "--noprofile", "--norc", str(INSTALLER)],
            env=env, cwd=self.directory, capture_output=True, text=True,
            encoding="utf-8", timeout=15)
        commands = [json.loads(line) for line in self.log.read_text(
            encoding="utf-8").splitlines()] if self.log.exists() else []
        apt = [entry[1:] for entry in commands if entry[0] == "apt-get"]
        return result, apt

    def assert_installed(self, result, apt, webkit, pulse):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(apt[0], ["update"])
        self.assertEqual(len(apt), 2, apt)
        self.assertEqual(apt[1][0], "install")
        packages = apt[1][1:]
        self.assertEqual([name for name in packages if name.startswith(
            "gir1.2-webkit2-")], [webkit])
        self.assertEqual("gstreamer1.0-pulseaudio" in packages, pulse)
        self.assertTrue({"python3", "python3-gi", "gir1.2-gtk-3.0",
                         "ca-certificates", "librsvg2-common",
                         "gstreamer1.0-plugins-base", "gstreamer1.0-plugins-good",
                         "gstreamer1.0-libav", "gstreamer1.0-alsa"}.issubset(packages))

    def assert_rejected(self, result, apt, detail):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(apt, [["update"]])
        self.assertIn(detail, result.stderr)

    def test_prefers_41_when_both_abis_are_available(self):
        result, apt = self.run_installer()
        self.assert_installed(result, apt, "gir1.2-webkit2-4.1", pulse=False)

    def test_40_and_old_audio_plugins_support_minimum_releases(self):
        result, apt = self.run_installer({
            "gir1.2-webkit2-4.1": "(none)",
            "gir1.2-webkit2-4.0": "2.28.0-1",
            "python3": "3.8.0-1",
            "python3-gi": "3.36.0-1",
            "gir1.2-gtk-3.0": "3.24.0-1",
            "gstreamer1.0-plugins-good": "1.16.3-0ubuntu1",
        })
        self.assert_installed(result, apt, "gir1.2-webkit2-4.0", pulse=True)

    def test_too_old_41_can_fall_back_to_supported_40(self):
        result, apt = self.run_installer({"gir1.2-webkit2-4.1": "2.34.0-1"})
        self.assert_installed(result, apt, "gir1.2-webkit2-4.0", pulse=False)

    def test_both_webkit_versions_too_old_prevent_installation(self):
        result, apt = self.run_installer({
            "gir1.2-webkit2-4.1": "2.34.0-1",
            "gir1.2-webkit2-4.0": "2.26.4-1",
        })
        self.assert_rejected(result, apt, "WebKitGTK")

    def test_missing_webkit_candidates_prevent_installation(self):
        result, apt = self.run_installer({
            "gir1.2-webkit2-4.1": "(none)",
            "gir1.2-webkit2-4.0": "(none)",
        })
        self.assert_rejected(result, apt, "WebKitGTK")

    def test_outdated_core_runtime_prevents_installation(self):
        for package, version in (("python3", "3.7.17-1"),
                                 ("python3-gi", "3.34.0-1"),
                                 ("gir1.2-gtk-3.0", "3.22.30-1")):
            with self.subTest(package=package):
                if self.log.exists():
                    self.log.unlink()
                result, apt = self.run_installer({package: version})
                self.assert_rejected(result, apt, package)

    def test_good_118_does_not_add_transitional_audio_package(self):
        result, apt = self.run_installer({
            "gstreamer1.0-plugins-good": "1.18.0-1",
        })
        self.assert_installed(result, apt, "gir1.2-webkit2-4.1", pulse=False)

    def test_package_index_update_failure_stops_installation(self):
        result, apt = self.run_installer(failure="update")
        self.assertEqual(result.returncode, 42)
        self.assertEqual(apt, [["update"]])

    def test_install_failure_is_reported_as_failure(self):
        result, apt = self.run_installer(failure="install")
        self.assertEqual(result.returncode, 42)
        self.assertEqual(len(apt), 2)
        self.assertEqual(apt[1][0], "install")


if __name__ == "__main__":
    unittest.main()
