# Contributing to Keivotos

Thanks for pitching in.

1. Read the relevant tests and the existing implementation before changing user-visible behavior.
2. Keep changes focused. Don't weaken the local-first and data-safety rules. User data is never deleted without showing scope.
3. Never commit personal media, databases, sidecars, credentials, or work files.
4. When a change crosses layers, update all of them: API types, helper scripts, migrations, tests, and the docs.
5. Before opening a PR, run the backend tests and the frontend check/build:

   ```powershell
   uv run python -m unittest discover -s tests -v
   cd frontend
   npm.cmd run check
   npm.cmd run build
   ```

Use the issue templates for reproducible bugs and concrete feature proposals. If you want to propose a whole new module (manga, music, etc.), start with a discussion that covers its storage model, external tools, and how it fits the shared Keivotos shell.

By contributing, you agree that your contribution is licensed under Apache-2.0.
