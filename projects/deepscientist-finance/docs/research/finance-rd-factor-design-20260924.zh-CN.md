# Finance：按 R&D-Factor 设计进行方法比较

2026-09-24。用户已确认“因子实验设计，保留各方法比较”。本设计替代后续 Protocol B 的实验安排，历史协议和结果保持原样。**设计已登记，固定控制实验已启动，搜索执行器迁移尚未完成。**

执行更新：用户随后授权“开始实验”。固定控制评价器已接入，Alpha20/Alpha158 的 10 次训练及回测已进入执行；四个搜索组仍待执行器迁移，尚未开始 6 小时计时。运行状态以 `output/strategy_discovery/finance-rd-factor-20260924-v1/controls-status.json` 为准。数据价格截断至 2020-07-31；Qlib 所需的 2020-08-03/04 仅为日历元数据，不包含未来价格。运行环境采用现有项目的 Qlib threading 后端及显式启用的 MLflow 文件记录后端。

机器协议：[protocol.json](../../experiments/strategy_discovery/rd_factor_design/protocol.json)。当前设计指向：[active_finance_design.json](../../experiments/strategy_discovery/active_finance_design.json)。该指向是设计元数据，旧执行器不会自动采用它。

## 1. 依据及范围

依据本地 [R&D-Agent-Quant 论文](../../finance_paper/2505.15155_RD-Agent-Quant.pdf)，arXiv:2505.15155v2，§3、附录 C.1/C.4、表 5；以及 RD-Agent 提交 `32b3d395e73d9db5eee3fe9063d69aec0fdc83bd`。来源文件哈希列在机器协议中。

采用 R&D-Factor：固定 LightGBM，研发因子集合。不开展 R&D-Model 或因子／模型联合搜索。比较四个搜索组：DeepScientist full-feedback、DeepScientist no-feedback、AlphaAgent-adapted、RD-Agent-factor；固定 Alpha20 和 Alpha158 为控制组。各组使用种子 0–4。共 20 次完整搜索和 10 次固定控制评价。

所有搜索从同一 Alpha20 重新开始。保留各方法的生成、记忆和选择机制，统一数据、标签、LightGBM、账户及指标。因此结论针对共同评价环境中的完整搜索系统。DeepScientist 的 DSL 表达限制、AlphaAgent 的适配均须披露。

## 2. 主要变更

| 项目         | 原 Protocol B                        | 新 R&D-Factor 设计                                                    |
| ------------ | ------------------------------------ | --------------------------------------------------------------------- |
| 初始因子     | Alpha158                             | 论文表 5 的 Alpha20                                                   |
| 搜索预算     | 5 轮，每轮 5 个候选                  | 每个种子 6 小时，轮数和候选数由原生流程产生                           |
| 数据分段     | Development D1/D2                    | CSI300：训练 2008–2014，验证 2015–2016，回测 2017-01-01 至 2020-08-01 |
| 因子评价     | 单候选增量、D1/D2 同时为正等准入规则 | Alpha20 + 已接受因子 + 本轮因子批次，共同训练与回测                   |
| 因子选择     | 共同池准入                           | 各方法原生选择；RD-Agent 保留原生反馈与 SOTA 决策                     |
| 主要汇总     | D1/D2 年化净超额的均值比较           | 五次完整搜索终点净组合 ARR 的中位数                                   |
| 模型请求上限 | 内部 15 次；旧外部单轮 40 次         | 各组均无客户端调用次数和 token 上限                                   |

6 小时包括模型等待、生成、调试、训练、评价、反馈和运行内缓存开销。公共数据准备与固定基准评价在计时前完成；这是一项明确的本地实施约定。原设计为串行搜索，共计 120 小时搜索预算；用户随后选择保留每次 6 小时、优化并行和缓存，执行规则现由下述修订覆盖。

执行修订见 [parallel_execution.json](../../experiments/strategy_discovery/rd_factor_design/parallel_execution.json)：五路独立运行，每路固定 20 个不重叠 CPU 核，模型请求共用原有的两路并发限制。队列等待不计入单次搜索时钟，获分配槽位后的模型等待计入；所有方法同规则。原生 Docker 执行器须显式传入对应 `--cpuset-cpus`，不能只给宿主启动命令设置 affinity。理想搜索排程为四波、约 24 小时，实际另计准备和收尾，未声称已测得搜索加速倍数。

Alpha20/Alpha158 的确定性 DatasetH 在计时前预热。缓存身份包含数据快照清单、分段、特征与标签配置、软件版本、缓存实现哈希；写入加锁、原子发布并核验内容哈希。生成因子数据留在各运行私有缓存；模型、提案、反馈及研究历史不跨运行共享。缓存损坏时停止检查，不静默使用。两个 Alpha20 工程验证任务实测由串行约 111 秒变为并行约 57 秒，预测、标签、每日 IC 完全一致，账户差异仅为浮点舍入；该验证不增加正式种子数。搜索执行器仍在迁移，这一实测仅证明并行评价和数据缓存可用。

