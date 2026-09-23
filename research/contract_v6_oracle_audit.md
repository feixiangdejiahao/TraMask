# contract_v6 最终独立审计

**本轮七个已知 pilot 目标均有受控证据，目标检出为 7/7。逐条检查 25 条协议候选报警，没有发现无效或与 issue 矛盾的 oracle；3 条参考报警均属于需求支持的参考冲突。** 这一结论限于已知开发集，不能宣称普遍零误报、零漏报或证明没有过拟合。

审计读取本轮冻结测试、request/response、issue、原测试、候选 API/代码及实际结果；未读取参考补丁源码或隐藏测试，未修改生成器。核对包括实际输入、失败位置、两边来源对照及目标机制，不因与前版相似而自动认定正确。[紧凑 JSON](experiments/contract_v6_oracle_audit.json)包含完整 25 条协议报警 ID、3 条参考报警、全部 49 条差分 ID、40 条目标匹配 ID、代表证据和文件哈希。

| Case | 执行义务 | 候选报警/差分 | 参考报警 | 目标匹配证据 |
|---|---:|---:|---:|---:|
| P1 | 98 | 21 | 2 | 14 |
| P2 | 90 | 1 | 1 | 1 |
| P3 | 21 | 3 | 0 | 1 |
| P4 | 4 | 4 | 0 | 4 |
| P5 | 20 | 11 | 0 | 11 |
| P6 | 22 | 1 | 0 | 1 |
| P7 | 8 | 8 | 0 | 8 |
| 合计 | 263 | 49 | 3 | 40 |

263 条义务由 221 条静态声明与 42 条运行时展开义务组成，另有 168 个对照。没有编译、导入、超时、跳过或缺失结果；28 个静态不支持位置单列，不能算通过。9 个原始 reference control 失败不属于组合误报。22 条原始生成参考失败应拆为 **19 条来源对照阻断＋3 条参考报警**；所有 49 条候选差分的依赖对照在两边均通过。

## 25 条协议报警及目标证据

**P1 的 21 条**覆盖 A/B/C/D/E/F/H 七种注册功能键，各自组合 press、repeat、release。输入为 `ESC[1;1:event_type<终止符>`，原 phase 不变。候选把一个合法键包拆成 7 个事件，在 `len(events) == 1` 处失败，尚未执行 phase 字段断言；参考正常解码。14 条 repeat/release 符合已知目标，7 条 press 是同一解码问题的附加证据，不能写成 21 条均观察到错误 phase 值。

**P2 的 1 条**把 `ESC[65;4u` 变为 `ESC[65;4:1;97u`，继承 `character is None`。modifiers=4 是 alt+shift，新增 text=a 后候选返回 a，参考仍为 None。issue 明确要求非 shift modified printable shortcut 不产生 character；原测试也断言这条快捷键为 None。该测试确实暴露了 text 与快捷键语义的组合遗漏。

**P3 的 3 条**中，`ESC[61:43;5u → ESC[61:43;6:1u` 保持 `"ctrl+plus" in aliases`。候选只保留含冗余 shift 的别名，违反 alternate shortcut 匹配 shifted forms 的要求；plus 已表示 shifted key，原 membership 提供现成 oracle。这是目标证据。另两条给 code0/text97 增加 alt 或 ctrl，候选 character 变为 None；issue 明确要求 code0 使用 associated text 作为 key 与 character，因此两条是附加缺陷证据，不代替 alias 目标。三条均执行到字段断言。

本轮 `issue_contradicted_protocol_differential_witness_count = 0`。这是这 25 条报警的独立语义审计结果，不是对全部可能生成测试的 soundness 证明。

## 3 条参考报警的独立判断

以下三条候选均通过，故本身不是候选误报；来源对照在两边也都通过。

| Case / obligation | follow-up（省略 `ESC[`） | 原 oracle | 参考输出 | 判断依据 |
|---|---|---|---|---|
| P1 `transport_645231f0ffe7573b` | `97:65:113;2:2u` | character=A | None | 删除 text 后仍是 shift-only printable，shifted alternate=65；issue 和无 text 原测试均要求字符 A。 |
| P1 `transport_c39c8a9b2105fa5f` | `61:65:113;2:2;65u` | character=A | None | 主键仍是 printable 的 `=`，报告的 shifted alternate 和 text 都是 A；保留 A 有明确 shift-only 语义支持。 |
| P2 `transport_54897209fb60f68b` | `65:65:113;2:1u` | base_key=a | A | issue 明确要求 shifted A 保持 base_key a；原测试允许主键 65 的此语义。 |

因此记为 **3 条需求支持的参考冲突**，而非“3 条已确认生成误报”。本轮没有此前“功能主键却保留字母 alternate”的未判定参考报警。参考实现仍不等于需求真理。

## P4–P7 的复用及目标核验

逐字节核对当前四个 manifest 及其全部生成文件，与 `audited_structural_v3` 完全相同；候选和参考的历史执行 artifact SHA256 都与当前产物及 `execution_reuse.json` 一致。可以复用同一冻结产物的执行结果，没有拼接各 case 的不同方法版本。

四类代表证据也重新核对：P4 带空格且引用的既存路径没有触发原有 FileExistsError；P5 复合工厂后的 guest 调用 panic，而独立 host 路径期望 17；P6 clone 更新返回 1/2，但共享 observer 仍为 0，而 fresh 路径观察到 1/2、源状态保持 0；P7 递归 schema 丢失非恒等 `key2=123` 转换，有限展开得到该字段。其必要原始/恒等对照均通过，分别支持四个目标。

## 模型输入与 NamedExpr 校验器变更

本轮成功响应保存在 `results/combination_contracts/v6_retry`。检查三个 request 的结构：包含 issue、已有测试代码、候选 API docstrings 和公开 wire facts；`implementation_bodies_included=false`，没有 `candidate_sources` 或生产函数体字段。初始 `v6` 目录记录 TLS 握手失败；重试请求与其逐字节相同，没有因这次传输失败改变提示。

P1 原输出包含局部赋值表达式 `isinstance_placeholder := False`，旧 AST 校验器因不支持 NamedExpr 拒绝。后续只扩展解释器对**任意合法局部名字赋值表达式**的处理，没有删除该语句、重写模型 predicate 或修改 expected。已核对 response 的代码文本、`predicate.py` 与冻结 metadata 中源码一致，请求及 predicate 哈希一致。metadata 如实保留 `initial_predicate_valid=false` 和 `predicate_revalidated=true`，原拒绝原因也仍在。

校验器变更只允许局部名字赋值，保留布尔短路行为及输入不可变约束；其代码与生成时快照一致。独立重跑 `.venv/bin/python -m pytest -q tests/test_contract_predicates.py`，**6 passed**，包括短路、不修改输入、拒绝导入/属性访问/输入写入等回归。该证据排除了“手改模型输出使 pilot 通过”的解释，但不能据此证明开发集上的方法调整没有适配风险；后续仍需未见 case 的冻结验证。
