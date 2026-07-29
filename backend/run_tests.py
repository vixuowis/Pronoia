from __future__ import annotations

from pathlib import Path
import sys
import unittest


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    backend_root = Path(__file__).resolve().parent
    tests_dir = backend_root / "tests"
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(backend_root))

    try:
        import pytest  # type: ignore

        return int(pytest.main(["-q"]))
    except Exception:
        pass
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(tests_dir), pattern="test_*.py", top_level_dir=str(backend_root))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
