# Testing Standards

Standards for testing: what to test, how to write tests, and how the test
suite is organised.

## Type checking is a first-class gate

The language's type checker is configured (strict where the toolchain allows)
and runs in the test gate — errors fail the build, never suppressed.
A `# type: ignore` requires a comment explaining why, and a suppression is
itself a finding.

## Write the test before the code

Follow test-driven development: a failing test first, then the code that
makes it pass (`rule://test-first`). For LLM behaviour, write evals instead
(real AND fictional fixtures, running the production path exactly once).

## Test properties

- Tests mirror module paths.
- Deterministic: no wall-clock, network, or order dependence; seeded randoms.
- Assert behaviour, not implementation.
- Sort file listings before processing — `glob` order is filesystem-dependent.
- A test that cannot fail on a plausible bug is not a test (no tautological
  fixtures — validate real artifacts).

## Organisation

- **Unit tests:** one function/module in isolation, no API calls.
- **Integration tests:** full pipeline with fakes.
- **E2E tests:** real external APIs, one consolidated suite per API, skipped
  by default (`@pytest.mark.e2e`).
- Shared test infrastructure (fixtures, fakes) is extracted once, not
  copy-pasted per file.

## Mocking and dependency injection

Inject the dependency (service, output path, fake) — never
`monkeypatch`/`patch` global state. If something isn't reachable through DI,
refactor the code to accept a dependency. Fakes subclass the real protocol so
the type checker still holds at edit time.

Injection patterns, in order:
- **Parameter injection** for leaf-level dependencies (underscore-prefixed
  optional param falling back to the real implementation).
- **Services container** for deep call chains.
- **ContextVars** for request-scoped singletons.

Forbidden: `monkeypatch`/`unittest.mock.patch`, module-level mutable state,
lazy imports, and abstract base classes with a single concrete
implementation.

Pure functions need no mocking. Function-param injection is next. Containers
after that. Global patching is a last resort and a smell.
