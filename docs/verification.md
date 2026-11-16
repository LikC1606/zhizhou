# 首次迁移验证

日期：2026-11-16。以下结果来自本地实际执行，覆盖文件迁移与安装行为。

- 58 个 skill、2,397 个文件、约 42.1 MiB；逐个计算完整内容摘要，与原安装目录一致。
- 绝对软链来源已展开为真实目录；仓库内的 skill 快照没有软链，保留相对资源、执行权限和本地修改。
- 13 项隔离测试通过，覆盖预览零写入、已有规则保留、迁移后路径更新、重复安装、冲突整计划拒绝、管理区块与 skill 的本地修改保护、完整导入、缺失入口检测和 pending 记录。
- 完整仓库复制到另一路径后，分别安装到临时用户 home 和临时项目。每种范围都恢复了共享 skills 与 Claude skills 两套目录，各 58 项，全部与源内容摘要一致。
- Codex、Claude、Gemini 指令和 Cursor 导出／项目规则均生成在隔离目标；指令引用移动后的仓库路径。

日常验证命令：

```bash
./lzh-memory check
python3 -m unittest discover -s tests -v
```

在 node01，默认 `python3` 是进入另一文件视图的 shim，因此本次测试使用：

```bash
TMPDIR=/data/lzh/default-storage/tmp /usr/bin/python3 -m unittest discover -s tests -v
```

本次没有修改真实客户端配置、调用模型或运行外部 skill 服务。四个客户端实际加载和未来任务是否遵守约定，需要客户端运行证据；文件验证不能代替这些结果。
