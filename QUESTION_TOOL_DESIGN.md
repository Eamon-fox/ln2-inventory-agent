# Question Tool 设计方案

## 1. 概述

在 `ln2-inventory-agent` 中实现 `question` 工具，使 AI Agent 能在 ReAct 循环中暂停、向用户提问、获取回答后继续执行。

参考：[OpenCode question tool](https://github.com/anomalyco/opencode/blob/master/packages/opencode/src/tool/question.ts)

---

## 2. 现有架构约束

实现前必须理解的关键事实：

| 组件 | 现状 |
|------|------|
| `AgentRunWorker` | 继承 `QObject`（非 `QThread`），通过 `moveToThread()` 运行 |
| `AgentRunWorker.run()` | 同步阻塞调用 `bridge.run_agent_query()`，无暂停/恢复机制 |
| `ReactAgent.run()` | 同步阻塞，返回 `{"ok", "trace_id", "steps", "final", "conversation_history_used"}` |
| `ReactAgent._run_tool_call()` | 已存在，返回 `{"action", "action_input", "tool_call_id", "observation", "output_text"}` |
| 工具并行执行 | `ThreadPoolExecutor` 并行执行同一 step 的所有 tool calls |
| 事件处理 | Worker 通过 `progress` Signal 发送事件，GUI `on_progress()` 在主线程处理 |
| 停止机制 | `thread.terminate()` 强杀，无优雅停止 |
| `tool_specs()` | 返回 compact dict（`required`, `optional`, `aliases`, `params`, `notes`） |
| `tool_schemas()` | 从 `tool_specs()` 自动转换为 OpenAI function-calling 格式 |
| `_WRITE_TOOLS` | `{"add_entry", "record_thaw", "batch_thaw", "rollback"}`，会被 `plan_sink` 拦截 |

---

## 3. 核心设计：`threading.Event` 阻塞同步

原方案的根本问题：Worker 线程同步阻塞在 `agent.run()` 中，GUI 弹对话框不会暂停 worker。需要一个线程同步原语让 worker 主动等待。

### 3.1 整体流程

```
Worker Thread (blocking)                    Main Thread (GUI)
─────────────────────────                   ──────────────────
ReactAgent.run()
  └─ _run_tool_call("question", ...)
       └─ tool_runner.run("question", ...)
            └─ _run_question_tool()
                 ├─ emit "question" event ──────▶ on_progress()
                 │                                  └─ _show_question_dialog()
                 ├─ self._answer_event.wait() ◀──── user answers
                 │   (worker blocks here)            └─ worker._set_answer(answers)
                 │                                        └─ _answer_event.set()
                 └─ return answer as tool result
       └─ observation = {"ok": True, "answer": ...}
  └─ messages.append(tool_message)
  └─ continue ReAct loop (next LLM call)
```

关键点：question 工具的执行本身就是阻塞的——它在 worker 线程内等待用户回答，然后把答案作为普通 tool result 返回。ReAct 循环完全不需要修改暂停/恢复逻辑。

### 3.2 事件流

1. LLM 返回 `question` tool call
2. `_run_tool_call()` 调用 `tool_runner.run("question", ...)`
3. `_run_question_tool()` 通过 `progress` Signal 发送 `question` 事件
4. `_run_question_tool()` 调用 `self._answer_event.wait()` 阻塞 worker 线程
5. GUI 主线程 `on_progress()` 收到事件，弹出对话框
6. 用户回答后，GUI 调用 `worker._set_answer(answers)`，触发 `_answer_event.set()`
7. Worker 线程恢复，`_run_question_tool()` 返回包含答案的 tool result
8. ReAct 循环正常继续（答案作为 tool message 进入 messages）

---

## 4. 详细实现

### 4.1 Tool 注册 (tool_runner.py)

#### list_tools()

```python
def list_tools(self):
    return [
        # ... existing 13 tools ...
        "question",
    ]
```

#### tool_specs()

```python
"question": {
    "required": ["questions"],
    "optional": [],
    "description": "Ask the user clarifying questions before proceeding. "
                   "Use ONLY when you cannot infer the answer from inventory data. "
                   "Do NOT use for greetings or when the answer is obvious.",
    "params": {
        "questions": {
            "type": "array",
            "description": "List of question objects.",
            "items": {
                "type": "object",
                "properties": {
                    "header": {
                        "type": "string",
                        "description": "Short label (max 30 chars). E.g. 'Cell Line', 'Box Number'."
                    },
                    "question": {
                        "type": "string",
                        "description": "The question text."
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "If provided, user picks from these choices."
                    },
                    "multiple": {
                        "type": "boolean",
                        "description": "Allow multiple selections. Default false."
                    }
                },
                "required": ["header", "question"]
            }
        }
    },
    "notes": "question tool is NOT a write tool. It blocks the worker thread until user answers. "
             "Do not call question in parallel with other tools.",
},
```

`tool_schemas()` 无需修改——它从 `tool_specs()` 自动生成 OpenAI function schema。

#### question 不进入 plan_sink

`question` 不在 `_WRITE_TOOLS` 中，不会被 plan staging 拦截。无需额外处理。

### 4.2 Tool 执行逻辑 (tool_runner.py)

在 `AgentToolRunner` 上新增线程同步状态：

```python
import threading

class AgentToolRunner:
    def __init__(self, yaml_path, actor_id="react-agent", session_id=None, plan_sink=None):
        # ... existing init ...
        # Question tool synchronization
        self._answer_event = threading.Event()
        self._pending_answer = None   # set by GUI thread
        self._answer_cancelled = False

    def _set_answer(self, answers):
        """Called from GUI main thread to provide user answers."""
        self._pending_answer = answers
        self._answer_cancelled = False
        self._answer_event.set()

    def _cancel_answer(self):
        """Called from GUI main thread when user cancels."""
        self._pending_answer = None
        self._answer_cancelled = True
        self._answer_event.set()
```

在 `run()` 方法中添加 question 分支（在 `_WRITE_TOOLS` 检查之前）：

```python
def run(self, tool_name, tool_input, trace_id=None):
    if tool_name == "question":
        return self._run_question_tool(tool_input)

    if tool_name in _WRITE_TOOLS and self._plan_sink:
        return self._stage_to_plan(tool_name, tool_input, trace_id)
    # ... existing dispatch ...
```

question 工具的核心实现：

```python
def _run_question_tool(self, payload):
    """Execute question tool. Blocks worker thread until user answers."""
    questions = payload.get("questions", [])
    if not questions:
        return {
            "ok": False,
            "error_code": "no_questions",
            "message": "At least one question is required.",
        }

    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            return {
                "ok": False,
                "error_code": "invalid_question_format",
                "message": f"Question {i} must be a dict.",
            }
        if "header" not in q or "question" not in q:
            return {
                "ok": False,
                "error_code": "missing_required_field",
                "message": f"Question {i} missing 'header' or 'question'.",
            }

    question_id = str(uuid.uuid4())

    # Reset synchronization state
    self._answer_event.clear()
    self._pending_answer = None
    self._answer_cancelled = False

    # Emit question event via progress signal (plan_sink is repurposed here,
    # but see 4.3 for the actual mechanism via on_event callback)
    # The event emission happens in _run_tool_call level, not here.
    # This method just returns a special marker for _run_tool_call to handle.
    return {
        "ok": True,
        "waiting_for_user": True,
        "question_id": question_id,
        "questions": questions,
    }
```

但这里有个问题：`_run_question_tool` 在 `tool_runner.run()` 中执行，而事件发送在 `react_agent._run_tool_call()` 中。阻塞需要发生在事件发送之后。因此实际的阻塞逻辑放在 `_run_tool_call` 层级（见 4.3）。

### 4.3 ReAct Loop 修改 (react_agent.py)

只需修改 `_run_tool_call()` 方法。`run()` 方法的循环结构、返回值格式完全不变。

```python
def _run_tool_call(self, call, tool_names, trace_id):
    """Execute a single tool call and return the observation."""
    action = call["name"]
    action_input = call["arguments"]
    tool_call_id = call["id"]

    if action not in tool_names:
        observation = {
            "ok": False,
            "error_code": "unknown_tool",
            "message": f"Unknown tool: {action}",
            "_hint": "Choose action from available tools.",
        }
    else:
        observation = self._tools.run(action, action_input, trace_id=trace_id)

    # Handle question tool: emit event, block, collect answer
    if action == "question" and isinstance(observation, dict) and observation.get("waiting_for_user"):
        # Emit question event to GUI via on_event callback
        # on_event is not available here — need to pass it through.
        # See 4.3.1 for the threading approach.
        runner = self._tools  # AgentToolRunner instance

        # Block worker thread until GUI provides answer
        answered = runner._answer_event.wait(timeout=300)  # 5 min timeout

        if not answered:
            observation = {
                "ok": False,
                "error_code": "question_timeout",
                "message": "User did not answer within timeout.",
            }
        elif runner._answer_cancelled:
            observation = {
                "ok": False,
                "error_code": "question_cancelled",
                "message": "User cancelled the question.",
            }
        else:
            # Format answers as tool result for LLM
            answers = runner._pending_answer or []
            formatted = []
            for i, ans in enumerate(answers):
                q = observation["questions"][i] if i < len(observation.get("questions", [])) else {}
                header = q.get("header", f"Q{i+1}")
                if isinstance(ans, list):
                    formatted.append(f"{header}: {', '.join(ans)}")
                else:
                    formatted.append(f"{header}: {ans}")

            observation = {
                "ok": True,
                "result": {
                    "answers": formatted,
                    "raw_answers": answers,
                },
                "message": "User answered: " + "; ".join(formatted),
            }

    return {
        "action": action,
        "action_input": action_input,
        "tool_call_id": tool_call_id,
        "observation": observation,
        "output_text": self._serialize_tool_output(observation),
    }
```

#### 4.3.1 传递 on_event 到 _run_tool_call

当前 `_run_tool_call` 没有 `on_event` 参数。需要在 `run()` 方法中通过 `ThreadPoolExecutor` 调用时传入，或者将 `on_event` 存为实例属性。

推荐方案：在 `run()` 开始时存为实例属性。

```python
def run(self, user_query, conversation_history=None, on_event=None):
    self._on_event = on_event  # Store for _run_tool_call to use
    # ... rest unchanged ...
```

然后在 `_run_tool_call` 中发送 question 事件：

```python
# In _run_tool_call, before blocking:
if action == "question" and observation.get("waiting_for_user"):
    self._emit_event(
        self._on_event,
        {
            "event": "question",
            "type": "question",
            "trace_id": trace_id,
            "question_id": observation.get("question_id"),
            "questions": observation.get("questions"),
            "tool_call_id": tool_call_id,
        },
    )
    # Then block...
    runner._answer_event.wait(timeout=300)
```

#### 4.3.2 禁止 question 与其他工具并行

如果 LLM 在同一 step 同时调用 `question` 和其他工具（如 `query_inventory`），question 的阻塞会卡住 `ThreadPoolExecutor` 中的一个线程，其他工具正常完成，但 `results = [f.result() for f in futures]` 会等待所有 future 完成。这在功能上可行但语义上不合理。

在 `run()` 方法的工具调用处理中添加检查：

```python
# Before ThreadPoolExecutor dispatch
has_question = any(c["name"] == "question" for c in normalized_tool_calls)
if has_question and len(normalized_tool_calls) > 1:
    # Reject: question must be the only tool call
    for call in normalized_tool_calls:
        if call["name"] == "question":
            messages.append(self._tool_message(call["id"], {
                "ok": False,
                "error_code": "question_not_alone",
                "message": "question tool must be called alone, not with other tools.",
                "_hint": "Call question separately, then use other tools after getting the answer.",
            }))
        else:
            # Execute non-question tools normally
            result = self._run_tool_call(call, tool_names, trace_id)
            messages.append(self._tool_message(result["tool_call_id"], result["observation"]))
    continue
```

### 4.4 Worker 修改 (workers.py)

`AgentRunWorker` 需要暴露 `tool_runner` 引用，以便 GUI 调用 `_set_answer()` / `_cancel_answer()`。

```python
class AgentRunWorker(QObject):
    finished = Signal(dict)
    progress = Signal(dict)
    plan_staged = Signal(list)
    question_asked = Signal(dict)  # New: emitted when question event arrives

    def __init__(self, bridge, yaml_path, query, model, max_steps, history, thinking_enabled=True):
        super().__init__()
        # ... existing init ...
        self._tool_runner = None  # Set during run()

    def _emit_progress(self, event):
        if not isinstance(event, dict):
            return
        # Intercept question events for direct signal
        if event.get("type") == "question":
            self.question_asked.emit(event)
        else:
            self.progress.emit(event)

    def set_answer(self, answers):
        """Thread-safe: called from GUI main thread."""
        if self._tool_runner:
            self._tool_runner._set_answer(answers)

    def cancel_answer(self):
        """Thread-safe: called from GUI main thread."""
        if self._tool_runner:
            self._tool_runner._cancel_answer()

    def run(self):
        try:
            payload = self._bridge.run_agent_query(
                yaml_path=self._yaml_path,
                query=self._query,
                model=self._model,
                max_steps=self._max_steps,
                history=self._history,
                on_event=self._emit_progress,
                plan_sink=self._plan_sink,
                thinking_enabled=self._thinking_enabled,
                _expose_runner=self._receive_runner,  # New callback
            )
            # ... existing error handling ...
        except Exception as exc:
            # ... existing ...
        self.finished.emit(payload)

    def _receive_runner(self, runner):
        """Callback from bridge to capture tool_runner reference."""
        self._tool_runner = runner
```

#### 4.4.1 Bridge 修改 (tool_bridge.py)

`run_agent_query()` 需要传出 `tool_runner` 引用：

```python
def run_agent_query(self, ..., _expose_runner=None):
    # ... existing setup ...
    runner = AgentToolRunner(
        yaml_path=yaml_path,
        actor_id=f"{self._actor_id}-agent",
        session_id=self._session_id,
        plan_sink=plan_sink,
    )
    if callable(_expose_runner):
        _expose_runner(runner)
    # ... rest unchanged ...
```

### 4.5 GUI 事件处理 (ai_panel.py)

#### 4.5.1 Worker 连接

在 `start_worker()` 中添加 `question_asked` 信号连接：

```python
def start_worker(self, prompt):
    # ... existing worker setup ...
    self.ai_run_worker.question_asked.connect(
        self._handle_question_event,
        Qt.QueuedConnection,  # Ensure execution on main thread
    )
    # ... existing signal connections ...
```

#### 4.5.2 Question 事件处理

```python
def _handle_question_event(self, event_data):
    """Handle question event — runs on GUI main thread."""
    questions = event_data.get("questions", [])
    if not questions:
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
        return

    # Show in chat that agent is asking
    self._append_tool_message(tr("ai.question.asking"))

    answers = self._show_question_dialog(questions)

    if answers is not None:
        if self.ai_run_worker:
            self.ai_run_worker.set_answer(answers)
    else:
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
```

#### 4.5.3 Question 对话框

```python
def _show_question_dialog(self, questions):
    """Modal dialog for user to answer agent questions.

    Returns list of answers, or None if cancelled.
    """
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QLabel, QComboBox,
        QLineEdit, QCheckBox, QDialogButtonBox,
    )

    dialog = QDialog(self)
    dialog.setWindowTitle(tr("ai.question.title"))
    dialog.setMinimumWidth(400)
    layout = QVBoxLayout(dialog)

    answer_widgets = []

    for q in questions:
        header = q.get("header", "")
        question_text = q.get("question", "")
        options = q.get("options", [])
        multiple = q.get("multiple", False)

        label = QLabel(f"<b>{header}</b>: {question_text}")
        label.setWordWrap(True)
        layout.addWidget(label)

        if options and multiple:
            checkbox_group = []
            for opt in options:
                cb = QCheckBox(opt)
                layout.addWidget(cb)
                checkbox_group.append(cb)
            answer_widgets.append(("checkbox_group", checkbox_group))
        elif options:
            combo = QComboBox()
            combo.addItems(options)
            layout.addWidget(combo)
            answer_widgets.append(("combo", combo))
        else:
            edit = QLineEdit()
            layout.addWidget(edit)
            answer_widgets.append(("text", edit))

    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() == QDialog.Accepted:
        answers = []
        for widget_type, widget in answer_widgets:
            if widget_type == "checkbox_group":
                answers.append([cb.text() for cb in widget if cb.isChecked()])
            elif widget_type == "combo":
                answers.append(widget.currentText())
            else:
                answers.append(widget.text())
        return answers
    return None
```

### 4.6 System Prompt 补充 (react_agent.py)

在 `SYSTEM_PROMPT` 中添加 question 工具的使用约束：

```python
SYSTEM_PROMPT = """You are an LN2 inventory assistant.

Rules:
# ... existing rules 1-9 ...
10) You have a `question` tool to ask the user clarifying questions.
    Use it ONLY when you cannot determine the answer from inventory data.
    Always try query/search tools first before asking the user.
    Call `question` alone — never in parallel with other tools.
"""
```

---

## 5. 使用示例

### 5.1 Agent 调用 question

```json
{
    "name": "question",
    "arguments": {
        "questions": [
            {
                "header": "Cell Line",
                "question": "库存中有 K562、K562-dTAG、K562-RTCB 三种，你需要哪个？",
                "options": ["K562", "K562-dTAG", "K562-RTCB"]
            }
        ]
    }
}
```

### 5.2 Tool result（用户回答后）

```json
{
    "ok": true,
    "result": {
        "answers": ["Cell Line: K562-dTAG"],
        "raw_answers": ["K562-dTAG"]
    },
    "message": "User answered: Cell Line: K562-dTAG"
}
```

LLM 收到这个 tool result 后，继续调用 `query_inventory` 等工具完成任务。

### 5.3 用户取消

```json
{
    "ok": false,
    "error_code": "question_cancelled",
    "message": "User cancelled the question."
}
```

---

## 6. 边界情况

| 场景 | 处理方式 |
|------|----------|
| 用户取消对话框 | `cancel_answer()` → tool result `question_cancelled`，Agent 可直接回答或放弃 |
| 用户 5 分钟未回答 | `_answer_event.wait(timeout=300)` 超时 → `question_timeout` |
| question 与其他工具并行 | 拒绝 question，返回 `question_not_alone` 错误，正常执行其他工具 |
| 同一 run 多次提问 | 每次都走完整的 wait/answer 流程，`_answer_event` 每次 `clear()` 重置 |
| 用户回答为空字符串 | 正常返回空字符串作为答案，由 LLM 自行判断 |
| 用户点击"停止 Agent" | `thread.terminate()` 强杀 worker，`_answer_event` 随线程销毁 |
| 问题格式错误 | `_run_question_tool` 返回验证错误，不触发阻塞 |

---

## 7. 测试计划

### 7.1 单元测试 (tests/test_question_tool.py)

```python
import threading
from agent.tool_runner import AgentToolRunner

def test_question_no_questions():
    runner = AgentToolRunner(yaml_path="/tmp/test.yaml")
    result = runner.run("question", {"questions": []})
    assert result["ok"] is False
    assert result["error_code"] == "no_questions"

def test_question_missing_fields():
    runner = AgentToolRunner(yaml_path="/tmp/test.yaml")
    result = runner.run("question", {"questions": [{"header": "Test"}]})
    assert result["ok"] is False
    assert result["error_code"] == "missing_required_field"

def test_question_valid_returns_waiting():
    runner = AgentToolRunner(yaml_path="/tmp/test.yaml")
    result = runner.run("question", {
        "questions": [{"header": "Test", "question": "Hello?"}]
    })
    assert result["ok"] is True
    assert result["waiting_for_user"] is True
    assert "question_id" in result

def test_answer_event_synchronization():
    """Verify threading.Event blocks and resumes correctly."""
    runner = AgentToolRunner(yaml_path="/tmp/test.yaml")

    # Simulate GUI answering after a short delay
    def delayed_answer():
        import time
        time.sleep(0.1)
        runner._set_answer(["K562-dTAG"])

    threading.Thread(target=delayed_answer).start()

    # This would be called inside _run_tool_call in real code
    runner._answer_event.clear()
    answered = runner._answer_event.wait(timeout=5)
    assert answered is True
    assert runner._pending_answer == ["K562-dTAG"]

def test_cancel_answer():
    runner = AgentToolRunner(yaml_path="/tmp/test.yaml")

    def delayed_cancel():
        import time
        time.sleep(0.1)
        runner._cancel_answer()

    threading.Thread(target=delayed_cancel).start()

    runner._answer_event.clear()
    runner._answer_event.wait(timeout=5)
    assert runner._answer_cancelled is True
    assert runner._pending_answer is None
```

### 7.2 集成测试

```python
def test_react_question_flow(tmp_path):
    """Full ReAct loop with question tool — mock LLM returns question then final answer."""
    # Step 1: LLM calls question tool
    # Step 2: After answer injected, LLM calls query_inventory
    # Step 3: LLM returns final answer
    # Verify: run() returns normal {"ok": True, "final": "..."} — NOT a paused state
    pass
```

---

## 8. 国际化

在 `app_gui/i18n/translations/` 中添加：

```json
// zh-CN.json
{
    "ai.question.title": "Agent 提问",
    "ai.question.asking": "Agent 正在向您提问...",
    "ai.question.cancel": "取消",
    "ai.question.confirm": "确定",
    "ai.question.timeout": "提问超时，Agent 将继续执行"
}
```

```json
// en.json
{
    "ai.question.title": "Agent Question",
    "ai.question.asking": "Agent is asking you a question...",
    "ai.question.cancel": "Cancel",
    "ai.question.confirm": "OK",
    "ai.question.timeout": "Question timed out, agent will continue"
}
```

---

## 9. 文件修改清单

| 文件 | 修改类型 | 描述 |
|------|----------|------|
| `agent/tool_runner.py` | 修改 | 添加 `question` 到 `list_tools()` 和 `tool_specs()`；添加 `_run_question_tool()`、`_set_answer()`、`_cancel_answer()`；在 `run()` 中添加 question 分支 |
| `agent/react_agent.py` | 修改 | `_run_tool_call()` 添加 question 阻塞逻辑；`run()` 存储 `_on_event` 引用；工具并行检查拒绝 question 混合调用；`SYSTEM_PROMPT` 添加 rule 10 |
| `app_gui/ui/workers.py` | 修改 | 添加 `question_asked` Signal、`set_answer()`、`cancel_answer()`、`_receive_runner()`；`_emit_progress()` 拦截 question 事件 |
| `app_gui/tool_bridge.py` | 修改 | `run_agent_query()` 添加 `_expose_runner` 回调参数 |
| `app_gui/ui/ai_panel.py` | 修改 | 添加 `_handle_question_event()`、`_show_question_dialog()`；`start_worker()` 连接 `question_asked` 信号 |
| `app_gui/i18n/translations/zh-CN.json` | 修改 | 添加 `ai.question.*` 键 |
| `app_gui/i18n/translations/en.json` | 修改 | 添加 `ai.question.*` 键 |
| `tests/test_question_tool.py` | 新增 | 单元测试 + 线程同步测试 |

---

## 10. 依赖

- 无新增外部依赖
- `threading.Event`：Python 标准库
- PySide6 对话框组件：已有依赖
