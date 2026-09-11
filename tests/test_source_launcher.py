"""Source startup checks use disposable apps; never import the live backend."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_launcher", ROOT / "run.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class SourceLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keivotos launcher ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "frontend").mkdir()
        self.root_patch = patch.object(launcher, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def built(self):
        (self.root / "frontend" / "dist").mkdir()
        (self.root / "frontend" / "dist" / "index.html").write_text("ready")

    def test_existing_frontend_needs_no_npm_and_forwards_arguments_and_exit(self):
        self.built()
        (self.root / "app.py").write_text(
            "import os, sys\n"
            "assert sys.argv[1:] == ['--port', '52326', 'a path with spaces']\n"
            "assert os.getcwd() == os.path.dirname(__file__)\n"
            "raise SystemExit(7)\n"
        )
        previous_directory, previous_argv = Path.cwd(), sys.argv
        with patch.object(launcher.shutil, "which") as which:
            with self.assertRaises(SystemExit) as result:
                launcher.main(["--port", "52326", "a path with spaces"])
        self.assertEqual(result.exception.code, 7)
        which.assert_not_called()
        self.assertEqual(Path.cwd(), previous_directory)
        self.assertIs(sys.argv, previous_argv)

    def test_missing_frontend_builds_in_order_on_both_platforms(self):
        (self.root / "app.py").write_text("pass\n")
        for platform, executable in (("win32", "npm.cmd"), ("linux", "npm")):
            with self.subTest(platform=platform), \
                 patch.object(launcher.sys, "platform", platform), \
                 patch.object(launcher.shutil, "which", return_value=executable) as which, \
                 patch.object(launcher.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertEqual(launcher.main([]), 0)
                which.assert_called_once_with(executable)
                self.assertEqual([call.args[0] for call in run.call_args_list],
                                 [[executable, "ci"], [executable, "run", "build"]])
                self.assertTrue(all(call.kwargs["cwd"] == self.root / "frontend"
                                    for call in run.call_args_list))

    def test_missing_npm_does_not_start_app(self):
        with patch.object(launcher.shutil, "which", return_value=None), \
             patch.object(launcher.runpy, "run_path") as app:
            self.assertEqual(launcher.main([]), 1)
            app.assert_not_called()

    def test_install_or_build_failure_stops_startup(self):
        for codes in ([9], [0, 8]):
            with self.subTest(codes=codes), \
                 patch.object(launcher.shutil, "which", return_value="npm"), \
                 patch.object(launcher.subprocess, "run", side_effect=[
                     subprocess.CompletedProcess([], code) for code in codes
                 ]) as run, patch.object(launcher.runpy, "run_path") as app:
                self.assertEqual(launcher.main([]), codes[-1])
                self.assertEqual(run.call_count, len(codes))
                app.assert_not_called()

    def test_unlaunchable_npm_reports_failure(self):
        with patch.object(launcher.shutil, "which", return_value="npm"), \
             patch.object(launcher.subprocess, "run", side_effect=OSError("cannot execute")), \
             patch.object(launcher.runpy, "run_path") as app:
            self.assertEqual(launcher.main([]), 1)
            app.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "native Windows batch execution")
    def test_windows_npm_batch_failure_is_propagated(self):
        npm = self.root / "npm.cmd"
        npm.write_text("@echo off\nexit /b 7\n")
        with patch.object(launcher.shutil, "which", return_value=str(npm)), \
             patch.object(launcher.runpy, "run_path") as app:
            self.assertEqual(launcher.main([]), 7)
            app.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "POSIX signal and shell check")
    def test_shell_preserves_arguments_exit_and_interrupt(self):
        self.built()
        for name in ("run.py", "run.sh"):
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        # Fake uv keeps this a local process test with no dependency downloads.
        uv = self.root / "uv"
        uv.write_text('#!/bin/sh\nshift 4\nexec "$TEST_PYTHON" "$@"\n')
        uv.chmod(0o755)
        env = {**os.environ, "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
               "TEST_PYTHON": sys.executable}
        (self.root / "app.py").write_text(
            "import sys\nassert sys.argv[1:] == ['a path with spaces']\nraise SystemExit(7)\n"
        )
        result = subprocess.run(["sh", str(self.root / "run.sh"), "a path with spaces"],
                                cwd="/tmp", env=env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stderr)
        ready = self.root / "ready"
        (self.root / "app.py").write_text(
            "from pathlib import Path\nimport time\nPath('ready').touch()\ntime.sleep(60)\n"
        )
        process = subprocess.Popen(["sh", str(self.root / "run.sh")], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130, stderr)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()


if __name__ == "__main__":
    unittest.main()
