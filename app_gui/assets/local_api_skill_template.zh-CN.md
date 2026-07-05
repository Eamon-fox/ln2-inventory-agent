---
name: snowfox-local-api
description: 发现、探测并使用 SnowFox 本地 Open API，用于只读库存查询、校验和 GUI handoff（含把写操作暂存进 GUI 等待人工确认）。API 从不直接写库存；所有写入都以暂存计划的形式交给人在 GUI 中执行。
---

# SnowFox 本地 Open API

当用户希望查询当前 SnowFox 会话、校验当前打开的数据集、让 GUI 先准备好上下文，或把增删改操作暂存进 GUI 等待人工确认时，使用这个 Skill。API 本身从不直接执行写操作。

## 核心流程

1. 先确认 SnowFox 桌面应用正在运行。
2. 如果未运行，优先尝试宿主环境已有的应用拉起机制。
3. 不要硬编码安装路径。如果当前环境没有可靠的拉起方式，就请用户手动打开 SnowFox。
4. 在做任何库存查询前，先探测本地 API。
5. 如果 API 不可达，明确提示用户打开 SnowFox 设置，检查是否启用了本地 Open API，以及端口是否与当前探测值一致。
6. API 可达后，先调用 `/api/v1/capabilities`，再假设字段名或返回 key。
7. 使用 `/api/v1/capabilities` 里的 `dataset_schema` 来了解当前 GUI 数据集的字段、别名、`display_key`、`color_key` 和 `box_layout`。
8. 在解析 `/api/v1/inventory/search` 或 `/api/v1/inventory/filter` 之前，先读取 `/api/v1/capabilities` 里的 `response_shapes`。
9. 调用 `/api/v1/session`，确认 GUI 当前打开的是哪个数据集。
10. 如果用户要操作另一个受管数据集，先调用 `/api/v1/datasets` 列出可选数据集，再调用 `/api/v1/session/switch-dataset` 切换当前会话。
11. 默认优先使用只读查询接口；只有当用户希望 GUI 被预填、聚焦或暂存计划时，才使用 GUI handoff 接口。
12. 把计划暂存理解为“放进 GUI 里等待人工确认”，不要把它当成已经执行的写操作。

## 连接检查清单

- 只探测回环地址：`http://127.0.0.1:<port>`
- API 只监听 SnowFox 所在主机的回环地址。如果你运行在另一台机器上（例如通过 SSH 管理宿主机），先建立 SSH 本地端口转发（`ssh -L 37666:127.0.0.1:37666 <host>`），或直接在宿主机上执行探测与请求命令；不要引导用户把端口绑定到非回环地址。
- 第一优先默认端口：`37666`
- 首次探测：`GET /api/v1/health`
- 能力探测：`GET /api/v1/capabilities`
- 会话确认：`GET /api/v1/session`
- 在假设字段名或返回 key 之前，先读取 `dataset_schema` 和 `response_shapes`。
- 如果应用有响应但 `dataset_exists` 为 `false`，要告诉用户当前 GUI 会话还没有打开有效数据集。

## API 说明

{{LOCAL_OPEN_API_ROUTE_REFERENCE}}

## 写入暂存（stage-plan）注意事项

- `POST /api/v1/gui/stage-plan` 是唯一的写入型 handoff：条目只进入 GUI 暂存区，仍需人工在 GUI 中确认执行。
- `mode` 默认 `merge`（合并进现有暂存）；`replace` 会先清空当前所有已暂存条目，包括其他来源暂存的。改错重发前先 `GET /api/v1/gui/stage-plan` 查看现状；需要整体清空时用 `POST /api/v1/gui/stage-plan/clear`，不要用 `replace` 顺带清空。
- 各 action 的 payload 形状不同：`edit` 把改动包在 `payload.fields` 里，`takeout`/`move` 用平铺键。以 `/api/v1/capabilities` 返回的 `stage_plan_schema` 为准。
- `edit` 的 `record_id` 必须指向当前数据集中真实存在的记录（预检会拦截）；`edit` 不需要提供 `box`/`position`，服务端会自动补默认值。
- POST body 含非 ASCII（如中文备注）时，必须以 UTF-8 字节发送。Windows PowerShell 5.1 传字符串 `-Body` 会按系统代码页重编码，中文会变成 `?`；先转字节再传：`-Body ([System.Text.Encoding]::UTF8.GetBytes($body))`。

最小示例（一个 edit 加一个 takeout）：

```json
{"items": [
  {"action": "edit", "record_id": 7,
   "payload": {"fields": {"note": "已复苏一管"}}},
  {"action": "takeout", "record_id": 7, "box": 1, "position": 5,
   "payload": {"date_str": "2026-02-10"}}
]}
```

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
  - 先 `GET /api/v1/gui/stage-plan` 查看已暂存条目，修正被拒条目后按 `merge` 重发；不要为了省事直接 `mode: replace`

## 不可违反的规则

- 不要把这个 API 描述成“直接写库存”。
- 不要假设 SnowFox 的安装路径。
- 不要绕过当前 GUI 会话边界。
- 不要把受管数据集切换描述成后台任意文件访问。
- 不要把计划暂存说成已经执行。
- 当 API 不可用时，要明确引导用户到 SnowFox 设置 -> 本地开放 API 检查开关。
