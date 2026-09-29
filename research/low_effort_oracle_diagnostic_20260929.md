# 限制模型推理开销的成对诊断

本实验只检查相同请求在 `thinking=enabled, reasoning_effort=low` 下的响应可用性和语义质量，不改变主算法的默认模型参数，也不把通过结构检查的断言当作正确 oracle。

官方 [Chat Completions API 文档](https://api-docs.deepseek.com/api/create-chat-completion/) 说明 `low/high/max` 控制推理投入，默认是 `high`，且 thinking 模式下 `temperature` 不生效。因此，`temperature=0` 不能作为这些请求可复现生成的保证。文档显示的公共模型别名与用户的私有 provider 不同，本实验保留用户指定的 `deepseek-v4-flash`。

`relational_gap/provider.py` 仅在请求显式携带 `reasoning_effort` 时透传并记录它；未指定时，实际发送的请求字节与此前一致。没有加入自动重试，也没有改变主实验的默认 thinking 配置。14 个 mock 与协议测试验证了默认兼容性、参数和 manifest 一致、原请求库存与顺序不变，以及已启动诊断不能悄悄重跑。

诊断输入完整复用 `disabled_oracle_cache_diagnostic/protocol.json` 中的 32 条请求和授权范围证明。它们是对历史所有记录按确切 system+prompt 去重后的冻结请求，不依照此次或历史响应、正确性和是否击中缺陷进行过滤。新脚本逐一检查原请求、语料、case、历史实际 payload 的哈希，保存原请求副本、新请求、预期实际 payload、完整响应、解析结果、结构校验结果和源码快照。

参数变化必须分层解释：

| 历史参数 | 请求数 | 本次变化 |
| --- | ---: | --- |
| thinking enabled，未指定 effort | 21 | 显式设置 effort=low |
| thinking disabled | 11 | 开启 thinking，同时设置 effort=low |

执行预算是单并发、至多 32 请求、360 秒启动窗口、每条请求最多 16,384 输出 token、超时 300 秒、无重试。窗口届满后不再启动新请求；已经发出的请求可在其超时内结束。因此实际完成数可能小于 32，不能补跑后只报告成功部分。

结果目录：`results/relation_search_20260929/low_effort_oracle_cache_diagnostic/`。`protocol.json` 的冻结 SHA256 为 `040f1e2c1759ae354f89bb7398d63f6aeb878444a664f37e5f5d066764b2897a`。`diagnostic.json` 记录完成数、严格 JSON 数、空内容、长度截断、token 使用量和两个 strata；不会计算 correctness。独立评估者需根据相同输入语义检查具体断言，并在比较结构接受率时使用同一版 validator。此前 disabled 诊断之后曾增加原断言诊断消息的确定性恢复，不能把这一 validator 变化误记为模型质量提升。

诊断在预算内启动原顺序前 9 条（indices 0–8），结束时共耗时 419.6 秒；剩余 23 条没有启动。9 条均返回 HTTP 成功并完成记录，实际 payload 全部符合冻结的 `enabled+low`，但只有 3 条是严格 JSON：4 条用完 16,384 个推理 token 后返回空内容，另 2 条仅返回空白。3 条 JSON 都没有产生通过结构检查的 revision。原 enabled 层实际执行 6 条，其中 3 条 JSON；原 disabled 层执行 3 条，均非 JSON。

只比较两种配置都已执行的这 9 条，结果如下。历史 disabled 的响应已用相同新版 validator 重校验；这张表仍然不把结构接受数当作正确性。

| 同一前 9 条请求 | disabled | enabled + low |
| --- | ---: | ---: |
| 严格 JSON | 8/9 | 3/9 |
| 空或纯空白内容 | 0/9 | 6/9 |
| 达到输出长度上限 | 0/9 | 4/9 |
| 通过结构检查的 revision | 1 | 0 |
| provider 时间之和（秒） | 31.6 | 418.8 |
| 输出 token（含推理） | 7,267 | 92,183 |

具体配对证据及响应哈希存放在 `paired_availability.json`。本次向当前私有 provider 发送 `reasoning_effort=low` 没有解决空白或推理预算耗尽问题；服务端没有提供证据证明它是否实际遵从了 effort 设置。此结果不支持修改主实验默认参数。由于预算内没有执行到大部分历史正确 oracle 所在的请求，不能据此报告完整的五条 oracle 保留率，也不能把没有完成的 23 条算作模型语义失败。独立语义复核尚待完成。
