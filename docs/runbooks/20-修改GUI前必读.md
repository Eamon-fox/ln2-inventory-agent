# 修改 GUI 前必读

适用模块：

- `gui_presentation`
- `gui_application`

当一个需求主要影响 Qt 界面、主窗口流程、面板协作、计划执行接线或 GUI 到核心层的桥接时，先读本文档。

本文属于软约束，描述默认执行路径。必要时可以偏离，但不得违反硬约束。

## 第一步：先判断属于哪类 GUI 改动

### 纯展示层改动

符合以下特征时，优先按 `gui_presentation` 处理：

- 改面板布局、控件结构、表格显示、对话框交互
- 改局部输入约束、局部文案、局部视觉反馈
- 不需要改 `app_gui/main.py`
- 不需要改 `app_gui/main_window_flows.py`
- 不需要改 `app_gui/tool_bridge.py`

### 应用层改动

符合以下特征时，优先按 `gui_application` 处理：

- 改跨面板协作
- 改数据集切换、计划执行、事件总线
- 改主窗口 wiring
- 改 GUI 到核心层的桥接语义

### 自动升级为跨模块

只要命中下面任一条件，别把它当纯 GUI 小改：

- 需要改 `app_gui/main.py`
- 需要改 `app_gui/main_window_flows.py`
- 需要改 `app_gui/tool_bridge.py`
- 需要改 `lib/tool_api.py`
- 需要改 `lib/tool_registry.py`
- 需要新增或修改稳定公共方法签名

## 开工顺序

1. 先读 `docs/02-模块地图.md`
2. 再读对应模块文档：
   - `docs/modules/10-界面展示层.md`
   - `docs/modules/11-界面应用层.md`
3. 判断是否触及共享瓶颈点：
   - `docs/03-共享瓶颈点.md`
4. 只在当前层级必须负责的地方改动
5. 最后才做主窗口接线、bridge 接线和 i18n 合并

## GUI 改动的默认拆分法

推荐顺序：

1. 先改局部 UI 组件
2. 再改应用层流程编排
3. 最后改主窗口装配和桥接
4. 最后合并文案与翻译

不要反过来先改主窗口，再让各个面板被动适配。

## 明确禁止

1. 不要在 `app_gui/ui/` 里直接实现库存写入规则。
2. 不要在 UI 层直接导入 `lib.tool_api_write*` 或 `lib.tool_api_write_validation`。
3. 不要跨面板调用另一个面板的私有方法或私有字段。
4. 不要让 `main.py` 继续承载更多业务判断。
5. 不要在 `tool_bridge.py` 堆积面板私有逻辑。

## 高冲突文件

以下文件默认不适合多人同时改：

- `app_gui/main.py`
- `app_gui/main_window_flows.py`
- `app_gui/tool_bridge.py`
- `app_gui/i18n/translations/en.json`
- `app_gui/i18n/translations/zh-CN.json`

如果必须并行：

1. 一个人负责共享入口改动
2. 其他人只改各自面板或应用层内部实现
3. 最后统一合并翻译与 wiring

## 最小测试集

### 纯展示层改动

- `pytest -q tests/integration/gui`

### 应用层改动

- `pytest -q tests/integration/gui tests/integration/plan`

### 命中共享瓶颈点

- `pytest -q tests/integration/gui tests/integration/plan tests/contract/test_architecture_dependencies.py`

## 完成标准

1. 模块归属清楚
2. 没有把业务规则上拉到 UI
3. 没有新增跨模块私有依赖
4. 如果改了稳定入口或主窗口 wiring，已同步更新文档
5. 中英文翻译保持同步
