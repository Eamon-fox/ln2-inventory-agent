"""Agent runtime default constants.

These live in the agent layer so the runtime has no dependency on GUI config.
GUI re-exports them from ``app_gui.gui_config`` for backward compatibility.
"""

DEFAULT_MAX_STEPS = 120
# 0 disables fixed message-count compression; runtime checkpointing now controls
# long-context reduction based on model budget instead.
AGENT_HISTORY_MAX_TURNS = 0
