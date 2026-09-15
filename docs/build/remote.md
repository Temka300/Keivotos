# Build both portable artifacts through GitHub

This is the cross-platform build path for developers on native Ubuntu, Windows,
or WSL. GitHub runs separate Ubuntu and Windows jobs; your computer downloads
the results. No WSL or Windows build tools are needed on Ubuntu.

## One-time setup

Commit and push `.github/workflows/portable.yml` and its supporting scripts to
the repository's default branch. GitHub Actions must be enabled. Install the
[GitHub CLI](https://cli.github.com/) locally and authenticate:

```text
gh auth login
```

You need permission to run workflows in that repository. GitHub-hosted build
usage is subject to your repository/account's Actions allowance. No release,
tag, commit, or push is performed by this helper.

## Build and download

Commit and push the code you want to build, then run from the repository root.
On Linux (Python 3.9 or newer):

```bash
python3 scripts/release/build_remote.py
```

On Windows:

```powershell
python scripts/release/build_remote.py
```

Both targets are the default. Use `--target linux` or `--target windows` to
request only one. The helper selects local HEAD, checks that GitHub can access
that exact commit, starts the workflow from the default branch, waits for its
specific request, and downloads ZIPs/checksums into `artifacts/github-<run-id>/`.
It verifies each platform's recorded commit and SHA-256 before exposing the
completed output folder. Existing output folders are never replaced.

The working tree must be clean: commit your intended changes first. Ignored
application data is not uploaded by this tool. GitHub builds only the selected
pushed commit. The helper neither pushes local changes nor includes them in a
remote build automatically.

Both jobs run Python compilation/tests, frontend checks/build, and the existing
native builders' executable/resource and isolated HTTP-startup checks. Linux
uses Ubuntu 22.04 x64; Windows uses Windows Server 2022 x64. These checks do not
establish compatibility with every desktop distribution or every interaction.

## Resume or inspect a failure

The helper prints the Actions URL and run ID. Closing the terminal stops local
waiting, not the remote job. Resume without starting another build:

```bash
python3 scripts/release/build_remote.py --run-id 123456789
```

Replace the example ID with yours. Resume uses the platforms/commit recorded
by that run, regardless of local uncommitted changes. A failed build stops the
helper before download; inspect the Actions logs. With two targets, the other
job can still finish and its artifact remains available on the Actions page.
Workflow artifacts are retained for 14 days, subject to repository policy.

You can also start **Portable builds** from GitHub's Actions page by supplying
a full pushed commit SHA and choosing the targets; leave request_id as manual.
Download the outputs there or resume that run with this helper. Publishing a
GitHub Release remains a separate user-controlled action.

The native [local builders](windows.md) remain available. This workflow must
be pushed and run on GitHub before its hosted execution can be considered
verified; local orchestration tests use simulated GitHub responses.
