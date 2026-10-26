# 关系搜索实现：中断后的保存检查点

本轮没有达到 17/17。独立复核确认 **11/17 个 trial 有正确、能检出目标问题的组合测试，并有通过的原测试对照**；尚缺 P1、P3、P6、P7、N04、N05。这只是累计测试见证覆盖，不是统一配置、统一预算的端到端算法成绩。17 个 trial 对应 14 个 task，均为已见开发样例。

实验约定从 2026-09-28 15:49:29 UTC 开始，五小时截止点为 20:49:29 UTC。子任务恢复记录显示主进程约在 17:00 UTC 因上下文压缩连接故障中断；主进程于 2026-09-29 01:50 UTC 恢复时窗口已过。因此停止新增搜索和模型请求，完成离线核验、必要的记账错误修复和 Git 保存。不能把这段墙钟间隔描述为连续运行了五小时的实验。

## 保存了什么

- `experimental/relation_search_python.py`、`experimental/relation_search_go_ts.py`：根据源测试 AST、调用接收者、绑定和输入结构产生可执行的组合邻居。没有按 trial ID 分派，但算子是在这些已见案例上开发的，不能据此宣称没有过拟合。
- `relation_search/representations.py`：路径构造与命令表示的联合编辑。已确认一个有效 P4 见证，也保留了多处消费同一路径而只修改一处编码所产生的误报；该算子尚未闭合同一绑定的所有消费位置。
- `relation_search/runtime.py`、`instrument.py`、`frontier.py`：Python 运行探针、来源稳定的关系形状和候选保留/扩展接口。N03 有实际探针执行证据；主驱动尚未接入探针及后续扩展，Go/TS 也没有对应的完整动态反馈。因此真实任务结果主要支持构造能力，尚未证明反馈搜索的收益。
- `relation_search/oracle.py`：把程序选择的现有断言交给模型做局部期望修订，限制输入、动作、导入及观察位置的修改。机械校验不等于语义正确。
- 三个运行入口：`scripts/run_relation_search.py`、`scripts/execute_relation_search.py`、`scripts/relation_search_semantics.py`。执行复用已有离线 Docker harness，原测试对照与生成测试分进程运行。
- `scripts/evaluate_relation_search.py` 与[独立评价](relation_search_evaluation_20260928.md)：区分场景正确、断言正确、失败确为目标缺陷，保留失败和不确定的候选。

“关系形状”的核心设想仍是：对同一来源、对象和观察阶段，把具体值转换成相等/次序、别名、字段存在等联合关系；实际出现新关系后再扩展相应输入。当前实现与这一设想之间还缺完整的在线循环和同预算对照。新增更多构造算子本身不构成这一学术假说的验证。

保存前审计还发现 Go/TS 输入识别可能误编辑 expected 侧的嵌套调用、Go 类型和作用域检查不充分、全语料接口没有传递部分跨文件 guest 模板来源。这些限制未在本轮修复。Python 反馈的三项明确记账错误已修复：全未知事件不计新形状、容器重复引用不当作空容器、字符串截断状态不丢失；用修复代码重算既有 N03 trace，六个形状哈希及反馈与原记录完全相同，没有重跑实验或增加检测数。

## 结果应当怎样读

| 口径 | 结果 | 含义 |
|---|---:|---|
| 旧方法最好完整配置 | 4/17 | P2、N02、N07、N10；旧标签保持不变 |
| 本轮生成的正确测试来源 | 9/17 | P4、P5、N01、N03、N06、N07、N08、N09、N10 |
| 排除历史已执行关系 N06 | 8/17 | 仍是见证来源统计，不是固定预算检测率 |
| 旧、新见证合并 | 11/17 | 新增确认 P4、P5、N01、N03、N06、N08、N09 |
| 未完成的目标交付 | 6/17 | P1、P3、P6、P7、N04、N05 |

部分 Go/TS 机制见证先从收窄的源测试集合生成。后续完整语料的预算 128 检查仍未把已确认的 N07 严格部分重叠候选排进预算。不能将分次见证的并集包装成一次自动运行的 11/17，更不能由此声称漏报率已从 13/17 降到 6/17。

误报依然存在：P4 的部分输入没有在所有调用处正确编码；P6、P7 有组合后旧期望失效的报警。N04 则已经形成问题场景，却因旧断言认可错误结果而漏检。这些发现说明“造出新关系”和“有正确且充分的观察”是两个必须分别解决的环节。目前没有全体报警的穷尽标注，没有可靠的整体误报率，也没有 issue resolution rate 提升证据。

## 模型使用与待执行内容

本轮已有 11 次 `deepseek-v4-flash` 请求完成，累计 83,822 tokens（输入 75,477，输出 8,345），全部是局部现有断言判断，使用 `thinking=disabled`。缓存产生 7 个通过机械校验的 P3 断言修订；独立复核没有增加确认检出，其余 N04、N05、P7 请求没有产生修订。

加入明确输入差异、导入绑定并启用 thinking 的 v2 请求，以及 Go/TS 子任务准备的三个局部请求，只保存在本地，**尚未发送或验证**。新提示和可选 thinking 参数已在代码中保存，不能把旧补全结果算作新配置结果。模型调用不包含隐藏 verifier、参考补丁或封存评价标签。

## 复核与恢复入口

本地完整证据保留在 `results/relation_search_20260928/`；大体积结果、仓库副本、依赖与密钥不纳入 Git。[紧凑证据索引](relation_search_20260928_evidence.json)保存逐例状态和实际文件 SHA，不能代替原始运行文件。

主要记录：

- `evaluation/checkpoint_08_evaluation.json` 及同名 deliveries/reviews：权威累计结果。
- `evaluation/RECOVERY.md`、`go_ts/RECOVERY.md`、`recovery/RECOVERY_INVENTORY.md`：已完成、未完成和复用限制。
- `python/profile_proof_N03/`：真实探针及来源相同的 seed/candidate 对比。离线按 seed 优先计算反馈，不是在线搜索收益证明。
- `round1_completions/`：已完成的 v1 请求；`round1_semantics_v2/` 和 `go_ts/pending_oracles/`：未发送请求。

生成和物化可单独执行，不会调用模型或运行 Docker；输出目录必须尚不存在：

```bash
.venv/bin/python scripts/run_relation_search.py prepare \
  --source results/relational_gap_20260928/batch7/P1 \
  --output results/my_relation_search/P1 --include-baseline --limit 128
.venv/bin/python scripts/execute_relation_search.py emit \
  --input results/my_relation_search/P1 \
  --output results/my_relation_search_emitted/P1
```

这只是恢复命令示例，不代表 P1 已检出。完整单元回归使用 `.venv/bin/python -m pytest tests -q`，默认禁止真实网络请求。旧最好完整配置标签 `relational-gap-20260928-best` 保留；新检查点另行保存，避免替换已验证的旧配置。

保存前最终验证：**1851 passed，30 subtests passed（29.29 秒）**；`git diff --check` 与新增 Python 模块编译检查通过。独立评价离线重算与 checkpoint 08 逐结构一致，215 个直接记录的证据文件哈希全部匹配。以上回归验证实现和记录一致性，不等于补上剩余六个任务或证明算法泛化。
