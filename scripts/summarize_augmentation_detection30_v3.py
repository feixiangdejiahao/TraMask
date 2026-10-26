"""Offline audit for the frozen detection-only pilot. No provider or execution."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from augmentation.pipeline import write_json
from scripts.review_augmentation_detection30_v3 import RUN, inventory


# These are explicit Codex static review judgments, not keyword scoring.
# Scope: candidate conditions and focused operations in the selected eight.
# Source excerpts outside the focus remain available to the model.
EXTRACTION = {
 'T01-R1': ('incomplete', 'joint_a32901cf4d2d475d238f', '已提取完成状态和注册分支。未把批内重复项、串行调度及完成后再次调用放入同一行为表示。'),
 'T06-R1': ('incomplete', 'joint_9f560ade63f4b7db7e47', '已提取当前值、路由值和默认值的优先级。未表达两次 include 之间来源标记的变化。'),
 'T08-R1': ('incomplete', 'joint_ebc8ff44af6813fda83f', '已提取边界判断和扫描退出。未区分起始边界扫描与读完正文后缺少结束边界。'),
 'T10-R1': ('incomplete', 'joint_599164e23e1cea9226e3', '已明确提前退出会跳过输出调用。该候选未把 JSON 输出要求设为联合条件；另一候选含 JSON 分支，但没有形成这一具体输出区别。'),
 'T12-R1': ('incomplete', 'joint_9386169490d4c2f36979', '已提取包解析和符号查询。未表达导入别名替换原包名后的有效名称集合。'),
 'T13-R1': ('incomplete', 'joint_7a7a80c736f77e79ee2a', '已提取复制函数和 Free 字段。未选中明确表示不同输入项共享存储的候选，也未表示复制后经另一个闭包读回。'),
 'T15-R1': ('incomplete', 'joint_3bcdd64ef7a7112d7e1e', '已提取语义版本识别与类型分类。未把不合法版本中的前导零与跨类型排序结果连接起来。'),
 'T17-R1': ('incomplete', 'joint_c088b9c70fc6e4a4f0f2', '已提取默认表达式和编译分支。选中的存在性关系主要描述宿主 AST 下标，未表达被解释语言中字段存在但值为 undefined。'),
 'T18-R1': ('incomplete', 'joint_e526f605ffc0cad6bf6c', '已提取 PreserveResets 对截断调用的传递。未明确无截断的 String 路径与中间 reset 的交互。'),
 'T24-R1': ('explicit', 'joint_c798aea419106e4dce92', '已明确表达省略 mode、入口默认 put、原 options 传入辅助函数及下游跳过必填检查。'),
 'T25-R1': ('incomplete', 'joint_cacd832c5b836441c133', '条件表已包含模式、stack/stackFrames 和属性许可。但自动列出的 8 项组合主要围绕消息清理和 cause，没有列出该目标的模式与许可组合。'),
 'T27-R1': ('incomplete', 'joint_fe129584bc9776845451', '已提取异步响应到应用结果的调用。未把远端给出的非本地匹配项与再次本地过滤连接为行为区别。'),
 'T28-R1': ('incomplete', 'joint_a5e688b49a9b61ad4c4a', '已提取恢复、是否过期和再次请求的条件。未把恢复后的错误状态与观察者挂载及 staleTime=Infinity 连接起来。'),
 'T08-G1': ('incomplete', 'joint_c3ffae6857f048c92057', '已提取按分号分割和引号检查。未表达引号内部的分号属于边界值，而不是参数分隔符。'),
 'T16-G1': ('incomplete', 'joint_f5beecadbbc1ef1d8285', '已提取 typed 检查与赋值。未表示同一环境在前后两次执行中切换 TypedBindings 选项。'),
 'T18-G1': ('incomplete', 'joint_8cb72f591a7e0b9ce8dd', '已提取剩余宽度与尾串宽度比较。未把尾串包含 ANSI 控制序列作为输入类别，与按普通文本截断连接。'),
 'T19-G1': ('incomplete', 'joint_772f942a7067c75b412b', '已选到语法分析的控制流。包含 containsNegation 的具体候选未选中；没有表示普通前缀后接否定项。'),
 'T20-G1': ('incomplete', 'joint_93ee7a7f1ce1c8d1e31e', '已提取运行时 TTL 解析。声明校验候选未选中，也未形成声明正则与运行解析对小数时长的接受差异。'),
 'T20-G2': ('incomplete', 'joint_559991bd25d5405cff2e', '已提取查询参数合并。声明中的唯一键约束未进入所选行为表示，无法显式比较准入拒绝与运行去重。'),
 'T22-G1': ('incomplete', 'candidate_dc633bafaef9cd3f0952', '已提取异步递归根和 Recur 调用。未把同步 array 消费返回值、非空子树与 Promise 返回类型连在一起。'),
 'T24-G2': ('incomplete', 'joint_676204a5fe677dcb97eb', '已提取更新条件表达式的输出。未把 anyOf 的实际匹配分支与收集条件时遍历的分支连接起来。'),
 'T27-G1': ('incomplete', 'joint_85efca873ff47409e470', '已提取输入过短时的提前返回。未表示此前选择值、清空候选之后再提交这一状态顺序。'),
 'T30-G1': ('incomplete', 'joint_3cdf4fc49d84afe7eb4f', '已提取自动宽度相关函数和返回零的分支。未把嵌套子网格内容与父网格的尺寸消费连接起来。'),
 'T08-N1': ('incomplete', 'joint_620d04a08755428f16cb', '已提供头部终止与边界的相关语句，但把未遇空行和到达文件末尾合成一个布尔条件。该条件为 false 无法区分已遇空行与未遇空行但先遇边界，模型仍需恢复该区别。'),
}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def query_audit():
    counts, kinds, errors, bad_paths, test_rows = Counter(), Counter(), Counter(), [], []
    for p in sorted(RUN.glob('cases/*/detector/*/round*/feedback.json')):
        response = read(p)
        counts[response.get('status', 'returned_evidence')] += 1
        if response.get('status') == 'action_error':
            errors[response.get('error', '')] += 1
        a = p.with_name('action.json')
        if not a.exists():
            continue
        action = read(a)
        if action.get('action') != 'inspect':
            continue
        query = action.get('query', {})
        kinds[query.get('kind', 'missing')] += 1
        if query.get('kind') != 'tests':
            continue
        requested = query.get('path')
        paths = [t['span']['path'] for t in response.get('tests', [])]
        if requested:
            normalized = requested.removeprefix('./').rstrip('/')
            # Historical tests are stored at virtual paths. Their written_path
            # records the actual queried repository path.
            wrong = [t['span']['path'] for t in response.get('tests', [])
                     if not any(v and (v == normalized or v.startswith(normalized + '/'))
                                for v in (t['span']['path'], t.get('written_path')))]
            if wrong:
                bad_paths.append({'request':str(a), 'path':requested, 'returned':wrong})
        test_rows.append({'request':str(a), 'query':query, 'status':response.get('status'),
                          'returned_tests':len(paths), 'total_tests':response.get('total_tests'),
                          'has_more':response.get('has_more'), 'returned_paths':sorted(set(paths))})
    return {'feedback_status':dict(counts), 'inspect_kinds':dict(kinds), 'action_errors':dict(errors),
            'tests_queries':test_rows, 'wrong_path_results':bad_paths,
            'meaning':'Path fidelity only. Does not establish semantic relevance, branch feasibility or complete test coverage.'}


def main():
    rows = inventory()
    extractions = [read(p) for p in sorted(RUN.glob('cases/*/extraction.json'))]
    detections = [read(p) for p in sorted(RUN.glob('cases/*/detection.json'))]
    claims = [read(p) for p in sorted((RUN/'evaluation/claims').glob('*.json'))]
    by_claim = {v['id']:v for v in claims}
    found = {target for v in claims if v['verdict']=='correct' for target in v.get('reference_targets', [])}
    targets = []
    for target in read(RUN/'evaluation/reference_targets.json')['targets']:
        tid, case = target['id'], target['case']
        grade, cid, reason = EXTRACTION[tid]
        pack = read(RUN/'evaluation/extraction'/f'{case}.json')
        c = next(v for v in pack if v['id']==cid)
        assert c['selected'], (tid, cid)
        result = next((v for v in rows if v['case']==case and v['candidate']==cid), None)
        targets.append({'id':tid, 'case':case, 'description':target['description'], 'set':target['set'],
                        'selected_representation':grade, 'candidate':cid, 'extraction_review':reason,
                        'direct_relationship_retained':tid in {'T08-N1','T24-R1','T25-R1'},
                        'model_decision_for_related_candidate':result['decision'] if result else 'pending',
                        'target_detected':tid in found})
    write_json(RUN/'evaluation/target_review.json', {'reviewer':'Codex static semantic review; not independent human validation',
        'scope':'Explicit joint behavior in selected conditions, focused operations AND enumerated values. Not source retrieval recall or global static-analysis precision. Earlier relation-only check is separately archived.',
        'grades':{'explicit':'The key interaction and a value combination distinguishing its behavior are present in the selected representation.',
                  'incomplete':'A necessary input category, identity, phase, consumer or relationship is not explicit; related source may still be supplied.'},
        'targets':targets})
    audit = query_audit()
    write_json(RUN/'evaluation/query_audit.json', audit)
    models = Counter()
    for p in RUN.glob('cases/*/detector/*/round*/manifest.json'):
        m = read(p)
        models[m.get('response_model','unknown')] += 1
    families, selected_families = Counter(), Counter()
    for d in extractions:
        families.update(d['families'])
        selected_families.update(c['family'] for c in d['selected'])
    frozen = read(RUN/'protocol.json')['implementation_sha256']
    mismatches = [p for p,digest in frozen.items() if sha(ROOT/p)!=digest]
    claimed = [v for v in rows if v['decision']=='gap']
    primary = [v for v in targets if v['set']=='primary23']
    summary = {'updated_at':datetime.now(timezone.utc).isoformat(),
       'status':'complete' if len(detections)==30 and len(rows)==240 and all(v['id'] in by_claim for v in claimed) else 'in_progress',
       'completed_extractions':len(extractions), 'completed_detections':len(detections),
       'retained_candidates':sum(v['counts']['candidates'] for v in extractions),
       'selected_candidates':sum(len(v['selected']) for v in extractions),
       'finished_candidates':len(rows), 'model_decisions':dict(Counter(v['decision'] for v in rows)),
       'stop_reasons':dict(Counter(v['stop_reason'] for v in rows)),
       'external_model_calls':sum(v['external_model_calls'] for v in detections),
       'charged_tokens':sum(v['charged_tokens'] for v in detections), 'response_models':dict(models),
       'test_generation_calls':0, 'test_execution_calls':0,
       'claim_review':dict(Counter(v['verdict'] for v in claims)),
       'unreviewed_claims':[v['id'] for v in claimed if v['id'] not in by_claim],
       'correct_task_ids':sorted({v['case'] for v in claims if v['verdict']=='correct'}),
       'new_discoveries':[{'id':v['new_target_id'],'case':v['case'],'claim':v['id']} for v in claims if v['verdict']=='correct' and v.get('new_target_id')],
       'false_positive_task_ids':sorted({v['case'] for v in claims if v['verdict']=='false_positive'}),
       'primary_targets':len(primary), 'primary_detected':sum(v['target_detected'] for v in primary),
       'primary_missed':sum(not v['target_detected'] for v in primary),
       'expanded_targets':len(targets), 'expanded_detected':sum(v['target_detected'] for v in targets),
       'expanded_missed':sum(not v['target_detected'] for v in targets),
       'reference_positive_tasks':len({v['case'] for v in primary}),
       'missed_positive_task_ids':sorted({v['case'] for v in primary}-{v['case'] for v in primary if v['target_detected']}),
       'selected_representation_review':dict(Counter(v['selected_representation'] for v in targets)),
       'direct_relationships_retained':sum(v['direct_relationship_retained'] for v in targets),
       'retained_families':dict(families), 'selected_families':dict(selected_families),
       'tests_query_count':len(audit['tests_queries']), 'wrong_test_path_queries':len(audit['wrong_path_results']),
       'implementation_hash_mismatches':mismatches,
       'semantic_review':'Codex compared saved source, original trajectory and gold semantics. No independent human review; no new benchmark execution.',
       'limits':['Fixed targets are not exhaustive negatives. No global accuracy or true-negative rate.',
                 'Unknowns count as target misses where appropriate, never as proof of no gap.',
                 'Previous v2 combined detection and generation; this is not a controlled ablation.',
                 'No resolution-rate measurement.']}
    write_json(RUN/'summary.json', summary)
    print(json.dumps({k:summary[k] for k in ('status','completed_detections','finished_candidates','model_decisions','claim_review','unreviewed_claims','primary_detected','expanded_detected','selected_representation_review')},ensure_ascii=False))


if __name__=='__main__':
    main()
