import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "app_gui" / "i18n" / "translations"


def _operations_for(locale_file: str):
    data = json.loads((I18N_DIR / locale_file).read_text(encoding="utf-8"))
    return data.get("operations", {})


def _agent_tool_runner_section(locale_file: str, section: str):
    data = json.loads((I18N_DIR / locale_file).read_text(encoding="utf-8"))
    return data.get("agentToolRunner", {}).get(section, {})


def test_removed_print_guide_keys_are_absent_in_en_and_zh():
    removed_keys = {"printGuide", "noPlanToPrint", "planEmptyPrintingLast", "guideOpened"}
    for locale in ("en.json", "zh-CN.json"):
        operations = _operations_for(locale)
        leftovers = sorted(key for key in removed_keys if key in operations)
        assert leftovers == [], f"{locale} still contains removed keys: {leftovers}"


def test_last_executed_print_opened_key_exists_in_en_and_zh():
    for locale in ("en.json", "zh-CN.json"):
        operations = _operations_for(locale)
        assert "lastExecutedPrintOpened" in operations, (
            f"{locale} missing operations.lastExecutedPrintOpened"
        )


def test_agent_tool_contracts_are_aligned_across_en_and_zh():
    en_contracts = _agent_tool_runner_section("en.json", "toolContracts")
    zh_contracts = _agent_tool_runner_section("zh-CN.json", "toolContracts")
    assert en_contracts == zh_contracts, "agentToolRunner.toolContracts should match across locales"


def test_agent_hints_are_aligned_across_en_and_zh():
    en_hints = _agent_tool_runner_section("en.json", "hint")
    zh_hints = _agent_tool_runner_section("zh-CN.json", "hint")
    assert en_hints == zh_hints, "agentToolRunner.hint should match across locales"


def test_takeout_query_tool_contract_supports_event_and_summary_modes():
    contracts = _agent_tool_runner_section("en.json", "toolContracts")
    events_desc = str((contracts.get("query_takeout_events") or {}).get("description") or "").lower()

    assert "summary" in events_desc, "query_takeout_events should mention summary capability"
    assert "range" in events_desc, "query_takeout_events should mention range selector for summary"
