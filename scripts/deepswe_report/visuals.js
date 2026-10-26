// Coverage tables and a compact, evidence-linked transcript reader.
function createGapViews({bi,esc,codeBlock,excerptNote}) {
  const states={
    observed:['已有检查','Check recorded','✓'],gap:['缺少有效检查','Effective check missing','!'],
    weak:['观察不足','Weak observation','~'],exposed:['正确反馈已产生','Correct feedback recorded','↪'],
    unknown:['证据未定','Uncertain evidence','?'],not_applicable:['非组合归因','No combination attribution','—']
  };
  const kinds={plan:['规划','Plan'],write:['生成测试','Write test'],run:['执行','Run'],
    revise:['修改测试','Revise test'],feedback:['检查反馈','Inspect feedback'],
    decision:['作出选择','Decision'],reference:['表格来源','Table evidence']};
  function inline(value) {
    return esc(value).replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  }
  function prose(value) {
    // Plain recorded text with a small safe Markdown subset, never raw HTML.
    const parts=String(value).split(/```[^\n]*\n([\s\S]*?)(?:```|$)/g);
    return parts.map((part,index)=>{
      if(index%2) return `<pre class="recorded-code" tabindex="0">${esc(part)}</pre>`;
      return part.split(/\n\s*\n/).filter(x=>x.trim()).map(block=>{
        const lines=block.trim().split('\n');
        if(lines.every(line=>/^\s*[-*]\s+/.test(line))) return `<ul>${lines.map(line=>`<li>${inline(line.replace(/^\s*[-*]\s+/,''))}</li>`).join('')}</ul>`;
        if(lines.every(line=>/^\s*\d+[.)]\s+/.test(line))) return `<ol>${lines.map(line=>`<li>${inline(line.replace(/^\s*\d+[.)]\s+/,''))}</li>`).join('')}</ol>`;
        if(/^#{1,6}\s/.test(block)) return `<h4>${inline(block.replace(/^#{1,6}\s+/,''))}</h4>`;
        return `<p>${lines.map(inline).join('<br>')}</p>`;
      }).join('');
    }).join('');
  }
  function table(row) {
    const table=row.gap_table,used=[...new Set(table.rows.flatMap(r=>r.cells.map(c=>c.state).filter(Boolean)))];
    const cited=table.rows.some(r=>r.steps.length);
    const headers=table.columns.map(c=>`<th scope="col">${bi(c.zh,c.en)}</th>`).join('');
    const body=table.rows.map(r=>`<tr>${r.cells.map((cell,i)=>{
      const state=states[cell.state];
      return `<${i===0?'th scope="row"':'td'} class="gap-cell${state?' state-'+cell.state:''}">${state?`<span class="state-symbol" aria-hidden="true">${state[2]}</span>`:''}${bi(cell.zh,cell.en)}${state?`<span class="sr-only"> · ${bi(state[0],state[1])}</span>`:''}</${i===0?'th':'td'}>`;
    }).join('')}${cited?`<td class="gap-evidence">${r.steps.map(step=>`<button type="button" data-action="trace-step" data-step="${step}"><span class="sr-only">${bi('查看步骤','View step')} </span>#${step}</button>`).join('')||'—'}</td>`:''}</tr>`).join('');
    return `<section class="gap-explorer"><div class="visual-heading"><h3>${bi('组合缺口表','Combination gap table')}</h3><span>${bi('按实际条件与观察维度展开','Dimensions follow the actual conditions and observations')}</span></div>${bi(table.title.zh,table.title.en,'p','gap-table-title')}<div class="gap-legend">${used.map(key=>`<span class="legend-item state-${key}"><b aria-hidden="true">${states[key][2]}</b>${bi(states[key][0],states[key][1])}</span>`).join('')}</div><div class="gap-table-scroll" tabindex="0"><table class="gap-table"><thead><tr>${headers}${cited?`<th scope="col">${bi('轨迹来源','Trace evidence')}</th>`:''}</tr></thead><tbody>${body}</tbody></table></div>${bi(table.note.zh,table.note.en,'p','gap-table-note')}<p class="visual-boundary">${bi('状态表示记录中的检查与观察强度，不是新增测试的执行结果。点击步骤编号查看对应 trajectory。','States describe recorded checks and observation strength, not new test-run results. Select a step number to inspect its trajectory evidence.')}</p></section>`;
  }
  function step(event) {
    const kind=kinds[event.kind]||kinds.reference;
    const summary=event.summary.zh===event.title.zh && event.summary.en===event.title.en ? '' : `<p class="trace-label">${bi('记录概括','Record summary')}</p>${bi(event.summary.zh,event.summary.en,'p','trace-summary')}`;
    return `<article class="trace-event" data-trace-step="${event.step}"><div class="trace-event-top"><span class="trace-kind kind-${event.kind}">${bi(...kind)}</span><code>ATIF #${event.step}</code>${event.timestamp?`<time datetime="${esc(event.timestamp)}">${esc(event.timestamp)}</time>`:''}</div>${bi(event.title.zh,event.title.en,'h4','trace-event-title')}${summary}<div class="recorded-section"><h5>${bi('Agent 原文摘录','Recorded agent excerpt')}</h5>${event.quotes.length?event.quotes.map(q=>`<blockquote class="recorded-quote">${q.before_omitted?'<p aria-hidden="true">…</p>':''}${prose(q.text)}${q.after_omitted?'<p aria-hidden="true">…</p>':''}</blockquote>`).join(''):bi('该步骤没有选入可引用的生成理由；下面仅展示已记录的操作和反馈。','No quotable generation rationale was selected for this step. Only recorded actions and feedback are available.','p','trace-no-quote')}</div><div class="trace-relation"><h5>${bi('与组合缺口的联系 · 事后分析','Connection to the gap · retrospective analysis')}</h5>${bi(event.relation.zh,event.relation.en,'p')}</div><details class="trace-execution" data-lazy="trace-actions" data-step="${event.step}"><summary>${bi('查看该步骤的操作与运行反馈','View recorded actions and execution feedback')}</summary><div class="lazy-content"></div></details></article>`;
  }
  function story(data,trial) {
    const primary=data.events[0];
    const outline=data.events.map((event,i)=>`<button type="button" class="trace-step-button" data-action="trace-select" data-step="${event.step}" role="tab" aria-selected="${i===0}" aria-controls="trace-detail-${esc(trial)}"><span class="trace-ordinal">${i+1}</span><span><span class="trace-step-meta">#${event.step} · ${bi(...kinds[event.kind])}</span>${bi(event.title.zh,event.title.en,'span','trace-step-title')}</span></button>`).join('');
    const references=data.references.length?`<div class="trace-reference-list"><p>${bi('表格引用的其他步骤','Other steps cited by the table')}</p>${data.references.map(event=>`<button type="button" data-action="trace-select" data-step="${event.step}">#${event.step}</button>`).join('')}</div>`:'';
    return `<p class="trace-reading-note">${bi('这里只呈现与测试生成、修改及验证相关的选取步骤。概括和缺口联系是编辑分析；引文、操作和输出来自实际记录。','This view selects steps related to test creation, revision and validation. Summaries and gap connections are editorial analysis; excerpts, actions and outputs come from the actual record.')}</p><div class="trace-layout"><nav class="trace-outline" role="tablist" aria-label="Trajectory steps">${outline}${references}</nav><section class="trace-detail" id="trace-detail-${esc(trial)}" role="tabpanel" tabindex="-1">${step(primary)}</section></div><div class="trace-takeaway"><strong>${bi('这段过程说明什么','What this sequence shows')}</strong>${bi(data.takeaway.zh,data.takeaway.en,'p')}</div>`;
  }
  function execution(event) {
    const actions=event.actions.map(action=>action.command.text?codeBlock(action.command.text,action.tool,{wrap:true,truncated:action.command.truncated}):`<p>${esc(action.tool)}</p>`).join('');
    const output=event.output.text?codeBlock(event.output.text,'Observed output',{wrap:true,truncated:event.output.truncated}):bi('此步骤没有可展示的运行输出。','No execution output is recorded for this step.','p','excerpt-note');
    return `<p class="trace-label">${bi('记录中的操作','Recorded actions')}</p>${actions||bi('未记录工具操作。','No tool action was recorded.','p','excerpt-note')}<p class="trace-label">${bi('记录中的反馈','Recorded feedback')}</p>${output}`;
  }
  return {table,story,step,execution};
}
