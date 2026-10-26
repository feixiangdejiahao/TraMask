'use strict';
(() => {
  const DATA = JSON.parse(document.getElementById('report-data').textContent);
  const store=createEvidenceStore(DATA);
  const cards = [...document.querySelectorAll('.trial')];
  const query = document.getElementById('query');
  const status = document.getElementById('status');
  const loaded = new Map(),rendering=new Map(),blocks=new WeakMap();
  let language = 'zh';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text = (zh, en) => language === 'zh' ? zh : en;
  const bi = (zh, en, tag='span', cls='') => `<${tag}${cls ? ` class="${cls}"` : ''} data-lang="zh">${esc(zh)}</${tag}><${tag}${cls ? ` class="${cls}"` : ''} data-lang="en">${esc(en)}</${tag}>`;
  const analysis = (row, field, cls='') => bi(row.analysis.zh[field], row.analysis.en[field], 'p', cls);
  const literal = (value, diff=false) => String(value).split('\n').map(line => {
    let cls = '';
    if (diff && line.startsWith('+') && !line.startsWith('+++')) cls = ' add';
    if (diff && line.startsWith('-') && !line.startsWith('---')) cls = ' remove';
    if (diff && (line.startsWith('@@') || line.startsWith('diff --git'))) cls = ' hunk';
    return `<span class="code-line${cls}">${esc(line) || ' '}</span>`;
  }).join('');
  const excerptNote = () => bi('摘录；[…] 或 … 表示有省略。源码保留原始语言。','Excerpt; […] or … marks omitted content. Source text retains its original language.','p','excerpt-note');
  function codeBlock(value, label, {diff=false, wrap=false, truncated=false}={}) {
    return `<div class="source-block${wrap ? ' wrap' : ''}"><div class="source-header"><span>${esc(label)}</span><span><button type="button" data-action="wrap">${bi('换行','Wrap')}</button><button type="button" data-action="copy">${bi('复制','Copy')}</button></span></div><pre tabindex="0">${literal(value, diff)}</pre></div>${truncated ? excerptNote() : ''}`;
  }
  const gapViews=createGapViews({bi,esc,codeBlock,excerptNote});
  function downloadButton(kind, zh, en) {
    return `<button type="button" data-action="download" data-kind="${kind}">${bi(zh,en)}</button>`;
  }
  function failureBlock(failure) {
    const message = failure.message.text ? `<pre tabindex="0">${esc(failure.message.text)}</pre>` : bi('该条未提供错误消息；请结合 stdout 摘录。','No error message was reported for this row; see the stdout excerpt.','p','excerpt-note');
    return `<div class="failure"><p class="failure-name">${esc(failure.name)} <span>· ${esc(failure.status)}</span></p>${message}${failure.message.truncated ? excerptNote() : ''}</div>`;
  }
  function lazyBlock(kind,title,extra='') {
    return `<details class="small-details" data-lazy="${kind}" ${extra}><summary>${title}</summary><div class="lazy-content"></div></details>`;
  }
  function validationCommands(validation) {
    return validation.steps.map((s,i)=>{
      const command=s.commands.text ? codeBlock(s.commands.text,`ATIF step ${s.step} · command`,{wrap:true,truncated:s.commands.truncated}) : '';
      const output=s.output.text ? lazyBlock('step-output',bi('该步骤的实际输出','Observed output for this step'),`data-step="${i}"`) : '';
      return i===0 ? command+output : lazyBlock('step-command',`${bi('相关验证步骤','Related validation step')} ${s.step}`,`data-step="${i}"`);
    }).join('');
  }
  function makeBody(row) {
    const ev = row.evaluation, validation = row.validation;
    const files = row.files.map(f => `<li><code>${esc(f.path)}</code><span class="file-counts">+${f.added} −${f.removed}</span></li>`).join('');
    const patchAdded = row.files.reduce((n,f) => n+f.added, 0), patchRemoved = row.files.reduce((n,f) => n+f.removed,0);
    const failHead = ev.focus.slice(0,2).map(failureBlock).join('');
    const failMore = ev.focus.length > 2 ? lazyBlock('more-failures',`${bi('更多失败消息','More failure messages')} (${ev.focus.length-2})`) : '';
    const failIndex = lazyBlock('failure-index',`${bi('全部失败条目标识','All failure-row identifiers')} (${ev.failure_count})`);
    const finalTests = validation.final_test_excerpts.map((s,i)=>lazyBlock('submitted-test',`${bi('提交补丁中的测试','Tests in the submitted patch')} · ${esc(s.path)}`,`data-test="${i}"`)).join('');
    const focusedValidation=validation.focus ? codeBlock(validation.focus.excerpt.text,`model.patch · ${validation.focus.path}`,{diff:true,truncated:validation.focus.excerpt.truncated}) : '';
    const combination = row.analysis.zh.combination ? analysis(row,'combination','combination') : bi('当前证据未建立组合缺口与失败的联系。','The evidence does not establish a combination gap linked to this failure.','p','combination');
    return `${bi(row.overview.zh,row.overview.en,'p','overview')}
      <div class="identity"><code>${esc(row.trial)}</code><span>${esc(row.repository)}</span><a class="permalink" href="#${encodeURIComponent(row.trial)}">${bi('定位此 trial','Link to this trial')} ↗</a></div>
      <div class="interaction"><span class="interaction-label">${bi('组合联系','Interaction under review')}</span>${combination}</div>
      ${gapViews.table(row)}
      <details class="trace-panel" data-lazy="test-story"><summary><span>${bi('测试生成过程 · Trajectory','Test generation · trajectory')}</span><span class="trace-count">${row.test_story.recorded_events} ${bi('个相关步骤','related steps')} / ${row.test_story.total_steps}</span></summary>${bi(row.test_story.intro.zh,row.test_story.intro.en,'p','trace-intro')}<div class="lazy-content"></div></details>
      <div class="context-grid"><details class="source-details" data-embedded="issue"><summary>${bi('Issue · 完整任务需求','Issue · complete task requirements')}</summary><div class="source-inner"><div class="embedded-source"></div><div class="evidence-label">${bi('完整原文已内嵌','Complete source embedded')}${downloadButton('issue','下载需求','Download issue')}</div></div></details>
      <details class="source-details" data-embedded="patch"><summary>${bi('Patch · 完整提交与修改文件','Patch · full submission and changed files')} (${row.files.length})</summary><div class="source-inner"><ul class="file-list">${files}</ul><p class="excerpt-note">+${patchAdded} / −${patchRemoved}</p><div class="embedded-source"></div><div class="evidence-label">${bi('这是 agent 提交的补丁','Patch submitted by the agent')}${downloadButton('patch','下载 patch','Download patch')}</div></div></details></div>
      <div class="comparison"><section class="panel evaluation-panel"><div class="panel-heading"><h3>${bi('Evaluation · 发生了什么失败','Evaluation · observed failure')}</h3><span class="kicker">${bi('评价侧证据','EVALUATION EVIDENCE')}</span></div><div class="panel-content">${analysis(row,'evaluation','panel-analysis')}
      <div class="evidence-label">${bi('出错测试的源码定位','Source context for the failing test')}</div>${ev.test_excerpt.matched ? codeBlock(ev.test_excerpt.text,'evaluation test.patch · source lines',{diff:true,truncated:ev.test_excerpt.truncated}) : bi('当前评价测试补丁未包含或未定位到该失败条目的源码；本项仅展示实际报告和日志，不能由 missing 推断运行时错误。','The evaluation test patch does not contain, or does not locate, source for this failure row. Read the reported result and logs; a missing entry alone does not establish a runtime failure.','p','empty-evidence')}
      <div class="evidence-label">${bi('实际失败测试与消息','Actual failing tests and messages')}<span>${ev.failure_count} ${bi('条报告记录','report rows')}</span></div>${failHead}${failMore}${failIndex}
      <details class="small-details" data-embedded="evaluation"><summary>${bi('完整 evaluation 测试补丁','Complete evaluation test patch')}</summary><div class="embedded-source"></div><div class="evidence-label">${bi('完整文件已内嵌','Complete file embedded')}${downloadButton('evaluation','下载测试补丁','Download test patch')}</div></details>
      ${lazyBlock('stdout',bi('Evaluation stdout · 定位摘录','Evaluation stdout · selected context'))}</div></section>
      <section class="panel validation-panel"><div class="panel-heading"><h3>${bi('Validation · agent 检查了什么','Validation · what the agent checked')}</h3><span class="kicker">${bi('开发时证据','DEVELOPMENT EVIDENCE')}</span></div><div class="panel-content">${analysis(row,'validation','panel-analysis')}<div class="evidence-label">${validation.focus ? bi('提交中的相关测试 · 源码摘录','Related submitted test · source excerpt') : bi('相关验证代码、命令与执行结果','Relevant validation code, commands and results')}</div>${focusedValidation}${validation.focus ? lazyBlock('commands',bi('实际验证命令与运行输出','Actual validation commands and observed outputs')) : validationCommands(validation) || bi('未定位到可展示的验证命令；请结合提交测试与分析阅读。','No displayable validation command was located; read the submitted tests and analysis together.','p','empty-evidence')}${finalTests}<p class="excerpt-note">${bi('步骤中的验证可能早于最终提交；存在或执行过某输入，并不自动说明最终补丁有有效断言。','A validation step may precede the final submission. An input being present or executed does not by itself establish an effective assertion against the submitted patch.')}</p></div></section></div>
      <section class="diagnosis"><h3>${bi('归因与下一步检查','Attribution and next check')}${row.metric ? `<span class="metric-target">${esc(row.metric)}</span>` : ''}</h3><p class="repair-label">${bi('补充检查 → 失败反馈 → 可能修复与收益（建议未执行）','Additional check → feedback → possible repair and benefit (not executed)')}</p>${analysis(row,'counterfactual','repair')}</section>
      <details class="provenance"><summary>${bi('证据文件校验值','Evidence file hashes')} · SHA-256</summary><dl>${Object.entries(row.evidence_hashes).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl></details>`;
  }
  function loading() {return bi('正在加载这部分材料…','Loading this section…','p','loading-note');}
  async function loadCard(card) {
    if(loaded.has(card.id)) return true;
    if(rendering.has(card.id)) return rendering.get(card.id);
    const body=card.querySelector('.case-body');
    body.innerHTML=loading();body.setAttribute('aria-busy','true');
    const pending=(async()=>{
      try {
        const row=await store.getCase(card.id);
        body.innerHTML=makeBody(row);loaded.set(card.id,row);card.dataset.loaded='true';
        performance.mark(`trial-ready-${row.n}`);
        return true;
      } catch(error) {
        body.innerHTML=bi('材料加载失败，可收起后重试。','Unable to load evidence. Collapse and reopen to retry.','p','loading-error')+`<p class="excerpt-note">${esc(error.message)}</p>`;
        return false;
      } finally {body.removeAttribute('aria-busy');rendering.delete(card.id);}
    })();
    rendering.set(card.id,pending);
    return pending;
  }
  let filterGeneration=0;
  async function filter() {
    const generation=++filterGeneration;
    const words=query.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    let searchIndex;
    if(words.length) {
      document.getElementById('shown').textContent=text('正在搜索全部 trial…','Searching all trials…');
      try {searchIndex=await store.getSearch();}catch(error){toast(error.message);return;}
      if(generation!==filterGeneration) return;
    }
    let count=0;
    for(const card of cards) {
      const category=!status.value || (status.value==='positive' ? card.dataset.positive==='true' : card.dataset.status===status.value);
      card.hidden=!(category && words.every(word=>searchIndex[card.id].includes(word)));
      if(!card.hidden) count++;
    }
    document.getElementById('shown').textContent=text(`显示 ${count} / 211 条 trial`,`Showing ${count} / 211 trials`);
    document.getElementById('empty').hidden=count!==0;
    document.querySelectorAll('.stat').forEach(button=>button.classList.toggle('active',button.dataset.filter===status.value));
  }
  function setLanguage(value) {
    language=value==='en'?'en':'zh';
    document.documentElement.lang=language==='zh'?'zh-CN':'en';
    document.title=text('DeepSWE · 失败 trial 与组合验证缺口','DeepSWE · Failed trials & combination testing gaps');
    document.querySelectorAll('[data-language-toggle]').forEach(button=>{
      button.textContent=language==='zh'?'English':'中文';
      button.setAttribute('aria-label',text('Switch to English','切换到中文'));
    });
    query.placeholder=query.dataset[language];
    status.setAttribute('aria-label',text('判定','Judgment'));
    status.querySelectorAll('option').forEach(option=>option.textContent=option.dataset[language]);
    try{localStorage.setItem('deepswe-report-language',language);}catch{}
    filter();
  }
  async function openLinkedTrial() {
    let id;
    try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}
    const card=document.getElementById(id);
    if(card?.classList.contains('trial')) {
      query.value='';status.value='';filter();card.open=true;await loadCard(card);
      requestAnimationFrame(()=>card.scrollIntoView({block:'start'}));
    }
  }
  function toast(value) {
    document.querySelector('.toast')?.remove();
    const item=document.createElement('div');item.className='toast';item.setAttribute('role','status');item.textContent=value;document.body.append(item);setTimeout(()=>item.remove(),1800);
  }
  async function renderBlock(detail) {
    if(detail.dataset.rendered==='true') return;
    if(blocks.has(detail)) return blocks.get(detail);
    const target=detail.querySelector(detail.dataset.embedded ? '.embedded-source' : '.lazy-content');
    target.innerHTML=loading();target.setAttribute('aria-busy','true');
    const pending=(async()=>{
      try {
        const row=await store.getCase(detail.closest('.trial').id),ev=row.evaluation,v=row.validation;
        let html='';
        if(detail.dataset.embedded) {
          const kind=detail.dataset.embedded,value=await store.getAsset(row.assets[kind]);
          html=kind==='issue' ? `<pre class="issue-text" tabindex="0">${esc(value)}</pre>` : codeBlock(value,kind==='patch'?'model.patch':'evaluation test.patch',{diff:true});
        } else switch(detail.dataset.lazy) {
          case 'more-failures': html=ev.focus.slice(2).map(failureBlock).join('');break;
          case 'failure-index': html=bi('包括报告缺失或 suite 汇总；行数不等于独立缺陷数。','May include missing report entries or suite summaries; row count is not a defect count.','p','excerpt-note')+`<ul>${ev.failure_index.map(f=>`<li>${esc(f.name)} · ${esc(f.status)}</li>`).join('')}</ul>`;break;
          case 'stdout': html=codeBlock(ev.stdout.text,'test-stdout.txt · source lines',{wrap:true,truncated:ev.stdout.truncated});break;
          case 'commands': html=validationCommands(v);break;
          case 'step-command': {
            const i=Number(detail.dataset.step),s=v.steps[i];
            html=codeBlock(s.commands.text,`ATIF step ${s.step} · command`,{wrap:true,truncated:s.commands.truncated});
            if(s.output.text) html+=lazyBlock('step-output',bi('该步骤的实际输出','Observed output for this step'),`data-step="${i}"`);
            break;
          }
          case 'step-output': {
            const s=v.steps[Number(detail.dataset.step)];html=codeBlock(s.output.text,`ATIF step ${s.step} · output`,{wrap:true,truncated:s.output.truncated});break;
          }
          case 'submitted-test': {
            const s=v.final_test_excerpts[Number(detail.dataset.test)];html=codeBlock(s.text,s.path,{diff:true,truncated:s.truncated});break;
          }
          case 'test-story': html=gapViews.story(await store.getStory(row.trial),row.trial);break;
          case 'trace-actions': {
            const story=await store.getStory(row.trial);
            const event=[...story.events,...story.references].find(e=>e.step===Number(detail.dataset.step));
            html=gapViews.execution(event);break;
          }
        }
        target.innerHTML=html;detail.dataset.rendered='true';
      } catch(error) {target.innerHTML=bi('材料加载失败，请重新展开。','Loading failed. Reopen this section to retry.','p','loading-error')+`<p class="excerpt-note">${esc(error.message)}</p>`;}
      finally {target.removeAttribute('aria-busy');blocks.delete(detail);}
    })();
    blocks.set(detail,pending);return pending;
  }
  cards.forEach(card=>card.addEventListener('toggle',()=>{if(card.open) loadCard(card);}));
  document.addEventListener('toggle',event=>{
    const detail=event.target;
    if(detail.open && (detail.dataset.embedded || detail.dataset.lazy)) renderBlock(detail);
  },true);
  document.querySelectorAll('[data-language-toggle]').forEach(button=>button.addEventListener('click',()=>setLanguage(language==='zh'?'en':'zh')));
  query.addEventListener('input',filter);status.addEventListener('change',filter);
  document.querySelectorAll('.stat').forEach(button=>button.addEventListener('click',()=>{status.value=status.value===button.dataset.filter?'':button.dataset.filter;filter();}));
  document.getElementById('reset').addEventListener('click',()=>{query.value='';status.value='';filter();});
  let expandGeneration=0;
  document.getElementById('expand').addEventListener('click',async()=>{
    const generation=++expandGeneration;
    for(const card of cards) {
      if(generation!==expandGeneration) break;
      if(!card.hidden){card.open=true;await loadCard(card);await new Promise(resolve=>setTimeout(resolve,0));}
    }
  });
  document.getElementById('collapse').addEventListener('click',()=>{expandGeneration++;cards.forEach(card=>{card.open=false;});});
  document.addEventListener('click',async event=>{
    const button=event.target.closest('button[data-action]');if(!button)return;
    if(button.dataset.action==='trace-step' || button.dataset.action==='trace-select') {
      try {
        const trial=button.closest('.trial'),panel=trial.querySelector('[data-lazy="test-story"]');
        panel.open=true;await renderBlock(panel);
        const story=await store.getStory(trial.id);
        const selected=[...story.events,...story.references].find(e=>e.step===Number(button.dataset.step));
        if(!selected) return;
        panel.querySelector('.trace-detail').innerHTML=gapViews.step(selected);
        panel.querySelectorAll('.trace-step-button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.step===button.dataset.step)));
        panel.querySelectorAll('.trace-reference-list button').forEach(b=>b.classList.toggle('active',b.dataset.step===button.dataset.step));
        if(button.dataset.action==='trace-step') panel.scrollIntoView({block:'nearest'});
      }catch(error){toast(error.message);}
      return;
    }
    if(button.dataset.action==='wrap'){button.closest('.source-block').classList.toggle('wrap');return;}
    if(button.dataset.action==='copy'){
      const value=button.closest('.source-block').querySelector('pre').innerText;
      try {
        if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
        else {const area=document.createElement('textarea');area.value=value;document.body.append(area);area.select();document.execCommand('copy');area.remove();}
        toast(text('已复制','Copied'));
      }catch{toast(text('请选中代码后复制','Select the code and copy it'));}
    }
    if(button.dataset.action==='download'){
      button.disabled=true;
      try {
        const row=await store.getCase(button.closest('.trial').id),kind=button.dataset.kind;
        const value=await store.getAsset(row.assets[kind]);
        const url=URL.createObjectURL(new Blob([value],{type:'text/plain;charset=utf-8'}));
        const a=document.createElement('a');a.href=url;a.download=`${row.trial}.${kind==='issue'?'issue.md':kind==='patch'?'model.patch':'evaluation.patch'}`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
      }catch(error){toast(error.message);}finally{button.disabled=false;}
    }
  });
  window.addEventListener('hashchange',openLinkedTrial);
  let initial='zh';
  try{initial=new URLSearchParams(location.search).get('lang') || localStorage.getItem('deepswe-report-language') || 'zh';}catch{}
  setLanguage(initial);
  store.stats.ready=true;performance.mark('controls-ready');
  openLinkedTrial();
  if(!location.hash){cards[0].open=true;loadCard(cards[0]);}
})();
