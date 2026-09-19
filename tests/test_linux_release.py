"""Behavior checks for Linux packaging without producing an application artifact."""
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("linux_release", ROOT / "scripts/release/build_linux.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_archive_preserves_executable_mode_and_refuses_overwrite(tmp_path):
    stage = tmp_path / "Keivotos-linux"
    stage.mkdir()
    executable = stage / "Keivotos"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    destination = tmp_path / "artifact.zip"
    builder.archive(stage, destination)
    with zipfile.ZipFile(destination) as archive:
        info = archive.getinfo("Keivotos-linux/Keivotos")
        if sys.platform != "win32":
            assert info.external_attr >> 16 & stat.S_IXUSR
        assert archive.read(info) == executable.read_bytes()
    original = destination.read_bytes()
    with pytest.raises(FileExistsError):
        builder.archive(stage, destination)
    assert destination.read_bytes() == original


def test_failed_build_step_stops(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        builder.run(sys.executable, "-c", "raise SystemExit(7)", cwd=tmp_path)


def test_version_and_output_guards_run_before_build(tmp_path):
    with patch.object(builder.sys, "platform", "linux"), patch.object(builder.platform, "machine", return_value="x86_64"):
        with pytest.raises(SystemExit):
            builder.main(["--version", "0.0.0-invalid"])
        with pytest.raises(SystemExit):
            builder.main(["--output-directory", str(tmp_path)])


@pytest.mark.parametrize("frozen", [False, True])
def test_vault_uses_helper_only_when_frozen(frozen):
    import credentials
    result = SimpleNamespace(returncode=0, stdout='{"value": "test-value"}')
    with patch.object(sys, "frozen", frozen, create=True), patch.object(credentials.subprocess, "run", return_value=result) as invoke:
        assert credentials._vault("get", "dummy-reference") == "test-value"
    command = invoke.call_args.args[0]
    assert command == ([sys.executable, "--credential-worker"] if frozen else [sys.executable, "-c", credentials._VAULT_WORKER])
    assert "dummy-reference" not in command
    assert invoke.call_args.kwargs["timeout"] == 10


def test_credential_helper_dispatches_without_server_startup():
    import app
    import credentials
    with patch.object(credentials, "_VAULT_WORKER", 'print("worker-ok")'), patch.object(app, "_load_asgi_app", side_effect=AssertionError("server started")), patch("sys.stdout", new_callable=io.StringIO) as output:
        assert app.main(["--credential-worker"]) == 0
    assert output.getvalue().strip() == "worker-ok"


@pytest.mark.parametrize("target,suffix", [("linux", ""), ("win32", ".exe")])
def test_frozen_portable_check_uses_target_tool_names(tmp_path, target, suffix):
    import app
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").touch()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/windows_folder_picker.py").touch()
    (tmp_path / "scripts/danbooru_gallery_dl.py").touch()
    config = SimpleNamespace(**{name: tmp_path for name in ("SUITE_HOME", "RUNTIME_CONFIG_FILE", "DATA_ROOT", "METADATA_DIR", "GALLERY_DL_DIR")})
    with patch.object(app, "ROOT", tmp_path), patch.object(sys, "platform", target), patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(tmp_path / f"Keivotos{suffix}")), patch.object(app, "_load_asgi_app", return_value=SimpleNamespace(routes=[SimpleNamespace(path="/")])):
        assert app._portable_check(config) == 1
        for tool in ("gallery-dl", "ffmpeg"):
            (tmp_path / f"{tool}{suffix}").touch()
        assert app._portable_check(config) == 0


@pytest.mark.parametrize("target,suffix", [("linux", ""), ("win32", ".exe")])
def test_frozen_thumbnail_uses_bundled_ffmpeg(tmp_path, target, suffix):
    import thumbnails
    from PIL import Image
    frame = io.BytesIO()
    Image.new("RGB", (2, 2)).save(frame, format="PNG")
    ffmpeg = tmp_path / f"ffmpeg{suffix}"
    ffmpeg.touch()
    with patch.object(sys, "platform", target), patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(tmp_path / f"Keivotos{suffix}")), patch.object(thumbnails.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=frame.getvalue(), stderr=b"")) as invoke:
        assert thumbnails._video_frame(tmp_path / "video.mp4").size == (2, 2)
        assert invoke.call_args.args[0][0] == str(ffmpeg)
        ffmpeg.unlink()
        with pytest.raises(RuntimeError, match="Portable video thumbnails"):
            thumbnails._video_frame(tmp_path / "video.mp4")


