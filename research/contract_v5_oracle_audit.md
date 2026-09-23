# contract_v5 紧凑审计

**30 条协议候选报警中未发现无效或与 issue 矛盾的 oracle；仅存的 2 条参考报警均属于需求支持的参考冲突。** 全 7 case 的已知目标检出仍为 **6/7，P2 漏报**，不能用附加差异替代 P2 目标。

本轮观察到 267 条组合义务：225 条静态声明，另 42 条 Go 义务在运行时展开。候选报警与受控差分均为 54 条，其中协议 30 条、P4–P7 共 24 条。没有编译、导入、超时、跳过或缺失执行结果；另有 28 个静态不支持位置，不能算测试通过。

| Case | 执行义务 | 候选报警 | 参考报警 | 本次审计结论 |
|---|---:|---:|---:|---|
| P1 | 101 | 27 | 1 | 27 条合法功能键序列均被候选拆成 7 个事件；reference 报警为需求冲突。 |
| P2 | 83 | 0 | 1 | 目标漏报；reference 报警为需求冲突。 |
| P3 | 29 | 3 | 0 | 1 条 alias 目标、2 条 text-only 附加差异，oracle 有独立依据。 |
| P4–P7 | 54 | 24 | 0 | 当前产物与已审计产物逐字节相同，核验后复用执行。 |

P1 的 27 条失败均发生在 `len(events) == 1`，**尚未执行所搬运的字段断言**。它们包括 14 条 repeat/release、7 条 press、6 条功能键 `character=None`；输入编码为注册的 A/B/C/D/E/F/H 功能键，并使用合法的 modifier/event-type 语法。候选只在 `u` 分支支持 event-type，与日志中的拆包一致。不能把这 27 条都描述成字段值错误。

P3 的三条分别是 `61:43;5u → 61:43;6:1u` 保持 `ctrl+plus` membership，以及 code0/text97 加 ctrl 或 alt 后保持 `character == "a"`。候选分别产生冗余 shift alias 和丢失 text-only 字符；issue 的 shifted shortcut 与 code0 text 规则支持原断言。三条均执行到字段断言，所有关联来源对照在两边通过。`issue_contradicted_protocol_differential_witness_count = 0`。

两条参考报警均在候选通过：

- **P1**：`ESC[61:65:113;2:2;65u`，期望 A，候选 A、参考 None。主键仍 printable，shifted alternate 与 associated text 都明确为 A；issue 要求 shift-only 保留 shifted character。
- **P2**：`ESC[65:65:113;2:1u`，期望 base_key a，候选 a、参考 A。issue 明确要求 shifted A 保持 base_key a，原测试也允许主键 65。

因此这 2 条不是候选误报；参考通过/失败都不能替代独立的需求判断。原始生成参考失败为 22 条，其中 **20 条被失败的来源对照阻断**，余下才是这 2 条参考报警。9 个原始 reference control 失败单列；全部 54 条候选差分的依赖对照均通过。

P4–P7 的复用经过实际核验：当前 `manifest.json` 与 `audited_structural_v3` 对应 manifest 逐字节相等，所有生成文件也逐字节相等且满足 manifest SHA256；候选和参考的历史执行 `artifact_sha256` 均匹配当前产物及 `execution_reuse.json`。这是同一冻结产物的执行缓存复用，不是为各 case 拼接不同算法的最优版本。

[紧凑证据数据](experiments/contract_v5_oracle_audit.json)保存 30 条协议报警、2 条参考报警、运行哈希和 4 项复用验证。审计未读取参考补丁、隐藏目标或 v6 产物，未修改生成器。这一已知发现集上的审计没有证明全局零误报、零漏报或 issue resolution rate 提升。
