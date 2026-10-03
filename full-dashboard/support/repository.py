from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath

import yaml

from support.config import ROOT
from support.models import Ticket
from support.privacy import Redactor

SOURCE_SUFFIXES = {".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".graphql", ".proto"}
EXCLUDED = {"node_modules", "vendor", "generated", "testdata", ".git", ".venv", "dist"}
SECRET_NAME = re.compile(r"secret|credential|password|token|private.?key|\.env", re.I)
STOP_WORDS = {
    "the",
    "this",
    "that",
    "with",
    "from",
    "have",
    "when",
    "please",
    "thanks",
    "report",
    "error",
    "crash",
    "bug",
    "matiks",
}


class RepositoryProvider:
    """Bounded, local reads only. No shell, hooks, patches, or repository writes."""

    def __init__(self, root: Path, ticket: Ticket, mapping: dict | None = None):
        self.root = root.expanduser().resolve(strict=True)
        if (
            not self.root.is_dir()
            or Path(self.git("rev-parse", "--show-toplevel").strip()).resolve() != self.root
        ):
            raise ValueError("REPO_PATH must be a Git repository root")
        self.ticket = ticket
        self.mapping = mapping or yaml.safe_load((ROOT / "repo_map.yaml").read_text())
        self.head = self.git("rev-parse", "HEAD").strip()
        paths = self.git("ls-files", "-z").split("\0")
        if len(paths) > 50000:
            raise ValueError("Repository inventory exceeds the bound")
        self.tracked = {p for p in paths if p}
        self.module, self.paths, self.terms = self.select()
        self._code = None

    def git(self, *args: str) -> str:
        env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
        result = subprocess.run(
            ["git", "--no-pager", "-c", "core.fsmonitor=false", "-C", str(self.root), *args],
            env=env,
            capture_output=True,
            timeout=10,
            check=True,
        )
        if len(result.stdout) > 2_000_000:
            raise ValueError("Repository output exceeds the bound")
        return result.stdout.decode("utf-8", errors="strict")

    def select(self):
        text = f"{self.ticket.subject} {self.ticket.body}".lower()
        modules = self.mapping["modules"]
        candidates = [
            (sum(term.lower() in text for term in cfg["terms"]), key, cfg)
            for key, cfg in modules.items()
        ]
        score, module, cfg = max(candidates, key=lambda c: c[0])
        if not score:
            module, cfg = "app", modules["app"]
        paths = []
        for path in cfg["paths"]:
            parsed = PurePosixPath(path)
            if (
                parsed.is_absolute()
                or ".." in parsed.parts
                or any(p in EXCLUDED for p in parsed.parts)
            ):
                raise ValueError("Unsafe repository mapping")
            paths.append(str(parsed).rstrip("/"))
        terms = list(
            dict.fromkeys(
                t.lower()
                for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,40}", text)
                if t.lower() not in STOP_WORDS
            )
        )[:12]
        return module, paths, terms

    def read(self, path: str, *, source: bool = True) -> str:
        parsed = PurePosixPath(path)
        if path not in self.tracked or parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("Only tracked relative files may be read")
        if SECRET_NAME.search(parsed.name) or any(p in EXCLUDED for p in parsed.parts):
            raise ValueError("Sensitive or excluded path")
        if source and (
            parsed.suffix not in SOURCE_SUFFIXES or path.endswith((".pb.go", "_generated.go"))
        ):
            raise ValueError("Unsupported source file")
        target = self.root.joinpath(*parsed.parts)
        current = self.root
        for part in parsed.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlinks are excluded")
        if (
            not target.resolve(strict=True).is_relative_to(self.root)
            or target.stat().st_size > 131072
        ):
            raise ValueError("Source outside repository or too large")
        return target.read_text(encoding="utf-8")

    def code(self) -> dict:
        if self._code is not None:
            return self._code
        candidates = [
            p
            for p in self.tracked
            if any(p.startswith(d + "/") for d in self.paths)
            and PurePosixPath(p).suffix in SOURCE_SUFFIXES
        ]
        candidates.sort(key=lambda p: (-sum(t in p.lower() for t in self.terms), p))
        matches = []
        for path in candidates[:128]:
            try:
                content = self.read(path)
            except (ValueError, OSError, UnicodeError):
                continue
            lines = content.splitlines()
            line_scores = [sum(term in line.lower() for term in self.terms) for line in lines]
            score = max(line_scores, default=0) + sum(t in path.lower() for t in self.terms)
            if not score:
                continue
            center = line_scores.index(max(line_scores)) if lines else 0
            start, end = max(0, center - 3), min(len(lines), center + 9)
            snippet = {
                "path": path,
                "start_line": start + 1,
                "end_line": end,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "text": Redactor().text("\n".join(lines[start:end]))[:1600],
            }
            matches.append((score, snippet))
        matches.sort(key=lambda m: (-m[0], m[1]["path"]))
        snippets = [m[1] for m in matches[:5]]
        commits = []
        if snippets:
            raw = self.git(
                "log", "-8", "--format=%H%x1f%cI%x1f%s", "--", *[s["path"] for s in snippets]
            )
            for row in raw.splitlines():
                parts = row.split("\x1f", 2)
                if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{40,64}", parts[0]):
                    commits.append(
                        {
                            "hash": parts[0],
                            "committed_at": parts[1],
                            "subject": Redactor().text(parts[2])[:160],
                            "causation_verified": False,
                        }
                    )
        dirty = bool(self.git("status", "--porcelain", "--untracked-files=no", "--", *self.paths))
        self._code = {
            "module": self.module,
            "files": [s["path"] for s in snippets],
            "snippets": snippets,
            "commits": commits,
            "repo_head": self.head,
            "working_tree_dirty": dirty,
            "search_terms": self.terms,
            "hypothesis": None,
            "confidence": 0,
            "coverage": f"Bounded lexical search: inspected at most 128 of {len(candidates)} candidate files; at most 5 excerpts. Working-tree source is not deployed/runtime evidence.",
        }
        return self._code

    def owners(self) -> dict:
        code = self.code()
        owners, sources, role, confidence = [], [], "unknown", 0
        for file in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            if file not in self.tracked:
                continue
            try:
                content = self.read(file, source=False)
                rules = []
                for number, line in enumerate(content.splitlines(), 1):
                    parts = line.split("#", 1)[0].split()
                    if not parts:
                        continue
                    pattern, identities = parts[0], parts[1:]
                    # A deliberately narrow subset: global, literal root file, root directory.
                    # Any unsupported syntax means no inferred ownership from this file.
                    if pattern != "*" and (
                        not pattern.startswith("/") or re.search(r"[?*\[\]!\\]", pattern)
                    ):
                        raise ValueError("Unsupported CODEOWNERS pattern")
                    if any(
                        not re.fullmatch(r"@[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?", o)
                        for o in identities
                    ):
                        raise ValueError("Unsupported owner identifier")
                    rules.append((pattern, identities, number))
                chosen = []
                for path in code["files"]:
                    matching = [
                        (p, ids, n)
                        for p, ids, n in rules
                        if p == "*"
                        or (p.endswith("/") and path.startswith(p.lstrip("/")))
                        or path == p.lstrip("/")
                    ]
                    if not matching or not matching[-1][1]:
                        chosen = []
                        break
                    chosen.append(matching[-1])
                if chosen:
                    owners = sorted({owner for _, ids, _ in chosen for owner in ids})
                    role = (
                        "global_code_reviewer"
                        if all(p == "*" for p, _, _ in chosen)
                        else "path_code_reviewer"
                    )
                    confidence = 0.6 if role == "global_code_reviewer" else 0.9
                    sources = [
                        {
                            "path": file,
                            "line": n,
                            "pattern": p,
                            "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        }
                        for p, _, n in dict.fromkeys((p, tuple(ids), n) for p, ids, n in chosen)
                    ]
            except (ValueError, OSError, UnicodeError):
                sources = [
                    {
                        "path": file,
                        "ownership_unavailable": True,
                        "reason": "Unsupported or unsafe CODEOWNERS content",
                    }
                ]
            break
        # Author identities never leave the provider. Pseudonymous activity is not ownership.
        contributors = []
        if code["files"]:
            identities = self.git("log", "-30", "--format=%aE", "--", *code["files"]).splitlines()
            counts = Counter(
                hashlib.sha256(i.lower().encode()).hexdigest()[:12] for i in identities if i
            )
            contributors = [
                {
                    "contributor_ref": f"contributor:{i}",
                    "recent_commits": count,
                    "ownership_verified": False,
                }
                for i, count in counts.most_common(10)
            ]
        return {
            "module": self.module,
            "owners": owners,
            "confidence": confidence,
            "role": role,
            "sources": sources,
            "contributors": contributors,
        }

    def fetch(self, topic: str, user_id: str | None) -> tuple[dict, str]:
        if topic == "code_search":
            return self.code(), f"repo:{self.head}:working-tree"
        if topic == "get_module_owner":
            return self.owners(), f"repo:{self.head}:ownership"
        raise LookupError("Repository provider cannot read this topic")

    def close(self):
        pass


class CompositeProvider:
    def __init__(self, data=None, repository=None):
        self.data, self.repository = data, repository

    def fetch(self, topic: str, user_id: str | None):
        provider = self.repository if topic in {"code_search", "get_module_owner"} else self.data
        if provider is None:
            raise LookupError("Read-only source unavailable")
        return provider.fetch(topic, user_id)

    def close(self):
        for provider in (self.data, self.repository):
            if provider is not None:
                provider.close()
