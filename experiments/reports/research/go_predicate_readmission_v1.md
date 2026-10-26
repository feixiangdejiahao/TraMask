> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/go_predicate_readmission_v1.md) · [旧路径映射](../../../results/path_map.tsv)

# Go 谓词接口兼容性回放

2026-09-29，当前接口修复基于 commit `42e9096`。独立审计实现为 `scripts/audit_go_predicate_readmission.py`，封存结果位于 `results/relation_search_20260929_v3/go_predicate_readmission_v1/seal.json`。

修复允许已有 `require` / `assert` 的一元检查在 `NoError/Error`、`Nil/NotNil`、`Empty/NotEmpty`、`True/False` 内改变预期方向。接收对象、测试参数、观察表达式以及所有诊断参数不变。这是表达已有模型回答的接口补全；语法准入不证明导入绑定、API 契约或新预期在语义上正确。

此次未调用模型或执行仓库。脚本冻结审计开始时已经存在 `feedback.json` 的全部 Go round，逐请求处理所有 response，未读取目标标签、选择目标 ID 或覆盖原结果。未完成 round 单列到 protocol，后续新增完成的 round 不会悄悄进入当前分母。新增测试检验互补谓词、对象/参数/诊断不变、额外操作拒收、原文件不变、response 来源哈希和非 complete 响应保留；与现有 predicate 测试合计 43 通过。

对每个 complete response，脚本核对冻结 prompt、provider wire request、response 原始 body、解析后的 response 和 completion 文本的一致性。保留原 validation，并用 current `validate` 的私有函数副本替换为 frozen old guard 进行对照重验，再以 current guard 重验。模块本身不被 monkey patch。每个准入变化还由独立 AST 叶节点比较确认：只允许互补方法名不同，其余 receiver、t、actual 和诊断保持不变。完整 revision 保存在每条审计记录中。

| Case | Complete 请求 | 新增准入 revision |
| --- | ---: | ---: |
| N05 | 16 | 0 |
| N06 | 16 | 0 |
| N07 | 16 | 4 |
| N08 | 16 | 0 |
| 合计 | 64 | 4 |

64 条旧 guard 重验全部精确重现原 validation。新 guard 改变了 4 条 response 的准入结果，revision 总数由 14 变为 18，没有撤销既有 revision；全部变化均通过独立谓词 AST 检查。其余 60 条回答的完整重验结果不变，原拒收和原空修订均保留。

这四条新增记录只能称为“已有回答现在能够表达并通过结构检查”。尚未据此确认四个正确 oracle、四个有效测试或额外 case 检出，需独立语义评价和真实执行。原请求没有获得新上下文，模型没有重新推理，所以该结果属于接口兼容性回放，不能作为程序分析上下文或模型推理质量的新增收益。