到期后不启动新阶段或请求，主终点使用截止前最后一个完整提交的已选择因子集合。在途任务的迟到输出单独保存，不进入主终点。不因收益或完成轮数延长时间。Co-STEER 每任务最多 10 次内部演化；实现单元 600 秒、验证单元 3600 秒，采用论文 C.1 设置。这些工作流约束与 token 费用限制不同。

## 3. 数据、训练和交易

[base_factors.json](../../experiments/strategy_discovery/rd_factor_design/base_factors.json) 从固定版本源码的 `ALPHA20` 直接提取，含 20 个公式。已生成三份可解析的 Qlib 配置：[Alpha20 基准](../../experiments/strategy_discovery/rd_factor_design/evaluator-baseline.yaml)、[组合因子](../../experiments/strategy_discovery/rd_factor_design/evaluator-combined.yaml)、[Alpha158 控制](../../experiments/strategy_discovery/rd_factor_design/evaluator-alpha158.yaml)。它们是评价规格，尚未构成完整实验启动器。

标签采用源码的 `Ref($close, -2)/Ref($close, -1) - 1`。固定原生 LightGBM 超参数，显式写入 Qlib 默认的 1000 棵最大迭代、50 轮早停和示例种子 0；生成每个正式运行配置时替换对应种子，绑定相同数据快照。验证区间仅用于模型早停。特征必须因果构造，边界处缺失标签不得填造。

基准模板使用 RobustZScoreNorm、Fillna；组合模板不含这两个 infer processors。两者均使用 DropnaLabel 和标签 CSZScoreNorm。这是原生模板的实际差异，保留并披露，不冒称完全相同的预处理。

交易采用原生 Qlib `TopkDropoutStrategy(topk=50, n_drop=5)`：多头策略，初始资金 1 亿元，基准 SH000300，收盘价成交，涨跌停阈值 0.095，买入费率 0.0005、卖出费率 0.0015、最低费用 5 元。信号错位、持仓保留和费用计算须在执行迁移时验证。论文文字同时存在多空、开盘与收盘成交的不同描述，本设计按固定源码落实，不自行拼接。

## 4. 反馈、选择与测试含义

RD-Agent 原生 runner 每轮评价整个因子组合。它对新增因子与历史生成因子按日计算截面 Pearson 相关再取时间均值，保留最大有符号相关小于 0.99 的新因子；这里不是绝对相关阈值，也不是旧的 D1/D2 准入。

原生反馈使用 IC、含成本年化超额收益和回撤，LLM 输出 `Replace Best Result` 决策；原生历史提示还包含部分不含成本指标。保留原始请求、决策、因子集合与真实 trace。其他方法保留自己的选择机制，不能伪装成原生 RD-Agent。

**论文命名的 test 区间在原生代码中参与多轮反馈，因此这里明确称为自适应回测区间。** 不将其声称为未见测试或独立泛化证据。若以后另做仅验证集反馈、封存测试的实验，必须另立协议，不能悄悄替换本设计。C 阶段仍因没有合格未暴露数据而未执行。

无反馈组的评价控制器可以选择集合，但研究生成器不能看到收益、准入标记、已选择集合身份或性能诊断；只保留自身未打分提案与编码错误。否则选中因子的身份本身就会泄露反馈。

## 5. 指标及失败处理

主要结果为各注册种子终点组合的净 ARR，再取五个种子的中位数。净 ARR 按论文公式计算：`prod(1 + return - cost) ** (252/N) - 1`。另报 IC、ICIR、RankIC、RankICIR、IR、MDD、Calmar，以及 Qlib 原生含成本年化超额指标。

论文的组合复合 ARR 与 Qlib 原生算术年化超额收益分开命名。IR 同时报组合净收益相对零无风险利率的 Sharpe 型值和相对 SH000300 的原生超额 IR；无风险利率零是本地显式约定。MDD 报负值，Calmar 分母取绝对值；分母为零记缺失。完整定义见机器协议。

运行时核对：Qlib 0.9.6 的 `risk_analysis(freq="day")` 实际默认年化系数为 238，虽然函数说明仍写 252。原生超额指标按 238 对齐保存的 Qlib 结果；论文口径的组合 ARR 与 Sharpe 型 IR 仍按 252。首批已保存的预测与每日收益保持不变，汇总字段修正另存回执。

