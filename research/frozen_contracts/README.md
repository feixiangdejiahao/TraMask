# 冻结的模型条件

`v6/P1–P3` 是主实验使用的三次成功响应，`v6_repeat/P1–P3` 是完全相同请求的独立重抽样。每个目录保存未修改的 request、response、predicate 和原始 manifest；[index.json](index.json) 记录原路径、文件大小及 SHA-256。它们不含 API 凭据、参考补丁、隐藏 verifier 或手工目标。

`v6/P1/manifest.json` 保留旧解释器最初拒绝 NamedExpr 的记录；当前解释器支持纯局部赋值表达式，并在每次生成时重新验证相同 predicate 字节。没有改写模型代码来使测试通过。

在已准备本项目数据和检索产物的环境中，完全离线重新生成：

```bash
.venv/bin/python -m combination_testing.experiment \
  --protocol-mode contract --contracts research/frozen_contracts/v6 \
  --output results/frozen_reproduction
```

将缓存目录换成 `research/frozen_contracts/v6_repeat` 可重放独立重抽样。上述命令不调用模型；模型请求所使用的参数和提示以各 `request.json` 为准。重新调用 provider 不保证相同输出，固定缓存也不等于语义正确性证明。
