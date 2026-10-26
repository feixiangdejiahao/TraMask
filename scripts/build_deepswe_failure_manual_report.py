"""Current entry point for the evaluation-linked revision; retain the legacy renderer."""
from collections import Counter
from datetime import datetime, timezone
from html import escape
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'research/deepswe_failure_manual_20261006'
DESTINATION = ROOT / 'docs/20261022_deepswe_failure_analysis_n211.html'
VERDICTS = {
    'confirmed_combination_gap': '发现组合验证缺口',
    'selection_problem': '已有联合测试，但执行有问题',
    'mixed_gap_and_selection': '既有组合缺口，也有测试执行问题',
    'no_confirmed_combination_gap': '本次未确认组合验证缺口',
    'insufficient_evidence': '现有证据不足',
    'pending': '尚未完成逐条审查',
}
LABELS = {
    'test': '原测试', 'tests': '原测试', 'path': '文件', 'id': '记录编号',
    'kind': '关系类型', 'relation': '具体关系', 'description': '说明',
    'checks': '原测试实际检查什么', 'operations': '操作', 'setup': '输入和初始状态',
    'assertions': '结果检查', 'examples': '原输入或期望示例', 'observations': '实际观察',
    'creation_steps': '测试建立步骤', 'definition_steps': '测试建立步骤',
    'execution_steps': '执行步骤', 'steps': '相关开发步骤', 'evidence_steps': '证据步骤',
    'step': '开发步骤', 'step_id': '开发步骤', 'result': '原运行结果',
    'status': '判断状态', 'fact': '直接观察', 'event': '开发过程',
    'missing_combination': '具体缺少什么组合', 'missing_relation': '具体缺少什么关系',
    'original_checks': '原来已经检查什么', 'why_missing': '原测试为何不足',
    'augmentation_target': '应补充哪项检查', 'oracle_basis': '期望依据',
    'patch_bug_status': '是否已证明实现错误', 'scope_boundary': '判断范围',
    'source_mechanism': '实现中的相关路径', 'detection_use': '如何帮助检测',
    'augmentation_use': '如何帮助补测', 'method_use': '如何利用这条信息',
    'use': '方法设计用途', 'evidence': '依据', 'version_note': '代码版本说明',
    'certainty': '证据强度及限制', 'qualification': '判断限制',
    'hypothesis': '原因推测', 'support_steps': '支持该判断的步骤',
    'interpretation': '解释', 'counter_evidence': '需要保留的反证',
    'final_present': '是否保留在提交补丁中', 'execution_problem': '执行问题',
    'limit': '限制', 'limits': '限制', 'scope': '本条判断范围',
    'setup_and_assertions': '输入及结果检查', 'existing_tests': '已经存在的测试',
    'test_definition_or_creation_step': '测试建立或修改步骤',
    'execution_step_and_result': '执行步骤与结果',
    'relevant_implementation_edit_steps': '相关实现修改步骤',
    'later_relevant_edits': '验证之后的相关修改',
    'final_patch_relationship': '与最终提交补丁的关系',
    'original_observation_note': '原观察的限制',
    'future_available_signal': '公开材料能提供的线索',
    'field': '原记录位置', 'quote': '原文摘录', 'excerpt': '原文摘录',
    'public_program_analysis_feature': '是否属于公开可提取材料',
    'data_flow': '数据怎样传递', 'control_flow': '分支怎样影响结果',
    'exception_flow': '错误怎样传播', 'dependency': '哪些代码相互依赖',
    'cross_test': '不同测试之间的关系', 'version': '版本关系',
    'test_selection': '哪些测试实际被选中', 'observation_strength': '结果检查能否区分错误',
    'error_feedback': '如何处理原运行反馈', 'source_location_dependency': '源码位置对应关系',
    'confirmed_joint_test_gap': '确认缺少联合检查',
    'confirmed_observation_and_sequence_gap': '确认操作顺序或结果检查不足',
    'confirmed_temporal_combination_gap': '确认缺少操作时序检查',
    'claim': '待判断的原因或事实', 'basis': '依据', 'meaning': '这条证据说明什么',
    'observation': '实际观察', 'coverage': '已经检查的范围', 'operation': '具体操作',
    'implication': '对方法设计的影响', 'method': '相关方法', 'support': '支持依据',
    'missing_observation': '仍缺少哪项结果检查', 'contract_basis': '需求或接口依据',
    'identity': '对象身份', 'causal_evidence': '开发过程中的直接依据',
    'interpretation_boundary': '需求解释的边界', 'reading_limit': '阅读范围的限制',
    'final_patch_read': '最终补丁的阅读范围', 'total_steps': '原记录的总步骤数',
    'operation_index_step_ids': '已顺序阅读的操作编号', 'public_step_index': '公开操作范围',
    'fully_expanded_relevant_steps': '已展开全文的关键步骤', 'full_steps_read': '已阅读的关键步骤',
    'final_commit': '最后提交编号', 'previous_product_commit': '此前产品代码提交编号',
    'last_product_edit_step': '最后产品代码修改步骤', 'last_test_edit_step': '最后测试修改步骤',
    'last_formal_test_edit_step': '最后正式测试修改步骤', 'final_execution_step': '最后执行步骤',
    'final_test_steps': '最终测试执行步骤', 'final_test_evidence': '最终测试证据步骤',
    'final_scope': '最终验证范围', 'configuration_limit': '执行配置的限制',
    'suite_limit': '项目测试范围的限制', 'pipeline_limit': '原命令输出的限制',
    'scope_limit': '判断范围的限制', 'historical_failures': '历史失败与后续处理',
    'history_limits': '历史结果的适用范围', 'note': '说明', 'later_steps': '后续步骤',
    'build_configuration': '编译配置与执行路径', 'generator_domain': '随机输入能表达的范围',
    'test_change_and_version': '测试内容及代码版本变化', 'requirement_and_history': '需求与开发选择',
    'history': '历史开发步骤之间的联系', 'observation_and_version': '结果检查与版本',
    'mutable_analysis_state': '分析数据的修改及共享', 'analysis_state': '分析数据的保存与修改',
    'finding': '其他需求问题', 'source_basis': '原始依据',
    'missing_evidence': '尚缺少的证据', 'problem': '原测试反馈中的问题',
    'definition_step': '测试建立步骤', 'final_source': '提交时保留的测试文件',
    'execution_audit': '实际选测与执行核对', 'final_selection_step': '最终选测步骤',
    'last_semantic_product_edit_step': '最后影响行为的产品代码修改步骤',
    'shared_resource': '不同操作共享的资源', 'dependency_and_configuration': '依赖与配置顺序',
    'cross_test_observation': '输入与结果检查之间的关系',
    'temporal_version': '验证步骤与代码版本', 'requirement_to_api': '需求与实际接口的对应关系',
    'existing_checks': '原测试已经检查什么', 'features': '需要共同出现的条件',
    'program_basis': '相关实现依据', 'facts': '直接事实',
    'same_object_or_phase': '对应的对象或执行阶段', 'observed': '原执行实际观察',
    'why_not_cartesian': '为何这些条件存在实际联系', 'confidence': '证据强度',
    'type': '类型', 'patch_relation': '测试与实现修改的联系', 'oracle': '期望依据',
    'statement': '待核对的判断', 'runtime_status': '是否已经实际运行',
    'missing_joint_observation': '缺少的联合结果检查', 'setup_assertions': '输入与结果检查',
    'detail': '具体说明', 'existing_test': '已经存在的原测试', 'effect': '实际影响',
    'combination': '需要验证的条件组合', 'separate_coverage': '原来的分开检查',
    'augmentation': '应补充的测试', 'original_tests': '原测试',
    'existing_components': '已有的操作或条件', 'contract': '需求或接口依据',
    'patch_defect_status': '是否已证明实现错误', 'existing_parts': '已有的分开检查',
    'public_basis': '公开需求依据', 'mechanism': '相关实现路径',
    'source': '原始来源', 'existing_sequence': '已出现的操作顺序',
    'separate_evidence': '原来的分开证据', 'required_observation': '需要增加的结果检查',
    'chain': '操作或数据的传递路径', 'necessary_facts': '判断所需事实',
    'causal_status': '是否已证明原因', 'why_gap': '原验证为何不足',
    'bug_status': '是否已证明实现错误', 'missing_discrimination': '原结果为何无法区分错误',
    'augmentation_implication': '对补测的要求', 'not_established': '尚未证明的判断',
    'original_separate_checks': '原来的分开检查', 'patch_defect': '实现错误的证据边界',
    'source_steps': '原始证据步骤', 'boundary': '判断边界',
    'distinguishing_behavior': '怎样区分正确与错误结果', 'uncertainty': '尚不能确定的内容',
    'source_chain': '原证据之间的联系', 'detection': '检测所需关系',
    'classification': '本次判断', 'requirement': '相关需求',
    'final_execution_steps': '最终执行步骤', 'missing_discriminator': '缺少的有效结果检查',
    'existing_joint_test': '已有联合测试', 'consequence': '实际影响',
    'final_patch_paths': '最终修改文件', 'detection_implication': '对检测的要求',
    'missing_facts': '仍缺少的事实', 'final_formal_tests': '最终正式测试',
    'public_contract': '公开需求或接口依据', 'post_commit_suite': '提交后的验证',
    'oracle_boundary': '期望依据的边界', 'available_parts': '已有的操作或条件',
    'components': '共同涉及的行为', 'defect_status': '是否已证明实现错误',
    'limitation': '证据限制',
    'binding': '操作与具体对象的绑定', 'data_dependency': '数据依赖',
    'control_and_exception_flow': '分支与错误传播', 'exception_control': '错误处理分支',
    'oracle_provenance': '期望结果的来源', 'transitive_dependency': '间接代码依赖',
    'exception_cleanup': '错误发生后的资源清理', 'event_propagation': '事件怎样传递',
    'callback_dataflow': '回调中的数据传递', 'public_dependency': '公开接口依赖',
    'version_dependency': '测试结果与代码版本的依赖',
    'exception/control flow': '错误传播与执行分支',
    'interprocedural_size_flow': '不同函数之间的大小参数传递',
    'lifecycle_state': '创建、使用与销毁时的状态', 'placement_order': '结果放置顺序',
    'observer_strength': '结果检查能否区分错误', 'control_dependency': '分支依赖',
    'data_flow_and_cross_test': '数据传递与跨测试关系',
    'noncommuting_pipeline': '改变操作顺序会改变结果', 'recursive_dependency': '递归依赖',
    'state producer/consumer': '状态写入与后续读取', 'edit-to-test dependency': '修改与测试的对应关系',
    'sensitive SQL relation': 'SQL 操作与约束的关系', 'API surface alignment': '测试与公开接口的对应关系',
    'representation_and_merge_data_flow': '数据表示与合并过程',
    'test_declaration_change': '测试定义的变化', 'fixture_path_and_execution': '测试准备与实际执行路径',
    'transaction_identity': '是否使用同一事务', 'causal_dependency': '行为之间的依赖',
    'exception_atomicity': '错误发生时能否完整撤销操作', 'representation_binding': '数据表示与对象绑定',
    'phase composition': '相邻执行阶段的关系', 'control': '执行分支',
    'data_order_and_copy': '数据顺序与复制', 'stateful_constraint': '状态与约束',
    'parser_overwrite': '解析结果被后续步骤覆盖', 'destructive_oracle_scope': '结果检查是否先改变被测状态',
    'counterfactual_input_effect': '输入能否改变目标条件的真假',
    'queue_cross_entry': '不同入口对同一队列的作用',
    'test_contract_dependency': '测试期望与接口约定的关系',
    'callback_binding': '回调与接收对象的绑定',
    'confirmed_validation_gap_static_defect_hypothesis': '确认验证缺口；实现错误只有源码推测',
    'confirmed_validation_gap_static_hypothesis': '确认验证缺口；只有源码分析',
    'confirmed_validation_gap_not_runtime_confirmed_defect': '确认验证缺口；尚未运行确认实现错误',
    'confirmed_validation_gap_static_bug_hypothesis': '确认验证缺口；实现错误只有源码推测',
    'confirmed_observation_gap': '确认结果检查不足',
    'confirmed_input_combination_gap': '确认联合输入不足',
    'confirmed_validation_gap': '确认验证缺口',
    'confirmed_missing_discriminating_combination': '确认缺少能区分错误的联合检查',
    'hypothesis': '尚待验证的原因推测',
    'source_supported_candidate': '源码支持的候选，仍需确认',
    'historical_resolved': '原记录中的问题已经处理',
    'direct_validation_scope_fact': '直接记录已验证的范围',
    'candidate_validation_gap': '潜在验证缺口，仍需确认',
    'secondary_observation_gap': '另有结果检查不足',
    'unconfirmed_observation_candidate': '潜在观察不足，仍需确认',
    'observed_joint_input_unresolved_feedback': '联合输入已经运行，结果尚未处理',
    'unconfirmed_candidate': '尚未确认的候选',
    'static only': '只有源码分析，没有新增运行',
    'static hypothesis': '根据源码提出的推测',
    'not executed': '尚无实际执行证据',
    'handled': '原记录已经处理该反馈',
    'handled_skip': '原记录已经处理跳过问题',
}
OMIT = {'trajectory_sha256', 'raw_sha256', 'step_sha256'}
FIELD_LABELS = {'message': '公开说明', 'tool_calls': '文件读写或运行命令',
                'command': '原运行命令', 'observation': '命令输出',
                'observation.results': '命令输出', 'reasoning_content': '原智能体私有推理'}


