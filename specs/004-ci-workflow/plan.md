# Plan: CI Workflow

**Spec**: [specs/004-ci-workflow/spec.md](specs/004-ci-workflow/spec.md) | **Date**: 2026-04-04

## Summary

Add a single GitHub Actions workflow file that runs the full test suite on every push/PR to `main`. The workflow installs Python 3.12, project dependencies, optionally downloads BambuStudio AppImage for slicer E2E tests, then executes pytest with coverage reporting. BambuStudio provisioning is best-effort — slicer tests auto-skip if the binary is unavailable.

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Single workflow file | `.github/workflows/ci.yml` | Simple project; one workflow covers all test types |
| BambuStudio download | `gh release download` from `bambulab/BambuStudio` | Reliable; uses GitHub API via `gh` CLI (pre-installed on runners) |
| AppImage extraction | `--appimage-extract` | FUSE unavailable on GitHub Actions runners |
| Binary path | `squashfs-root/usr/bin/bambu-studio` | Standard AppImage extraction layout; lowercase binary name on Linux |
| `continue-on-error` | On BambuStudio download step only | Slicer download is best-effort; pytest fixture handles skip |

## Implementation Phases

### Phase 1: Create CI Workflow

1. [ ] Create `.github/workflows/ci.yml` with:
   - Trigger: `push` to `main`, `pull_request` targeting `main`
   - Runner: `ubuntu-latest`
   - Steps:
     1. `actions/checkout@v4`
     2. `actions/setup-python@v5` with Python 3.12
     3. `pip install -e ".[dev]"` to install project + dev deps
     4. Best-effort BambuStudio download:
        - Use `gh release download` to fetch the latest Linux AppImage from `bambulab/BambuStudio`
        - `chmod +x` and `--appimage-extract` to extract
        - Set `BAMBUSTUDIO_BIN` env var to extracted binary path
        - Mark step with `continue-on-error: true`
     5. Run `pytest --tb=short -v --cov=full_spectrum --cov-report=term-missing`
        - Set `BAMBUSTUDIO_BIN` as env var (if extraction succeeded)
2. [ ] Verification: Push to branch, open PR, confirm workflow triggers

### Phase 2: Validate & Iterate

1. [ ] Monitor CI run output
2. [ ] Fix any failures (dependency issues, path issues, permissions)
3. [ ] Confirm slicer tests either run or skip gracefully
4. [ ] Verification: Green CI on the PR

## File Changes

| File | Action | Purpose |
|------|--------|---------|
| `.github/workflows/ci.yml` | Create | CI workflow definition |

## Testing Strategy

- [ ] CI workflow itself is the test — validate it passes on the PR
- [ ] Confirm unit/integration/CLI acceptance tests run
- [ ] Confirm slicer tests either execute or skip with clear message

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| BambuStudio AppImage download URL changes | M | Use `gh release download` with pattern matching; `continue-on-error` ensures graceful fallback |
| BambuStudio binary requires display/GUI deps | M | AppImage bundles most deps; add `xvfb` if needed |
| AppImage extraction path differs from expected | L | Verify path with `find` command in CI; adjust `BAMBUSTUDIO_BIN` accordingly |
| BambuStudio release has no Linux AppImage | L | Slicer tests auto-skip; non-blocking |
