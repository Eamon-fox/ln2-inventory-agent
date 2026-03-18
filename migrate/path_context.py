from pathlib import Path


MIGRATE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = MIGRATE_ROOT.parent
INPUTS_DIR = MIGRATE_ROOT / "inputs"
NORMALIZED_DIR = MIGRATE_ROOT / "normalized"
NORMALIZED_SOURCE_DIR = NORMALIZED_DIR / "source"
OUTPUT_DIR = MIGRATE_ROOT / "output"
DEFAULT_SOURCE_SHEET = NORMALIZED_SOURCE_DIR / "sheets" / "01_Sheet1.csv"
OUTPUT_YAML = OUTPUT_DIR / "ln2_inventory.yaml"
SESSION_CHECKLIST = OUTPUT_DIR / "migration_checklist.md"
VALIDATION_REPORT = OUTPUT_DIR / "validation_report.json"


def repo_path(*parts):
    return REPO_ROOT.joinpath(*parts)


def migrate_path(*parts):
    return MIGRATE_ROOT.joinpath(*parts)


def inputs_path(*parts):
    return INPUTS_DIR.joinpath(*parts)


def normalized_path(*parts):
    return NORMALIZED_DIR.joinpath(*parts)


def output_path(*parts):
    return OUTPUT_DIR.joinpath(*parts)
