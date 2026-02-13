# OpenCode UI 设计参考文档（补充版）

本文档基于进一步源码调研，整理 OpenCode 桌面版 AI 面板（Session Prompt Dock + Prompt Input）的设计细节，并结合 `ln2-inventory-agent` 现状给出可落地改造方案。

---

## 0. 调研范围

### 0.1 OpenCode 侧（重点文件）
- `packages/app/src/pages/session/session-prompt-dock.tsx`
- `packages/app/src/components/prompt-input.tsx`
- `packages/app/src/components/prompt-input/placeholder.ts`
- `packages/app/src/components/prompt-input/slash-popover.tsx`
- `packages/app/src/i18n/en.ts`
- `packages/ui/src/styles/theme.css`
- `packages/ui/src/styles/colors.css`
- `packages/ui/src/components/button.css`
- `packages/ui/src/components/icon-button.css`
- `packages/ui/src/components/select.css`
- `packages/ui/src/components/keybind.css`
- `packages/ui/src/components/tooltip.css`
- `packages/ui/src/components/session-turn.css`
- `packages/ui/src/components/font.tsx`

### 0.2 本项目侧（重点文件）
- `app_gui/ui/ai_panel.py`
- `app_gui/ui/theme.py`
- `app_gui/main.py`
- `app_gui/i18n/translations/en.json`
- `app_gui/i18n/translations/zh-CN.json`

---

## 1. OpenCode AI Panel 的关键实现细节

## 1.1 布局结构：输入区是“底部浮动 Dock”
- `session-prompt-dock.tsx` 使用底部绝对定位，输入区挂在消息流底部。
- 视觉上使用渐变背景：`bg-gradient-to-t from-background-stronger via-background-stronger to-transparent`。
- 交互上外层 `pointer-events-none`，内层 `pointer-events-auto`，避免覆盖消息滚动区域。
- 结果：输入区“轻浮在内容之上”，不是重边框面板。

## 1.2 输入容器：弱边框 + 背景分层 + 小尺寸控件
- `prompt-input.tsx` 的 form 主体使用：
  - `bg-surface-raised-stronger-non-alpha`
  - `shadow-xs-border`
  - `rounded-[14px]`
  - `overflow-clip`
- 核心不是“厚边框分区”，而是通过背景层次和轻阴影做边界。
- 底部操作条采用紧凑间距：`p-3`、`gap-1/2`，按键高度普遍 20-24px。

## 1.3 Placeholder 行为（重点）

### 1.3.1 文案来源
- `packages/app/src/i18n/en.ts` 定义了 `prompt.example.1` 到 `prompt.example.25`。
- `prompt.placeholder.normal` 文案模板：`Ask anything... "{{example}}"`。

### 1.3.2 何时显示
- `prompt-input.tsx` 通过 `<Show when={!prompt.dirty()}>` 覆盖一层 placeholder 文本。
- 一旦有输入（`prompt.dirty() == true`），placeholder 立即隐藏。

### 1.3.3 示例选择逻辑
- 初始化随机：`Math.floor(Math.random() * EXAMPLES.length)`。
- 新会话页面（无 `params.id`）会定时轮换（6.5s）；已进入会话时不轮换。

### 1.3.4 与补全无关
- placeholder 只是视觉提示文本，不参与补全，不接受 Tab 选中。

## 1.4 补全机制和 Placeholder 是两套系统
- `slash-popover.tsx` / `prompt-input.tsx` 中：
  - 输入 `@` 触发文件/agent 列表。
  - 输入 `/` 触发 slash command 列表。
- 列表可通过方向键 + Tab/Enter 选择。
- 这套机制由 popover 驱动，不依赖 placeholder。

## 1.5 快捷键信息的展示策略：默认隐藏、悬停显示
- OpenCode 使用 `TooltipKeybind` 包裹控件。
- 快捷键在 tooltip 中出现，不占据输入区常驻空间。
- `keybind.css` 的 keybind 视觉块也很紧凑：高度约 20px。

## 1.6 控件密度（可直接借鉴）
- `button.css`:
  - small: `height: 22px`
  - normal: `height: 24px`
  - large: `height: 32px`
- `icon-button.css`:
  - small: `20x20`
  - normal: `24x24`
  - large: `32px` 高
- 这套尺寸比常见桌面应用更紧凑，和“AI 聊天输入条”场景匹配。

## 1.7 色彩与字体系统
- `theme.css` / `colors.css` 使用大量 token（surface/text/icon/border/shadow）。
- 典型暗色变量：
  - `--background-base`
  - `--surface-raised-stronger-non-alpha`
  - `--border-weak-base`
  - `--shadow-xs-border`
- 字体：`font.tsx` 中主字体 Inter，代码字体 IBM Plex Mono（并支持多种 Nerd Font）。

---

## 2. ln2-inventory-agent 当前状态（结合点）

## 2.1 当前 UI 结构
- `main.py` 中 AI 面板作为 splitter 第三列：`self.ai_panel = AIPanel(...)`。
- `ai_panel.py` 里输入区和聊天区都用 `QGroupBox`：
  - `prompt_box = QGroupBox(tr("ai.prompt"))`
  - `chat_box = QGroupBox(tr("ai.aiChat"))`
- 输入框是 `QTextEdit`，placeholder 来自 `tr("ai.placeholder")`。

## 2.2 当前样式特征
- `theme.py` 的全局样式给 `QGroupBox` 和 `QTextEdit` 都加了边框：
  - `QGroupBox { border: 1px solid var(--border-weak); ... }`
  - `QLineEdit, ... , QTextEdit { border: 1px solid var(--border-weak); ... }`
- 这会让 AI 面板“框感”明显，和 OpenCode 的弱边界策略不一致。

