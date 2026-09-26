# Python 轨迹：组合缺口证据与排除案例

本轮收集采用回顾性分析：允许阅读公开 verifier 日志来定位真实残留缺陷，再回查 agent 的完整 trajectory、实际验证命令、断言和候选补丁。没有调用 `.env` 的模型服务，没有读取参考补丁。以下 `step` 均为原始 `step_id`，不是数组下标。原始来源、大小及 SHA256 见各 trial 的 `acquisition.json`。

已确认三条适合本研究的轨迹，来自三个不同任务，均纳入最终十条主集合。其中 HTTPX 两条具有相同的异常资源释放机制，第二条是跨任务的机制复现，不应当作两种独立 insight。公开日志确认的是候选代码真实失败；本文关于“已有验证缺了哪种组合”的结论来自源码和完整可见验证轨迹的回顾分析，不是随机对照实验对历史失败原因的因果估计。

| Trial | 公开结果 | 轨迹实际覆盖 | 缺少组合 | 确认范围 |
|---|---|---|---|---|
| `httpx-streaming-json-iteration__asmX2Cz` | 107/108 F2P，1404/1404 P2P | 畸形 NDJSON 的异常；合法流的关闭 | 未耗尽流 × 解析异常 × 同一 response 的关闭断言 | 轨迹、候选代码、公开 verifier；本次未重放完整仓库 |
| `httpx-multipart-response-parsing__pAv36Bv` | 117/122 F2P，1272/1272 P2P | 畸形内存 body 的异常；合法流的关闭 | 畸形 framing × stream 模式 × 异常退出后的关闭 | 轨迹、候选代码、公开 verifier；本次未重放完整仓库 |
| `mnamer-daemon-watch-lifecycle__4add9Ug` | 50/51 F2P，319/319 P2P | 单来源限额；重复来源无限额；不同来源合并 | 重复资源 identity × 有限全局配额 | 上述证据，另有候选组件与官方镜像真实 CLI 两次四格重放 |

## PYN1：HTTPX JSON 的解析异常绕过资源关闭

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/httpx-streaming-json-iteration__asmX2Cz)。[原始材料](../../results/expanded_trials_20260926/trials/httpx-streaming-json-iteration__asmX2Cz/metadata.json)明确记录 `model=deepseek-v4-flash`、`outcome=fail`、`errored=false`、`reward=0`，不是环境中断造成的失败。

Issue 要求新增 `iter_json/aiter_json`，非法 JSON 应抛 `DecodingError`；对 streaming response，迭代需要消费并关闭 response，内存 response 则允许重复迭代。

Agent 确实验证了两边，而不是完全没有测试新功能：

1. [step 57](../../results/expanded_trials_20260926/trials/httpx-streaming-json-iteration__asmX2Cz/steps/057.txt) 将 `test_iter_ndjson_invalid_line` 加入 `tests/models/test_responses.py`。它用 `content=b'{"a": 1}\nnot json\n'` 构造**内存 response**，仅断言 `with pytest.raises(httpx.DecodingError): list(response.iter_json())`。同一步执行 `python -m pytest tests/models/test_responses.py -q`，输出 `155 passed`。
2. [step 82](../../results/expanded_trials_20260926/trials/httpx-streaming-json-iteration__asmX2Cz/steps/082.txt) 又新增 `test_iter_ndjson_streams_incrementally`：generator 依次产生两条合法记录；断言第一次 `next` 后未关闭，第二次得到正确数据，迭代结束后 `response.is_closed`。测试文件变成 `156 passed`。
3. [step 95](../../results/expanded_trials_20260926/trials/httpx-streaming-json-iteration__asmX2Cz/steps/095.txt) 最后再次运行同一文件，仍为 `156 passed`。完整 suite 曾有其他失败，因此本文只使用有明确通过输出的针对性验证作为 A/B 证据。

公开唯一失败是 `tests.test_json_stream.test_iter_json_ndjson_invalid_line_raises_and_closes_streaming_response`：[CTRF](../../results/expanded_trials_20260926/trials/httpx-streaming-json-iteration__asmX2Cz/verifier/ctrf.json) 显示输入 `[b'{"a":1}\n', b'{"b":\n']`。`DecodingError` 的检查通过，后面的 `assert response.is_closed` 失败，实际为 `False`。

