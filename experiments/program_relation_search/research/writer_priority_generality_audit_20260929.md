# Writer priority 的独立 generality 审查

审查时间：2026-09-29。审查对象为 main 的 `experimental/exception_write_priority.py`、其静态分析依赖及 `--writer-priority` 集成。未修改算法，未修改 frozen worktree，未启动 Docker 或模型。另审查并单独提交了已完成诊断的 `scripts/diagnose_singleton_fallback.py`，commit 为 `0d042ca`。

## 结论

**没有发现 pilot ID、仓库 API、字段名或目标标签驱动的排序特判。** 例如，规则不检查 `httpx`、`iter_json`、`close`、`is_closed`、目标测试名称或 expected/verdict 文件。优先级来自源断言绑定的对象、写入位置、方法调用路径和异常捕获位置。

但这不意味着方法已经 general：当前实现是 **Python + `pytest.raises` + 局部直接构造对象 + 同类字段写入** 子集上的启发式排序。它有明确的框架 API 适配，也存在与程序组织方式相关的漏优先，以及路径不可行导致的误优先。不能把“没有硬编码目标”写成“已证明对各种 combination 缺陷有效”。

本轮新增5个与 pilot 名称无关的结构测试，包含真实本地执行。加上已有 priority 和集成测试，共 **28 passed**。其中若干测试有意保留并证明当前算法的边界，没有修改实现来使这些边界消失。

## 核心判定实际依赖什么

[`exception_write_priority.py`](../experimental/exception_write_priority.py) 的 `evidence` 要求以下源证据同时存在：

1. 原断言 q 在修改后仍能按字节区间映射到同一个未改动的 `ast.Assert`。
2. q 中的读取形如局部变量的字段；重新解析后，其构造位置及类与原绑定一致。
3. 字段在构造路径中有初始化写入，并在另一个方法中有后续写入。
4. 原测试在 q 之前对同一对象调用了一个操作，该操作通过同类 `self.method()` 调用路径到达后续 writer。
5. 这条路径的至少一条调用边之前，存在可能抛异常、显式 raise 或生成器挂起的语法位置。
6. 原操作没有处于已识别的异常捕获上下文中；修改后相同调用形式在 q 之前、处于已识别的 `pytest.raises` 中，且唯一匹配。
7. 修改后的操作与修改后的 q 仍解析到同一个构造绑定；新 handler 已在 q 之前结束。

符合条件得到一个 boolean 优先级，不计算 API 关键词分数，也不由模型生成分类标签。证据记录明确保留异常可行性、动态分派、实际最后写入等 unknown。它没有验证操作真的抛出了该类型异常，没有验证异常被捕获后一定到达 q，也没有判断 q 的原期望是否正确。

依赖的 [`assertion_write_origin.py`](../experimental/assertion_write_origin.py) 建立源模块和类索引，解析导入/重导出、局部构造及直接别名，将简单 property 映射到存储字段，寻找单类直接字段赋值和同类调用路径。`__init__`、`property`、`staticmethod`、`classmethod` 等是语言模型；`pytest`/`raises` 是显式框架适配。它们不是 pilot API，但必须在方法适用范围中说明。

## 集成与标签隔离

[`run_relation_search.py`](../scripts/run_relation_search.py) 在候选构造之后、既有公平调度之前应用 stable boolean partition。它读取当前 corpus 的全部已登记测试/断言，不读取 evaluation 目录、目标测试、参考实现、隐藏 verifier 或 oracle verdict。case 信息和源文件 SHA 用于身份及恢复检查，不用于优先级条件。

[`analyze_assertion_write_origin_census.py`](../scripts/analyze_assertion_write_origin_census.py) 确实含有固定 `CASES` 列表，但它仅供独立 census CLI 枚举实验 cohort。已经核对：这8个 ID 恰好是17例 registry 中全部 Python case。主线调用的是参数化的 `analyze_corpus(corpus)`，不读取该列表，因此没有按这些 ID 才启用算法的分支。已有真实集成测试也通过任意命名的 case 目录运行。

Go/TypeScript 输入启用该 flag 后记录 `unsupported_language`，保留候选顺序。Python 候选不会因为缺少 writer 证据被此步骤删除。后续 [`candidate_scheduling.py`](../experimental/candidate_scheduling.py) 仍按 operator 历史服务次数公平取候选；因此该排序主要改变 operator 队列内的顺序，**并非所有有证据候选都能全局优先进入前 k**。跨轮 attempted 记录和精确输入去重也仍然生效。

集成将 flag 和分析代码 SHA 纳入配置及恢复身份；已有测试覆盖默认行为不变、flag 传播、无证据语言回退、真实 control/generated 执行，以及恢复时拒绝配置变化。当前静态优先级没有使用独立 observed-write frontier；不能把已有 trace 的离线回放写成闭环搜索收益。

## 新增结构反例及含义

测试位于 [`test_writer_priority_generality.py`](../tests/test_writer_priority_generality.py)。所有例子只使用本地玩具代码，不读取 trial、目标或评估材料。

| 检查 | 实际执行 | 当前静态结果 | 说明 |
|---|---|---|---|
| 整数字段从17经 `+= 3` 变20，异常留下17 | control 通过，generated 原断言失败 | 有优先级 | 支持非 bool 字段和 AugAssign，不依赖资源关闭命名 |
| 将上述 writer 从 `self.commit()` 内联回 `apply()` | 内联前后 control/generated 结果相同 | 辅助方法版本有优先级，内联版本没有 | 存在对等价调用结构变化的漏优先 |
| 将捕获改为等价 `try/except ValueError` | control 通过，generated 在同一原断言失败 | 没有优先级 | 识别的是框架上下文子集，不是一般异常控制流 |
| 将前置 raise 放入 `if False` | control 通过，generated 在 pytest 的 DID NOT RAISE 处失败，尚未到 q | 有优先级 | 没有路径可行性证明；语法 bypass 不等于实际 bypass |
| 测试覆盖实例方法后调用同名操作 | control 通过，generated 原断言失败 | 仍借用旧类方法路径产生优先级 | 同一对象绑定不能证明运行时调用目标相同；已有 dynamic unknown 有实际意义 |

