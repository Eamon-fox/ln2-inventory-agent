# Repository Guidelines

## Project Structure & Module Organization

- `lib/`: Core library (config, validators, YAML I/O). All mutations enter via `lib/tool_api.py`.
- `app_gui/`: PySide6 desktop GUI. `app_gui/tool_bridge.py` adapts GUI actions to Tool API calls. i18n: `app_gui/i18n/translations/{en,zh-CN}.json`.
- `agent/`: ReAct agent runtime (DeepSeek client + tool runner) calling the same Tool API.
- `tests/`: `pytest` suite for lib/GUI/agent.
- `references/` and `demo/`: Sample config/data for local testing.
- `ln2_inventory.spec` and `installer/windows/`: Windows packaging (PyInstaller + Inno Setup).

## Build, Test, and Development Commands

```bash
# Conda environment setup
source /analysis4/software/miniconda3/etc/profile.d/conda.sh
conda activate /analysis4/fanym/conda/envs/bio-py

python -m pip install -r requirements.txt
pytest -q

# GUI (optional)
pip install PySide6
python app_gui/main.py

# AI Copilot (optional)
export DEEPSEEK_API_KEY=...
python app_gui/main.py
```

Config:
- `LN2_CONFIG_FILE=/path/to/config.json` overrides `yaml_path` and schema ranges (see `references/ln2_config.sample.json`).
- GUI settings live in `~/.ln2agent/config.yaml`.

## Coding Style & Naming Conventions

- Python 3.8+, 4-space indentation. Keep changes type-hint friendly.
- Data model: **tube-level**. One `inventory[]` record represents one physical tube; identical tubes are separate records with independent moves/consumption.
- GUI strings must use i18n keys; update both `en.json` and `zh-CN.json` together.

## Testing Guidelines

- Prefer temp directories; never mutate a real `ln2_inventory.yaml` in-place.
- For write operations, assert invariants + audit/backups (e.g., `ln2_inventory_audit.jsonl`, `ln2_inventory_backups/`).
- Naming: `tests/test_*.py`, `test_*` functions/methods.

## Commit & Pull Request Guidelines

- History often uses Conventional Commit prefixes like `feat:`, `fix:`, `refactor:`, `test:` (sometimes with scopes like `fix(i18n):`); keep subjects short and imperative.
- PRs should include: behavior change, repro steps, how you tested (`pytest -q`), and screenshots for GUI changes.
