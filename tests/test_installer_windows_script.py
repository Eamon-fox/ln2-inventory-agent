import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER_SCRIPT = ROOT / "installer" / "windows" / "LN2InventoryAgent.iss"


def test_windows_installer_preserves_existing_config_yaml():
    text = INSTALLER_SCRIPT.read_text(encoding="utf-8", errors="replace")

    assert "if not FileExists(ConfigFile) then" in text

    guarded_write = re.search(
        r"if not FileExists\(ConfigFile\) then\s*begin(?P<body>.*?)end;",
        text,
        flags=re.DOTALL,
    )
    assert guarded_write is not None
    assert "StringList.SaveToFile(ConfigFile);" in guarded_write.group("body")