候选根因见 [model.patch](../../results/expanded_trials_20260926/trials/httpx-streaming-json-iteration__asmX2Cz/model.patch) 的 `_iter_json_lines` 和 `Response.iter_json`（patch 行 247–282）：NDJSON 分支把 `self.iter_bytes()` 传给文本解码器，再传给逐行 JSON 解析器。解析器在底层流尚未完成耗尽时抛异常，外围没有 `finally: self.close()`；正常耗尽路径上的关闭不能保证异常退出也关闭。

最小判别组合示意：

```python
def body():
    yield b'{"a": 1}\n'
    yield b'not json\n'

r = httpx.Response(200, content=body(),
                   headers={"Content-Type": "application/ndjson"})
with pytest.raises(httpx.DecodingError):
    list(r.iter_json())
assert r.is_closed
```

它复用 A 的畸形内容、B 的 generator 容器和关闭观察。不是追加两个独立测试：异常必须发生在**同一底层 stream 尚未耗尽的动态调用中**，关闭观察必须绑定到这一个 response。

可计算关系是 `raise_site → exceptional_exit` 与 `resource.close` 的控制依赖，以及 `resource(response_A) = resource(response_B)` 的对象来源一致性。当前已有测试证明了“正常退出后关闭”，没有证明“异常退出后关闭”。核心缺口是后置条件对退出方式不闭合。

## PYN2：HTTPX multipart 的同类缺口，独立任务复现

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/httpx-multipart-response-parsing__pAv36Bv)。[metadata](../../results/expanded_trials_20260926/trials/httpx-multipart-response-parsing__pAv36Bv/metadata.json) 同样是 `deepseek-v4-flash / fail / errored=false`。

Issue 同时要求 malformed framing 抛 `DecodingError`，streaming response 在 multipart 迭代后被关闭。

Agent 在 [step 54](../../results/expanded_trials_20260926/trials/httpx-multipart-response-parsing__pAv36Bv/steps/054.txt) 提供了两组测试：

- `test_multipart_response_malformed_framing` 使用 `content=body`，包括缺结束 boundary 等内存输入，只断言 `DecodingError`。
- `test_multipart_response_streaming_consumes_and_closes` 使用 `stream=IteratorByteStream(stream())`，每次切 3 字节，但 body 格式合法；断言得到一个 part、`is_stream_consumed is True`、`is_closed is True`，第二次迭代抛 `StreamConsumed`。

[step 57](../../results/expanded_trials_20260926/trials/httpx-multipart-response-parsing__pAv36Bv/steps/057.txt) 的 verbose pytest 输出逐项显示两组均通过。最终 [step 118](../../results/expanded_trials_20260926/trials/httpx-multipart-response-parsing__pAv36Bv/steps/118.txt) 运行 `python -m pytest tests/test_multipart_response.py tests/test_multipart.py tests/test_exported_members.py -q`，`87 passed`。

公开失败全部属于 `test_iter_multipart_missing_or_malformed_closure_raises` 的 5 个参数：[CTRF](../../results/expanded_trials_20260926/trials/httpx-multipart-response-parsing__pAv36Bv/verifier/ctrf.json) 中每个 malformed streaming body 的异常检查都通过，`assert response.is_closed is True` 都得到 `False`。例如 body `b'--BOUNDARY\r\nX: 1\r\n\r\nx'`，缺少关闭 delimiter。

[候选 patch](../../results/expanded_trials_20260926/trials/httpx-multipart-response-parsing__pAv36Bv/model.patch) 行 112–117 为：

```python
with request_context(request=self._request):
    yield from decoder.iter_parts()
self.close()
```

`close()` 只在正常返回可达。前一个案例通过依赖底层耗尽来关闭，这个案例直接把关闭语句放在可能抛异常的迭代之后；表面实现不同，缺失的程序约束相同：`close` 未后支配异常退出路径。

最小组合是把 agent 畸形 framing 用例中的 `content=body` 换成合法流用例的分块 stream 形式，再在异常捕获后搬入 `assert response.is_closed`。此例本次没有在完整 HTTPX checkout 上重新执行，确认依据是公开 verifier 的实际失败和源码路径，不能标为本地全仓复现。

