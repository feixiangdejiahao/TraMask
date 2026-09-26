# 新增十条失败轨迹：发现集、组合特征与学术抽象

完成时间：2026-09-26。**主集合为10条新trial、10个不同task、9个仓库**，均为 DeepSWE v1.1 官方索引中的 `deepseek-v4-flash / fail / errored=false`，与原七个pilot不重叠。两个HTTPX任务复现同一清理机制，不把它们当成两种独立机制。

本轮下载了62条轨迹、涉及58个任务；这是收集量，不是全部已深入裁决的数量。索引快照共31,617条trial，其中该模型failed有211条、90个任务。筛选是有目的的案例发现：优先实际断言失败、可追到已执行validation、能给出局部组合解释的任务；分组筛查一般取task内按trial_name排序的第一条符合条件记录，并补查部分trial。它不是随机样本，不能从10/62估计缺陷比例或方法准确率。

每条均审阅实际命令、输入、观察/断言及输出，再结合候选补丁与公开失败分析。**6条在完整候选代码上执行了局部测试或真实CLI，2条只重放候选核心函数，2条未新增本地重放。** 所有重放见证都是人工事后构造，不是现有生成器自动找到的测试；也没有运行十个完整官方verifier。

## 十条主案例

| ID / 官方trial | 已有验证实际覆盖了什么 | 未合理组合的关系 | 缺陷表现；本轮证据 |
|---|---|---|---|
| N01 [HTTPX streaming JSON](https://deepswe.datacurve.ai/data/v1.1/trials/httpx-streaming-json-iteration__asmX2Cz) | 内存非法NDJSON会报错；正常流迭代后关闭 | **真实流 × 解析异常 × 同一response关闭** | 抛错后response仍未关闭；公开失败+源码，未新增重放 |
| N02 [HTTPX multipart](https://deepswe.datacurve.ai/data/v1.1/trials/httpx-multipart-response-parsing__pAv36Bv) | 内存错误framing被拒绝；正常流消费后关闭 | **流式multipart × framing异常 × 清理** | decoder抛错跳过后续close；公开失败+源码，未新增重放 |
| N03 [mnamer daemon](https://deepswe.datacurve.ai/data/v1.1/trials/mnamer-daemon-watch-lifecycle__4add9Ug) | 批量额度；多来源目录；部分重复来源但无额度 | **同一目录被两个入口指定 × 有限额度** | 重复文件占据额度，限2实际只处理1；真实CLI四格复现 |
| N04 [SQLite safe import](https://deepswe.datacurve.ai/data/v1.1/trials/sqlite-utils-safe-import-checkpo__LraMgba) | 非法INSERT拒绝回滚；bulk UPDATE在COUNT invariant下成功 | **bulk UPDATE修改invariant读取的字段，并使其为假** | 非法UPDATE仍提交；真实CLI四格复现 |
| N05 [termenv resets](https://deepswe.datacurve.ai/data/v1.1/trials/termenv-preserve-ansi-resets__Qgybsr5) | Output截断保留样式；Style不截断保留样式 | **Output入口 × 无需截断 × 保留reset后的样式** | 快速返回丢掉样式恢复；候选仓库2对照过、1组合失败 |
| N06 [etree merge](https://deepswe.datacurve.ai/data/v1.1/trials/etree-xml-diff-patch__N3t8VYg) | 文本变更、独立新增、真正冲突的合并 | **一侧改已有child文本 × 另一侧新增兄弟节点** | 共同parent被误判写冲突；候选仓库2对照过、1组合失败 |
| N07 [go-git merge](https://deepswe.datacurve.ai/data/v1.1/trials/go-git-worktree-merge-conflicts__ruQZqrh) | 同行冲突；不相交修改可合并 | **同一文件，两修改区间起点不同但部分重叠** | 错误地无冲突合并；候选扫描循环组件复现 |
| N08 [Pebble durability](https://deepswe.datacurve.ai/data/v1.1/trials/pebble-durability-wait-apis__2UjdyFm) | 已提交batch内部序号可等待；远未来仍阻塞 | **等待目标等于刚完成范围的exclusive上界** | 下一序号未持久化即成功；候选tracker函数组件复现 |
| N09 [Koota deferred](https://deepswe.datacurve.ai/data/v1.1/trials/koota-deferred-mutation-buffer__whVuJZW) | 全显式参数的pending读取；全缺省参数读取 | **同一record部分显式、部分默认 × flush前观察** | 省略字段undefined而应为默认0；14原测试+3对照过、1组合失败 |
| N10 [DynamoDB requiredIf](https://deepswe.datacurve.ai/data/v1.1/trials/dynamodb-toolbox-conditional-att__dRJudvE) | 显式put执行条件规则；普通schema的默认parser | **省略mode的默认调用 × 条件必填规则** | 应拒绝的输入被接受；8原新增+4基线+2对照过、1组合失败 |

“分别验证过”不等于每一侧都是agent新写的assert：N09的全缺省侧来自step194打印结果的人工验证；N10默认parser侧来自已有仓库tests，历史step201执行相应schema suite，本轮又逐项重放原4项。N04已经同时启用bulk和invariant，缺的是有区分力的写入，而不是两个API没有共同出现。

逐条轨迹步骤、原测试、根因与失败值：

- [Python：N01–N03](python_cases.md)
- [SQLite：N04](root_cases.md)
- [Go：N05–N08](go_cases.md)
- [TS：N09–N10及补充排除](ts_cases.md)
- [机器可读主集合](cases.json)：模型、task、仓库、base commit、steps、重放层级、来源文件SHA256。

## 这些轨迹增加了哪些实质认识

**第一，组合对象应该是关系，而不只是功能。** go-git需要“部分重叠”，Pebble需要“恰好等于边界”，mnamer需要“两个入口指向同一资源”。两次调用存在、覆盖同一个函数、两个test有依赖，都不能表达这些差异。

**第二，同一对象与同一阶段是组合有效的条件。** 把非法内存数据测试和正常流测试首尾运行，不会测试“同一真实流在异常时关闭”。把Koota完整值测试和默认值测试并排放置，也不会得到一个同时包含两类字段的record；等flush以后再读还会掩盖bug。

**第三，“都出现了”可能仍然没有判别力。** SQLite已注册COUNT invariant并执行UPDATE name，但改变name不会改变COUNT真假。这样的通过不提供“bulk会拒绝违反约束的写入”的证据。读写依赖能缩小搜索范围，但还需跨越谓词边界，并检查拒绝和原状态保持。

**第四，依赖既可能导致漏冲突，也可能制造假冲突。** go-git漏掉实际重叠；etree把共享parent错误扩大为写冲突。算法不能只找可能依赖的test pair后默认它们应该相互影响，需要表达相交、独立及包含关系。

以mnamer本地真实CLI为例，同样5个文件的四格结果是：

| 目录来源 | 不限额度 | 额度2 |
|---|---|---|
| 单一来源 | 5/5处理成功 | 2/2成功 |
| watch和positional指向同一目录 | 5/5成功 | **1/2成功** |

根因是候选列表在去除/消耗重复资源前就截取前2个。同一文件占了两个名额。仅增加“再测试一次batch-size”没有用；要绑定资源身份，才会暴露交互。

## 建议的核心抽象与算法

核心单位是**带观察的关系单元 `(q,ρ)`**：`q`表示检查什么，`ρ`表示参与者在同一运行中的关系。例如 `q=是否报告合并冲突`，`ρ=同一文件且 sA<sB<eA<eB`。

算法围绕它做三件事：从相关程序比较、对象来源及现有验证提取有限关系域；找出没有被有效检查的单元；用约束和最少源测试修改生成新见证。已有控制提供可构造输入与观察，少量LLM只处理不能从程序/已有断言确定的局部契约。观察发生过、断言有正确依据、断言最终通过是三件不同的事。

完整定义、机械抽取规则、Pebble逐步例子、十例支持边界及2026论文依据见 [abstraction.md](abstraction.md)。这是一项待验证的研究假说。比较关系覆盖、边界值分析、数据流指导组合和可观察性均有既有研究；不能仅换一个名字就声称创新。潜在贡献在于从agent实际验证恢复关系域并补其见证闭包，需优于等预算的现有方法才能成立。

这次没有继续给旧生成器添加pilot专用变换，也没有把新报告改写成旧算法已经成功的描述。

## 排除案例与证据边界

最值得保留的反例是SuperJSON、Bandit、Tengo和部分FastAPI：**目标组合已经执行过，有的已经失败，但agent接受错误期望或改掉测试**。这属于oracle/规格理解问题，不能算“没有生成组合”。Meriyah的公开失败与官方语法lookahead存在冲突；Quill的本地测试版本与公开失败不一致，均未纳入。Koota snapshot缺少既有独立A的一侧直接证据，降为补充。

这些决定及其步骤号见分组报告。交叉复核还纠正了两项易误读事实：mnamer的公开测试名虽然写“跨轮”，实际在第一轮就因重复目录失败；DynamoDB step181跑的是entity suite，默认parser的历史证据应使用step201 schema suite。

本轮是回顾性的发现集分析，人工读取了公开verifier日志，部分案例还读取本地公开task测试作辅助；没有读取参考实现、没有调用模型服务。未向`.env` provider发送新增代码。未来自动生成输入不能包含这些评价证据。

这里的因果结论限于：缺失的判别组合可以暴露已提交候选的一个具体缺陷。部分trial有其他失败，不能说该见证解释全部失败，也不能证明提供测试后agent一定完成修复。十条均是选出的失败正例，不能据此报告现有算法precision、recall改善或issue resolution rate提升。所有已审阅样本现在都属于已见数据。

## 数据与复核入口

原始数据在 `results/expanded_trials_20260926/`，受现有`.gitignore`排除；Git保存报告、十条清单/哈希、采集和重放代码、手写见证。每条trial的`acquisition.json`保存下载URL与SHA。公开索引来自 [DeepSWE v1.1](https://deepswe.datacurve.ai/data/v1.1/trials)，原始JSON端点由 [采集脚本](../../scripts/collect_deepswe_failures.py) 固定记录。

```bash
# 明确刷新公共索引；历史快照哈希保存在 cases.json
.venv/bin/python scripts/collect_deepswe_failures.py --refresh-index
# 按精确trial名收集，不下载reference solution
.venv/bin/python scripts/collect_deepswe_failures.py --trials httpx-streaming-json-iteration__asmX2Cz
# 已有官方镜像下的TS局部复现；使用本目录vendor/replay副本
.venv/bin/python scripts/replay_expanded_ts_cases.py koota_deferred
.venv/bin/python scripts/replay_expanded_ts_cases.py dynamodb
# Go组件复现；输出预期的判别测试失败，不是完整repo重放
.venv/bin/python scripts/expanded_trials_20260926/replay_go_components.py
```

其他入口：mnamer [真实CLI](../../scripts/replay_mnamer_combination_cli.py)与[组件](../../scripts/replay_mnamer_combination_component.py)；SQLite [真实CLI](../../scripts/replay_sqlite_combination.py)；termenv/etree及TS [手写探针](../../scripts/expanded_trials_20260926/probes)。Go全候选的具体Docker命令、base与image ID在各`review_evidence/repository_replay_result.json`；SQLite的隔离venv、源码URL与依赖快照在`local_replay/manifest.json`。所有新增Docker重放使用已有image，不拉取大镜像、不改变Docker存储。
