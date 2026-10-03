"""Check prospective Git files against local secret values without printing them."""

from __future__ import annotations

import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).resolve().parent).decode().strip())


def main() -> int:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    secrets: dict[bytes, set[str]] = {}
    for env_file in [*ROOT.glob(".env*"), *ROOT.glob("*/.env*")]:
        if env_file.name == ".env.example" or not env_file.is_file():
            continue
        for key, value in dotenv_values(env_file).items():
            sensitive = any(
                word in key.upper()
                for word in ("TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "API_KEY")
            )
            sensitive |= bool(
                value and "://" in value and "@" in value.split("://", 1)[1].split("/", 1)[0]
            )
            if sensitive and value and len(value) >= 8:
                secrets.setdefault(value.encode(), set()).add(key)
    failures: list[tuple[str, str]] = []
    for name in sorted(set(names)):
        if not name:
            continue
        path = ROOT / name
        if path.name.startswith(".env") and path.name != ".env.example":
            failures.append((name, "populated environment file"))
            continue
        if path.is_symlink() or not path.is_file():
            failures.append((name, "unreviewed symlink or missing file"))
            continue
        content = path.read_bytes()
        for value, keys in secrets.items():
            if value in content:
                failures.append((name, "local secret key(s): " + ", ".join(sorted(keys))))
    for name, reason in failures:
        print(f"BLOCKED {name}: {reason}")
    if failures:
        return 1
    print(
        f"Secret check passed for {len(set(names)) - 1} prospective Git files; no secret values printed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