def read(path):
    return json.loads(path.read_text())


def prose(value):
    text = str(value)
    for old, new in VERDICTS.items():
        text = re.sub(r'(?<![A-Za-z_])' + old + r'(?![A-Za-z_])', new, text)
    for old, new in [
        ('trajectory', '开发记录'), ('oracle', '期望结果依据'),
        ('seed', '原测试'), ('native', '项目原测试环境'),
        ('patch', '补丁'), ('gap', '验证缺口'), ('counterexample', '错误证据'),
        ('provider', '模型接口'), ('subject', '被审查项目'),
    ]:
        text = re.sub(r'(?<![A-Za-z_])' + old + r'(?![A-Za-z_])', new, text)
    return escape(LABELS.get(text, text))


def value_html(value, literal=False):
    if value is None:
        return '<p>未记录。</p>'
    if isinstance(value, bool):
        return '<p>' + ('是。' if value else '否。') + '</p>'
    if isinstance(value, dict):
        rows = []
        for key, item in value.items():
            if key in OMIT:
                continue
            # These labels organize stored records. The neighboring explanation carries
            # the substantive claim; keep the exact label in the linked JSON, not the prose.
            if (key in {'status', 'kind', 'type'} and isinstance(item, str)
                    and item not in LABELS and item not in VERDICTS
                    and re.fullmatch(r'[A-Za-z0-9_ /+()\-]{1,120}', item)):
                continue
            label = LABELS.get(key, '补充说明')
            field_name = item.split('.', 1)[0] if key == 'field' and isinstance(item, str) else None
            if field_name in FIELD_LABELS:
                item = FIELD_LABELS[field_name]
                rows.append('<div class="fact"><dt>' + escape(label) + '</dt><dd><p>'
                            + escape(item) + '</p></dd></div>')
                continue
            rows.append('<div class="fact"><dt>' + escape(label) + '</dt><dd>'
                        + value_html(item, literal or key in {'quote', 'excerpt', 'path', 'field'}) + '</dd></div>')
        return '<dl>' + ''.join(rows) + '</dl>'
    if isinstance(value, list):
        if not value:
            return '<p>本条审查未记录此类情况。</p>'
        if all(isinstance(item, (int, float)) for item in value):
            return '<p>' + escape('、'.join(str(item) for item in value)) + '</p>'
        return '<ol>' + ''.join('<li>' + value_html(item, literal) + '</li>' for item in value) + '</ol>'
    if literal:
        return '<pre>' + escape(str(value)) + '</pre>'
    return '<p>' + prose(value) + '</p>'


