# 实验环境安装记录

本文件记录此前安装的环境。最新授权已扩展为实现算法并进行本地 target-test 检索实验，使用本目录 venv；不发送仓库代码给模型服务。当前运行方式与结果见 [README.md](README.md)。

## Python

本目录 `.venv` 使用 Python 3.12.6。

```bash
source .venv/bin/activate
python -m pip check
```

主依赖清单：`requirements.txt`；本次实际安装的全部依赖版本：`requirements.lock.txt`。
在已有 Python 3.12 的机器重建：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python scripts/install_harness_versions.py
```

已安装 Harbor 0.5.0、datacurve-pier 0.3.1、mini-swe-agent 2.4.6、pytest、coverage、httpx、python-dotenv、Pydantic 和 Python/Go/TypeScript 的 Tree-sitter 解析器。`pip check` 通过。具体版本及导入检查在 `results/environment.json`。

## Trajectory harness

七个 trajectory 分别使用 mini-swe-agent 2.4.1 / 2.4.2 / 2.4.3 / 2.4.6。
2.4.6 安装在主 venv；其余版本分别安装在 `vendor/harness/<version>/`，共享主 venv 的依赖，避免包版本互相覆盖。三个历史版本均已通过导入检查；这不代表历史实验已完整复现。

指定历史版本时，可使用：

```bash
PYTHONPATH="$PWD/vendor/harness/2.4.1" .venv/bin/python -m minisweagent.run.mini --help
```

版本映射保存在 `data/cases.json` 和 `results/harness_versions.json`。Harbor / Pier 是本地复现基础设施；trajectory 实际 agent harness 是 mini-swe-agent。

## Docker

Docker daemon 的既有 `data-root` 为 `/data3/jhx/docker`，符合镜像存放要求，未修改 daemon 配置。
Textual、IPython、Tengo、Valibot 所需的四个 v1.1 镜像已经存在，并逐一通过 `docker image inspect` 检查；ID 和 digest 记录在 `results/docker_environment.json`。

镜像内已有 Python/pytest、Go 1.25.5、Node 24.12.0、pnpm 10.11.0 及仓库相关依赖，无需安装到宿主机。前期环境 smoke 检查已通过。Docker socket 在执行沙箱内不可访问，需要在具有 Docker 权限的宿主机上下文使用。

## 本地 replay 工具

从 `~/oracle_gap/scripts/` 复制的代码位于 `vendor/replay/`，来源和 SHA-256 保存在 `vendor/replay/PROVENANCE.json`。当前项目入口为 `scripts/replay.py`，运行时使用本目录副本和本地数据，不从 `~/oracle_gap` 导入执行代码。

```bash
.venv/bin/python scripts/replay.py --help
```

入口支持明确命令重放和 chronological trajectory 重放，两者意义不同；完整 replay 等待后续授权。七个 case 的原始 trajectory、candidate patch 和候选仓库已在用户缩小范围之前复制/准备到 `data/cases/`，不包含隐藏 verifier 或 reference patch。

## 模型配置与停止状态

`.env` 的 `base_url` / `api_key` 已能安全读取；此前只查询了模型列表，确认标准接口位于 `/v1`。没有发送 issue、补丁或测试代码。按用户最新要求，`configs/execution_policy.json` 禁止模型代码上传；`scripts/model_worker.py` 在提交模型请求前检查此设置。

早期产生的静态分析中间文件保留在 `results/P*/`，不视为本次检索实验结论；P1 早期 trajectory 重放的中断日志保留备查。最新用户已明确授权本地检索实现与实验，其结果单独存放在 `results/anchor_retrieval/`。本次没有重放被测仓库或运行模型生成。
