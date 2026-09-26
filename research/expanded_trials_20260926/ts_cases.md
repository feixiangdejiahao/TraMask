# 2026-09-26 TS/JS failed trials：两条复现案例、补充案例与排除证据

这是回顾性案例发现，不是 blind generation。读取了公开 trajectory、提交的 model.patch、公开 verifier 输出，以及本地 DeepSWE task 的 tests/test.patch；**没有读取 reference solution，也没有向 `.env` provider 发送任何代码**。本地 verifier patch 是辅助证据，不声称它与网站运行版本逐字相同。来源及 SHA 见 [清单](ts_evidence_manifest.json)。

一共筛查了 17 个不同 task，各取按 trial_name 排序的第一条 `model=deepseek-v4-flash,outcome=fail,source=deep-swe`、具备 trajectory 和 model.patch 的记录。前两条纳入主案例；Koota snapshot 只作补充待确认，不计入最终 10 条。后者未找到“flat trait 值相等、引用不同”这一关系被已有独立 validation 直接断言的充分证据，不能把事后发现的关系冒充已有 test A。所有“缺陷原因”均指可解释目标失败的局部代码机制，不声称已经证明增加测试能让 agent 最终完成 issue。

| Trial | 历史官方 F2P / P2P | 实际 validation 的分离覆盖 | 遗漏组合 | 本地重放 |
|---|---|---|---|---|
| `koota-deferred-mutation-buffer__whVuJZW` | 70/71；128/128 | 全部参数的 pending read；无参数的 default read | 部分参数 × 未指定字段默认值 × flush 前读取 | 原 14 项通过，3 个新控制通过，组合失败 |
| `dynamodb-toolbox-conditional-att__dRJudvE` | 30/31；1267/1267 | `requiredIf` 配合显式 `mode:'put'`；普通 schema 配合默认 parser options | 默认 options × 条件必填规则 | 原新增 8 项及基线 4 项通过，2 个新控制通过，组合失败 |
| `koota-entity-snapshot-rollback__nXanPNw` | 79/84；47/47 | data trait 深拷贝、entity diff、world diff 的 tag 不变/data 变化 | world 包装 × data trait × 等值但不同引用 | 未本地重放；公开失败、代码、历史测试相互吻合 |

## 1. Koota deferred：同一个 pending 对象同时包含显式值和默认值

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/koota-deferred-mutation-buffer__whVuJZW)；[历史轨迹](../../results/expanded_trials_20260926/trials/koota-deferred-mutation-buffer__whVuJZW/trajectory_normalized.txt)；[候选补丁](../../results/expanded_trials_20260926/trials/koota-deferred-mutation-buffer__whVuJZW/model.patch)。

实际已有验证不是没有测试 `get()`：

- 补丁第 1405 行的 `spawns entities on flush` 创建 `A({value:1})`，在 flush 前后均断言 `.get(A).value === 1`。第 1420 行 `adds and removes traits` 验证 `deferred.add(..., A({value:5}))` 后 flush 前立即读到 5。
- 轨迹 **STEP 194** 修复默认值投影，并执行 `/tmp/tt4.ts`。同一脚本打印 `pair get before { amount: 7 }`、`pair default before { amount: 0 }`、`trait default before { value: 0 }`。也就是说显式参数和全默认分支确实分别执行过，不是根据测试名推测。该脚本是 `console.log` 验证而非 assert；原 patch 的 14 个测试仍保留 assert。
- **STEP 195** `pnpm --filter @koota/core test run tests/deferred.test.ts`：14 passed。STEP 191 的完整 suite 为 core 142 passed、react 32 passed；STEP 211 最后执行 `pnpm test`，尾部保留 react 32 passed。

缺口在于所有 schema 都只有一个被观察字段，或者一个字段全部给值/完全不给值。`hasParams=true` 并不代表每个字段都给了值。候选 `deferredGet`（补丁第 731 行起）在第 755 行直接 `if (traitState.hasParams) return traitState.params`，因此没有进入后面的 defaults 路径。

遗失的测试应把两种来源绑定到**同一 trait 实例**：

```ts
const V = trait({ vx: 0, vy: 0 });
world.deferred.add(e, V({ vx: 100 }));
expect(e.get(V)).toEqual({ vx: 100, vy: 0 }); // flush 前
```

公开 verifier 的 `should merge pending value with schema defaults for get()` 得到 `vy === undefined`，期望 0。只检查 `vx`、只检查 `has(V)`、或先 flush 再检查，都发现不了这个问题。把独立 tests 顺序执行也不会创造“同一对象中部分字段显式/部分字段默认”的输入。