def section(label, value):
    return '<div class="section"><p class="section-label">' + escape(label) + '</p>' + value_html(value) + '</div>'


def synthesis_html(data, expected_ids):
    """Explain the method basis; keep source identifiers only in optional evidence links."""
    blocks = ['<p class="label">全量审查对方法设计的启示</p>']
    for paragraph in data.get('summary_paragraphs', []):
        blocks.append('<p>' + prose(paragraph) + '</p>')
    for item in data.get('design_basis', []):
        blocks.append('<p><strong>' + escape(item['title']) + '</strong></p>')
        explanation = item.get('explanation', [])
        for paragraph in explanation if isinstance(explanation, list) else [explanation]:
            blocks.append('<p>' + prose(paragraph) + '</p>')
        blocks.append('<div class="table"><table><thead><tr><th>实际案例</th><th>原测试及不足</th>'
                      '<th>程序和开发记录能提供什么</th><th>判断限制</th></tr></thead><tbody>')
        for example in item.get('examples', []):
            trial = example['trial']
            assert trial in expected_ids
            primary = read(STUDY / 'trials' / (trial + '.json'))
            task = example.get('task_description', primary['task'])
            grouped_steps = example.get('steps', [])
            if isinstance(grouped_steps, dict):
                steps = '；'.join(label.replace('helper', '辅助函数').replace('observer', '查询结果').replace('core', '核心模块')
                                 + '：' + '、'.join(str(step) for step in ids)
                                 for label, ids in grouped_steps.items())
            else:
                steps = '、'.join(str(step) for step in grouped_steps)
            cells = [
                '<a href="#trial-' + escape(trial) + '">' + escape(task) + '</a>'
                + ('<p class="small">开发步骤：' + escape(steps) + '。</p>' if steps else ''),
                '<p>' + prose(example.get('original_checks', '')) + '</p><p>'
                + prose(example.get('missing_relation', '')) + '</p>',
                '<p>' + prose(example.get('program_signal', '')) + '</p><p>'
                + prose(example.get('trajectory_signal', '')) + '</p>',
                '<p>需求依据：' + prose(example.get('contract_basis', '')) + '</p><p>'
                + prose(example.get('qualification', '')) + '</p><p>已有有效检查：'
                + prose(example.get('counter_evidence', '')) + '</p>',
            ]
            blocks.append('<tr>' + ''.join('<td>' + cell + '</td>' for cell in cells) + '</tr>')
        blocks.append('</tbody></table></div>')
    for title, key in [('建议采用的问题抽象', 'proposed_abstraction'),
                       ('学术新意：目前能支持什么', 'novelty_assessment')]:
        blocks.append('<p class="label">' + title + '</p>')
        for paragraph in data.get(key, []):
            blocks.append('<p>' + prose(paragraph) + '</p>')
    blocks.append('<p class="label">下一轮小规模实验应检查什么</p>')
    blocks.append('<p>以下是实验建议，本次没有执行。它们先检查材料提取和补测目标确认，'
                  '不要求插件形式，也不评价后续补丁修复。</p>')
    for item in data.get('pilot_design', []):
        blocks.append('<p><strong>' + escape(item['title']) + '</strong></p>')
        for label, key in [('输入', 'input'), ('操作', 'procedure'),
                           ('评价', 'measure'), ('结果怎样解释', 'interpretation')]:
            content = item.get(key, '')
            paragraphs = content if isinstance(content, list) else [content]
            for paragraph in paragraphs:
                blocks.append('<p>' + label + '：' + prose(paragraph) + '</p>')
    blocks.append('<p class="label">综合结论的适用范围</p>')
    for paragraph in data.get('limits', []):
        blocks.append('<p>' + prose(paragraph) + '</p>')
    return ''.join(blocks)


