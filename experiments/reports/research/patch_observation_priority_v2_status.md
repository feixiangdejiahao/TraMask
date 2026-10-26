> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/patch_observation_priority_v2_status.md) · [旧路径映射](../../../results/path_map.tsv)

# Independent v2 source-analysis prototype

This prototype preserves the frozen v1 implementation and the scored main configuration. It is not integrated into the campaign and was not used in the completed 4,502-candidate ranking study.

`experimental/patch_observation_priority_v2.py` adds identity-scoped lexical/call caches and transports a proved Python implicit receiver to the first formal parameter. Binding depends on source declarations, argument positions and descriptor semantics, rather than receiver spelling. Unknown decorators and rebinding remain unsupported. This does not provide heap, exception or callback dependence summaries.

`disable_receiver_fix=True` retains the original binding rules while enabling caches. Synthetic fixtures check exact v1/v2 cache-only rankings and evidence, modified-source cache invalidation, renamed receivers, aliases, static/class methods, shadowing and unsupported effects. The two v2 test files contain **56 passing tests**, rerun on 1 October 2026.

These tests establish bounded source-binding behavior and fixture-level cache equivalence. They do not establish real-pool speedups, witness exposure, oracle correctness or defect detection. In particular, they do not override the [negative v1 ranking result](patch_observation_priority_results.md), or claim that its strict zero coverage has been resolved on real tasks.

Next verification must freeze the prototype and apply it to a predetermined source sample, separating cache-only equivalence/cost from receiver-binding coverage. Target ranks must not guide new rules. The main **16/17** native result and remaining N05 gap are unchanged.
