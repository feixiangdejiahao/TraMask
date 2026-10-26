"""Audit the completed pilot's saved inputs and interactions. No model calls."""
from collections import Counter
from html import escape
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from scripts.run_augmentation_pilot30_v2 import RUN, read, receipt, check_protocol
from augmentation.pipeline import write_json

OUT = RUN / "diagnosis_v1"
REPORT = ROOT / "docs/archive/20261009_behavioral_gap_diagnosis_v02_n30.html"


def candidate_stream(path):
    """Read one candidate at a time from the frozen, indented JSON artifact."""
    active, buffer = False, []
    with path.open() as stream:
        for line in stream:
            if not active:
                if line.rstrip() == '  "candidates": [':
                    active = True
                continue
            if line.rstrip() == "  ],":
                return
            if line.startswith("    {"):
                buffer = [line]
            elif buffer:
                buffer.append(line)
            if buffer and line.rstrip() in {"    },", "    }"}:
                yield json.loads("".join(buffer).rstrip().removesuffix(","))
                buffer = []


def audit():
    check_protocol()
    summary = read(RUN / "summary.json")
    cases = {c["id"]: c for c in read(RUN / "cases.json")}
    inputs, queries, actions, results = [], [], [], []
    dimension_total, dimension_known = Counter(), Counter()
    for path in sorted(RUN.glob("cases/*/agent/*/round1/request.json")):
        request = read(path)
        evidence = json.loads(request["messages"][-1]["content"])["evidence"]
        candidate = evidence["analysis_candidate"]
        kinds = {d["id"]: d["kind"] for d in candidate["conditions"]}
        total, known = Counter(), Counter()
        for row in evidence["test_scope"]:
            for key, value in row["conditions"].items():
                kind = kinds[key]
                total[kind] += 1
                known[kind] += bool(value.get("known"))
        dimension_total.update(total)
        dimension_known.update(known)
        inputs.append({"case": path.parts[-5], "candidate": candidate["id"],
                       "family": candidate["family"], "dimensions": candidate["condition_dimensions"],
                       "scope": evidence["input_scope"], "condition_values": dict(total),
                       "known_condition_values": dict(known),
                       "included_tests": len(evidence["related_tests"]),
                       "included_excerpts": len(evidence["source_excerpts"]),
                       "append_module_scope_rule_present": "legal module scope" in request["messages"][0]["content"],
                       "request": receipt(path)})
    for path in sorted(RUN.glob("cases/*/agent/*/round*/action.json")):
        action = read(path)
        actions.append(action)
        query = action.get("query", {})
        if action["action"] != "inspect" or query["kind"] != "tests" or "path" not in query:
            continue
        feedback_path = path.with_name("feedback.json")
        if not feedback_path.exists():
            continue
        feedback = read(feedback_path)
        if "tests" not in feedback:
            continue
        requested = query["path"].rstrip("/")
        paths = [t["span"]["path"] for t in feedback["tests"]]
        case = path.parts[-5]
        queries.append({"case": case, "requested_path": requested, "query": query,
                        "path_exists": (Path(cases[case]["repository"]) / requested).exists(),
                        "returned_paths": paths,
                        "contains_requested_path": any(p == requested or p.startswith(requested + "/") for p in paths),
                        "action": receipt(path), "feedback": receipt(feedback_path)})
    for path in sorted(RUN.glob("cases/*/agent/*/result.json")):
        result = read(path)
        results.append({"case": path.parts[-4], "candidate": result["candidate_id"],
                        "status": result["status"], "proposals": len(result["proposals"]),
                        "result": receipt(path)})
    # Save a compact, exact example where extraction succeeded but selection omitted it.
    selected = read(RUN / "cases/T10/agent/protocol.json")["selected_candidates"]
    selection_example = None
    for rank, c in enumerate(candidate_stream(RUN / "cases/T10/prepared.json"), 1):
        if c["id"] == "joint_599164e23e1cea9226e3":
            selection_example = {"case": "T10", "candidate": c["id"], "rank_in_prepared_list": rank,
                                 "selected": c["id"] in selected, "family": c["family"],
                                 "conditions": c["behavior"]["conditions"], "function_ids": c["function_ids"],
                                 "seed_operations": [n for n in c["behavior"]["operations"]
                                                     if n["id"] in c["evidence"]["source_operations"]],
                                 "selection_protocol": receipt(RUN / "cases/T10/agent/protocol.json")}
            break
    assert selection_example and not selection_example["selected"]
    assert len(inputs) == len(results) == 240
    assert sum(dimension_total.values()) == 2971
    assert sum(dimension_known.values()) == 63
    feedback_examples = []
    for case, candidate, message in [("T21", "joint_0090c635589afbc206d2", "world is not defined"),
                                     ("T14", "candidate_341e3036fd084d25e0a6", "undefined: time")]:
        path = RUN / "cases" / case / "agent" / candidate / "round3/feedback.json"
        feedback_examples.append({"case": case, "actual_error_message": message,
                                  "message_in_model_feedback": message in path.read_text(),
                                  "feedback": receipt(path)})
    stats = {
        "version": "pilot30-v2-diagnosis.v1", "scope": "Saved pilot records and implementation; no intervention or new execution",
        "new_model_calls": 0, "new_subject_executions": 0,
        "candidates_retained": summary["extraction"]["total_candidates"], "candidates_reviewed": len(inputs),
        "initial_inputs_truncated": sum(r["scope"]["presentation_truncated"] for r in inputs),
        "initial_inputs_with_one_test": sum(r["included_tests"] == 1 for r in inputs),
        "initial_inputs_without_test": sum(r["included_tests"] == 0 for r in inputs),
        "initial_inputs_with_one_excerpt": sum(r["included_excerpts"] == 1 for r in inputs),
        "prompts_retaining_original_append_scope_rule": sum(r["append_module_scope_rule_present"] for r in inputs),
        "condition_value_records": dict(dimension_total), "known_condition_value_records": dict(dimension_known),
        "inspection_kinds": dict(Counter(a["query"]["kind"] for a in actions if a["action"] == "inspect")),
        "test_queries_with_ignored_path": len(queries),
        "test_queries_with_existing_path": sum(q["path_exists"] for q in queries),
        "existing_path_queries_without_matching_tests": sum(q["path_exists"] and not q["contains_requested_path"] for q in queries),
        "candidates_that_proposed_tests": sum(r["proposals"] > 0 for r in results),
        "candidates_that_proposed_twice": sum(r["proposals"] > 1 for r in results),
        "accepted_proposals_including_withdrawn": sum(r["proposals"] for r in results),
        "final_claims": summary["final_claim_count"], "last_round_final_claims": summary["final_claims_at_last_round"],
        "conditional_generation_success_rate": None,
        "missing_failure_detail_examples": feedback_examples,
        "interpretation": "The 1/30 end-to-end outcome is not generation accuracy with a correct target supplied. Counts of input records are not independent tests or causal effect estimates.",
        "pilot_summary": receipt(RUN / "summary.json"),
        "implementation": [receipt(ROOT / "src/augmentation" / name) for name in
                           ("pipeline.py", "agent.py", "joint.py", "scopes.py", "history.py", "presentation.py")],
    }
    write_json(OUT / "inputs.json", inputs)
    write_json(OUT / "test_queries.json", queries)
    write_json(OUT / "candidate_results.json", results)
    write_json(OUT / "selection_example.json", selection_example)
    write_json(OUT / "summary.json", stats)
    render(stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def link(path, label):
    return '<a href="' + escape(os.path.relpath(path, REPORT.parent), quote=True) + '">' + escape(label) + '</a>'


def trace(case, candidate, round_number, filename, label):
    return link(RUN / "cases" / case / "agent" / candidate / ("round" + str(round_number)) / filename, label)


def table(headers, rows):
    return '<div class="scroll"><table><tr>' + ''.join('<th>'+escape(h)+'</th>' for h in headers) + '</tr>' + ''.join('<tr>'+''.join('<td>'+escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows) + '</table></div>'


def render(s):
    p = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>改进算法的 30 个任务：检测与补测失败原因</title>
<style>body{font:16px/1.8 system-ui,sans-serif;max-width:1100px;margin:35px auto;padding:0 22px;background:#fafbfd;color:#192832}h1{font-size:28px}h2{font-size:23px}a{color:#08628e}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{border:1px solid #dce3e8;padding:10px;vertical-align:top;text-align:left}th{background:#eaf1f6}p{max-width:1040px}code{overflow-wrap:anywhere}</style>
<h1>检测与补测为何失败</h1><p>2026-10-09。范围：改进算法的 30 个任务。分析只读取已保存输入、模型动作、测试和执行结果。没有新增模型调用或被测程序执行。</p>
<p>主要问题是：算法没有稳定地把相关程序关系转成具体的错误触发条件；模型识别出的条件也没有稳定保留到最终测试。输入删减、查询接口和三轮预算进一步放大了这些问题。</p>''']
    p.append('<h2>先分清两个评价对象</h2><p>正确检测要求指出能揭示原补丁错误的组合。正确补测还要求生成代码实际构造该组合，并使用有依据的断言。gold 是 benchmark 的参考补丁，只用于离线评价。</p>')
    p.append('<p>本轮正确检测和正确补测均为 1/30，来自 T08 新目标。原有 23 个固定目标均未在最终输出中命中。但本轮没有把 23 个正确目标逐项提供给生成阶段。因此，1/30 是整条流程的效果，不能解释为“给定正确缺口后，模型只有 1/30 能写对测试”。</p>')
    p.append('<p>61 项最终建议生成了可通过原补丁的补充测试。其主要问题是未揭示所提组合中的原补丁错误。另有 13 项存在测试自身错误。不能把这两类失败全部归为代码生成能力差。</p>')
    p.append('<p>T17 和 T24 的中间动作已经出现关键线索。最终输出仍漏掉目标。下文把这种情况记为判断未完成或目标被更换，不把它说成整个过程从未理解缺口。</p>')
    p.append('<h2>检测原因一：目标仍偏向补充覆盖</h2><p>当前提示要求模型判断缺少的验证，并写补充测试。它没有要求模型解释当前实现在哪个具体组合下可能违背需求。缺少覆盖与存在错误之间仍缺一层判断。</p>')
    p.append('<p>这个设计能生成有用的回归测试，却容易把调用预算用在已经正确实现的组合上。61 项通过原补丁的建议说明该偏差。通过结果只能否定该项错误假设，不能证明整个任务没有其他错误。</p>')
    p.append('<p>检测目标应同时保留三点：需求要求什么；当前代码在哪个条件下可能做错；现有测试为何没有区分这两种行为。这里只需一条短的可检验假设，不需要模型编写完整规则体系。</p>')
    p.append('<h2>检测原因二：已提取的有效方向未必送入模型</h2><p>程序保留 6,714 个候选，只选择 240 个。选择器先取每类关系的第一个候选，再补足每任务 8 个。相同优先级内的标识顺序会影响选择。选择器没有根据某次测试的结果重新安排其他候选。</p>')
    p.append('<p>T10 已经提取到缓存预热、提前退出和结果输出的联系。一个相关候选位于列表第 12 位，包含 main 和 output_results，但没有被选中。实际选择仍主要集中在缓存内部读写。这是提取后选择失败，不能继续沿用旧版本“没有提取到该联系”的解释。</p>')
    p.append('<p>'+link(OUT/'selection_example.json','T10 的未选候选')+' · '+link(ROOT/'src/augmentation/agent.py','固定候选选择与逐候选处理')+'</p>')
    p.append('<h2>检测原因三：条件名称没有充分绑定到测试行为</h2><p>程序能够提出“共享存储”和“后续观察阶段”。但 dimension_value 只计算部分布尔条件、字段存在性和简单值类别。它没有计算共享关系和观察阶段。对这两类维度，原测试范围仍返回未知。</p>')
    kind_names = {'predicate':'布尔条件','presence':'字段或位置是否存在','value_category':'读取值的类别','phase':'观察阶段','sharing':'对象共享关系'}
    p.append(table(['首轮输入中的条件类型','取值记录数','程序能确定的记录数'], [[kind_names[k],s['condition_value_records'][k],s['known_condition_value_records'].get(k,0)] for k in s['condition_value_records']]))
    p.append('<p>这里统计模型实际收到的测试范围记录。共 2,971 个条件取值记录，只有 63 个有确定值。记录可以来自同一测试的不同路径；它不是独立测试数量。未知是合理的保守结论，但模型需要重新完成大部分条件推导。</p>')
    p.append('<p>T17 的一个“存在性”候选绑定到了语法解析器的 x[0]。它读取的是左侧表达式列表，并不是脚本运行时的数组或 map。模型先用两轮识别这个偏差，第三轮才转向“位置存在但值为 undefined”。</p>')
    p.append('<p>程序应保留条件所作用的具体对象、值来源和观察时点。对解释器，应分清宿主语言的数据结构与被执行脚本的值。仅给出“存在/缺失”或“写入后/消费后”名称，仍把关键工作交给了模型。</p>')
    p.append('<p>'+link(ROOT/'src/augmentation/scopes.py','条件取值和测试范围实现')+' · '+trace('T17','joint_0306f8ab26bc7193f023',3,'action.json','T17 第三轮已识别关键线索')+'</p>')
    p.append('<h2>检测原因四：输入删减与查询接口削弱了已有信息</h2><p>240 份首轮输入中，202 份发生展示删减；108 份只保留一条测试正文。155 份只保留一个源码片段。相关测试可以很多，但直接可读的材料很少。</p>')
    p.append('<p>展示函数超出长度时，先删除源码片段，再删除历史和测试正文。它保留了较多程序关系和测试范围记录。很多记录仍为未知，因此输入长度并没有转化成同等数量的可用证据。</p>')
    p.append('<p>T24 的相关测试列表有 212 项，首轮只提供一项 formatter/list 测试。它检查 defined 选项，与当前 requiredIf 的默认解析模式不直接对应。模型因此继续查源码，而没有直接比较最相关的原测试与缺失条件。</p>')
    p.append('<p>查询接口还有明确缺陷。113 次测试查询中，99 次带有 path 参数。函数却只使用 test_ids 或候选列表分页，忽略 path 和行号。97 次请求指向实际存在的路径，其中 61 次返回结果没有该路径内的测试，含空列表。模型得到的材料与它提出的问题不一致。</p>')
    p.append('<p>这不是单纯“模型没认真看”。程序没有按查询意图返回证据。应先修正该接口，再评价模型能否利用更好的材料。对于空列表，还应区分“该路径没有测试”和“当前候选列表未包含该路径”。</p>')
    p.append('<p>'+link(OUT/'test_queries.json','全部路径查询及返回记录')+' · '+link(ROOT/'src/augmentation/presentation.py','输入删减与查询实现')+'</p>')
    p.append('<h2>检测原因五：模型混淆关系的作用范围</h2><p>T13 已收到共享捕获变量的具体候选，并读取了复制实现。模型随后认为：保持副本内部闭包共享会违背快照隔离。这把两种关系混为一谈。</p>')
    p.append('<p>正确要求是：副本与源实例互不影响；同一副本内部，原本共享变量的两个闭包仍共享该变量。一次复制需要同时保留这两项性质。模型用实例间隔离否定了实例内共享，形成语义误判。</p>')
    p.append('<p>'+trace('T13','joint_013873c0942a42c19978',3,'action.json','T13 明确否定共享目标的答复')+'</p>')
    p.append('<p>T28 也存在范围混淆。读取恢复后的结果，与订阅或挂载观察者并触发刷新，是不同操作。已有测试能证明恢复后的立即读取正确，不能证明刷新后的状态仍正确。</p>')
    p.append('<h2>生成原因一：测试丢失了决定性的条件</h2>')
    p.append(table(['任务','过程中的有效方向','最终测试或动作','失败位置'], [
        ['T17','键存在但值为 undefined','第三轮仍在查阅原测试，随后预算结束','目标已接近，但没有完成判断和生成'],
        ['T20','同一配置先通过声明校验，再进入运行处理','直接调用内部 cookie 合并函数','绕过应当检查的入口校验'],
        ['T24','省略 mode 导致规则被跳过','显式使用 put 模式，改查默认值填充','生成时更换了触发条件'],
        ['T28','恢复后的状态继续经过后续操作','恢复后读取状态或 getCurrentResult','没有执行挂载或订阅触发的刷新'],
    ]))
    p.append('<p>T24 第二轮已明确提出省略 mode 的问题。随后模型请求了不存在的源码路径，查询失败。第三轮它转去检查另一个默认值问题。源码查询失败并不反驳原假设，但流程没有保留该假设并要求说明更换原因。</p>')
    p.append('<p>'+trace('T24','joint_2fe1cb0bd70ea99dc878',2,'action.json','T24 已识别的条件')+' · '+trace('T24','joint_2fe1cb0bd70ea99dc878',2,'feedback.json','查询失败')+' · '+trace('T24','joint_2fe1cb0bd70ea99dc878',3,'assessment.json','最终更换的目标与测试')+'</p>')
    p.append('<p>生成后应检查目标条件是否仍在测试里。例如，目标要求省略参数，就不能显式填入；目标要求经过配置校验，就不能直接调用内部函数。此检查不要求模型证明整个测试正确，只要求它保留已选定的关键条件。</p>')
    p.append('<h2>生成原因二：测试环境与输入前提不完整</h2><p>13 项最终建议存在测试自身错误。T09 使用错误的导入位置或异常路径接口；T21 和 T27 在外层测试引用局部变量；T26 使用仓库未安装的 Vitest；T16 在到达 nil 赋值前就构造了非法初始化；T24 把默认必填字段当成可选字段。</p>')
    p.append('<p>这些错误来自不同环节。导入、变量作用域和测试框架属于执行上下文。字段必填性和初始化合法性属于输入语义。应分别反馈，不能都概括为“测试失败”。</p>')
    p.append('<p>追加代码的位置还有提示遗漏。单次调用提示明确说明 append 会在文件末尾追加代码。agent 模式通过截取提示前半段构建新提示，遗漏了这一段说明。实际发送的提示没有解释文件末尾的作用域限制。T21、T27 的新增测试却引用了测试组内部的局部变量。</p>')
    p.append('<p>这提供了具体的失败机制，但尚未通过补回提示的对照实验测量收益。框架和导入错误仍需逐项检查，不能仅凭这一处遗漏解释全部 13 项。</p>')
    p.append('<h2>生成原因三：三轮预算让反馈难以用于修正</h2><p>每个候选只有三次模型调用。模型通常先查源码，再查测试，最后生成代码。78 项最终建议中，77 项在第三轮才提交。执行虽然发生，但模型没有下一轮读取结果并修正测试。</p>')
    p.append('<p>240 个候选中，85 个曾提出测试；只有 2 个提出过第二版测试。接口提供了运行能力，但这项配置没有给大多数候选提供一次完整的“生成、运行、修正”机会。</p>')
    p.append('<p>反馈内容也有缺陷。Go 编译详情没有完整交给模型。部分 Vitest 结果只保留前 30 条测试记录。T21 的失败记录位于这些条目之后，返回列表只包含跳过的测试。Go 和 TypeScript 也没有目标条件的运行事件，模型不能直接判断预期的组合是否被触发。</p>')
    p.append('<p>应为首次生成后的判断和修正保留预算。反馈先给编译错误或失败断言，再给是否执行到目标操作。候选之间也应共享“已经检查过什么”，避免不同关系重复生成相同的通过测试。</p>')
    p.append('<h2>trajectory 的利用仍不足</h2><p>新版本已经连接相关修改、附近阅读和后续测试。不能再把它描述成完全没有使用历史。它仍主要按路径、函数名和时间邻近关系选记录，最多保留 12 步；展示时还可能进一步删除。</p>')
    p.append('<p>这些历史记录没有稳定转成“输入条件、检查结果、修改后是否重跑”的验证事实。模型常需重新查阅。379 次查阅中，264 次查源码，113 次查测试，只有 1 次追加查询历史。首轮已包含历史，因此追加查询少不能证明模型完全没有使用它。</p>')
    p.append('<p>本轮记录能支持“验证范围没有对齐”的结论。它不能证明原 agent 只追求覆盖率、遗忘某项逻辑或具有其他隐藏动机。历史分析应围绕可观察的测试变化和反馈，不推测动机。</p>')
    p.append('<h2>改进顺序与判断边界</h2><p>先修正按路径查询测试的接口，并保留至少一次执行后的修正机会。这两项是已确认的实现和实验设置问题。</p>')
    p.append('<p>随后压缩候选。每个候选保留一个有源码依据的错误假设、必要的对象或值关系、操作顺序和结果检查。优先保留能解释行为差异的联系。不要仅按关系种类和标识顺序选择。</p>')
    p.append('<p>最后检查生成测试是否保持这些条件。若测试通过，先判断目标条件是否实际成立。若条件没有成立，应修正构造；若条件成立且行为正确，应结束该错误假设，并转向其他候选。</p>')
    p.append('<p>以上诊断包含直接实现证据和具体过程证据，但没有做替换输入或预算消融。原因可以同时存在。不能把 23 个漏检强行分配为互斥的因果百分比，也不能据此保证修正接口后会增加多少成功项。</p>')
    p.append('<p>'+link(OUT/'summary.json','诊断统计')+' · '+link(OUT/'inputs.json','240 份首轮输入核验')+' · '+link(OUT/'candidate_results.json','候选结果记录')+' · '+link(ROOT/'docs/archive/20261009_behavioral_gap_pilot_v02_n30.html','原实验完整报告')+'</p></html>')
    REPORT.write_text('\n'.join(p) + '\n')


if __name__ == "__main__":
    audit()