**本地复现已完成。** 使用已有官方镜像，基线 HEAD 为 `31cbe9a1a26b3822a6c82ad50132508087cd24bc`，只应用公开 candidate patch。原 14 项 validation 全通过；新增完整参数、完全省略参数、部分参数但 flush 后读取三个控制均通过；部分参数且 flush 前读取这一组合失败：实际 `{vx:100}`，期望 `{vx:100,vy:0}`。因此这里不是整个 defaults 功能未实现。

[见证代码](../../results/expanded_trials_20260926/replays/koota_deferred/research_combination.test.ts)、[stdout](../../results/expanded_trials_20260926/replays/koota_deferred/stdout.txt)、[stderr](../../results/expanded_trials_20260926/replays/koota_deferred/stderr.txt)、[命令/镜像/输入 SHA](../../results/expanded_trials_20260926/replays/koota_deferred/replay_manifest.json)。

程序分析可以抓住的不是“deferred”这个关键词，而是：`get` 的多个返回路径分别提供 caller fields 和 schema fields；整体条件 `hasParams` 将它们互斥化，但输出 record 的字段来源应当允许混合。应寻找同一输出字段集合中存在不同来源的情况，并生成一个显式字段加一个省略字段的局部输入。观察必须覆盖省略字段。

## 2. DynamoDB Toolbox：规则被显式 mode 测试掩盖

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/dynamodb-toolbox-conditional-att__dRJudvE)；[历史轨迹](../../results/expanded_trials_20260926/trials/dynamodb-toolbox-conditional-att__dRJudvE/trajectory_normalized.txt)；[候选补丁](../../results/expanded_trials_20260926/trials/dynamodb-toolbox-conditional-att__dRJudvE/model.patch)。

已有两侧的验证都有实际代码依据：

- 新增 `zod parser and formatter enforce requiredIf`（补丁第 821 行附近）在同一 schema 上断言 `zod.parser({mode:'put'}).parse({pk:'x',type:'a'})` 抛 `ZodError`，加上 `details:'d'` 则通过。**STEP 124** 的临时 `.tmp-zod.ts` 也只对 parser 传显式 mode。**STEP 180** 新增 8 项测试全通过。
- 基线已有 [parser/item.unit.test.ts](../../results/expanded_trials_20260926/trials/dynamodb-toolbox-conditional-att__dRJudvE/base_zod_parser_item.unit.test.ts) 的 `returns object zod schema`，第 16 行直接 `itemZodParser(schema)`，不提供 options；随后断言 `output.parse(VALUE) === VALUE`，`parse(undefined)` 抛错。该文件从本地官方 base image 只读提取，来源及 SHA 在邻接 `base_zod_parser_item_source.json`，并非参考实现。轨迹 **STEP 201** 执行 `npx vitest run src/schema --reporter=dot`，75 files / 730 tests passed，包含该文件所在目录；尾部摘要没有逐条 test 名。STEP 181 的 19 files / 374 是 `src/entity`，不能拿它当 Zod 目录证据。
- STEP 38 展示 `ZodSchemer.parser(options={})`，STEP 39 展示 `itemZodParser` 将 options 继续传递。普通 parser 工具的默认 mode 为 put；新增 `assertRequiredIf` 也用 `{mode='put'}`（STEP 152）。任务明确要求 parser Zod schema 执行 conditional requirements。

新 helper `withRequiredIf` 却只解构 `{mode}`（补丁第 1070 行起），并在 `mode !== 'put'` 时直接返回原 Zod schema。调用默认 parser 时 `mode` 仍是 undefined，条件校验被跳过。

缺失的组合实际上只需保留新增测试的 schema 与输入，改用已有默认调用方式：

```ts
const parser = new ZodSchemer(schema).parser();
expect(parser.safeParse({ type: 'verbose' }).success).toBe(false);
```

公开 verifier 的 `parser Zod schema enforces conditional requirements`：实际 `success === true`，期望 false。其他 30 项新行为和 1267 项原行为通过。

**本地复现已完成。** 官方 image 基线 HEAD 为 `1f2a18664f8aded292707fcafb01ff15ea33d3b8`，原 8 项 agent validation 全通过；新增显式 put + 条件规则、默认 parser + 普通 required 两个控制通过；默认 parser + 条件规则失败，和官方错误一致。首次运行 10 pass / 1 fail，保存在 `run1_without_base_test/`。为核实原始默认 parser 的具体执行，第二次另外加入基线 `parser/item.unit.test.ts`，其 4 项也全部通过；最新总计 **14 pass / 1 fail**，包含明确的 `returns object zod schema` 通过记录。

[见证代码](../../results/expanded_trials_20260926/replays/dynamodb/research_combination.unit.test.ts)、[stdout](../../results/expanded_trials_20260926/replays/dynamodb/stdout.txt)、[stderr](../../results/expanded_trials_20260926/replays/dynamodb/stderr.txt)、[命令/镜像/输入 SHA](../../results/expanded_trials_20260926/replays/dynamodb/replay_manifest.json)。

