# Trajectory slicing 实现

已将“历史执行关系 + 对应版本的程序切片”接入 EviWeave。现在从 D 的匹配点出发，可以找回它运行时使用的源码、准备状态、生成的数据和输出；最终仓库只是其中一个状态。旧测试被修改或删除后，其历史版本仍可分析。

## 方法怎样工作

1. **Replay 时记录实际动作。** 每条原命令执行一次，观察文件读写、进程启动、管道和输出。在写入和读取发生时保存文件字节，因此同一命令内“创建脚本 → 运行 → 删除”也有记录。
2. **把每份材料放回对应的历史状态。** 相同路径的不同内容分别保存；同样内容在不同次写入中的来源也分别保留。初始和提交快照连接仓库状态。读文件连接到实际读到的版本，复制、追加、覆盖和删除分别处理。
3. **从匹配点恢复程序依赖。** 先确定哪些执行消费过这个源码版本，再在各自的版本环境中切片。向前找到使用该值或对象状态的操作与观察，向后补齐它们的数据、控制和状态依赖。可解析的 helper、import、全局状态和常见测试 setup 一同连接。
4. **沿材料关系补回跨动作上下文。** 从切片涉及的文件或输入，追到产生它们的动作；沿实际消费者找到后续输出，再补齐这些输出的其他输入。只因时间相邻，不会建立依赖。

例如，Agent 先运行一个旧测试，再修改实现、删除旧测试。对旧测试切片时，使用旧实现；最后提交的实现仍保存为另一个版本。若旧测试先写入 JSON，另一条命令再读取该 JSON，二者通过具体数据版本连接。

Python 缓存需要额外处理：磁盘源码可能已经修改，但进程仍加载旧字节码。实现通过保存源码的编译结果确认对应关系；pytest 缓存使用原环境中的断言改写器比较。这个检查不会执行目标源码，也不会将磁盘状态改写成旧源码状态。

## 哪些关系已经支持

|材料或上下文|当前处理|
|---|---|
|中间源码、临时脚本、删除的测试|保存历史字节和产生/消费动作；按实际版本切片|
|helper 与调用者|静态解析调用、导入别名、实参/形参；向调用者恢复观察与准备状态|
|全局状态|汇总函数读写，连接调用前后的状态依赖|
|测试 setup|连接 beforeEach/beforeAll、unittest setUp、pytest 具名/autouse fixture 等常见规则|
|生成文件、JSON、snapshot|连接实际生产者与读者；JSON 可读取结构，其他格式保留原文|
|管道与输出|用实际流字节连接发送者和接收者；原 trajectory 输出与 replay 输出分别保存|
|命令中的程序|实际 Python/Node argv 和 stdin 建立代码材料；已知字面量 eval/exec 单独解析|
|源码被当作输入|保留完整输入及其消费动作，包括不能归入可执行语句的文本|

文件和流的读写来自实际执行；程序内部的依赖、调用和 setup 是静态分析。读取一个测试文件，只能确认该文件版本被消费，不能确认其中每个函数都运行过。一次进程内的输入到后续输出使用保守关系 `process_may_depend`，尚未取得语句级动态数据流。

动态计算的 eval 内容、未支持的嵌入语言、无法唯一连接的并发流保留材料及具体未解原因。命令结束后仍继续运行的后台进程会留下未解记录，跨后续命令的后台 IO 尚未持续观察。

## 接口与产物

`eviweave collect` 默认同步生成 `tests/trajectory.json`。B 仍只有 `id / text / source`，新增材料通过 A 的引用回读；D 使用原有查询与选择算法，编写来源改为依据实际写入判断。

```bash
PYTHONPATH=src .venv/bin/python -m eviweave slice \
  --manifest /absolute/replay/tests/manifest.json \
  --out /absolute/new-slicing-directory
```

该命令完成 D→F。`slices/` 保留原始匹配端口，`views/` 是程序切片，`graphs/` 是共享源码图，`episodes/` 是外层轨迹闭包。同语句与相同视图共享计算，原始入口仍保留。完整 B 材料保存在 `targets.json`，未降到语句的入口列入 `pending_roots`。

单位置接口为 `TrajectorySlicer(manifest).location(source, start, end, consumer=None)`；范围使用回读文本的 UTF-8 字节坐标。操作示例见[使用说明](../../src/eviweave/README.md)，模块边界见[架构](../../src/eviweave/ARCHITECTURE.md)。独立 `eviweave.replay` 仍只依赖标准库、Docker、Git；IO 观察器由采集器提供。

## 验证结果

|检查|结果|
|---|---|
|EviWeave 相关回归|171 项通过，其中新增 18 项真实执行的轨迹/切片测试|
|小型 Git/Docker 完整链路|4 条动作；提交状态一致；恢复已删除测试及旧实现；stdin 可检索；116 条 B 记录全部回读|
|同一小型链路的 D→F|10 个语句条件、18 个视图、4 份共享源码图、2 份轨迹闭包；另保留 2 个未降到语句的入口|
|S030 实际仓库检查|两条原验证命令成功；提交状态一致；851 份文件版本、2,796 个事件、1,046 份材料；14 个选定源码位置形成 28 个有文件消费上下文的视图|

18 项新增检查覆盖追加/删除、旧实现、管道、stdin/argv、失败尝试、跨文件全局状态、helper 调用者、beforeEach、setUp 与绑定方法、pytest fixture、嵌入程序、snapshot 覆盖、内核复制、编译产物来源、缓存旧版本及原始/replay 输出的区别。

S030 检查从已有提交 checkpoint 执行两条原验证命令，issue 使用该 API 的简短检查说明；没有重跑完整原轨迹。28 个视图表示文件版本与两次执行的关联，不表示 14 个位置都被实际执行。本轮验证实现连接；[旧 88 条静态 Pilot](../slicing_pilot_20261103/README.md)的引用覆盖结果保持原样，尚未用新采集器重测全部 88 条的证据覆盖。

本轮没有调用 LLM。算法没有读取手工证据标签或 Verifier。

- [检查汇总与代码快照](../../results/behavioral_masking/20261103_trajectory_slicing_verification_r02/verification.json)
- [小型 Docker 原始结果](../../results/behavioral_masking/20261103_trajectory_slicing_docker_r07/verification.json)
- [S030 原始结果](../../results/behavioral_masking/20261103_trajectory_slicing_s030_r05/verification.json)
- [轨迹建模实现](../../src/eviweave/trajectory.py)、[切片实现](../../src/eviweave/slicing.py)、[执行检查](../../tests/test_eviweave_trajectory.py)
