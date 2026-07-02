# Test Runbook

This runbook documents common local test commands and troubleshooting steps.
测试分层与文件清单见 `tests/INDEX.md`：`unit/`（纯函数）、`integration/`（多模块协作）、`contract/`（一致性/卫生检查）。

## Prerequisites

1) Activate the repository-local virtual environment:

    source .venv/bin/activate

2) Install project + dev dependencies (both are version-locked):

    python -m pip install -r requirements.txt -r requirements-dev.txt

`requirements.txt` 覆盖运行依赖（PyYAML / mistune / PySide6 / openpyxl），
`requirements-dev.txt` 覆盖 pytest / ruff / pre-commit。两者分别与
`pyproject.toml` 的 `[project].dependencies` 与 `[project.optional-dependencies].dev` 同源。

## Headless GUI (offscreen)

- GUI tests require PySide6 and run headless via `QT_QPA_PLATFORM=offscreen`.
- `tests/conftest.py` 在导入期用 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`
  兜底该默认值（不会覆盖你显式设置的值），并提供 session 级 `qapp` fixture
  （复用 `QApplication.instance()` 单例，与各 GUI 测试自建 QApplication 兼容）。
- 若无 PySide6，`qapp` fixture 会自动 skip，非 GUI 测试仍可运行。
- 手动指定（一般无需）：

    QT_QPA_PLATFORM=offscreen python -m pytest -q tests/integration/gui

## Common Commands

Run all tests:

    python -m pytest -q

Run by layer:

    python -m pytest -q tests/unit
    python -m pytest -q tests/contract
    python -m pytest -q tests/integration

Run one file (注意实际路径在分层目录下):

    python -m pytest -q tests/integration/inventory/test_tool_api.py

Run focused subsets:

    python -m pytest -q tests/integration/agent/test_agent_tool_runner.py tests/integration/agent/test_react_agent.py
    python -m pytest -q tests/integration/plan/test_plan_model.py tests/integration/plan/test_plan_executor.py
    python -m pytest -q tests/integration/gui

Collect-only (discovery check):

    python -m pytest --collect-only -q

Stop on first failure:

    python -m pytest -q -x

## Lint (ruff)

配置在 `pyproject.toml` 的 `[tool.ruff]`（宽松起步：select E/F/W，存量违规规则暂列 ignore，
保证全绿；行宽兼容历史超长行不强制）。

    ruff check .

## Pre-commit

安装并全量自检：

    pre-commit install
    pre-commit run --all-files

说明：mutating 的基础 hooks（trailing-whitespace / end-of-file-fixer）仅作用于工程化
基建文件白名单，避免对既有历史源码产生大面积改动；check-yaml/check-json 只校验；
ruff 只检查不 `--fix`，与 CI 口径一致。

## CI

`.github/workflows/ci.yml`（ubuntu-latest + Python 3.11，push main / pull_request 触发）依次执行：
validate_version → ruff check → `pytest tests/unit tests/contract` → `pytest tests/integration`，
并预装 Qt 无头运行库（libegl1/libgl1/libxkbcommon0 等）。

## Troubleshooting

1) Import error for local modules:
   - Run from repository root.
   - Verify current interpreter points to `.venv/bin/python`.

2) pytest command not found:
   - Use `python -m pytest` instead of `pytest`.

3) Flaky local state:
   - Re-run a single failing test first.
   - Then run the smallest relevant file subset before full suite.

## Maintenance

If run commands or required dependencies change, update this file in the same PR.
