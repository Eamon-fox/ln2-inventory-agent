---
name: snowfox-local-api
description: 发现、探测并使用 SnowFox 本地 Open API，用于只读库存查询、校验和 GUI handoff。适用于需要读取 SnowFox 当前会话或准备 GUI 上下文、但不进行直接写入的场景。
---

# SnowFox 本地 Open API

当用户希望查询当前 SnowFox 会话、校验当前打开的数据集，或只是让 GUI 先准备好上下文而不直接执行写操作时，使用这个 Skill。

## 核心流程

1. 先确认 SnowFox 桌面应用正在运行。
2. 如果未运行，优先尝试宿主环境已有的应用拉起机制。
3. 不要硬编码安装路径。如果当前环境没有可靠的拉起方式，就请用户手动打开 SnowFox。
4. 在做任何库存查询前，先探测本地 API。
5. 如果 API 不可达，明确提示用户打开 SnowFox 设置，检查是否启用了本地 Open API，以及端口是否与当前探测值一致。
6. API 可达后，先调用 `/api/v1/session`，确认 GUI 当前打开的是哪个数据集。
7. 如果用户要操作另一个受管数据集，先调用 `/api/v1/datasets` 列出可选数据集，再调用 `/api/v1/session/switch-dataset` 切换当前会话。
8. 默认优先使用只读查询接口；只有当用户希望 GUI 被预填、聚焦或暂存计划时，才使用 GUI handoff 接口。
9. 把计划暂存理解为“放进 GUI 里等待人工确认”，不要把它当成已经执行的写操作。

## 连接检查清单

- 只探测本机回环地址：`http://127.0.0.1:<port>`
- 第一优先默认端口：`37666`
- 首次探测：`GET /api/v1/health`
- 会话确认：`GET /api/v1/session`
- 如果应用有响应但 `dataset_exists` 为 `false`，要告诉用户当前 GUI 会话还没有打开有效数据集。

## API 说明

{{LOCAL_OPEN_API_ROUTE_REFERENCE}}

## 失败处理

- 连接被拒绝或超时：
  - SnowFox 可能未启动
  - 本地 Open API 可能未开启
  - 端口可能不是默认值
- `404 route_not_found`：
  - 当前 SnowFox 版本可能还没有开放该路由
- `404 dataset_not_found`：
  - 当前 SnowFox 数据根目录下不存在该受管数据集
- `400 invalid_request`：
  - 先修正参数，不要原样重试
- 校验失败：
  - 将 `report.errors` 和 `report.warnings` 清晰回传给用户
- `plan_stage_blocked` 或 `plan_action_not_allowed`：
  - 明确说明这是 GUI 暂存接口，不是直接执行接口

## 不可违反的规则

- 不要把这个 API 描述成“直接写库存”。
- 不要假设 SnowFox 的安装路径。
- 不要绕过当前 GUI 会话边界。
- 不要把受管数据集切换描述成后台任意文件访问。
- 不要把计划暂存说成已经执行。
- 当 API 不可用时，要明确引导用户到 SnowFox 设置 -> 本地开放 API 检查开关。
