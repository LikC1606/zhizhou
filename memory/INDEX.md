# lzh 的记忆索引

此目录保存可跨服务器使用的工作经验。开始任务时先按范围选择材料，再读取相关 skill；无需把整个知识库塞进每次上下文。

| 内容 | 范围与来源 |
| --- | --- |
| [working-agreements.md](working-agreements.md) | 通用工作约定；首次来自 `~/.codex/AGENTS.md`，于 2026-11-16 收录 |
| [maintenance.md](maintenance.md) | 本知识库如何记录和使用经验；来源为用户在本项目对话中的确认 |
| [research.md](research.md) | 通用科研协作要求及相关 skills；由已存在的个人约定整理 |
| [projects/theorem-os.md](projects/theorem-os.md) | TheoremOS 系统维护与逐题干预边界；来源为用户 2026-11-15 的明确要求 |
| `notes/` | 后续记录；逐条保留 source、scope 和 confirmed/pending 状态 |
| [../projects/README.md](../projects/README.md) | 既有项目指南的历史快照及来源 |
| [../clients/README.md](../clients/README.md) | 客户端专用规则、agent 定义和插件恢复资料 |
| [../skills/](../skills/) | 可复用工作流程、脚本和资源 |

使用 `notes/` 时只把 `confirmed` 记录视为已确认经验，并检查其范围是否适用于当前任务。`global` 面向通用工作方式，`research` 面向科研工作，`project:<id>` 只适用于相应项目。`pending` 是待讨论建议。

本项目现名为知舟（Zhizhou）。历史记录中的 `project:lzh-memory` 与 `project:zhizhou` 指同一项目；`superseded` 表示已被后续记录替代，不再作为当前约定执行。历史原名和来源保留，不改写成当时已采用新名称。

记忆不改变宿主工具的系统规则，也不扩展用户给出的操作授权。遇到相互矛盾或时间顺序不清的记录，核对原始来源；不能靠 AI 猜测把建议升级成用户决定。

查找示例：

```bash
rg -n '评测|baseline|干预|确认' memory skills projects
```

修改核心规则和 skills 后，预览并重新安装以更新各工具副本。新增 note 会保存在本仓库，后续任务按入口指引读取；这不等于跨服务器自动同步。
