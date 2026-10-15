"""Prove voice can be removed without breaking the platform, in an isolated copy.

Requires uv/pnpm and a disposable migrated PostgreSQL database. Set DATABASE_URL,
DATABASE_SYSTEM_URL, DATABASE_AUTH_URL and corresponding TEST_* URLs first.
The source checkout and its lockfiles are never modified.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1]
    for key in (
        "DATABASE_URL",
        "DATABASE_SYSTEM_URL",
        "DATABASE_AUTH_URL",
        "TEST_DATABASE_URL",
        "TEST_AUTH_DATABASE_URL",
        "TEST_SYSTEM_DATABASE_URL",
    ):
        if not os.environ.get(key):
            raise SystemExit(f"Set {key} to a disposable migrated database before running")
    with tempfile.TemporaryDirectory(prefix="clinic-without-voice-") as temporary:
        root = Path(temporary) / "repo"
        shutil.copytree(
            source,
            root,
            ignore=shutil.ignore_patterns(
                ".git",
                ".env",
                ".env.*",
                "node_modules",
                ".venv",
                ".next",
                ".turbo",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                ".import_linter_cache",
                "test-results",
                "playwright-report",
                ".terraform",
                "*.tsbuildinfo",
            ),
        )
        shutil.rmtree(root / "packages/features/voice-receptionist")
        shutil.rmtree(root / "apps/web/app/(fullscreen)/voice-receptionist")
        manifest = root / "apps/web/package.json"
        data = json.loads(manifest.read_text())
        del data["dependencies"]["@clinic/feature-voice-receptionist"]
        manifest.write_text(json.dumps(data, indent=2) + "\n")
        project = root / "pyproject.toml"
        contents = project.read_text()
        contents = (
            "\n".join(line for line in contents.splitlines() if "clinic-feature-voice-receptionist" not in line) + "\n"
        )
        contents = contents.replace('"clinic_voice_receptionist", ', "")
        contents = contents.replace(" | clinic_voice_receptionist", "")
        project.write_text(contents)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("VIRTUAL_ENV", None)
        env["PATH"] = str(root / ".venv/bin") + os.pathsep + env["PATH"]
        # The test app uses a simulated identity provider, never real OAuth secrets.
        env.pop("GOOGLE_CLIENT_ID", None)
        env.pop("GOOGLE_CLIENT_SECRET", None)
        env["UV_PROJECT_ENVIRONMENT"] = str(root / ".venv")
        commands = [
            ["pnpm", "install", "--offline", "--no-frozen-lockfile"],
            ["uv", "sync", "--offline"],
            ["pnpm", "build"],
            ["pnpm", "test"],
            ["pnpm", "boundaries"],
            ["pnpm", "typecheck"],
            ["pnpm", "--filter", "@clinic/web", "test:e2e"],
        ]
        for command in commands:
            print("REMOVAL CHECK:", " ".join(command), flush=True)
            subprocess.run(command, cwd=root, env=env, check=True)
        print("PASS: platform builds, tests, authenticates and respects boundaries without voice.")


if __name__ == "__main__":
    main()