保留全部五个注册种子，报告每次终点、均值、中位数、标准差、范围、完成率、有效轮数、因子数、请求/token 与耗时。失败使用最后一个已核验的集合；只有基准成功且从未提交新集合时才使用 Alpha20。没有可核验终点则标缺失，五次主汇总不完整，不补零、不补种子、不只展示成功子集。

旧的 D1/D2 bootstrap、p 值和候选名额学习曲线不沿用；改报按相同 elapsed time 的进展。这是五种子历史比较，不是独立市场重复。

## 6. 保留的本地差异与执行衔接

存储路径更新：`rd_factor_design/storage.json` 统一指定数据根目录 `/data/lzh/DeepScientist_finance`。`execute.py` 的默认批次直接位于该目录下的 `output/strategy_discovery/finance-rd-factor-20260924-v1`，provider、search-data、shared-data-cache、runs 均使用该位置。`execute.py --show-paths` 可只读查看路径；源码工作区仍在 `/home/lzh/DeepScientist_finance`。已有正式实验的冻结清单不重写，旧路径通过迁移兼容链接继续解析；恢复实验仍需原有检查，存储配置变更不会重启实验。

2026-09-24 最终联调更新：当前 `deepseek` 配置下四组真实单轮均通过评价、反馈选择和终点提交。完整反馈/无反馈分别评价 4/6 个因子，RD-Agent/AlphaAgent 各 3 个。外部两组的真实历史检查点均可恢复下一轮上下文。37 项本地测试通过；原生评价集成检查再次通过。详细回执为 `output/strategy_discovery/finance-rd-factor-20260924-v1/integration-completion.json`。这些是工程联调，不计入正式五种子结果，正式 20 次搜索尚未启动。

本轮新增兼容修复：AlphaAgent 空成功案例列表不再越界，提示明确说明没有成功案例；其原生模板仅替换 `$` 前缀列，避免公共数据的无前缀别名重复替换；RD-Agent 知识库调用统一经本机代理访问已固定版本的 BGE-M3 嵌入服务，嵌入回执独立保存。服务使用共享 4 CPU 线程，等待计入搜索时钟。保留全部失败联调及原始模型回执；三个修复不改变因子选择阈值。

LLM 按用户最新指令统一使用 `deepseek`，配置西湖 `/v1/chat/completions` 接口，无客户端 token 上限；该模型的真实联调尚待验证。此前 `deepseek-flash` 在 `/v1/responses` 返回 404，Chat Completions 短文本与 JSON 调用成功，但四组真实联调首请求均返回 500，串行诊断报告 engine-core fatal failure。此前 GLM 与 deepseek-flash 工程记录保留，不作为当前模型联调通过的证据。原始用量保留并将 prompt/completion tokens 映射到公共用量字段。当前设计只用各方法共同可用的行情字段，不能假装已有论文中的 Wind 基本面。保留现有四个搜索方法与两组固定控制，不把 Alpha101、Alpha360、AutoAlpha 的未运行结果补进论文对照表。

v4/v5 的批次和轮次调度器已暂停；正在执行的原生阶段允许收尾。暂停回执分别位于旧批次的 `design-change-pause.json`。旧运行日志可能仍显示 `running`，应以进程和暂停回执联合判断。不恢复旧调度、不复用其搜索因子作为新初始池、不混合统计。

下一步执行迁移包括：四个方法接入 Qlib 评价和原生选择、实现统一 6 小时时钟、验证跨轮历史与无反馈隔离、绑定完整数据快照和运行环境、生成独立运行目录。现有 Protocol B 启动脚本只能执行旧协议，不能拿来直接运行这些新配置。设计变更本身没有读取新市场数据或启动模型请求。

最新并行验证：五个 Alpha20 种子同时运行并全部命中预热缓存，总耗时约 14 秒；20 项输出一致性检查通过。该数字不代表 LLM 搜索吞吐。五个搜索共享两路模型请求服务，排队仍计入各自 6 小时，须在正式搜索中报告每方法等待时间与完成轮数。搜索执行器迁移尚未完成，尚无五路真实搜索正在运行。

追加执行修订：10 路 × 10 核替代 5 路 × 20 核，20 次搜索分两批，理论搜索排程 12 小时（不含迁移、准备和收尾）。Qlib 与 LightGBM 线程数跟随 worker 配额。10 次 Alpha20/Alpha158 预热缓存评价约 41.8 秒全部完成；输出以 1e-12 容差核验，Alpha158 seed-0 预测最大浮点差异 5.6e-17，其余预测完全一致。16 项测试通过。验证回执为 `output/strategy_discovery/finance-rd-factor-20260924-v1/ten-worker-validation.json`。模型请求仍为两路，未验证十路搜索吞吐；正式搜索仍待执行器迁移，12 小时不代表从现在起的交付时间。