这里的程序关系是同一 options 对象经过多个 wrapper，下游 guard 与其他消费者的默认归一化不一致。单纯“两个 test 调用同一个方法”会产生很多噪声；应关注同一个配置字段在一条路径被 defaulted，在另一条新增判定路径仍以 raw undefined 判断。原测试提供显式值，已有接口测试提供 omitted 形态，二者可用于构造反例。这个例子同时说明少量 LLM 不应重新猜整个 oracle：`mode` 省略与显式默认值应等价这一依据可以来自参数默认值及调用链。

## 3. 补充待确认：Koota snapshot 的同值不同引用与 world wrapper

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/koota-entity-snapshot-rollback__nXanPNw)；[历史轨迹](../../results/expanded_trials_20260926/trials/koota-entity-snapshot-rollback__nXanPNw/trajectory_normalized.txt)；[候选补丁](../../results/expanded_trials_20260926/trials/koota-entity-snapshot-rollback__nXanPNw/model.patch)。

不能简单说它“没有测试组合”：agent 写了 37 项 snapshot 测试，包含 rollback 后 query、关系排序、default/missing relations 等组合，**STEP 75** 10 files / 172 tests passed，**STEP 79** 最终再次 172 passed。

公开失败涉及一个值之间的关系：**flat trait 值相等，但 object identity 不同**。现有验证没有直接给出这个关系在 entity diff 上成立的 test A；因此这里只能说发现了遗漏的关系场景，尚不满足主案例要求的“已有验证两侧可组合”的强标准。

- `should snapshot tag traits as true and data traits as deep copies`（补丁第 779 行）验证 `{position:{x:1,y:2},isPlayer:true}`。紧接的 `should deep copy trait data` 修改 snapshot 的 x，确认 entity 中 x 仍为 1，明确验证了“值可相等但对象必须独立”的来源。
- `diffEntitySnapshots` 的 `should compute added, removed and changed traits sorted`（第 1046 行）使用 `b:{v:1}`→`b:{v:2}`；`should use shallow equality for data` 使用不同嵌套对象并期望变化。
- `diffWorldSnapshots` 的 `should compute added, removed and changed ids sorted`（第 1082 行）未变化实体只有 `a:true`；变化实体由 `a:true` 变成 `a:{value:2}`。`should treat empty relations and missing relations as equal`（第 1104 行）及 ordering 测试也以 `true` tag 为 trait 值。所以“world + data”虽然出现过，但“world + data 相等且不同引用”没有被对应 oracle 检查。

另一个 world 测试 `should ignore relation target ordering with data` 确有等值不同引用的 relation payload，但把这条 oracle 从 relation role 迁移到 trait role，需要额外语义论证，不能混称同一类对象已经测过。

候选的 `diffEntitySnapshots` 按 trait 的 data 逐个比较；`entitySnapshotsEqual`（第 561 行）却直接 `shallowEqual(a.traits, b.traits)`。这把 shallow equality 施加在 trait-name→data 的**外一层字典**，导致独立的 `{x:1,y:2}` 被当成不同值。

```ts
const a = { id: 1, traits: { Position: { x: 1, y: 2 } } };
const b = { id: 1, traits: { Position: { x: 1, y: 2 } } };
expect(diffWorldSnapshots({ entities: [a] }, { entities: [b] }).changed)
  .toEqual([]);
```

任务要求 trait data 用 shallow equality、world 包装不改变这条规则。公开 verifier 的 `flat data traits with identical values are not changed` 实际 changed.length=1、期望0；`snapshot-rollback-snapshot roundtrip produces identical world diff` 实际2、期望0，另外三个同根相关验证也失败。对 nested object 则不应强行要求 deep equality；新组合 oracle 必须保留**平面 data**这个适用前提。

**没有本地执行该 repository。** 对应官方 image 不在本地；尝试只读查询已有 deferred image 中是否有 snapshot 的准确 base commit，返回不存在，因此没有拿错误 base 代替，也没有拉新镜像。本条依据公开运行失败、完整 candidate patch 与历史 validation 的对应，强度低于前两条局部复现。

这里可抽象的关系是“观察在容器提升后应当检查同一级别的值”。静态上可寻找 wrapper 和 inner 操作共同读的字段路径：内层比较 `traits[k]`，外层却比较 `traits`。测试侧应保留等价输入的关系，而非只搬运一个具体常量。

## 排除、暂缓和有价值的反例

