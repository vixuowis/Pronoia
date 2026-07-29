from __future__ import annotations

import ast
import sys
import trace
import unittest
from pathlib import Path


def _docstring_ranges(tree: ast.AST) -> dict[tuple[int, int], None]:
    out: dict[tuple[int, int], None] = {}

    def add(node: ast.AST) -> None:
        if not hasattr(node, "body"):
            return
        body = getattr(node, "body", None)
        if not body or not isinstance(body, list):
            return
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
            val = first.value.value
            if isinstance(val, str):
                start = getattr(first, "lineno", None)
                end = getattr(first, "end_lineno", None) or start
                if start is not None:
                    out[(int(start), int(end or start))] = None

    add(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node)
    return out


def _statement_lines(path: Path) -> set[int]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    ds = _docstring_ranges(tree)

    def in_docstring(line: int) -> bool:
        for (s, e) in ds.keys():
            if s <= line <= e:
                return True
        return False

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.stmt, ast.ExceptHandler)):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None) or start
            if start is None:
                continue
            for ln in range(int(start), int(end or start) + 1):
                if not in_docstring(ln):
                    lines.add(ln)
    return lines


def _collect_target_files(app_dir: Path) -> list[Path]:
    files = []
    for p in app_dir.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        files.append(p)
    return sorted(files)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    app_dir = project_root / "backend" / "app"
    if not app_dir.exists():
        print(f"missing app dir: {app_dir}")
        return 2

    ignoredirs = []
    for prefix in {sys.prefix, sys.exec_prefix}:
        if prefix:
            ignoredirs.append(prefix)

    tracer = trace.Trace(count=True, trace=False, ignoredirs=ignoredirs)

    def run_suite() -> bool:
        loader = unittest.TestLoader()
        suite = loader.discover(str(project_root / "backend" / "tests"), pattern="test_*.py")
        runner = unittest.TextTestRunner(verbosity=1)
        res = runner.run(suite)
        return res.wasSuccessful()

    ok = tracer.runfunc(run_suite)
    results = tracer.results()
    counts = results.counts

    total_stmt = 0
    total_hit = 0
    per_file: list[tuple[str, int, int, float]] = []
    for f in _collect_target_files(app_dir):
        rel = str(f.relative_to(project_root))
        try:
            stmt_lines = _statement_lines(f)
        except Exception:
            continue
        hit = 0
        for ln in stmt_lines:
            if counts.get((str(f), ln), 0) > 0:
                hit += 1
        tot = len(stmt_lines)
        total_stmt += tot
        total_hit += hit
        pct = (hit / tot * 100.0) if tot else 100.0
        per_file.append((rel, hit, tot, pct))

    per_file.sort(key=lambda x: (x[3], x[2]), reverse=False)
    overall = (total_hit / total_stmt * 100.0) if total_stmt else 100.0

    print("STD-COVERAGE backend/app (statement-line approximation)")
    print(f"OVERALL {total_hit}/{total_stmt} = {overall:.2f}%")
    for rel, hit, tot, pct in per_file[:30]:
        print(f"{pct:6.2f}%  {hit:4d}/{tot:<4d}  {rel}")
    if len(per_file) > 30:
        print(f"... ({len(per_file) - 30} more files)")

    return 0 if ok and overall >= 0.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
