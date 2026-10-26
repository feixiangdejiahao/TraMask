> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/generic_control_evaluator_plan_v1.md) · [旧路径映射](../../../results/path_map.tsv)

# 独立控制评价与资产归档

本文件及 `scripts/evaluate_generic_controls.py` 仅供 evaluator 使用，不属于 `algorithm_files()`，不进入生成、模型准入或候选选择。当前评价对象为 `results/generic_v1/batch2`；批次 1 的产物保留，不按结果择优。此时尚未查看新候选或新执行结果。

## 判定单位与前提

每个 control 的 r1、r2、direct 均独立报告，固定 8×3 个单元。每条静态生成义务合并其全部参数化/Go 子测试叶子，避免将一条组合重复计数。candidate alarm 只由候选结果、相关 source controls 和执行状态计算，不使用 reference 结果。

所有 source controls 必须有运行记录且全部通过；失败、缺失、skip、setup error 分别保留。零生成、尚未冻结、未执行和基础设施失败不会从案例分母消失。参考通过仅是差分证据，不能将 oracle 自动标为有效；双方通过的测试也可以保持 `unknown`。

语义标签单独保存在人工 adjudication 文件中，绑定 case、variant、义务 ID 和完整 frozen manifest SHA-256。标签包括有限域内有效、契约推导有效、错误断言、无效输入/前提和 unknown。非 unknown 标签必须提供审阅者、独立推理与封存证据的路径/哈希。有限域内有效还必须引用真实存在的 oracle table 行号。哈希检查仅证明证据来源未变，不宣称自动验证了人工证明。

361 行表是有界语义校准，不是全语言/全输入域的证明。超出已封存输入、状态轨迹或别名形状的组合，须另给契约推导；无法证明则 unknown，不扩大有限表来迎合生成结果。源测试中出现但未落入有限枚举的值，同样不能冒称已由该表穷举证明。

只有语义有效且 source controls 通过的候选报警才能命中预先注入的交互缺陷。正确控制上出现“语义有效但候选失败”的矛盾单列，要求重新核对评价证据，不能擅自改 gold 或宣布新缺陷。参考报警率、错误 oracle、无效前提、未知报警分别统计，不以 reference failure 代替真误报。

## 延迟归档

等全部 admission/freeze 阶段结束后，再创建 `evaluation_assets/generic_controls_v1`。复制时保持以下原始字节不变：

- `seal.json`：原 research seal；`source_manifest.json`：原控制 manifest。
- `oracle_table.json`、`correct_replacements.json`：封存真值及正确替换。
- `original_correct_repositories.json`、`finite_validation.json`：原 evaluator 索引和有限域验证记录，保留其中历史绝对路径。
- `build_controls.py`、`validate_domains.py`：原构造与验证脚本。
- `source_control_runs.json`、`source_validation.json`：原源控制运行及环境摘要。
- `inputs/<case>/...`：按原 manifest 枚举的公开输入文件。
- `correct/<case>/...`：公开输入加封存替换所得的正确版本。

另写新的 `portable_registry.json` 和 `archive_inventory.json`，使用相对路径并记录逐文件 SHA-256，不改写旧哈希 manifest。归档 README 标明 evaluator-only 与复现步骤。所有控制源码与替换都只依赖本实验已有 Python/Go/Node 环境；不包含 `.env`、模型凭据或任何 holdout reference/verifier。

运行适配器先校验原 seal 三项哈希，再逐文件校验输入，并从原输入＋替换重建预期正确字节，核对 archived correct。Git 归档由根代理统一完成。当前 `/tmp/cc-generic-evaluator-v1` 保持不动，不提前将其内容放入生成可见资料。

## 运行方式

归档与本轮冻结均完成后：

```bash
.venv/bin/python scripts/evaluate_generic_controls.py \
  --experiment-root results/generic_v1/batch2 \
  --assets evaluation_assets/generic_controls_v1 \
  --adjudications results/generic_v1/control_adjudications_v1.json \
  --output results/generic_v1/control_audit_v1.json
```

不提供 adjudications 时，脚本只做结构/运行审计，所有未独立审核的语义均为 unknown。输出文件不可覆盖；后续补充审阅形成新版本，不回流生成器。