| Task / trial | 处理 | 具体理由 |
|---|---|---|
| superjson-error-stack-serializat__5Kj9Tsk | 排除 | STEP 54 的 `basename × stripInternalFrames` **已经失败**；STEP 55 agent 称规格顺序允许该结果，将 basename 改成 strip_cwd。属于已有报警被语义解释/改测试消解，不能说从未生成组合导致没检出。 |
| awilix-async-container-initializ__LMriNy2 | 排除 | candidate 新增 `scope initializing a parent singleton marks it initialized for the root too`（patch 564 行）直接支持 verifier 不接受的行为；更接近 contract/oracle 分歧，不能硬归因缺少组合。 |
| meriyah-explicit-resource-declar__KGRetgh | 排除，保留 oracle 冲突反例 | 看似遗漏 `using × of-binding × for-of`，但 TC39 官方语法的 ForDeclaration 路径有 `[lookahead ≠ using of]`。verifier 要求 `for(using of of [1,2])` 输出 using declaration，与该限制冲突；issue 没有明确要求更改这条语法。agent STEP 142/145 实际对照 Babel。两项 array-pattern 失败也涉及 `using[a]=...` 普通表达式歧义。不能据 reward=0 就把它当可靠缺陷。 |
| quill-shared-toolbar-focus__UWpkZiB | 暂缓 | 公开 ctrf 报收到被 size 格式化的 alpha、期望未格式化 alpha；本地同名测试的 focus 顺序却要求格式化 alpha。两份 oracle 版本/顺序可能不同，未建立准确失败与代码对应。 |
| koota-query-predicates__AmA3TJ7 | 暂缓 | 轨迹 STEP 100–103 明确比较 empty baseline 和 event baseline，最终修改断言；不是没有测 Added/Removed(predicate)。生命周期组合可能存在，但不能忽略显式语义选择。 |
| koota-pair-relation-tracking__Kseb8j5 | 暂缓 | agent 已有特定pair remove、exclusive replacement、destroy组合的通过测试；与公开失败差异可能在 modifier 创建、query drain、事件日志窗口。需要更严格局部重放才可计入。 |
| kea-atomic-signal-selectors__DdFHHYq | 暂缓 | 唯一失败是 includes 跟踪期望 `list.0`，实际 `list.includes:b`；可能是内部依赖表示的 oracle 分歧，未确认可观察语义错误。 |
| clack-async-autocomplete-options__9Fnk4dd | 暂缓 | 多项失败来自 loadError `''` 与 undefined 的精确默认值差异；另有 abort/显示问题，但未充分确认 A/B组合缺口。 |
| yjs-map-conflict-detection__yDjeJ5K | 暂缓 | 8/9新测试失败，整体feature语义尚未达成，未建立独立通过的组合因素。 |
| effect-sse-httpapi-streaming__HFfgmqh | 暂缓 | 存在plain handler×SSE、OpenAPI等候选，但本轮未充分追踪实际validation/byte类型root cause。 |
| testem-per-launcher-reports__4R5czBX | 排除当前计数 | 64/65，唯一失败要求comma-separated字符串布局；属于format oracle，尚无两个验证行为组合缺口证据。 |
| testem-bail-on-test-failure__7ojToaD | 暂缓 | 33个失败横跨adapter和reporter输出，大量单项功能缺失/精确格式；未界定组合机制。 |
| ts-pattern-match-each__k6ApMwi | 排除 | 新测试0/85均没有运行结果；不能将测试未执行归为组合遗漏。 |
| arktype-json-schema-refs-depende__H9LqAo6 | 备选 | recursive ref、dependent ref、anyOf分别/部分组合有通过测试，唯一失败为deep recursive $defs+nested property。尚未缩减，不能断言深组合是必要条件，而非其中某个primitive约束实现错。 |

Meriyah 规范来源：[TC39 Explicit Resource Management，for-in/of 语法](https://tc39.es/proposal-explicit-resource-management/#sec-for-in-and-for-of-statements)。这个排除尤为重要：组合覆盖不足和错误 benchmark oracle 是两个不同问题。

## 对学术抽象的直接约束

前两条复现案例和第三条补充观察不能用“tests共享callee”来概括。需要追踪的程序事实不同：缺省字段值、条件校验义务、值比较深度。实际失败涉及很小的代码条件，分别是整体 `hasParams` 提前返回、未归一化 `mode` 提前返回、对外层字典执行 shallowEqual。第三条尚缺原始关系验证的一侧证据，不能与前两条同等支持该假设。

可检验的研究假设是：从已有tests抽取“输入关系/配置关系 + 观察义务”，沿同一数据对象或同一配置字段的依赖追踪其在另一路径、wrapper或阶段的传递；当原义务在上下文变化后被 guard 跳过，或被施加在不同字段层级，就生成局部组合见证。重点是程序关系与可执行断言，而不是把多条自然语言标签填进 schema。这个假设目前只得到案例支持，尚不是实现完且经过泛化验证的新算法。

还必须保留三个区分：字段共同出现不等于读到缺省字段；API共同出现不等于同一归一化配置；对象共同出现不等于等值/不等值关系被验证。Snapshot尤其说明feature pair覆盖可以已经存在，缺的仍然是**关系约束**。
