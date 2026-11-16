# 本轮查漏与收录范围

日期：2026-11-16。首轮主要保存全局安装入口；本轮继续检查个人配置、主要项目入口、项目内技能和持久科研规则。

| 范围 | 当前收录 | 本轮发现与处理 |
| --- | --- | --- |
| 个人工作约定 | Codex 全局约定、home 约束、科研导航 | 已与源文件核对，未发现漂移 |
| 通用 skills | 59 项完整内容 | 原有 58 项一致；补入尚未全局安装的 `competition-optimize`，记录源提交 |
| 项目指南 | 11 个项目／独立 checkout，16 份文件 | 补入 Finance、demo-video 与 TheoremOS 各 checkout；按真实路径去除别名重复 |
| 项目专用 skills | 24 份、12 种完整内容 | 补入项目 `.claude/skills`、视频技能和 3 种 `theoremos-research` 变体，保留未提交修改 |
| 科研协议与决定 | 8 份文件 | 保存 TheoremOS 分支状态与决定原文，以及 Finance 旧协议和后续修订的关系 |
| Gemini / Antigravity | 2 份个人规则／agent 定义 | 保留客户端范围与机器路径，不当作 Codex 或 Gemini CLI 的通用默认 |
| Claude 插件 | 2 个插件的来源与版本；Cloudflare 14 个 skill 的完整快照 | Document 四项声明启用内容可由记录来源恢复；Cloudflare 本地修改未知，完整保留技能内容 |

对应入口：

- [个人与科研记忆](../memory/INDEX.md)
- [项目资料](../projects/README.md)
- [客户端资料](../clients/README.md)
- [通用 skill 来源](../sources/skill-imports.json)

本轮检查了 `/home/lzh` 顶层已识别项目、`/data/lzh/workspace/projects` 的主要项目入口，以及 Codex、共享 agents、Claude、Gemini 的相关配置与技能位置。未发现额外的个人 `CLAUDE.md`、`GEMINI.md`、Cursor 规则入口；现有源与快照的核对结果见来源清单。

项目指南、项目技能、科研记录和客户端资料分别登记在 `sources/project-guides.json`、`project-skills.json`、`research-records.json`、`client-assets.json`。`./zhizhou check` 会检查这些登记项是否缺失；它不会因原服务器路径在新机器不存在而拒绝使用已保存的内容。

采集时的 commit、branch、dirty 和内容摘要用于定位历史状态。不能只凭 commit 复现未提交的修改，因此保存的是采集到的完整内容。同名 skill 的分支变体保持各自项目身份。

当前恢复有几项范围限制：项目原文所引用的代码、数据和机器协议没有全部随知识库打包；实验目录中的静态 skill bundle 与原始运行轨迹没有提升为通用规则；上游依赖仍需按源项目恢复。新出现的项目和技能也需要继续登记，不能将本轮结果理解为穷尽本机所有 Markdown。

名称改为 **知舟（Zhizhou）**，取载着积累继续工作的含义。当前仓库、目录、主命令和新安装状态使用新名称；旧命令、环境变量和安装标记保留迁移兼容，历史来源不改写。
