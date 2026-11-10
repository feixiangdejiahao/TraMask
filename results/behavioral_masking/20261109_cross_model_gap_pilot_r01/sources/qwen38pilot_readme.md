---
pretty_name: DeepSWE 1.1 Agent Trajectories — Qwen3.8-27B
language:
  - en
license: apache-2.0
task_categories:
  - text-generation
tags:
  - coding-agents
  - software-engineering
  - evaluation
  - trajectories
  - deepswe
size_categories:
  - n<1K
---

# DeepSWE 1.1 trajectories: Qwen3.8-27B agents and baselines

This dataset contains agent trajectories and evaluation results from
7 complete runs on [DeepSWE 1.1](https://deepswe.datacurve.ai/).
The main experiments evaluate Qwen3.8-27B through Mini-SWE, Claude Code, and Pi.
Muse-Glimmer-30B and Qwen3.6-27B are included as weaker reference baselines.

Every run covers all 113 benchmark tasks. Altogether, the dataset contains:

- 791 task-level result records;
- 791 compressed agent trajectories;
- 425 submitted text patches;
- exact run configurations, aggregate scores, and efficiency statistics.

This repository contains evaluation outputs. The tasks, environments, and
verifiers live in the separate
[DeepSWE repository](https://github.com/datacurve-ai/deep-swe).

## What is DeepSWE?

DeepSWE measures coding agents on 113 original, long-horizon software-engineering
tasks drawn from active TypeScript, Go, Python, JavaScript, and Rust projects.
For each task, an agent receives an isolated repository and a natural-language
request. It must inspect the code, implement the requested behavior, run tests,
and submit a patch. DeepSWE then applies that patch to a clean copy and grades it
with held-out tests.


## Results

| Model | Agent | Reasoning | F2P (%) | Reward (%) | Solved | Execution errors |
|---|---|---:|---:|---:|---:|---:|
| [Muse-Glimmer-30B](runs/muse-glimmer-30b-mini-swe-xhigh/run.json) | Mini-SWE | xhigh | 39.43 | 5.31 | 6/113 | 19 |
| [Qwen3.6-27B](runs/qwen3.6-27b-pi-thinking-on/run.json) | Pi | thinking on | 63.44 | 3.54 | 4/113 | 1 |
| [Qwen3.8-27B](runs/qwen3.8-27b-mini-swe-xhigh/run.json) | Mini-SWE | xhigh | 77.42 | 41.59 | 47/113 | 0 |
| [Qwen3.8-27B](runs/qwen3.8-27b-claude-code-xhigh/run.json) | Claude Code | xhigh | 88.52 | 42.48 | 48/113 | 0 |
| [Qwen3.8-27B](runs/qwen3.8-27b-pi-low/run.json) | Pi | low | 86.47 | 39.82 | 45/113 | 0 |
| [Qwen3.8-27B](runs/qwen3.8-27b-pi-medium/run.json) | Pi | medium | 84.10 | 43.36 | 49/113 | 1 |
| [Qwen3.8-27B](runs/qwen3.8-27b-pi-xhigh/run.json) | Pi | xhigh | 86.65 | 46.02 | 52/113 | 3 |

An execution error means that the agent phase ended with an error. It is not the
number of tasks receiving zero reward. Exact model, sampling, context-window,
output-limit, timeout, retry, and agent-version settings are available through
the linked `run.json` files.



## Repository layout

```text
README.md

summary/
    main-results.csv
    efficiency-quantiles.csv

runs/
    <run-id>/
        run.json
        tasks/
            <task-id>/
                result.json
                trajectory.json.gz
                model.patch          # when available
```

`run.json` contains the run configuration, aggregate scores, efficiency
distributions, and an index of all tasks. `result.json` contains one task's
scores, status, durations, usage metrics, and artifact availability.
`trajectory.json.gz` contains the task prompt, assistant messages, reasoning
trace, tool calls, tool outputs, and usage information. Message details vary
slightly between agent interfaces.

`model.patch` is available for 425 tasks. Patch availability is recorded in
each task's `result.json`.

## Loading the data

Download a local snapshot:

```python
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(snapshot_download(
    repo_id="kaitchup/DeepSWE1.1-trajectories-Qwen3.8-27B",
    repo_type="dataset",
))
```

Read the result table and one trajectory:

```python
import csv
import gzip
import json

with (root / "summary" / "main-results.csv").open() as file:
    runs = list(csv.DictReader(file))

run_dir = root / "runs" / "qwen3.8-27b-pi-xhigh"
task_dir = sorted((run_dir / "tasks").iterdir())[0]
result = json.loads((task_dir / "result.json").read_text())

with gzip.open(task_dir / "trajectory.json.gz", "rt", encoding="utf-8") as file:
    trajectory = json.load(file)

print(result["task_name"], result["verifier"])
print("trajectory steps:", len(trajectory["steps"]))
```

## Limitations

- Each configuration has one run, so small differences should not be treated as
  statistically significant without repetitions.
- Agent interfaces differ in prompting, tools, context management, retry policy,
  and output limits. This is not a controlled model-only comparison.
- `low`, `medium`, and `xhigh` are configuration labels, not standardized amounts
  of inference compute across different agents or models.
- Token and turn counts come from different agent adapters and may not be
  perfectly comparable.

## Acknowledgments

[Verda](https://verda.com/?utm_source=kaitchup.substack.com&utm_medium=referral&utm_content=qwen38agenticcoding)
provided the RTX Pro 6000s and H200s used to run these experiments.

Verda is a full-stack AI cloud built for high-performance inference, training,
and agentic workloads, with data privacy and sustainability at its core.

## License and third-party code

This dataset is released under Apache-2.0. The benchmark tasks use third-party
open-source projects under their respective licenses. Trajectories and patches
can contain excerpts from or modifications to those projects; those materials
remain subject to their applicable upstream licenses.

See DeepSWE's
[project-level provenance table](https://github.com/datacurve-ai/deep-swe/blob/main/PROVENANCE.md).
