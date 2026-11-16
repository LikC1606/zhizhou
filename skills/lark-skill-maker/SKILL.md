---
name: lark-skill-maker
version: 1.0.0
description: "创建 lark-cli 的自定义 Skill。当用户需要把飞书 API 操作封装成可复用的 Skill（包装原子 API 或编排多步流程）时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---

# Skill Maker

基于 lark-cli 创建新 Skill。Skill = 一份 `SKILL.md`，教 AI 用 CLI 命令完成任务。

## CLI 核心能力

```bash
lark-cli <service> <resource> <method>          # 已注册 API
lark-cli <service> +<verb>                      # Shortcut（高级封装）
lark-cli api <METHOD> <path> [--data/--params]  # 任意飞书 OpenAPI
lark-cli schema <service.resource.method>       # 查参数定义
```

优先级：Shortcut > 已注册 API > `api` 裸调。

## 调研 API

```bash
# 1. 查看已有的 API 资源和 Shortcut
lark-cli <service> --help

# 2. 查参数定义
lark-cli schema <service.resource.method>

# 3. 未注册的 API，用 api 直接调用
lark-cli api GET /open-apis/vc/v1/rooms --params '{"page_size":"50"}'
lark-cli api POST /open-apis/vc/v1/rooms/search --data '{"query":"5F"}'
```

如果以上命令无法覆盖需求（CLI 没有对应的已注册 API 或 Shortcut），使用 [lark-openapi-explorer](../lark-openapi-explorer/SKILL.md) 从飞书官方文档库逐层挖掘原生 OpenAPI 接口，获取完整的方法、路径、参数和权限信息，再通过 `lark-cli api` 裸调完成任务。

通过以上流程确定需要哪些 API、参数和 scope。

## SKILL.md 模板

文件放在 `skills/lark-<name>/SKILL.md`：

```markdown
---
name: lark-<name>
version: 1.0.0
description: "<功能描述>。当用户需要<触发场景>时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---


# <标题>

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)。

## 命令

\```bash
# 单步操作
lark-cli api POST /open-apis/xxx --data '{...}'

# 多步编排：说明步骤间数据传递
# Step 1: ...（记录返回的 xxx_id）
# Step 2: 使用 Step 1 的 xxx_id
\```

## 权限

| 操作 | 所需 scope |
|------|-----------|
| xxx | `scope:name` |
```

## 关键原则

- **description 决定触发** — 用简短描述说明具体领域、操作和必要的排除边界；不堆砌宽泛关键词或命令清单，不因任务沾边就触发。
- **按需加载** — 多工作流的根 SKILL.md 只保留路由、必要约束和完成条件；参数、示例及分支流程放到按场景链接的 references。已有明确上下文时不为重新走一遍流程而要求用户确认。
- **认证** — 说明所需 scope，登录用 `lark-cli auth login --domain <name>`
- **安全** — 普通写入从上下文核实目标与授权，明确时继续；高风险操作保留共享与领域的明确批准要求。需要批准时先完成已授权的准备工作并给出具体预览；等待时仅暂停依赖批准的步骤。
- **编排** — 说明数据传递、可并行步骤、完成条件和失败后的状态核验；结果不确定时先查询，避免重做成功步骤。回滚本身也须在授权范围内，不能默认删除用户数据。
