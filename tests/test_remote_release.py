"""Remote build orchestration; all GitHub responses and downloads are fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("remote_release", ROOT / "scripts/release/build_remote.py")
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)
SHA = "a" * 40


def artifact(directory, target="linux", commit=SHA):
    directory.mkdir(parents=True, exist_ok=True)
    name = f"Keivotos-V1.2.3-{target}-x64.zip"
    (directory / name).write_bytes(b"test artifact bytes")
    digest = hashlib.sha256(b"test artifact bytes").hexdigest()
    (directory / (name + ".sha256")).write_text(f"\ufeff{digest}  {name}\n", encoding="utf-8")
    (directory / "build-manifest.json").write_text(json.dumps(dict(commit=commit, target=target, version="1.2.3")))
    return directory / name


def test_checksums_and_provenance(tmp_path):
    archive = artifact(tmp_path)
    assert remote.verify_artifact(tmp_path, SHA, "linux")[0] == archive
    with pytest.raises(RuntimeError, match="requested commit/platform"):
        remote.verify_artifact(tmp_path, "b" * 40, "linux")
    archive.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        remote.verify_artifact(tmp_path, SHA, "linux")


def test_manifest_path_escape_rejected(tmp_path):
    artifact(tmp_path)
    (tmp_path / "build-manifest.json").write_text(json.dumps(dict(commit=SHA, target="linux", version="../../secret")))
    with pytest.raises(RuntimeError, match="Invalid version"):
        remote.verify_artifact(tmp_path, SHA, "linux")


def test_find_run_matches_request_not_latest():
    with patch.object(remote, "gh_json", return_value=[dict(databaseId=99, displayTitle="other"), dict(databaseId=12, displayTitle="mine")]):
        assert remote.find_run("owner/repo", "mine") == 12


def test_download_requires_both_valid_outputs(tmp_path):
    def download(args, **kwargs):
        target = args[args.index("--name") + 1].removeprefix("keivotos-")
        directory = Path(args[args.index("--dir") + 1])
        artifact(directory, target, SHA if target == "linux" else "b" * 40)
    with patch.object(remote.subprocess, "run", side_effect=download):
        with pytest.raises(RuntimeError):
            remote.download("owner/repo", 123, SHA, "both", tmp_path)
    assert not (tmp_path / "github-123").exists()
    assert not list(tmp_path.iterdir())


def test_download_success_and_no_overwrite(tmp_path):
    def download(args, **kwargs):
        target = args[args.index("--name") + 1].removeprefix("keivotos-")
        artifact(Path(args[args.index("--dir") + 1]), target)
    with patch.object(remote.subprocess, "run", side_effect=download):
        destination = remote.download("owner/repo", 123, SHA, "both", tmp_path)
        assert len(list(destination.glob("*.zip"))) == 2
        with pytest.raises(RuntimeError, match="already exists"):
            remote.download("owner/repo", 123, SHA, "both", tmp_path)


def test_dirty_tree_never_dispatches(monkeypatch, tmp_path):
    monkeypatch.setattr(remote, "ROOT", tmp_path)
    monkeypatch.setattr(remote.shutil, "which", lambda _: "tool")
    monkeypatch.setattr(remote, "gh_json", lambda *a: dict(nameWithOwner="owner/repo"))
    with patch.object(remote, "command", return_value=" M app.py") as command:
        assert remote.main([]) == 1
    assert command.call_args.args == ("git", "status", "--porcelain")


def test_resume_watches_existing_run_without_dispatch(monkeypatch, tmp_path):
    monkeypatch.setattr(remote, "ROOT", tmp_path)
    monkeypatch.setattr(remote.shutil, "which", lambda _: "tool")
    def response(*args):
        if args[0] == "repo":
            return dict(nameWithOwner="owner/repo")
        return dict(path=".github/workflows/portable.yml", display_title=f"portable-{SHA}-both-id", html_url="https://github.com/owner/repo/actions/runs/123")
    monkeypatch.setattr(remote, "gh_json", response)
    with patch.object(remote, "command", side_effect=AssertionError("dispatch attempted")), patch.object(remote.subprocess, "run") as watch, patch.object(remote, "download", return_value=tmp_path) as download:
        assert remote.main(["--run-id", "123"]) == 0
    assert "--exit-status" in watch.call_args.args[0]
    assert download.call_args.args[2:4] == (SHA, "both")


def test_failed_run_never_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(remote, "ROOT", tmp_path)
    monkeypatch.setattr(remote.shutil, "which", lambda _: "tool")
    monkeypatch.setattr(remote, "gh_json", lambda *a: dict(nameWithOwner="owner/repo") if a[0] == "repo" else dict(path=".github/workflows/portable.yml", display_title=f"portable-{SHA}-both-id", html_url="url"))
    with patch.object(remote.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gh")), patch.object(remote, "download") as download:
        assert remote.main(["--run-id", "123"]) == 1
    download.assert_not_called()


def test_new_dispatch_uses_exact_pushed_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(remote, "ROOT", tmp_path)
    monkeypatch.setattr(remote.shutil, "which", lambda _: "tool")
    def response(*args):
        if args[0] == "repo":
            return dict(nameWithOwner="owner/repo", defaultBranchRef=dict(name="main"))
        if "/commits/" in args[-1]:
            return dict(sha=SHA)
        return dict(path=".github/workflows/portable.yml", display_title=f"portable-{SHA}-both-unique", html_url="url")
    def command(*args):
        return SHA if args == ("git", "rev-parse", "HEAD") else ""
    monkeypatch.setattr(remote, "gh_json", response)
    with patch.object(remote, "command", side_effect=command) as calls, patch.object(remote, "find_run", return_value=123), patch.object(remote.subprocess, "run"), patch.object(remote, "download", return_value=tmp_path):
        assert remote.main([]) == 0
    dispatch = [c.args for c in calls.call_args_list if c.args[:3] == ("gh", "workflow", "run")][0]
    assert f"commit={SHA}" in dispatch
    assert "target=both" in dispatch
    assert dispatch[dispatch.index("--ref") + 1] == "main"


def test_workflow_is_manual_and_tests_both_native_platforms():
    import yaml
    workflow = yaml.load((ROOT / ".github/workflows/portable.yml").read_text(), Loader=yaml.BaseLoader)
    assert list(workflow["on"]) == ["workflow_dispatch"]
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["portable"]
    assert "ubuntu-22.04" in job["runs-on"] and "windows-2022" in job["runs-on"]
    steps = job["steps"]
    assert steps[0]["with"]["ref"] == "${{ inputs.commit }}"
    test = next(i for i, s in enumerate(steps) if s.get("name") == "Compile and test")
    uploads = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert test < uploads
    assert "python -m pytest" in steps[test]["run"]
