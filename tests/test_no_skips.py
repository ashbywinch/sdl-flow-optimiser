"""The testing standard's no-skip rule, machine-checked.

docs/testing-standards.md: a test that needs an external dependency fakes
it — never `@pytest.mark.skipif` on environment presence. A skipped test
rots silently and the coverage gate lies. This test scans the suite for
the forbidden patterns so a future agent can't reintroduce them.
"""

from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

FORBIDDEN = (
    "pytest.mark.skipif",
    "pytest.mark.skip(",
    "STORE_PRESENT",
    'reason="omp session store not available"',
)


def test_no_environment_skips_in_the_suite():
    offenders = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == "test_no_skips.py":
            continue  # this file documents the forbidden tokens
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(token in line for token in FORBIDDEN):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "tests must fake their dependencies, never skip on environment presence "
        f"(see docs/testing-standards.md):\n{chr(10).join(offenders)}"
    )
