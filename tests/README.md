# Test Suite Guide

This repository currently keeps test files flat under tests/.
To keep navigation clear without changing discovery behavior, use this guide
with tests/INDEX.md and tests/RUNBOOK.md.

## What Is Covered

The suite covers these major areas:

- Agent runtime and tool execution
- GUI behavior and dialog flows
- Core library APIs and validation
- Plan and staging models and execution
- Import and migration behavior
- Contract and i18n hygiene checks

## Current Structure Policy

- Keep all executable test files named test_*.py.
- Keep files directly under tests/ for now (no path migration in this phase).
- Keep domain mapping up to date in tests/INDEX.md.

## Naming Guidelines

For new tests, prefer descriptive names:

- File: test_<domain>_<feature>.py
- Function: test_<scenario>_<expected_behavior>

Avoid vague suffixes such as _new, _missing, or 2 for new files.

## Maintenance Rules

When adding or changing tests:

1. Add the file to the proper domain section in tests/INDEX.md.
2. If run instructions change, update tests/RUNBOOK.md.
3. Keep setup helpers reusable; avoid copy-pasting large fixtures.

## Notes For Future Refactor

A later migration can move files into domain folders such as tests/agent/ and tests/gui/.
This phase intentionally does not move files, to avoid test discovery or import risk.
