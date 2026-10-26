> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/call_dependency_evidence_review_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# 调用依赖输入证据的独立审查

审查对象为 `a1992c2` 中的 [call_dependency_evidence.py](../../../prototypes/call_dependency_evidence.py)。使用真实 frontend 构造通用 toy，未手工伪造依赖图，没有模型或 Docker 调用，没有修改被审代码。其 8 项现有测试再次全部通过。

没有发现将该图明确冒称为修改后依赖、或没有原源码支持却肯定存在的边。`source_scope`、边名和 renderer 开头均指明 original-source may evidence；runtime object identity 标为 unknown，`modified_bindings_recomputed=False`，完整修改后测试是必需输入。改变 callee 文本、receiver 原定义时，会停止复用对应 target 和 actual/formal。focused 版本只显示编辑关联的 seed calls 及其 q，不再展开同 q 的其他生产调用；这是不完整的补充材料，不能从“未显示其他调用”推断 q 只依赖这些调用。

发现一个明确的常见结构覆盖损失：

```python
class Box:
    def __init__(self): self.value = 1
    def read(self): return self.value

def test_case():
    box = Box()
    box.value = 2  # 候选只把这里的 2 改为 3
    result = box.read()
    assert result == 2
```

原测试真实执行通过；改变这个输入值后，旧断言真实失败。因此存在输入编辑→字段状态→`read()` 返回→断言的影响，但 renderer 给出 `seed_call_ids=[]`、关联 q 数 0，只有 `no_original_call_link_for_edits`。这里的失败用于证明输入确实影响观察，并非把应当更新期望的 toy 宣称为被测缺陷。原因是现有 seed 通过调用范围重叠、value-use 和局部 binding 引用连接，没有覆盖这个实例属性赋值对后续方法读取的关系。

不能把该反例扩大为“所有可变输入都漏”。同样经过真实 frontend 的六个对照——算术中间变量、局部 alias、容器 literal、subscript 赋值、条件分支、`append` 后传入读取函数——都关联到了预期 q。`append` 自身没有已解析 declaration 时会 unknown，但编辑到最终 q 的关联仍存在。通过局部变量调用 `handler` 的 callable-alias 例子也未关联 q，原目标本就未解析，是现有绑定范围的另一限制。

另一个具体的保守丢证据情况是：把整个 `f(a,b)` 的 span 替换为 `f(b,a)`。callee 文本实际仍为 `f`，但 `changed_call_context` 因编辑范围覆盖 callee，将原目标标为 `edited_callee_unresolved`，不再输出其 target 或 actual/formal。结果没有虚构新绑定，也仍保留 seed 与 q；代价是丢掉可以进一步检查的源码关系。此处不建议在截止前扩展重绑定规则，而应明确输入编辑粒度会影响证据覆盖。

因此，这个 renderer 能提供可追溯的原源码关系，但目前不能保证找出所有输入变更影响的断言。`unknowns=[]` 也不是完整性证明，尤其原图并未重建修改后的别名、动态目标与堆状态。已有全修改测试和 issue 契约必须继续共同提供；这些结构事实不能代替模型作新的 oracle 判断。

9 个 toy 的源码、精确 edits、实际 graph 摘要及字段例子的执行结果封存在 [call_dependency_review_v1](../../../results/program_relation_search/program_relation_search_20260929/call_dependency_review_v1)，包含被审源码 SHA 和快照。复现命令：

```bash
.venv/bin/python results/relation_search_20260929/call_dependency_review_v1/repro.py
```

本审查只记录具体覆盖边界，未更改 renderer、frontend 或任何冻结实验，也不主张这些 toy 能代替独立任务上的 LLM 效果评测。