## PYN3：mnamer 重复来源与批量配额相互干扰

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/mnamer-daemon-watch-lifecycle__4add9Ug)。[metadata](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/metadata.json) 为 `deepseek-v4-flash / fail / errored=false`。Issue 要求合并 `--watch`、位置参数和配置文件来源，`--batch-size` 限制每轮全局处理数量。

轨迹已有以下实际验证：

- [step 32](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/steps/032.txt) 写 `/tmp/test_daemon.py`：在单一 watch 目录放 `a.mkv,b.mkv`，设置 `--batch-size 1`，断言目的地文件数恰好 1；另一段将同一个 `watch6` 同时放进 CLI 和 JSON 配置，**不设配额**，断言两个文件均成功移动。
- [step 39](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/steps/039.txt) 写 `/tmp/test_daemon_edges.py`：位置参数目录 `d1` 与 `--watch d2` 不同，断言两个目录的文件都移动成功。
- [step 78](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/steps/078.txt) 实际再次运行这两个脚本，以及全局 batch 等脚本，均显示 `OK`；已有本地测试 `322 passed`。最终 [step 109](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/steps/109.txt) `tests/local` 为 `335 passed`。

公开唯一失败叫 `test_daemon_batch_size_carries_across_runs`，但不能凭测试名字把问题归为跨轮状态。公开 [CTRF](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/verifier/ctrf.json) 明确是**第一轮**期待 2 个文件、实际 1 个。公开 task test 的调用将 `Downloads` 同时传给 `--watch` 与位置参数，并设置 `--batch-size 2`，共放置 5 个不同文件。

候选的实际路径为：

```python
# _resolve_watch_configs
cli_watches.extend(self.settings.watch or [])
cli_watches.extend(str(target) for target in self.settings.targets or [])
# 每个来源都扫描，未按路径或文件 identity 去重
candidates.sort(key=lambda item: str(item[1]))

# run_once
candidates = candidates[:batch_size]
for config, source in candidates:
    try:
        move(str(source), str(destination))
    except OSError:
        continue
```

两个逻辑来源别名指向同一目录，所以扫描结果是 `[movie.00, movie.00, movie.01, movie.01, ...]`。先截断两个候选，两次都选中同一个文件；第一次成功，第二次源已不存在，异常被跳过，最终只移动一个不同文件。

这里 A 的“重复输入在无限配额下可完成所有工作”和 B 的“单一来源下 batch=2 可处理两个文件”都成立，二者同场景失效。可计算关系是集合元素的资源 identity 相等、列表拼接产生重复、排序保持重复邻接、`take(k)` 位于去重/成功计数之前。共同调用函数并不是关键；**别名与有界消费次序**才是关键。

已使用[本地重放脚本](../../scripts/replay_mnamer_combination_component.py)从候选 `model.patch` 原样提取完整 `mnamer/daemon.py`，对它的真实 `_resolve_watch_configs → _scan → run_once` 运行四格对照：[结果](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/component_replay/result.json)。

| 同目录同时作为 watch 和位置参数 | batch size | 期望移动数 | 实际移动数 |
|---|---:|---:|---:|
| 否 | 无限 | 5 | 5 |
| 否 | 2 | 2 | 2 |
| 是 | 无限 | 5 | 5 |
| 是 | 2 | 2 | **1** |

组件重放只替换 import-only 的包壳、异常类型，以及 `SettingStore` 的数据容器；不替换三个被分析函数，不启动后台 daemon，不发网络请求。

随后又以[真实 CLI 重放脚本](../../scripts/replay_mnamer_combination_cli.py)，在本地已有官方 task image `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh71jf6d7mtqaw5z1h69krrarx820dys-v1.1` 上确认 base commit `73f5b537c8cad998e8e6d6bc40ad60e2e23bf268`，只应用 candidate patch，禁用网络，再从真实 `python -m mnamer` 执行相同四格。这里没有 settings 或模块替身。结果同样为 **5/5、2/2、5/5、1/2**，四次 CLI 均正常退出 0：[完整输出](../../results/expanded_trials_20260926/trials/mnamer-daemon-watch-lifecycle__4add9Ug/full_cli_replay.json)。没有安装 reference patch 或 verifier 测试；这是官方镜像内真实 CLI 的目标重放，不是全套 verifier 重跑。脚本均放在本目录使用，未修改 `oracle_gap`。