最值得注意的是内联反例：`path['calls']` 只包含调用边，优先级只从这些边提取 `possible_bypass_sites`。当 writer 本来就在操作方法内，operation→writer 路径的 `calls=[]`，即使 writer 前面有明确 raise，也得不到优先级。这不是字段/API 特判，却是影响泛化的结构性缺口。若后续修正，合理的方向是把**具体写入作为路径终点并分析其前驱**，而不是再添加某个方法名或案例模板。本轮只记录，没有修改算法。

上述“漏优先/误优先”是排序信号相对于实际路径的偏差，不是最终缺陷检测器的统计漏报/误报。无证据候选仍可能被公平调度选中；有证据候选也必须经过运行、control 和 oracle 检查。

## 其他已知覆盖边界

- 只支持直接局部构造和有限别名；fixture/工厂返回、参数传入对象、容器或嵌套接收者、条件重绑定通常无法绑定。
- 只从同一类的方法提取直接字段写入；跨对象/helper 函数修改、继承 writer、动态 descriptor、native 修改不构成完整写入图。
- 初始 writer 与后续 writer 必须位于不同方法；不适用于许多纯函数输入组合、集合元素交互、错误值关联及同方法内部多次写入场景。
- 源断言已修改、已有异常上下文、handler 内同形式调用不唯一时不提升优先级。把 q 移入 handler 或恢复对象时也可能失去映射。
- 框架识别限于已解析的 `pytest.raises`/导入别名和同步 `with`。`try/except`、`unittest.assertRaises`、自定义异常工具或 `async with` 没有统一异常边表示。
- 调用图和源码先后关系不是 CFG/异常可达性证明。循环次数、条件路径、递归、异常类型、生成器创建与恢复/穷尽均没有完整建模；分析还受深度12及路径数64上限约束。
- `finally` 处理是局部语法保护判断，不是跨调用的完整异常后支配分析。

因此目前可以表述为“一个不依赖仓库名称的、可复现的源级异常写入优先规则”，不能表述为“所有 combination 缺口的统一检测算法”。现有8例上的结果属于开发数据上的有界实验；字段改名与这些反例能检查机制，不能代替新的独立仓库/任务验证。

## Singleton 诊断脚本的维护性与凭据审查

[`diagnose_singleton_fallback.py`](../scripts/diagnose_singleton_fallback.py) 是独立、一次性有界实验驱动，没有接入 production 搜索。选择只读取已完成 transport 状态、候选数量和严格 JSON 语法；不读取 target、expected、review、guard decision 或 semantic-cache verdict。固定17-trial registry 是授权及实验 cohort 边界，不是模型内容筛选规则。

它对 `(system,prompt)` 去重，按 case 内 SHA 和 case 轮转冻结最多32条；同 prompt 跨 case 时采用字典序代表，并保留全部来源及 scope。原 request、原 completion、输入 SHA、代码快照、授权映射和新 raw response 均可复查。新实际 provider payload 逐条验证只有 thinking 改变。`strict_json` 只表示 JSON 语法有效，数组或标量 JSON 仍可能无法形成有效回复结构；程序把 JSON、guard 和独立 oracle 评价分开，符合这个诊断的目的。

脚本本身不读取 `.env`，只调用既有 `complete`→`dispatch`。凭据由 [`relational_gap/provider.py`](../relational_gap/provider.py) 的 dotenv loader 读取，仅放入发往同 provider 的 Authorization header；request/manifest 不记录 header、key 或明文 endpoint。provider 不跟随重定向，异常日志只记录类型；新脚本也只输出序号、case、状态、计数和耗时，不打印 prompt、response、base URL 或 key。历史 completion 的复制没有增加新外发数据。没有发现此次脚本导致的凭据输出路径。

维护性边界是明确的一次性协议：不静默恢复或重试；prepare 中途失败会保留原输出目录，需要另开目录；启动前的总并发证明由外部 host 审计和预留槽提供，并非脚本自己的跨进程信号量。360秒只限制启动新请求，已在途请求可完成。这些边界适合当前受控实验，但不是通用生产任务队列的保证。

该脚本单独提交为 `0d042ca`，没有夹带其他 agent 的修改。已完成脚本编译、6项严格 JSON 边界检查、32条实际 payload 比较和459份封存文件 SHA 复核。32/32 JSON 成功不替代完整 oracle 评价，原始材料已交独立 evaluator。

## 审查版本及验证

```text
exception_write_priority.py:
d19608f142dfd4f3fcd294ac5caf3ee231bf0c4039ccbcb8a10df990606ee712
assertion_write_origin.py:
8eb7076f1c3629e23dbf4abddf9e4f0fd3dff802f7eb383e16ef0fde989a5cff
run_relation_search.py:
19b522f430acf5616a974f0e108871d3d1fc0dad778a5a8a06ea11da3dbcee14
run_relation_campaign.py:
73fb0a11919a947d2311ec48b41e548d7eb38e614b58815123201749eb159fe5
diagnose_singleton_fallback.py:
be1cbe3d36af8c6e62c31df4603d5ceea40ddee80245cba849dc993778ad403b
```

验证命令：

```text
.venv/bin/python -m pytest -q tests/test_writer_priority_generality.py \
  tests/test_exception_write_priority.py tests/test_writer_priority_integration.py
28 passed
```
