> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/model_call_ledger.md) · [旧路径映射](../../../results/path_map.tsv)

**实验模型调用账本（2026-09-23）**

保留的实验 API 缓存共 **36 个请求记录、32 个模型响应，已报告用量合计 616,176 tokens**。其中 35 个请求有响应或失败记录佐证网络尝试，1 个仅保存请求文件。4 个请求没有用量记录；货币费用字段全部缺失，因此 token 总量是不完整的已知累计，**不能报告总费用为零**。

统计范围为 `results/combination_contracts/v*/P*` 与 `results/combination_screening/v*/P*`。完整逐调用来源、文件哈希、usage、校准和失败分类见 [model_call_ledger.json](../../../research/experiments/model_call_ledger.json)。不包含本研究工作中助手自身的推理成本或其他未保留在这两个目录中的服务调用。

| 阶段 | 请求记录 | 有响应 | 已报告 tokens | 缺失用量 |
| --- | ---: | ---: | ---: | ---: |
| 主实验 v6_retry | 3 | 3 | 25,992 | 0 |
| 首次 v6（TLS 失败） | 3 | 0 | 未知 | 3 |
| v6_repeat 独立模型调用 | 3 | 3 | 27,200 | 0 |
| 历史开发：contracts v1–v5、screening v1–v4 | 27 | 26 | 562,984 | 1 |

主实验 3 次调用使用 `gpt-6-astra`，输入 15,268、输出 10,724，共 **25,992 tokens**。P1 的 predicate 曾因 NamedExpr 被解释器拒绝；之后仅扩展解释器并重用原响应，没有额外模型调用。首次 TLS 失败的 3 个请求与随后 retry、repeat 的请求字节相同，但分别发生在独立调用目录，不能因请求哈希相同而去重。

| 系列 / 版本 | 请求 / 响应 | 模型 | 已报告 tokens | 返回及验证状态 |
| --- | ---: | --- | ---: | --- |
| contracts / v1 | 3 / 3 | deepseek-v4-flash | 85,296 | 3 次 length 截断，predicate 结构检查失败（无 manifest，有本地 audit） |
| contracts / v2 | 3 / 3 | deepseek-v4-flash | 70,758 | 3 次受限 AST 拒绝（Try/Try/For） |
| contracts / v3 | 3 / 2 | deepseek-v4-pro | 80,514 | 2 次 length 截断及结构拒绝；P2 仅有请求文件 |
| contracts / v4 | 3 / 3 | gpt-6-astra | 71,107 | 3 次 predicate 初检通过 |
| contracts / v5 | 3 / 3 | gpt-6-astra | 75,045 | 3 次 predicate 初检通过 |
| contracts / v6 | 3 / 0 | gpt-6-astra | 未知 | 3 次 TLS handshake EOF；用量未知 |
| contracts / v6_repeat | 3 / 3 | gpt-6-astra | 27,200 | 独立重复调用，3 次 predicate 初检通过 |
| contracts / v6_retry | 3 / 3 | gpt-6-astra | 25,992 | 主实验；1 次 NamedExpr 初检拒绝，原缓存重新验证后使用 |
| screening / v1 | 3 / 3 | deepseek-v4-flash | 29,449 | 3 次 ID 输出解析通过；未加入校准 |
| screening / v2 | 3 / 3 | deepseek-v4-pro | 48,066 | 3 次校准失败：21 次错误准入、4 次遗漏准入 |
| screening / v3 | 3 / 3 | claude-opus-4-6 | 53,978 | 3 次 JSON 解析失败，其中 1 次 length 截断 |
| screening / v4 | 3 / 3 | gpt-6-astra | 48,771 | 3 次 ID 输出解析及校准通过 |

“有响应”只表示提供方返回了被保存的响应；输出截断、格式错误、AST 拒绝、校准失败仍然计入 token 成本。所有版本合计有 9 次 predicate 初次检查拒绝（包括后来接受的 NamedExpr）、3 次 screening JSON 解析失败、3 次校准失败；另有 6 次 `finish_reason=length`，它与前述类别有重叠，不能直接相加。

`contracts/v3/P2` 只有 request.json，没有 response、manifest 或超时日志。前序会话摘要曾报告 timeout，但没有可独立引用的原始记录，因此账本按 **request_only_unknown** 处理，不补写失败日志、不估算 token。其余 3 个缺失用量请求有明确 TLS EOF 记录，也不把未知用量写成零。

去重检查覆盖全部 36 个缓存目录：没有物理目录别名、重复 provider response ID 或逐字节重复响应。token 只累加一次顶层 `response.usage.total_tokens`；manifest 和嵌套 `billing_usage` 中的复制用量不重复计数。未发现显式 fee/cost/price/currency 等货币字段，账本保留费用为 null，未按公开价格推算。

`results/combination_testing/` 中的 request.json 是本地执行请求；生成器冻结、Docker 执行和 deterministic replay 均不新增本账本内的实验模型 API 调用。`v6_repeat` 是实际再次请求模型，已单列计入 3 次调用及 27,200 tokens，不能与缓存重放混为一谈。