def test_build_copy_excludes_dependencies_and_user_data(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    builder.copy_sources(ROOT, source)
    assert (source / "scripts/release/build_linux.py").is_file()
    assert (source / "frontend/package-lock.json").is_file()
    assert not (source / ".venv").exists()
    assert not (source / "frontend/node_modules").exists()
    assert not (source / "data").exists()
    assert not (source / "frontend/dist").exists()


def test_smoke_stops_failed_server_and_isolates_environment(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setenv("DANBOORU_API_KEY", "dummy-secret")
    monkeypatch.setenv("KEIVOTOS_HOME", "live-home-must-not-be-used")
    process = MagicMock()
    process.poll.return_value = 9
    listener = MagicMock()
    listener.__enter__.return_value = listener
    listener.getsockname.return_value = ("127.0.0.1", 52300)
    with patch.object(builder, "run") as run, patch.object(builder.socket, "socket", return_value=listener), patch.object(builder.subprocess, "Popen", return_value=process) as start:
        with pytest.raises(RuntimeError, match="Portable server exited"):
            builder.smoke(tmp_path, tmp_path / "isolated-home")
    assert run.call_count == 4
    environment = start.call_args.kwargs["env"]
    assert environment["KEIVOTOS_HOME"] == str(tmp_path / "isolated-home")
    assert "DANBOORU_API_KEY" not in environment


def test_smoke_terminates_server_after_success(tmp_path):
    from unittest.mock import MagicMock
    process = MagicMock()
    process.poll.return_value = None
    listener = MagicMock()
    listener.__enter__.return_value = listener
    listener.getsockname.return_value = ("127.0.0.1", 52300)
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.status = 200
    with patch.object(builder, "run"), patch.object(builder.socket, "socket", return_value=listener), patch.object(builder.subprocess, "Popen", return_value=process), patch.object(builder.urllib.request, "build_opener", return_value=opener):
        builder.smoke(tmp_path, tmp_path / "isolated-home")
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)


def test_windows_target_does_not_require_linux_build_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(builder.sys, "platform", "linux")
    monkeypatch.setattr(builder.platform, "machine", lambda: "x86_64")
    output = ROOT / "artifacts/test-dispatch-only"
    with patch.object(builder, "windows_tools", return_value=("wslpath", "powershell.exe")), patch.object(builder, "build_windows") as windows, patch.object(builder.shutil, "which", side_effect=AssertionError("Linux tools queried")), patch.object(Path, "mkdir"):
        assert builder.main(["--target", "windows", "--output-directory", str(output)]) == 0
    assert windows.call_args.args[1] == output


def test_windows_target_requires_interop_before_build(monkeypatch):
    monkeypatch.setattr(builder.sys, "platform", "linux")
    monkeypatch.setattr(builder.platform, "machine", lambda: "x86_64")
    with patch.object(builder, "windows_tools", side_effect=RuntimeError("Windows builds require WSL")), patch.object(builder, "copy_sources") as copy:
        with pytest.raises(SystemExit):
            builder.main(["--target", "both"])
    copy.assert_not_called()


def test_windows_bridge_uses_curated_copy_and_literal_arguments(tmp_path):
    import json
    with patch.object(builder.subprocess, "check_output", side_effect=lambda args, **kw: args[-1]), patch.object(builder, "run") as invoke:
        def inspect(*args, **kwargs):
            request = json.loads(Path(args[-1]).read_text())
            source = Path(request["source"])
            assert request["output"] == str(tmp_path / "output with spaces")
            assert not (source / ".venv").exists()
            assert (source / ".github/SECURITY.md").is_file()
            assert (source / "scripts/release/build_windows_from_wsl.ps1").is_file()
        invoke.side_effect = inspect
        builder.build_windows("1.2.3", tmp_path / "output with spaces", ("wslpath", "powershell.exe"))
    command = invoke.call_args.args
    assert "-File" in command
    assert "-Command" not in command
    assert "-RequestFile" in command
    assert not Path(command[-1]).exists()


def test_windows_bridge_propagates_failure_and_cleans_input(tmp_path):
    with patch.object(builder.subprocess, "check_output", side_effect=lambda args, **kw: args[-1]), patch.object(builder, "run", side_effect=subprocess.CalledProcessError(7, "powershell.exe")) as invoke:
        with pytest.raises(subprocess.CalledProcessError):
            builder.build_windows("1.2.3", tmp_path, ("wslpath", "powershell.exe"))
    assert not Path(invoke.call_args.args[-1]).exists()


@pytest.mark.parametrize("installed", [False, True])
def test_both_target_runs_linux_then_windows(tmp_path, monkeypatch, installed):
    # Exercise the complete dispatch with fake build outputs, never PyInstaller.
    import module_registry
    if not installed:
        monkeypatch.setattr(module_registry, '_DELIVERY_PROVIDERS', ())
    tool_builds = []
    monkeypatch.setattr(builder.sys, "platform", "linux")
    monkeypatch.setattr(builder.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/product.py").write_text('VERSION = "1.2.3"\n')
    sequence = []
    def copy_sources(root, destination):
        (destination / "frontend").mkdir()
        (destination / "docs/user").mkdir(parents=True)
        (destination / "packaging/linux").mkdir(parents=True)
        for name in ("README.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "SECURITY.md", "packaging/linux/FFMPEG_SOURCE.md"):
            (destination / name).touch()
    def run(*args, cwd, **kwargs):
        if "PyInstaller" in args:
            dist = Path(args[args.index("--distpath") + 1])
            dist.mkdir(exist_ok=True)
            if "--onefile" in args:
                tool_builds.append(args[args.index("--name") + 1])
                (dist / "gallery-dl").touch()
            else:
                (dist / "Keivotos").mkdir()
        elif "scripts/release/collect_licenses.py" in args:
            Path(args[2]).mkdir()
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.touch()
    monkeypatch.setattr(builder, "copy_sources", copy_sources)
    monkeypatch.setattr(builder, "run", run)
    monkeypatch.setattr(builder.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(builder, "windows_tools", lambda: ("wslpath", "powershell.exe"))
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *a, **k: str(ffmpeg))
    monkeypatch.setattr(builder.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="license", stderr=""))
    monkeypatch.setattr(builder, "smoke", lambda *a: sequence.append("linux"))
    monkeypatch.setattr(builder, "build_windows", lambda *a: sequence.append("windows"))
    assert builder.main(["--target", "both"]) == 0
    assert sequence == ["linux", "windows"]
    assert tool_builds == (["gallery-dl"] if installed else [])
    assert (tmp_path / "artifacts/Keivotos-V1.2.3-linux-x64.zip.sha256").is_file()
