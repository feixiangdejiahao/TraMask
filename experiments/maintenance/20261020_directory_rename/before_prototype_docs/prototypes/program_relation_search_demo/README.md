# 有限关系 profile 搜索：机制验证 kernel

这是 **3 个独立合成 fixture 的机制验证，不是 17 个真实 pilot 的实验**。算法只输入 Python 源码和运行预算；不接收人工 terms、目标关系、case ID、rival 或正确输出。原源码中已有 assertion 保留执行，actual 仅记录，不反写 expected、不判定 bug。

从无参数 `test_*` 函数里的本地函数 literal-argument 调用恢复 seed 和 API。数字 terms 是参数位置与目标源码 comparison 常量，profile 记录所有可比较项的联合 `<,=,>`；mapping keys 来自源码 subscript/get 和 seed 字典，profile 同时记录所有 mapping 的完整 presence masks。参数名、具体数值和地址不直接充当 novelty。

同一通用搜索循环：参数向当前值/同伴值/比较锚及其 ±1 替换，或增删一个 dictionary 字段；真实执行目标函数和原测试，读取实际入口参数计算 profile，按新 profile 或每格有限代表保留扩展。字段补入值来自已有 seed/default literal。每候选记录源调用/terms/编辑的 AST 位置、具体参数、父候选、真实 profile、目标行覆盖与断言结果。

```bash
.venv/bin/python experimental/relation_frontier_demo/check.py
.venv/bin/python experimental/relation_frontier_demo/kernel.py \
  experimental/relation_frontier_demo/fixtures/equality.py \
  --budget 100 --output /tmp/relation-demo.json
```

自检输出到本目录 `artifacts/`；`summary.json` 包含生成器与检查脚本 SHA，另三份 JSON 保留逐候选证据。

| fixture | 执行数 | profile 数 | 验证内容 |
|---|---:|---:|---|
| equality | 74 | 13 | 新等值构型与原seed有完全相同的目标行覆盖；原断言仍执行 |
| presence | 73 | 16 | 两个mapping、两个机械恢复的key，覆盖16个联合mask，含partial |
| non_equivalence | 9 | 3 | 同一profile下actual仍不同，否定语义等价解释 |

另检查 identifier renaming、数字及源码比较锚整体平移后的搜索轨迹不变；检查一个测试多次调用同一API时，trace归属到被编辑的具体call。

**能力边界：**

- 只统计真实 line coverage，未实现 branch coverage；fixture 等值边界不进入新分支，但工具没有一般的分支覆盖测量。
- 只支持可信、终止的简单 Python fixture；直接执行源码，没有隔离、超时或生产级harness。literal局部call、普通参数、有限整数/浮点数和浅字典是本次范围；不支持alias、对象phase、producer链、guest语言或观察延伸。
- `source_assertion_evaluated` 只表示选定调用后原assert表达式被计算。presence的len断言对全部值变化都可能通过，**不等于observer充分**。
- 修改参数可能破坏原assert的语义前提。因此assertion failure不是缺陷报告。
- 每格保留两个代表只是有界搜索启发式；同格不意味着等价，也不保证穷尽合法输入。报告保存反例，不能用profile相同永久排除同格缺陷。
- mutation是单参数/单字段编辑，不保证恰好只跨一个关系邻居；实际到达的联合格子以trace为准。
- 三个fixture只验证自动提取—改写—执行—反馈闭环，不证明该指标优于dataflow/line coverage，不证明创新性或真实pilot检出率。