执行器迁移适配说明（验证中）：外部两组保留固定镜像内的原生提议、编码、因子处理、反馈选择及 trace；只将 Qlib workspace 的训练回测替换为主机统一评价服务。AlphaAgent 原生 runner 禁用了跨轮因子拼接，因此保留其“当前批次替换最佳批次”的行为；RD-Agent 继续累积接受因子并使用原生有符号相关性去重。DeepScientist 保留生产 DSL，取消五候选限制；旧双折准入规则已移除，控制器以注册主指标净组合 CAGR 严格改善选择整个新增批次，此项为明确的本地选择适配。完整反馈可见提议、评价和选择，无反馈仅可见自己的未评分提议和编码错误。各组均从已完成的同种子 Alpha20 控制结果启动。

执行数据采用固定原生镜像写入 HDF5：主机 pandas 的 HDF5 datetime 索引格式与旧镜像不兼容，转换已逐值核对。原生因子全量计算前后会用两个历史截止日（2016-12-30、2020-06-30）复算并比较公共前缀，未来依赖检查失败则不评价该结果；这是经验性检查，不是任意代码因果性的形式证明。生成因子缓存与模型调用回执都保存在本运行目录内。API 请求不发送输出 token 上限，单请求传输等待最多 3600 秒且受剩余运行时长限制；失败或未知用量不自动重发。原生算法内部的明确编码修复仍会产生新的、分别记账的模型请求。

迁移代码入口为 `experiments/strategy_discovery/rd_factor_design/search/launch.py`，批量冻结与调度入口为 `experiments/strategy_discovery/rd_factor_design/execute.py`。15 项执行器测试，原评价/资源测试 17 项，共 32 项通过；两个固定镜像各 3 项集成检查全部通过（因果性正反例、历史序列化与下一轮上下文、真实 Qlib 评价接原生选择和终点提交）。容器集成检查使用显式测试因子及模拟模型选择响应，不计入正式实验。

真实联调的两个 DeepScientist 组已完成单轮；AlphaAgent 一次模型请求在旧 900 秒传输等待设置下超时，原请求结果/用量仍未知。旧 RD-Agent 进程在 12 次调用全部落盘后已停止，单轮未完成，另存 `migration-live-v1/rd/timeout-retirement.json` 解释主动退役原因。按用户“修复”指令，在 `timeout-repair-v1` 独立目录对 AlphaAgent 原请求进行一次显式诊断重试，保留旧未知用量；此调用仅验证传输，不算完整原生单轮或正式实验。新请求回执记录实际生效的 3600 秒超时、运行截止时间与策略版本，不设客户端输出 token 上限，也不自动重发未知请求。正式批量启动状态仍为未就绪，最新诊断状态见该目录的 `state.json`，迁移验证见 `output/strategy_discovery/finance-rd-factor-20260924-v1/migration-validation.json`。

可复查的本地测试命令：

DeepSeek JSON 兼容修复：`deepseek` 在服务端 `response_format=json_object` 下曾返回非法或缺字段的输出。取消该参数后，简单请求与相同真实提议提示词均返回合法 JSON；当前设置 `jsonMode=prompt`，通过提示词要求完整对象并在传输层严格解析校验。修复后两次真实调用通过，提议包含 5 个候选，用量共 2457 tokens。原响应与用量保留，不补造缺失字段，不自动重发；回执为 `deepseek-json-fix-validation-v1/state.json`。这仅验证响应格式与提议结构，完整四组训练回测联调仍未完成。

超时修复诊断结果：新进程回执确认 `timeoutSeconds=3600`、`transportPolicy=rd-factor-timeout-v2`，但服务端返回 HTTP 500，未返回结果和用量。此诊断失败不再自动重试，旧超时和本次服务端错误各记一次未知用量；不能据此宣称真实原生联调通过。

```bash
PYTHONPATH=experiments/strategy_discovery/rd_factor_design/search /home/lzh/.venvs/deepscientist-experiment-a/bin/python -m unittest discover -s experiments/strategy_discovery/rd_factor_design/search -p 'test_*.py'
PYTHONPATH=experiments/strategy_discovery/rd_factor_design/runtime /home/lzh/.venvs/deepscientist-experiment-a/bin/python -m unittest discover -s experiments/strategy_discovery/rd_factor_design/runtime -p 'test_*.py'
```

原生集成检查可通过 `search/test_search.py --native --batch <batch> --output <新的工程验证目录>` 运行。该命令执行真实容器和 Qlib 训练回测，但模型响应为测试夹具，不发送远程模型请求。正式启动入口 `execute.py --batch <batch> --launch` 会检查验证回执和源代码绑定；验证尚未完成时明确拒绝启动。
