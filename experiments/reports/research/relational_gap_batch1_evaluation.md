> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_batch1_evaluation.md) · [旧路径映射](../../../results/path_map.tsv)

# Batch 1 独立审阅

本批完整保留冻结来源、34个请求/响应、候选测试及运行日志。所有模型请求HTTP200，无重试；没有通过手工选择或改写生成测试来补目标。

17例中语义接受192条；10例完全没有接受候选。已对接受项的编辑和相关源测试/实际失败进行目标关系审阅，未发现任一目标关系的有效新见证。固定源test检索与候选parent命中均15/17，不等价于目标关系检测。

机器结果为 **目标关系/正确目标组合测试检出0/17**。按candidate去重后有89条生成测试失败，其中80条关联原控制通过；本文明确确认6条无效oracle报警，其余74条受控报警的oracle保持unknown，不能由此计算总体precision。参数化展开和共享control没有重复计作独立candidate。

34份模型响应全部HTTP200，但只有9份通过完整协议校验：19份超过每响应32条上限而整包拒绝，另6份有字段、evidence、hole或JSON格式问题。记录的模型usage合计2,600,725 prompt tokens、92,341 completion tokens。这说明本批的语义辅助既昂贵又容易因协议失败丢失候选；这些数据不支持当前“少量辅助”已经有效成立。

| Case | 审阅结论 |
|---|---|
| P1 | 逐项检查接受编辑：仅其它UI测试及别名测试输入替换，没有功能/特殊键编码与repeat/release共同出现；新增别名输入为65;4u或0;1;233u，均非该目标关系。 |
| P3 | 逐项检查键相关接受编辑：目标alternate-metadata测试变为61:43;1:5u、97;1:2u、0;1;97u或97;2u，未保留alternate key同时加入shift组合位；其它Key测试没有目标的alternate+represented-shift关系。 |
| P4 | 全部接受编辑涉及cell代码、history开关、普通无空格bundle文件名或autoreload；没有引入合法引用的含空格路径经过magic接口。 |
| N04 | 全部接受编辑涉及insert/upsert记录、SQL查询名、输出字段、异常后的无关观察或源码编辑脚本；没有构造safe bulk UPDATE使注册invariant从真变假。 |
| N05 | 接受编辑为ANSI table字段互换、颜色/模板/文件名/诊断文本/输出句柄，没有Output入口preserve+fits的样式保持见证；全部发射group编译失败。 |
| N07 | 接受编辑涉及branch/file名称、相同单行ours/theirs、status/checkout与worktree基础测试，没有在同一base文件构造错位多行部分相交区间。 |
| N08 | 接受编辑主要是诊断文本、文件名、无关DB参数，以及禁用WAL测试的远未来常数；未将同一sync batch的s+k绑定为邻近等待目标。 |

## 已明确确认的无效报警样本

以下六条均依据具体输入/状态/断言检查，未将所有红灯一概算误报。完整oracle分类仍有unknown，不能用这六条估计整体precision。

| Case / candidate | 无效原因 |
|---|---|
| P1 / `04ab07ff835c8855107bb9d9` | 把custom1变量绑定到声明initial/magenta的custom2对象，仍断言red；实际magenta符合该CSS定义。 |
| P1 / `bd0899aa3f9cbefca887540c` | 把第二次paste改成copy，仍断言输入文本增加World；copy不插入文本，保留原paste期望无依据。 |
| P3 / `0658b31f5d9906c3e12f99e9` | 把modifier改成1（无modifier），却仍断言ctrl+equals_sign；还把5放在event字段，该失败不支持原shortcut期望。 |
| P3 / `b69f2f0801d954f68c71bc93` | 把Ctrl+=输入整体替成无modifier的a repeat，仍断言ctrl+equals_sign；原期望不再适用。 |
| P4 / `25ac36da27c1f7e3aa83b561` | 删除对_sb_a的赋值改为_sb_x=1+1，后续仍执行_sb_a*10并要求所有cell成功；缺失绑定导致NameError是生成测试自身破坏依赖。 |
| N04 / `e37a34bbf11f39553bd4553a` | 只创建dogs表却将查询改成不存在的rows表并期待返回dogs记录；no such table由无效组合产生。 |

机器评价入口：`batch1_reviews_audited.json` 与 `batch1_pipeline/runs.json`；运行 `scripts/evaluate_relational_gap.py evaluate` 时同时传 `--batch-root .../batch1 --additional-batch-root .../batch1_retry`。N08最初准备因通用数字格式断言失败，重试版本单独保留，不能隐去该事实。
