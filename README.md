# 程序分析辅助的组合测试推理

本项目研究 validation tests 为什么遗漏操作间的交互，以及如何自动生成能检出这些问题的组合测试。程序分析用于梳理输入绑定、调用、状态读写和断言依赖，帮助模型在具体源码证据上进行语义推理；测试执行与独立评价检查推理是否成立。

当前设计见 [method_design.md](research/method_design.md)。目前还没有在冷启动、统一预算下可靠覆盖全部17个 trial 的方法，也没有证明能够泛化到未参与设计的任务。17个 trial 对应14个不同任务，均为开发材料。模型使用 `.env` 指定的 **deepseek-v4-flash**；密钥不进入 Git 或实验记录。

最新五小时窗口为2026-09-29 11:35:35—16:35:35 UTC；中断后补齐的只读核验见[本轮独立评价](research/relation_search_v3_evaluation.md)。此前窗口见[历史五小时研究记录](research/relation_search_timebox_20260929.md)。

## 当前证据

- 最新统一新请求v3（冻结 `7a8ff95`）已完成17例两轮，确认 **16/17**：12例保留源断言，P1/P6/P7/N04使用本轮新预期；N05尚无确认合格目标见证。未达到全部17例的目标。后续修复没有回填；与历史12/17配置不同，不据差额单独证明某项分析有效。
- 新依赖排序及修改后图对照均没有改善五个语义目标的前16覆盖；精确材料去重也未释放预算。固定34对上下文消融的正确判断为14对13；固定17个三臂请求的完整上下文/无上下文/同源码声明为9/7/9。只保留源码节约token，却产生一条错误削弱断言，不能称更鲁棒。
- 历史 oracle 缓存重放的统一 v2 运行已确认 **17/17**；这是已获取模型判断的重放，不能当作冷启动成绩。
- 全新模型请求 v1 已完成全部17例，确认 **12/17**；v2 单独运行和评价，完成状态、漏检环节、已知错误 oracle 见[独立实验报告](research/relation_search_evaluation_20260929.md)。未完成案例不判漏检，多个运行不拼接成一次成绩。
- 八个 Python 任务，相同候选池和单轮八提案、零模型调用：写入路径静态优先排序使已确认检出 **3/8 → 4/8**。
- 旧关系 profile 与轮换对照均为4/8；新 writer 前沿在32组已有 trace 上去掉 writer 后，14个代表及全部保留决定也完全相同。尚无额外动态反馈收益证据。
- 同14个预期槽位请求开启 thinking 后，完整正确修订0→4；真实重放中，3个失效预期报警被消除，P6正确检出，另1个错误 P1 修订仍误报。4次调用耗尽输出预算无可用JSON。这是补充实验，不回填冻结主配置。
- 相同14个 enabled 请求去掉源码上下文，完整正确修订从4/14降为1/14；每条件只采样一次，尚未排除模型波动。新增的调用依赖和断言到写入路径 renderer 只完成确定性证据整理，尚未验证模型收益。

完整报警尚未穷尽标注，不报告整体误报率。首轮固定抽取34条源控制通过的失败候选，其中30条完整测试无效、2条有效、2条不确定，直接把原始失败当缺陷仍不可靠。当前也没有配对修复实验，不能声称提高 issue resolution rate。

## 研究与代码入口

| 内容 | 入口 |
|---|---|
| 当前流程、实现与待验证假设 | [方法说明](research/method_design.md) |
| 17条轨迹与组合缺口重审 | [轨迹分析](research/trajectory_logic_20260928/README.md) |
| 写入来源分析、静态排序及限制 | [局部搜索机制](research/assertion_writer_search_20260929.md) |
| 通用性反例、等价内联修复 | [审查](research/writer_priority_generality_audit_20260929.md)、[修复](research/writer_priority_terminal_write_fix_20260929.md) |
| 模型任务粒度、源码上下文与输出接口 | [预期判断实验](research/singleton_expected_slots_20260929.md) |
| 输入侧程序信息整理 | [调用依赖证据](research/call_dependency_evidence_20260929.md)、[断言到写入路径](research/assertion_path_context_prototype_20260929.md) |
| 学术证据与最小消融 | [学术审查](research/assertion_writer_academic_review_20260929.md) |
| STARS及2026论文启发 | [STARS逐节阅读](research/stars_abstraction_review.md)、[文献记录](research/literature_2026.md) |
| 源测试恢复、候选构造、搜索反馈 | `relation_search/`、`experimental/relation_search_*.py` |
| 断言与局部对象/字段写入分析 | `experimental/assertion_write_origin.py`、`exception_write_priority.py` |
| 有界模型语义判断 | `relation_search/oracle.py`、独立原型 `experimental/singleton_oracle_slots.py` |
| 固定配置主驱动 | `scripts/run_relation_campaign.py` |
| 物化与离线执行 | `scripts/execute_relation_search.py` |
| 独立评价 | `scripts/evaluate_relation_search_continuation.py` |

Python 关系探针与跨轮搜索已接入主驱动。新的 writer 运行跟踪仅有离线前沿实验；槽位接口也仍是独立原型，均不能写成已完成统一在线方法。源码编辑传递修复及真实测试见[专项记录](research/semantic_edit_transport_fix_20260929.md)。

## 运行

本地 `.venv`、依赖、Docker镜像和离线 harness 已准备。单元测试默认禁止真实网络请求：

```bash
.venv/bin/python -m pytest tests -q
```

零模型的八例静态排序实验可用新输出目录复现：

```bash
.venv/bin/python scripts/run_relation_campaign.py \
  --source results/relational_gap_20260928/batch7 \
  --output results/my_writer_search \
  --cases N01 N02 N03 N04 P1 P2 P3 P4 \
  --rounds 1 --limit 8 --pool 512 --include-baseline \
  --group-size 8 --workers 1 --timeout 180 \
  --oracle-mode none --writer-priority
```

主驱动还支持历史缓存 `replay` 与新请求 `fresh`，配置、源码哈希和预算冻结后不能修改并覆盖原实验。模型和生成阶段不读取参考补丁、隐藏 verifier 或封存评价标签。执行失败、合法JSON、结构接收和正确缺陷检出分别记账。

## 历史材料

旧版本的成绩和限制保留，不与当前配置合并：

- [2026-09-28五小时结果](research/relational_gap_timebox_20260928.md)：旧最好完整配置4/17。
- [中断后的历史检查点](research/relation_search_checkpoint_20260929.md)：当时累计见证11/17，非统一运行。
- [旧关系形状研究假说](research/relation_search_method.md)：保留设计推演及负面消融。
- [旧动作/观察方法](research/archive/method_design_action_observation_20260929.md)及[实验失败记录](research/semantic_transport_results.md)。
- [早期七例领域算子原型](research/archive/README_pilot.md)：有已知案例过拟合，不能作当前方法的泛化证据。
