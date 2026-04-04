# Spec 004 — CI Workflow

**Date**: 2026-04-04 | **Status**: Draft

## Context

The `full-spectrum-3mf` project has a comprehensive test suite — unit tests (7 files), integration tests (2 files), CLI acceptance tests, and slicer-based end-to-end tests — but no automated CI pipeline. Tests are only run locally, meaning regressions can be merged undetected. Adding a GitHub Actions workflow ensures every PR and push to `main` is validated automatically.

The slicer-based tests (`@pytest.mark.slicer`) require BambuStudio or OrcaSlicer to be installed. BambuStudio publishes Linux AppImage releases on GitHub that can be downloaded and run headlessly in CI, enabling full end-to-end validation without manual setup.

## Objective

Add a GitHub Actions CI workflow that runs all tests on every push/PR to `main`, including optional slicer-based E2E tests when BambuStudio can be provisioned.

## Scope

### In Scope

- GitHub Actions workflow file (`.github/workflows/ci.yml`)
- Python 3.12 matrix on Ubuntu
- Unit, integration, and CLI acceptance tests (always run)
- Slicer E2E tests via downloaded BambuStudio AppImage (best-effort)
- pytest-cov coverage reporting

### Out of Scope

- Multi-OS matrix (Windows, macOS) — deferred to future spec
- Multi-Python-version matrix beyond 3.12
- Publishing to PyPI
- Code coverage thresholds or badge integration
- Deployment workflows

## Requirements

### Functional

- **F1**: Workflow triggers on push to `main` and on pull requests targeting `main`.
- **F2**: Workflow installs Python 3.12 and project dependencies (including dev dependencies).
- **F3**: Workflow runs `pytest` for unit, integration, and CLI acceptance tests. These must always execute.
- **F4**: Workflow attempts to download the BambuStudio AppImage from the latest GitHub release and sets `BAMBUSTUDIO_BIN` so slicer tests can run.
- **F5**: If BambuStudio download or execution fails, the slicer tests auto-skip gracefully (existing `@pytest.mark.slicer` and fixture logic handles this).
- **F6**: Workflow reports test results and coverage summary.

### Non-Functional

- **NF1**: Total CI time should be under 5 minutes for the non-slicer tests.
- **NF2**: The slicer provisioning step should be best-effort — CI must not fail if BambuStudio cannot be downloaded.
- **NF3**: Workflow should use `pip install -e ".[dev]"` or equivalent to match local development setup.

## Design Constraints

- Python `>=3.12` is the only supported version (per `pyproject.toml`).
- Slicer tests use `BAMBUSTUDIO_BIN` environment variable for binary discovery (per Spec 003, decision D8).
- Slicer tests are marked with `@pytest.mark.slicer` and auto-skip when no binary is available.
- BambuStudio AppImage requires `fuse` or `--appimage-extract` to run on GitHub Actions runners (FUSE is not available in standard runners).

## Acceptance Criteria

- [ ] Pushing to `main` triggers the CI workflow
- [ ] Opening a PR against `main` triggers the CI workflow
- [ ] Unit, integration, and CLI acceptance tests run and pass
- [ ] Slicer tests either run (if BambuStudio is available) or skip gracefully
- [ ] Test failures cause the workflow to fail with clear output
- [ ] Coverage summary is visible in the workflow logs

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Runner OS | `ubuntu-latest` | Simplest to set up; BambuStudio publishes Linux AppImages |
| Python version | 3.12 only | Only supported version per pyproject.toml |
| BambuStudio provisioning | Download AppImage + `--appimage-extract` | GitHub Actions runners lack FUSE; extracting the AppImage is the standard workaround |
| Slicer step isolation | Same job, best-effort download | Keeps workflow simple; slicer fixture handles skip logic |
| Coverage tool | pytest-cov (already a dev dependency) | No new dependencies needed |

## Open Questions

- None — all critical questions resolved. The slicer auto-skip mechanism (Spec 003) handles the BambuStudio availability question gracefully.
