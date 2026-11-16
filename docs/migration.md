# 新服务器迁移

迁移的前提是能够取回这个仓库。用户已授权保存到私有远程 [LikC1606/zhizhou](https://github.com/LikC1606/zhizhou)；新服务器使用有访问权限的 GitHub 账号。也可以通过迁移压缩包传输；仅在旧服务器保存一份不能解决旧服务器丢失的问题。

## 取回和预览

```bash
git clone https://github.com/LikC1606/zhizhou.git
cd zhizhou
./zhizhou check
./zhizhou install
```

若使用复制方式，保留完整仓库和可执行的 `zhizhou` 启动器。运行时只需要适用的 Python 3，启动器优先选择 `/usr/bin/python3`。可以设置 `ZHIZHOU_PYTHON` 指向自己的解释器。

默认安装到当前用户。用 `--home /path/to/home` 可以预览另一个 home，用 `--project /path/to/project` 可以预览指定项目；两者是不同目标，分别执行。`--tools` 可选择 `codex`、`claude`、`cursor`、`gemini`；通用 `agents` 适配用于项目。`all` 在用户范围选择四种工具，在项目范围选择全部五种适配。

确认预览符合目标后，使用同一组参数追加 `--apply`：

```bash
./zhizhou install --apply
```

规则入口会引用此仓库的记忆索引，保留仓库在本机的可访问路径。移动仓库后重新预览、安装；不能直接把旧服务器生成的文件当作新机器的最终配置。

项目已更名为知舟（Zhizhou），命令为 `./zhizhou`。旧 `./lzh-memory` 与 `LZH_MEMORY_PYTHON` 保留为兼容入口。重装时可以读取旧 `.lzh-memory` 状态，将管理区块更新为新名称；本机修改仍会触发冲突。已存在的旧 Cursor 项目规则文件会原位更新，避免两份 `alwaysApply` 规则同时加载。

## 存储路径

默认路径随目标 home 生成：

| 用途 | 默认值 |
| --- | --- |
| 新项目 | `~/workspace/projects` |
| 大体积输出 | `~/workspace/outputs` |
| 下载 | `~/Downloads` |
| 临时文件后备位置 | `~/.cache/zhizhou/tmp` |

临时文件优先使用环境中的 `TMPDIR`。已有项目遵守原有路径，不为统一目录重启正在运行的任务。

`machines/node01.json` 保存当前服务器的数据盘布局，只在指定 `--machine machines/node01.json` 时使用。其他机器可以提供同结构 JSON，键为 `projects`、`outputs`、`downloads`、`temporary`。项目不迁移磁盘、数据集或正在运行的实验。

## 已有配置与更新

安装采用文件复制，并记录自己安装的内容。已有规则正文会保留，安装器追加 `zhizhou` 管理区块；再次安装时，只更新未被本机改动的区块，保留区块外的文字。已有不同 skill、改动过的管理区块及不兼容的 Cursor 规则文件会产生冲突。先检查冲突和对应内容，再决定如何合并。

后续修改尽量回到此仓库。若 skill 已在工具目录里修改，可以用 `import-skills` 预览、导入；导入会保护此仓库里自上次导入后修改过的内容。

```bash
./zhizhou import-skills /path/to/skills
./zhizhou import-skills /path/to/skills --apply
./zhizhou check
git diff
./zhizhou install
./zhizhou install --apply
```

在其他服务器取回 Git 更新前，先检查并保存当地变化；干净工作区可运行 `git pull --ff-only`。项目不自动提交或推送 Git。

## 客户端核对

按 [工具适配](adapters.md) 核对所需路径和设置，必要时启动新会话。文件安装成功只证明生成和复制完成，不足以证明每个客户端已经读取。

内置 skills 由对应工具提供。Lark CLI、其他命令行依赖和各服务的登录授权需要重新配置；本仓库不打包登录态。`stop-that-shit` 的现有快照只有 skill 文本及 agent 描述，不包含 Guard 的可执行拦截实现。
