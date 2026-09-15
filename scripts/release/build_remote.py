"""Request GitHub portable builds and download verified outputs on any host OS."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = "portable.yml"


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def gh_json(*args: str):
    return json.loads(command("gh", *args))


def find_run(repo: str, title: str, timeout: int = 180) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = gh_json("run", "list", "--repo", repo, "--workflow", WORKFLOW,
                       "--event", "workflow_dispatch", "--limit", "100",
                       "--json", "databaseId,displayTitle")
        for run in runs:
            if run["displayTitle"] == title:
                return int(run["databaseId"])
        time.sleep(5)
    raise RuntimeError(f"GitHub has not listed this request yet: {title}. Check Actions before retrying; the request may still run.")


def verify_artifact(directory: Path, commit: str, target: str) -> list[Path]:
    manifest = json.loads((directory / "build-manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("commit") != commit or manifest.get("target") != target:
        raise RuntimeError("Downloaded artifact does not match the requested commit/platform")
    version = manifest.get("version", "")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}[A-Za-z0-9._-]*", version):
        raise RuntimeError("Invalid version in artifact manifest")
    archive = directory / f"Keivotos-V{version}-{target}-x64.zip"
    checksum = directory / (archive.name + ".sha256")
    fields = checksum.read_text(encoding="utf-8-sig").strip().split(maxsplit=1)
    if len(fields) != 2 or fields[1] != archive.name or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        raise RuntimeError("Invalid archive checksum file")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != fields[0].lower():
        raise RuntimeError(f"Checksum mismatch: {archive.name}")
    return [archive, checksum]


def download(repo: str, run_id: int, commit: str, target: str, output: Path) -> Path:
    destination = output / f"github-{run_id}"
    if destination.exists():
        raise RuntimeError(f"Output already exists: {destination}")
    output.mkdir(parents=True, exist_ok=True)
    targets = ("linux", "windows") if target == "both" else (target,)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=output) as temporary:
        staging = Path(temporary)
        verified = staging / "verified"
        verified.mkdir()
        for platform in targets:
            directory = staging / platform
            subprocess.run(["gh", "run", "download", str(run_id), "--repo", repo,
                            "--name", f"keivotos-{platform}", "--dir", str(directory)], cwd=ROOT, check=True)
            for path in verify_artifact(directory, commit, platform):
                shutil.copy2(path, verified / path.name)
            shutil.copy2(directory / "build-manifest.json", verified / f"{platform}-manifest.json")
        # Only expose the final folder after all requested archives pass checks.
        verified.rename(destination)
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("both", "linux", "windows"), default="both")
    parser.add_argument("--run-id", type=int, help="Resume an existing run without starting another build")
    parser.add_argument("--output-directory", default="artifacts")
    args = parser.parse_args(argv)
    try:
        for tool in ("git", "gh"):
            if not shutil.which(tool):
                raise RuntimeError(f"Install {tool} first. GitHub CLI also needs gh auth login.")
        output = (ROOT / args.output_directory).resolve()
        if output == ROOT or not output.is_relative_to(ROOT):
            raise RuntimeError("Output directory must be inside the repository")
        repo_info = gh_json("repo", "view", "--json", "nameWithOwner,defaultBranchRef")
        repo = repo_info["nameWithOwner"]
        run_id = args.run_id
        if run_id is None:
            if command("git", "status", "--porcelain"):
                raise RuntimeError("Commit and push the changes you want built first; local changes cannot be included in a GitHub build.")
            commit = command("git", "rev-parse", "HEAD")
            remote = gh_json("api", f"repos/{repo}/commits/{commit}")
            if remote["sha"] != commit:
                raise RuntimeError("Push the selected commit before building")
            # The dispatch workflow must already be on the repository default branch.
            command("gh", "workflow", "view", WORKFLOW, "--repo", repo)
            request = uuid.uuid4().hex
            title = f"portable-{commit}-{args.target}-{request}"
            print(f"Requesting {args.target} for {commit}", flush=True)
            command("gh", "workflow", "run", WORKFLOW, "--repo", repo,
                    "--ref", repo_info["defaultBranchRef"]["name"],
                    "-f", f"commit={commit}", "-f", f"target={args.target}", "-f", f"request_id={request}")
            run_id = find_run(repo, title)
        run = gh_json("api", f"repos/{repo}/actions/runs/{run_id}")
        match = re.fullmatch(r"portable-([0-9a-f]{40})-(both|linux|windows)-.+", run["display_title"])
        if run["path"] != f".github/workflows/{WORKFLOW}" or not match:
            raise RuntimeError("Selected run is not a recognized portable build")
        commit, target = match.groups()
        print(f"Build: {run['html_url']}\nResume with --run-id {run_id}", flush=True)
        subprocess.run(["gh", "run", "watch", str(run_id), "--repo", repo, "--exit-status", "--interval", "10"], cwd=ROOT, check=True)
        destination = download(repo, run_id, commit, target, output)
        print(f"Verified artifacts: {destination}")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Build request failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped waiting. Any dispatched GitHub build continues; use --run-id to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
