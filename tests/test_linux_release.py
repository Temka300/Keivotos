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