## 2.3 文案现状
- `en.json` / `zh-CN.json` 的 `ai.placeholder` 当前包含快捷键说明：
  - `Enter to send, Shift+Enter for newline`（或中文等价）
- 这会让 placeholder 更像“说明书”，不是“启发式提示”。

## 2.4 已有优势（可保留）
- `ai_panel.py` 已有流式输出和 Thinking 折叠机制。
- 思考渲染频率（50ms）与 OpenCode 的“连续反馈”体验接近。
- 角色颜色映射也与 OpenCode 基本同风格。

---

## 3. 按你的偏好的融合策略（最终版）

你的明确偏好：
1. placeholder 不需要 Tab 补全。
2. 输入后自动消失即可。
3. 不要轮换；每次打开 GUI 随机一次。
4. 内容固定即可。

基于以上，建议如下：

## 3.1 Placeholder 策略
- 固定候选列表（可混合“操作提示”与“意图提示”，但都写死）。
- 每次打开窗口/切换到 AI 面板时随机选一条。
- 输入非空后由 `QTextEdit` 默认行为自动隐藏。
- 不做任何补全绑定，不接管 Tab。

## 3.2 文案策略
- 将 `ai.placeholder` 从“快捷键说明”改为“启发式示例”。
- 快捷键说明移出 placeholder（例如 tooltip、状态栏短提示、或不显示）。

## 3.3 视觉策略（减少框线）
- AI 面板优先去框：
  - prompt/chat 两个 `QGroupBox` 改无边框或弱边框。
  - 输入框边框改为默认透明，focus 才高亮（模拟 OpenCode 的弱焦点风格）。
- 统一紧凑尺寸：按钮高度尽量靠近 22-24px 区间。

## 3.4 快捷提示策略
- 删除常驻快捷提示文本（尤其是 placeholder 内快捷键串）。
- 如需保留，可改成 hover 才出现（Qt tooltip）。

---

## 4. 可落地实施点（本项目）

## 4.1 `app_gui/ui/ai_panel.py`
- 新增固定 placeholder 候选列表。
- 新增 `refresh_placeholder()`：随机一条并设置。
- 在 `setup_ui()` 结束后调用一次。
- 若后续有“切到 AI 面板”事件，可在该事件回调再调用一次。

示例伪代码：

```python
import random

PLACEHOLDER_EXAMPLES = [
    "Find K562-related records and summarize count",
    "List today's takeout/thaw events",
    "Recommend 2 consecutive empty slots",
    "Show all empty positions in box A1",
    "Add a new plasmid record",
    "Move tube from box A1:1 to B2:3",
]

def refresh_placeholder(self):
    if self.ai_prompt.toPlainText().strip():
        return
    self.ai_prompt.setPlaceholderText(random.choice(PLACEHOLDER_EXAMPLES))
```

## 4.2 `app_gui/i18n/translations/en.json` / `zh-CN.json`
- 改 `ai.placeholder` 为更简短、无快捷键版本。
- 可新增 `ai.placeholderExamples`（若后续要做多语言候选池）。

## 4.3 `app_gui/ui/theme.py`
- 给 AI 面板增加局部样式（通过 objectName 或属性选择器），避免影响其他面板。
- 目标是减少边框、提高层次感：
  - 容器弱边界
  - 输入框无常驻边框
  - focus 时轻描边

## 4.4 `app_gui/main.py`
- 可选：在 splitter 切换或窗口激活时触发 `ai_panel.refresh_placeholder()`。
- 如果不想增加事件复杂度，只在初始化调用一次也满足“每次打开随机一次”。

---

## 5. 建议实施顺序（低风险）

1. 先改 placeholder 逻辑和文案（最小改动，立刻见效）。
2. 再做 AI 面板局部样式去框（不改业务逻辑）。
3. 最后微调按钮/间距到紧凑规格（22-24px）。

---

## 6. 固定 placeholder 候选建议（可直接用）

### 6.1 操作提示类
- Find K562-related records and summarize count
- List today's takeout/thaw events
- Recommend 2 consecutive empty slots
- Show empty positions in box A1
- Move tube from box A1:1 to B2:3

### 6.2 意图提示类（固定文本，不做动态推断）
- Help me audit today's risky operations
- Check if any records have conflicting positions
- Summarize inventory distribution by box
- Find records that may need attention

---

## 7. 关键结论（针对本次讨论）

- OpenCode 的 placeholder 本质是“输入前启发文本”，不是补全系统。
- 对你当前需求，最合适方案是：
  - 固定候选池
  - 每次打开随机一条
  - 输入即消失
  - 不引入 Tab 补全
- 视觉上优先做“去框 + 紧凑 + 按需提示”，可以在不改业务逻辑的前提下显著提升接近度。

---

## 附录：源码路径索引

### OpenCode
- `packages/app/src/pages/session/session-prompt-dock.tsx`
- `packages/app/src/components/prompt-input.tsx`
- `packages/app/src/components/prompt-input/placeholder.ts`
- `packages/app/src/components/prompt-input/slash-popover.tsx`
- `packages/app/src/i18n/en.ts`
- `packages/ui/src/styles/theme.css`
- `packages/ui/src/styles/colors.css`
- `packages/ui/src/components/button.css`
- `packages/ui/src/components/icon-button.css`
- `packages/ui/src/components/select.css`
- `packages/ui/src/components/keybind.css`
- `packages/ui/src/components/tooltip.css`
- `packages/ui/src/components/session-turn.css`

### ln2-inventory-agent
- `app_gui/ui/ai_panel.py`
- `app_gui/ui/theme.py`
- `app_gui/main.py`
- `app_gui/i18n/translations/en.json`
- `app_gui/i18n/translations/zh-CN.json`