## 严格排除与对照

以下案例已经下载，但不能为凑足 10 条将它们算作“未合理组合导致漏检”：

| Trial | 判定理由 |
|---|---|
| `httpx-deterministic-cookie-store__mKVWFmf` | agent step 50 已组合同名不同路径，并明确断言只返回 `name=long`，step 55 全部通过。verifier 要求返回 `a=2; a=1`。是错误 oracle，不能说缺组合。 |
| `cattrs-partial-structuring-recov__WQL9fU3` | agent 写了 `test_refine_new_data_takes_precedence`，明确同时提交成功字段 `x=100` 和修复字段 `y`，断言覆盖原 `x=1`。已有交互输入，规范理解/oracle 错误。 |
| `fastapi-implicit-head-options__JDwjnKU` | 已验证 reset 后统计，但断言保留零计数键；verifier 需要 `{}`。不是遗漏组合。 |
| `fastapi-deprecation-response-hea__Gbd8zX5` | agent 明确断言普通路径 `/normal` 仍出现在 stats 且计数为 0；verifier 要求不出现。错误 oracle。 |
| `fastapi-implicit-head-options__nGLvwVs` | step 139 已测试内层 include=True、外层 include=False，并按候选实现断言 405；verifier nearest-wins 要 200。不是没有相同层级组合。 |
| `fastapi-deprecation-response-hea__KcekrJf` | agent 自写三层 include 测试，断言外层值覆盖内层；verifier 对 sunset 要内层 include 值。虽然 agent 用 deprecated，verifier 用 sunset，候选规范解释本身已经反向，不能仅归为缺组合。 |
| `adaptix-name-mapping-aliases__GjvAE5c` | alias 等于自身 primary key 时异常类别为 `ValueError`，期望 `ProviderNotFoundError`；未建立分别验证的两个条件之间的缺组合证据。 |
| `dateutil-rfc5545-timezone-intero__cuB6BaB` | agent 已有 `eval(repr(rule))`，失败在 `datetime` 绑定为模块 vs 类的命名空间；不能直接称遗漏两个已验证功能组合。 |
| `dateutil-rfc5545-timezone-intero__uaFFS5R` | IANA 名字序列化为 `Eastern`，多条失败共享该基础序列化问题；未建立缺组合证据。 |
| `langchain-request-coalescing__6MJsqSj` | agent 已有重复 batch 输入并断言底层调用数 2，公开得到 3；时间休眠与调度条件不同，暂属并发调度覆盖不足/待复现，不能说完全没组合 batch 与重复。 |
| `langchain-request-coalescing__9ApABCB` | 同样 batch 重复问题，另有 stats.total 统计；未建立足够组合因果证据。 |
| `igel-persist-feature-schema__CaydwTK` | 多个公开失败在 model/description 文件不存在处中断；未确认预期组合逻辑得到执行。 |
| `skrub-duration-encoding__7GQ5hQD` | robust scaling 的非空值算错，三种 dataframe 后端同一失败；目前证据不能说明是两个分别验证条件的交互。该任务在旧研究已见，不能称未见样本。 |
| `returns-validated-error-accumula__f9Lo7em` | 候选明确把 `lash` 定义为 no-op，导致基础 lash 和 Fold.collect_all 恢复语义都错；根因是基本操作契约误读，不够支持缺组合归因。 |
| `pwntools-tube-multiplexing__8zLk3He` | 大部分 verifier 在基本 open_channel 握手就超时；不能把这些失败当具体组合缺口。 |

## 对抽象的约束

这些证据支持从“功能标签两两组合”转向“已有测试建立的后置条件在哪些程序上下文中应继续成立”。HTTPX 的上下文改变是同一资源上的异常退出；mnamer 是同一资源通过两个来源进入受配额限制的消费过程。两者都需要先识别对象/资源对应，再检查组合后观察是否仍区分正确行为。

但它们不支持“所有已有断言可以直接迁移”：cookie、cattrs 和两条 FastAPI 轨迹已经给出反例——错误 oracle 可以完整覆盖目标输入却仍漏检。未来算法应明确区分输入组合缺口、退出/状态条件缺口、观察缺口与 oracle 错误，不能把它们放进一个宽泛的 combination 标签后声称统一解决。
