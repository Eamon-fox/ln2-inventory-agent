# ln2-inventory

[English](README.md) | [简体中文](README.zh-CN.md)

> This project is first and foremost a **Claude Code agent skill** (see `SKILL.md`). It can also run as a standalone **desktop GUI** and **Python library**.

Liquid nitrogen (LN2) inventory manager for frozen tubes. Data lives in a single YAML file; all write operations go through validation, automatic backups, and an append-only JSONL audit log.

## Features

- Tube-level records (one `inventory[]` record == one physical tube)
- Add, query, search
- Takeout / thaw / discard / move (single and batch)
- Position conflicts + empty slot listing + occupancy stats
- Backup & rollback + audit log
- Unified Tool API shared by GUI and AI Copilot

## Running the App

```bash
python -m pip install -r requirements.txt
cp references/ln2_inventory.sample.yaml ln2_inventory.yaml

# GUI (optional)
pip install PySide6
python app_gui/main.py

# Tests
pytest -q
```

## Configuration

Runtime config is optional. By default the app reads `ln2_inventory.yaml` from the current working directory.

To customize paths or schema ranges:

```bash
export LN2_CONFIG_FILE=/path/to/my_config.json
```

See `references/ln2_config.sample.json` for available options (`yaml_path`, `schema.box_range`, `schema.position_range`, `safety.*`, ...).

## AI Copilot (DeepSeek)

```bash
export DEEPSEEK_API_KEY="<your-key>"
export DEEPSEEK_MODEL="deepseek-chat"   # optional
# Use the GUI "AI Copilot" tab to chat and stage write operations into the Plan queue.
pip install PySide6
python app_gui/main.py
```

## Packaging (Windows EXE)

```bash
pip install pyinstaller
pyinstaller ln2_inventory.spec
```

Inno Setup script: `installer/windows/LN2InventoryAgent.iss`

```bat
"C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" installer\\windows\\LN2InventoryAgent.iss
```

Optional helper: `installer/windows/build_installer.bat`

## Project Structure

```
lib/              # Shared library (Tool API, YAML ops, validation)
app_gui/          # Desktop GUI (PySide6)
agent/            # ReAct runtime + tool dispatcher
tests/            # Unit tests (pytest)
references/       # Sample files and documentation
demo/             # Demo dataset for packaged app
installer/        # Windows installer assets (Inno Setup)
SKILL.md          # Claude Code skill definition
```

## Requirements

- Python 3.8+
- PyYAML (`requirements.txt`)
- Optional: PySide6 (GUI)
- Optional: `DEEPSEEK_API_KEY` (real-model AI Copilot)

## License

MIT
