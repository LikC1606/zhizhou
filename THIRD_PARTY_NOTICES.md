# 第三方来源与版权说明

核对日期：2026-11-16。以下记录依据仓库现有许可、组件元数据、素材 credits 和可核实的上游文本。根目录 MIT 许可的适用范围见 [NOTICE.md](NOTICE.md)。

## 已保留的许可与署名

| 内容 | 版权或来源 | 许可与依据 |
| --- | --- | --- |
| [Humanizer](skills/humanizer/) | Copyright (c) 2025 Siqi Chen；插件指向 [blader/humanizer](https://github.com/blader/humanizer) | 完整 [MIT License](skills/humanizer/LICENSE)；本地修改保留在快照中 |
| [taste-skill](skills/taste-skill/) 的代码和文档 | Copyright (c) 2026 Leonxlnx | 完整 [MIT License](skills/taste-skill/LICENSE)；素材另见下节 |
| [Cloudflare 技能快照](clients/claude/plugins/cloudflare/) | Cloudflare；元数据指向 [cloudflare/skills](https://github.com/cloudflare/skills) | [plugin.json](clients/claude/plugins/cloudflare/plugin.json) 声明 Apache-2.0；另存完整 [Apache-2.0 文本](LICENSES/Apache-2.0.txt) |

Cloudflare 的许可文本取自上游 [LICENSE](https://github.com/cloudflare/skills/blob/main/LICENSE)，SHA256 为 `58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd`。核对时上游 `main/NOTICE` 返回 404，未取得独立 NOTICE 文件。许可文本对应读取时的上游 main，不证明本地技能快照与某个上游提交完全一致；本地修改状态仍为 unknown，详见 [插件来源记录](sources/client-plugins.json)。

## 素材的独立许可

`taste-skill` 中的照片、图标和示例素材有独立署名与许可，不能仅凭目录中的 MIT 文件推定全部素材采用 MIT。现有 credits 涉及 Unsplash、CC0、CC BY 2.0/4.0、CC BY-SA 3.0/4.0、MIT 和 ISC，具体作者、源地址及条款保存在：

- [场景素材 credits](skills/taste-skill/assets/scenes/_demo/credits.json)
- [布局图片 credits](skills/taste-skill/assets/layout/img/credits.json)
- [UI 图标 credits](skills/taste-skill/assets/ui/icons/icons-credits.json)
- [交互示例图片 credits](skills/taste-skill/assets/moments/_demo/credits.json)
- [示例图标 credits](skills/taste-skill/assets/icons/demo/icons-credits.json)

部分品牌图标还带有商标标记。复制或发布素材时，应保留相应 credits，并按该项素材的许可处理署名、修改与再分发。

视频项目 `media-use` 快照含 19 个音效文件，其 [原始 CREDITS.md](projects/theorem-os-demo-video/skills/media-use/audio/assets/sfx/CREDITS.md) 声明采用 [Pixabay Content License](https://pixabay.com/service/license-summary/)。该声明介绍了在视频等衍生作品中的使用；本次未独立核实这些文件作为独立素材包的再分发权，官方条款页面读取返回 403。原 credits 保持原样，根目录 MIT 不为这些音频另行授予许可。

## 只有许可声明或来源记录的内容

| 内容 | 已核实的信息 | 当前边界 |
| --- | --- | --- |
| 8 项 GSAP skills：`core`、`frameworks`、`performance`、`plugins`、`react`、`scrolltrigger`、`timeline`、`utils` | 各 `skills/gsap-*/SKILL.md` 的 frontmatter 声明 MIT | 本地快照未附完整许可文本或已核实版权主体；不补猜作者 |
| [stop-that-shit](skills/stop-that-shit/SKILL.md) | frontmatter 声明 MIT | 本地快照未附完整许可文本或已核实版权主体 |
| 28 项 Lark skills | [来源锁](sources/lark-skills.lock.json) 指向飞书官方分发，记录上游摘要和本地修改 | 未在快照中确认具体许可，不默认纳入根目录 MIT |
| 其他通用 skills | [导入记录](sources/skill-imports.json) 保留安装来源与内容摘要，部分来源仍标为 unknown | 不能仅凭名称认定为原创或推定许可 |
| 项目技能、项目指南和科研快照 | [项目来源](sources/project-guides.json)、[技能来源](sources/project-skills.json)、[科研来源](sources/research-records.json) 保留所属项目及采集身份 | 未声明许可的快照保持原权利状态，不自动获得根目录 MIT 授权 |

`document-skills` 仅保存 [上游来源和版本信息](sources/client-plugins.json)，没有将其完整插件缓存再收录到本仓库。技能文本的许可也不替代其依赖软件、服务或素材自身的条款。

## 补充与纠正

如果你是相关内容的作者，发现署名、来源或许可记录不完整，可以通过 [GitHub Issues](https://github.com/LikC1606/zhizhou/issues) 提供对应文件及可核实的上游依据。补充记录时保留原作者、适用范围和修改历史。
