> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/assertion_path_context_prototype_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# 把现有程序分析结果整理成模型可读的源码证据

这个小原型将已有 `assertion_write_origin` 的结果用于输入侧：替模型找出原断言的对象构造、字段写入和跨函数调用路径，再展示相关源码。它不生成期望，不选择候选，不修改冻结 prompt，也不把 writer 当作已验证有效的覆盖信号。本轮没有调用模型或运行被测代码，因而尚未验证这些证据能否改善模型推理。

新增接口是 [render_context](../../../prototypes/assertion_path_context.py)，接收原分析结果和同一份源码，返回确定的 Markdown：

```python
from experimental.assertion_write_origin import Index, analyze_assertion
from experimental.assertion_path_context import render_context

index = Index(corpus['sources'])
facts = analyze_assertion(None, source_path, assertion_line, index=index,
                          assertion_start_byte=assertion_start_byte)
context = render_context(None, facts, index=index)
```

程序列出“原 assert → 局部对象构造/别名 → 已解析类和字段”，保留直接 property→storage 的源码；再列类内直接 writer，以及从同一绑定对象的已有操作出发、沿 `self` 调用到 writer 的路径。每一步指向原源码位置，相关完整函数只展示一次，重复路径中的同一调用边或 writer 上下文也只解释一次。try/finally 和 generator 的源码保留。输出是程序生成的路径与代码，不需要模型填写自然语言关系标签。

提前退出位置严格称为源码顺序上的 **may 候选**。现有分析按源码位置收集 call/raise/yield，没有证明 Python 求值顺序和分支可达性；外层调用在源码上先出现，但可能在内层调用后才执行。renderer 不把这种关系说成已证明的执行先后。没有候选也不证明不会异常。动态 dispatch、外部写入、复杂 property、无法绑定的 factory/fixture 等仍 unknown。所列对象关系属于原测试；组合编辑改变接收者后，不能不经重新绑定就把原关系当作新测试事实。

按固定八个 Python 池的完整已注册断言集合运行 [census driver](../../../scripts/render_assertion_path_context_census.py)，结果如下。输入只读取 corpus 源码及断言登记，不读取 target/verdict；不按已知缺陷选择断言。

| 池 | 已枚举观察 | 可渲染原 q | 含既有 test-operation→writer 路径的 q |
| --- | ---: | ---: | ---: |
| P1 | 518 | 13 | 0 |
| P2 | 431 | 15 | 0 |
| P3 | 611 | 10 | 0 |
| P4 | 760 | 1 | 0 |
| N01 | 581 | 62 | 14 |
| N02 | 608 | 118 | 34 |
| N03 | 470 | 22 | 0 |
| N04 | 646 | 2 | 0 |
| 合计 | 4,625 | 243 | 48 |

243 个 q 共包含 245 个可绑定字段读取，其余 4,382 个观察仍计作不支持。多数可渲染项只有构造路径，不能称为已找出交互关系。完整证据文档为 2,138–37,864 bytes，没有为保持长度而静默截断路径；目前也没有 token 节约或认知难度改善的测量。

全量分析之后，可以查看 N01 的[原关闭断言证据](../../../results/program_relation_search/program_relation_search_20260929/assertion_path_context_v2/N01/8e93a7a70e0aa97fbcf81c18.md)。它机械整理出 `response.iter_json()` → `iter_json` → `iter_bytes` → `iter_raw` → `close` → `self.is_closed = True`，并保留三处不同 `iter_bytes` 调用的位置及相关分支代码。模型无需自行在多个函数中找这条调用链，但仍须结合输入、generator 的消费过程和 issue 契约判断是否会跳过关闭、期望是否应保留。该示例未参与 census 的资格或排序选择。

[v2 协议、源码快照、243 份文档和汇总](../../../results/program_relation_search/program_relation_search_20260929/assertion_path_context_v2)均已封存。初版 v1 也保留；v2 只对重复说明去重并明确源码顺序的限制，支持集合未变。[3 个 toy 测试](../../../tests/test_assertion_path_context.py)通过，覆盖别名/property/helper/generator、同类不同实例与 unknown、finally 保护与 terminal writer 前的调用。当前结果只证明这些输入证据能够确定性提取和组织，不声称完整切片、统一支持全部 17 例或新的检出收益。
