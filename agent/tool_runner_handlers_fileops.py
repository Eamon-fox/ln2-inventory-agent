"""File and shell dispatch handlers for AgentToolRunner."""

from .file_ops_client import run_file_tool


def _run_file_tool(self, tool_name, payload):
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _run_bash(self, payload, _trace_id=None):
    return _run_file_tool(self, "bash", payload)


def _run_powershell(self, payload, _trace_id=None):
    return _run_file_tool(self, "powershell", payload)


def _run_fs_list(self, payload, _trace_id=None):
    return _run_file_tool(self, "fs_list", payload)


def _run_fs_read(self, payload, _trace_id=None):
    return _run_file_tool(self, "fs_read", payload)


def _run_fs_write(self, payload, _trace_id=None):
    return _run_file_tool(self, "fs_write", payload)


def _run_fs_copy(self, payload, _trace_id=None):
    return _run_file_tool(self, "fs_copy", payload)


def _run_fs_edit(self, payload, _trace_id=None):
    return _run_file_tool(self, "fs_edit", payload)