def render_historical():
    cohort = read(STUDY / 'cohort_audit.json')
    acquisition = read(ROOT / 'results/deepswe_failure_manual_20261006/acquisition_summary.json')
    checkpoint = read(STUDY / 'evidence_checkpoint.json')
    cross_path = STUDY / 'cross_review/evidence_checkpoint.json'
    cross_checkpoint = read(cross_path) if cross_path.exists() else {'accepted_reports': []}
    cross_checked = {row['trial']: row for row in cross_checkpoint['accepted_reports']}
    expected = cohort['trials']
    assert len(expected) == 211 and acquisition['ready'] == acquisition['expected'] == 211
    expected_ids = {row['trial_name'] for row in expected}
    checked = {row['trial']: row for row in checkpoint['checked_reports']}
    reports, cards, tally = {}, [], Counter()
    for path in sorted((STUDY / 'trials').glob('*.json')):
        assert path.stem in expected_ids, f'outside frozen cohort: {path}'
        try:
            report = read(path)
        except ValueError:
            continue  # The reviewer may be writing this file. It remains pending.
        reports[path.stem] = (report, hashlib.sha256(path.read_bytes()).hexdigest())
    checked_count = 0
    cross_count = 0
    for ordinal, row in enumerate(expected, 1):
        trial = row['trial_name']
        indexed_language = row['task_metadata']['language']
        language = indexed_language
        repository = row['task_metadata']['repository']
        record = reports.get(trial)
        verdict = record[0]['verdict'] if record else 'pending'
        tally[verdict] += 1
        evidence_ok = bool(record and trial in checked and checked[trial]['report_sha256'] == record[1])
        checked_count += int(evidence_ok)
        cross_ok = bool(record and trial in cross_checked
                        and cross_checked[trial]['primary_report_sha256'] == record[1])
        cross_count += int(cross_ok)
        raw = '../results/deepswe_failure_manual_20261006/trials/' + trial
        search_text = ' '.join([trial, row['task_name'], language, repository, VERDICTS[verdict]])
        if record:
            report = record[0]
            language = report.get('observed_implementation_language', report.get('language', indexed_language))
            if language.lower() != indexed_language.lower():
                search_text += ' ' + language
            search_text += ' ' + json.dumps(report.get('combination_gaps'), ensure_ascii=False)
            detail = '<p>' + prose(report['verdict_reason']) + '</p>'
            detail += section('问题一：原测试实际检查什么', report['validation_inventory'])
            detail += section('问题一：具体缺少什么组合，以及期望依据', report['combination_gaps'])
            detail += section('问题一：已有联合测试的执行问题', report['selection_problems'])
            if report.get('validation_feedback_problems'):
                detail += section('已经运行的输入：反馈或期望仍有什么问题', report['validation_feedback_problems'])
            if report.get('candidate_unconfirmed_relations'):
                detail += section('其他关系：现有证据尚不足以确认', report['candidate_unconfirmed_relations'])
            if report.get('other_requirement_findings'):
                detail += section('其他需求问题：不归为组合缺口', report['other_requirement_findings'])
            detail += section('问题二：哪些程序关系可以帮助检测和补测', report['program_relations'])
            detail += section('问题三：相关测试建立前后的开发过程', report['trajectory_sequence'])
            detail += section('问题三：直接证据摘录', report['direct_evidence'])
            detail += section('问题三：原因推测及其限制', report['causal_hypotheses'])
            detail += section('不能忽略的反证', report['counter_evidence'])
            detail += section('测试证据属于哪个代码版本', report['version_audit'])
            detail += section('这条记录对方法设计的启示', report['method_design_implications'])
            detail += section('本条审查的边界', report['limits'])
            detail += '<p class="small">记录完整性检查：' + ('已核对文件、步骤和原文摘录。' if evidence_ok else '等待更新或修正。') + '</p>'
            detail += '<p class="small">第二位分析助手复核：' + ('已检查原始证据与本条判断。' if cross_ok else '尚未完成。') + '</p>'
            if cross_ok:
                detail += '<p class="small"><a href="../research/deepswe_failure_manual_20261006/cross_review/trials/' + escape(trial) + '.json">本条第二次审阅的范围、逐项判断和修正</a>。</p>'
            detail += '<details><summary>阅读范围与文件核验记录</summary>'
            detail += value_html(report['timeline_read_coverage'])
            detail += '<p><a href="../research/deepswe_failure_manual_20261006/trials/' + escape(trial) + '.json">本条完整审查记录</a>。</p></details>'
        else:
            detail = '<p>原始开发记录和最终补丁已取得。本条尚未完成逐条审查。失败标签本身不能说明存在组合缺口。</p>'
        instruction = (ROOT / 'results/deepswe_failure_manual_20261006/trials' / trial / 'instruction.md').read_text()
        detail = ('<details><summary>本次开发任务的原始要求</summary><p>以下保留公开任务原文。'
                  '它用于核对测试期望，不是隐藏评价测试或参考实现。</p><pre>'
                  + escape(instruction) + '</pre></details>' + detail)
        detail += '<p class="small">原始材料：<a href="' + escape(raw) + '/instruction.md">任务要求</a> · <a href="' + escape(raw) + '/trajectory.json">开发记录</a> · <a href="' + escape(raw) + '/model.patch">最终补丁</a>。</p>'
        language_note = '。实现语言：' + escape(language)
        if language.lower() != indexed_language.lower():
            language_note += '。公开索引标记为 ' + escape(indexed_language) + '，与实际源码不一致'
        elif not record:
            language_note = '。公开索引语言：' + escape(indexed_language)
        cards.append('<details class="trial" id="trial-' + escape(trial) + '" data-status="' + escape(verdict)
                     + '" data-search="' + escape(search_text.lower(), quote=True) + '"><summary><span>'
                     + str(ordinal) + '. ' + escape(trial) + '</span><span class="badge">' + escape(VERDICTS[verdict])
                     + '</span></summary><p class="small">项目：' + escape(repository) + language_note
                     + '。任务编号：' + escape(row['task_name']) + '。</p>' + detail + '</details>')
    progress = len(reports)
    synthesis_path = STUDY / 'method_synthesis.json'
    complete = progress == checked_count == cross_count == 211 and synthesis_path.exists()
    aggregate = synthesis_html(read(synthesis_path), expected_ids) if synthesis_path.exists() else ''
    page_title = 'DeepSWE 全部失败记录：验证缺口与方法设计依据' if complete else 'DeepSWE 失败记录逐条分析：全量审查进度'
    completion_note = ('全部 211 条已完成逐条审查和第二次原始证据复核。下文给出定性归纳及每条依据。'
                       '这些结果不是自动检测器的性能。' if complete else
                       '本页保留全部 211 条记录。未完成的记录明确标出。现有结果只是审查进度，'
                       '不是全量结论，也不是组合缺口检测器的性能。')
    counts = ''.join('<tr><td>' + escape(VERDICTS[key]) + '</td><td>' + str(tally[key]) + '</td></tr>'
                     for key in VERDICTS)
    choices = ''.join('<option value="' + escape(key) + '">' + escape(label) + '</option>' for key, label in VERDICTS.items())
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{page_title}</title><style>
body{{margin:0;background:#f4f6f8;color:#20303d;font:16px/1.8 system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}}main{{max-width:1180px;margin:24px auto;padding:32px 40px;background:white}}
h1{{font-size:1.7rem;line-height:1.4}}p{{margin:11px 0}}.lead{{padding:12px 18px;background:#edf6fa;border-left:4px solid #17647d}}a{{color:#145e83;overflow-wrap:anywhere}}
.small{{font-size:.88rem;color:#526170}}.label{{font-size:1.16rem;font-weight:650;margin-top:28px}}.table{{overflow:auto}}table{{border-collapse:collapse;margin:18px 0}}td,th{{border:1px solid #d9e1e7;padding:8px 14px;text-align:left;vertical-align:top}}
.controls{{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}}input,select{{font:inherit;padding:8px;max-width:100%}}input{{flex:1;min-width:230px}}.trial{{border:1px solid #d9e1e7;border-radius:5px;padding:12px 16px;margin:12px 0}}
summary{{cursor:pointer;font-weight:600;overflow-wrap:anywhere}}.badge{{display:inline-block;font-size:.85rem;padding:2px 9px;background:#edf2f6;border-radius:5px;margin-left:10px}}.section{{border-top:1px solid #d9e1e7;margin-top:20px;padding-top:6px}}
.section-label{{font-weight:650}}dl{{margin:8px 0}}.fact{{display:grid;grid-template-columns:minmax(100px,190px) 1fr;gap:14px;padding:7px 0}}dt{{color:#526170}}dd{{margin:0;min-width:0}}dd p{{margin:0}}li{{margin:9px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f7;padding:10px;font-size:.86rem}}
@media(max-width:700px){{main{{margin:0;padding:20px 16px}}.fact{{display:block}}dt{{font-weight:600;margin:5px 0}}.badge{{margin-left:0}}}}[hidden]{{display:none!important}}
</style></head><body><main><h1>{page_title}</h1>
<p class="small">更新时间：{now}。本次工作只读取原始需求、开发记录和提交补丁。没有生成新测试，也没有继续此前的模型实验。</p>
<div class="lead"><p><strong>当前已保存 {progress}/211 条逐条审查。</strong>其中 {checked_count} 条通过文件、步骤和摘录完整性检查。仍有 {211-progress} 条未完成。该检查不能独立确认语义判断正确。</p>
<p>另有 {cross_count} 条完成第二位分析助手的原始证据复核。复核核对输入、结果检查、需求依据、实际执行和代码版本。它仍是 AI 分析助手的非盲审查，不是独立真人评审。</p>
<p>{completion_note}</p></div>
<p class="label">研究问题和数据范围</p>
<p>开发智能体可能分别测试两个行为，却漏掉它们共同发生时的结果。也可能已经生成联合测试，但没有运行它。我们逐条检查这些情况，为后续程序分析和测试补充寻找依据。</p>
<p>我们使用 DeepSWE v1.1 公开索引，保留模型名为 deepseek-v4-flash 且结果为 fail 的全部记录。该模型共有 452 次运行，241 次成功，211 次失败。失败记录涉及 90 个任务和 75 个项目。同一任务的不同运行单独审查。</p>
<p>全部 211 份原始开发记录和最终补丁已取得。旧 pilot 案例编号和既有研究结论不决定本次标签。公开失败标签只说明评价未通过，不能证明存在组合缺口，更不能确定失败原因。</p>
<p>原开发记录均由 mini-swe-agent 使用 DeepSeek-v4-flash 产生。本次 AI 分析助手手动阅读这些已有记录，并保存逐条判断。本次没有请 DeepSeek 重新生成测试。审查不是独立真人盲评。</p>
<p>案例卡片优先报告实际源码语言。已发现一条 HTTPX 记录的公开索引标为 TypeScript，实际实现为 Python。卡片保留两种信息；固定数据范围和索引原文没有改动。</p>
<p class="label">本文的名称和计数单位</p>
<table><thead><tr><th>名称</th><th>具体含义</th></tr></thead><tbody>
<tr><td>任务</td><td>一项开发需求及其基础代码。同一任务可以有多次智能体运行。</td></tr>
<tr><td>运行记录</td><td>智能体尝试完成任务的一次过程，包含消息、文件读写、执行反馈和提交补丁。本文共检查 211 次失败运行。</td></tr>
<tr><td>原验证测试</td><td>原智能体编写、修改或选择的仓库测试与临时脚本。本次没有生成替代测试。</td></tr>
<tr><td>联合检查</td><td>让相关条件或操作共同作用于需要验证的对象或数据结构，并检查其共同结果。</td></tr>
<tr><td>结果观察</td><td>读取或打印错误码、输出内容、对象身份或副作用。观察说明看到了什么，单独打印不保证能自动判错。</td></tr>
<tr><td>结果检查</td><td>依据需求比较实际结果与期望结果。测试用断言自动比较；临时脚本的输出也可能需要审阅者判断。</td></tr>
<tr><td>接口约定</td><td>公开需求、接口文档或项目已有规则对合法输入与结果的要求。它用于判断测试期望是否有依据。</td></tr>
<tr><td>契约</td><td>本文对公开需求或接口约定的简称。“契约观察”指检查这些要求规定的结果。</td></tr>
<tr><td>判别能力</td><td>如果目标行为违反要求，测试输入与结果检查能否让测试结果变化。例如，只查行数无法区分姓名约束是否生效。</td></tr>
<tr><td>程序关系</td><td>数据传递、分支条件、错误传播、共享对象、调用依赖或操作顺序。这些联系可以帮助选择补测目标。</td></tr>
<tr><td>代码版本</td><td>某次测试运行时实际使用的产品代码和测试内容。后续编辑可能使旧结果不再适用。</td></tr>
<tr><td>测试补充</td><td>保留原测试，增加缺少的有效检查。已有有效测试未运行时，应先处理执行问题。</td></tr>
</tbody></table>
<p>逐条记录保留具体函数名和文件名，便于核对源码。这些名称不是新算法术语。卡片省略只用于记录分组的未翻译英文标签；链接的完整记录仍保留原字段。展开卡片中的原任务要求，即可了解该项目要实现的行为。</p>
<p class="label">逐条如何判断</p>
<p>原验证测试包括仓库测试和临时验证脚本。审查先按顺序阅读公开操作，再展开相关代码阅读、测试建立、修改和运行窗口。审查同时读取最终补丁。大段无关输出并非全部全文阅读；每条记录单独说明阅读范围。</p>
<p>组合验证缺口必须对应任务需求或已有接口约定。审查说明原测试检查什么，缺少哪些条件、操作或结果，以及新检查应观察哪个对象。某项补测可能通过；验证缺口不等于实现错误。</p>
<p>已经存在且能区分错误的联合测试，若未被选中、未到达目标语句或使用错误版本，归为测试执行问题。已经运行的联合输入，若结果不符合要求却未被处理，另行记录反馈或期望问题。</p>
<p>测试同时出现两个函数，不代表已经检查交互。审查还需要确认对象身份、操作顺序和结果检查。例如，更新姓名不会改变行数；只检查行数就不能验证姓名约束。</p>
<p>审查分别记录直接事实和原因推测。私有推理若被阅读，只用于回顾分析。它不能当作所有智能体都能提供的程序分析输入。运行反馈需要对应当时的代码版本；旧失败不能自动套用到最终补丁。</p>
<p>每条记录回答三个问题：具体缺少什么联合检查；哪些数据、分支和依赖关系能帮助检测及补测；测试建立前后的开发过程提供什么线索。记录也保留已有联合验证及成功利用反馈的反证。</p>
<p class="label">逐条审查结果</p><table><thead><tr><th>本次审查判断</th><th>运行记录数</th></tr></thead><tbody>{counts}</tbody></table>
<p>各行互不重叠。{str(tally['confirmed_combination_gap'] + tally['mixed_gap_and_selection']) + '/211 条记录至少报告一项已确认组合验证缺口。其中 ' + str(tally['confirmed_combination_gap']) + ' 条归为缺口类，' + str(tally['mixed_gap_and_selection']) + ' 条同时报告测试执行问题。' if complete else '这些数字随审查更新。'}
它们不是独立任务数量，也不是实现错误数量。同一任务的多次运行可能出现相似缺口。本次只选择公开失败记录，不能据此估计全部智能体运行中的缺口发生率。</p>
<p>“本次未确认”只说明已阅读材料没有支持一项具体缺口。它不能证明测试充分。候选关系若缺少明确需求依据，仍单列保留，不计入该条的确定缺口。</p>
<p>候选关系、静态实现风险和已经运行的反馈问题，不单独增加上述组合缺口记录数。同一条记录可以另有这些情况。因此，表格不是所有验证问题的完整分类。</p>
{aggregate}
<p class="label">全部记录</p><p>可按项目、任务、语言、编号或缺口内容检索。展开一条记录即可查看三个问题、直接证据、反证和版本说明。</p>
<div class="controls"><input id="query" type="search" aria-label="检索记录" placeholder="检索项目、任务或缺口"><select id="status" aria-label="按审查状态筛选"><option value="">所有审查状态</option>{choices}</select></div>
<p id="shown" class="small">显示 211 条记录。</p>{''.join(cards)}
<p class="label">复核材料</p><p><a href="../research/deepswe_failure_manual_20261006/study_protocol.json">全量审查要求和分工</a> · <a href="../research/deepswe_failure_manual_20261006/cohort_audit.json">固定数据范围与来源核对</a> · <a href="../results/deepswe_failure_manual_20261006/acquisition_summary.json">全部原始文件取得情况</a> · <a href="../research/deepswe_failure_manual_20261006/evidence_checkpoint.json">逐条完整性检查结果</a>。</p>
<p class="small">数据范围核对文件记录的是取得原始文件之前的状态。原始文件是否齐全，以后续取得情况文件为准。完整性检查只核对文件身份、步骤序列和摘录，不替代语义复核。</p>
<p class="small"><a href="../research/deepswe_failure_manual_20261006/cross_review/protocol.json">第二次审阅要求</a> · <a href="../research/deepswe_failure_manual_20261006/cross_review/evidence_checkpoint.json">第二次审阅回执核对</a>。回执核对只确认报告身份、来源与审阅记录齐全；它不会自动判断结论正确。</p>
{'<p class="small"><a href="../research/deepswe_failure_manual_20261006/method_synthesis.json">跨案例的方法设计依据</a> · <a href="../research/deepswe_failure_manual_20261006/completion_audit.json">全量工作完成核对</a>。</p>' if complete else ''}
<p class="small">本文按短句、主动语态和单段单主题组织。中文不适用 ASD-STE100 的英语受控词表，本文不声称正式符合该英语标准。</p>
</main><script>
const query=document.getElementById('query'), status=document.getElementById('status'), cards=[...document.querySelectorAll('.trial')];
function filter(){{const words=query.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);let count=0;for(const card of cards){{const show=(!status.value||card.dataset.status===status.value)&&words.every(word=>card.dataset.search.includes(word));card.hidden=!show;if(show)count++;}}document.getElementById('shown').textContent='显示 '+count+' / 211 条记录。';}}
query.addEventListener('input',filter);status.addEventListener('change',filter);
function openLinkedTrial(){{const hash=decodeURIComponent(location.hash.slice(1));if(!hash)return;const target=document.getElementById(hash);if(target&&target.tagName==='DETAILS'){{if(target.hidden){{query.value='';status.value='';filter();}}target.open=true;target.scrollIntoView();}}}}
window.addEventListener('hashchange',openLinkedTrial);openLinkedTrial();
</script></body></html>'''
    DESTINATION.write_text(html)
    print(json.dumps({'report': str(DESTINATION), 'all_trials': 211, 'reports_saved': progress,
                      'evidence_checked': checked_count, 'semantic_second_reviews': cross_count,
                      'pending': 211-progress}, ensure_ascii=False))


def run():
    """Render the current revision from the manually authored records."""
    from build_deepswe_counterfactual_report import run as render_current
    render_current()


if __name__ == '__main__':
    run()
