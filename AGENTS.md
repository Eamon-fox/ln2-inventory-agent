# Coding Agent 工作入口

本文件与 `CLAUDE.md` 同源。**权威版本见仓库根目录 `CLAUDE.md`**，请以其为准，本文件不再单独维护规则，以消除多套约束分叉。

## 给非 Claude agent 的最小引导

任何 coding agent 接手任务前，按顺序读取：

1. `CLAUDE.md`（权威工作入口：改动边界、模块归类、并行规则、禁止项、交付要求）
2. `docs/00-约束模型.md`
3. `docs/01-系统架构总览.md`
4. `docs/02-模块地图.md`
5. `docs/03-共享瓶颈点.md`

运行与测试相关：

- 环境、命令：`CLAUDE.md`
- 测试执行：`tests/RUNBOOK.md`、`tests/INDEX.md`

约束强度：只有机器可读契约块（docs 里的 `<!-- contract:* -->`）默认算硬约束；`docs/modules/*.md` 与 `docs/runbooks/*.md` 默认按软约束理解。
