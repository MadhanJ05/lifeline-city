"""Design step 16 `privacy_guard`: scan files for unmasked phone numbers and street addresses.

Used two ways (Req 1.11, 1.12, 26.7, 31.4, 31.5):
  * by `pipeline.run` after `export`, over every file under `data/processed/` (including `llm_cache/`)
    and `api/`; any finding stops the run with a non-zero exit;
  * by the Privacy_Guard_Hook: `python -m pipeline.privacy_guard api data/processed`.

Output is `path:line: kind` only. The matched value is never printed. The lookbehind on `.` and `*`
keeps masked numbers (`+1 *** *** 1234`) and decimals out of the matches; short codes such as 2-1-1,
911 and 311 have too few digits to match. Binary files and `__pycache__/` are skipped; missing roots
are ignored.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

from pipeline.common import PROCESSED, ROOT, PipelineError

PHONE = r"(?<![\d.*])(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
ADDRESS = (r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|"
           r"Court|Ct|Boulevard|Blvd|Place|Pl|Terrace|Circle|Highway|Hwy)\b")
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("phone_number", re.compile(PHONE)),
    ("street_address", re.compile(ADDRESS)),
)

DEFAULT_ROOTS = (ROOT / "api", PROCESSED)
SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".hypothesis", "node_modules"})


class Finding(NamedTuple):
    path: Path
    line: int
    kind: str  # "phone_number" | "street_address"

    def __str__(self) -> str:
        return f"{_display(self.path)}:{self.line}: {self.kind}"


def _display(path: Path) -> str:
    """Path relative to the working directory (or the repo root) when possible."""
    p = Path(path).resolve()
    for base in (Path.cwd().resolve(), ROOT):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return str(p)


def _files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in map(Path, roots):
        if root.is_file():
            yield root
        elif root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts[:-1]):
                    yield p


def _text(path: Path) -> str | None:
    """File text, or None for binary (NUL byte or not UTF-8) and unreadable files."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_text(path: Path, text: str) -> list[Finding]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        out.extend(Finding(path, i, kind) for kind, rx in PATTERNS if rx.search(line))
    return out


def scan(roots: Iterable[Path]) -> list[Finding]:
    """Every finding in every text file under `roots`, in path then line order."""
    findings: list[Finding] = []
    for p in _files(roots):
        text = _text(p)
        if text is not None:
            findings.extend(scan_text(p, text))
    return findings


def report(findings: Iterable[Finding], stream=None) -> None:
    for f in findings:
        print(f, file=stream or sys.stdout)


def step(ctx) -> None:
    """Design step 16: scan data/processed/ (incl. llm_cache/) and api/ after export (Req 1.11, 1.12).
    Flagged files stay on disk until a clean run overwrites them."""
    roots = [PROCESSED, ROOT / "api"]
    findings = scan(roots)
    ctx["privacy_findings"] = findings
    if findings:
        report(findings)
        raise PipelineError(f"{len(findings)} finding(s) in {len({f.path for f in findings})} file(s); "
                            "see the path:line: kind lines above")
    n = sum(1 for _ in _files(roots))
    print(f"       privacy_guard: {n} files clean ({', '.join(_display(r) for r in roots)})")


def main(argv: list[str] | None = None) -> int:
    """`python -m pipeline.privacy_guard [root ...]`; defaults to api and data/processed. 1 on any finding."""
    args = sys.argv[1:] if argv is None else list(argv)
    findings = scan([Path(a) for a in args] if args else DEFAULT_ROOTS)
    report(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
