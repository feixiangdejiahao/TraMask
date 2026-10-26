// Exercise the actual portable file offline, including lazy evidence and downloads.
// DEEPSWE_PLAYWRIGHT_MODULE can point to an existing Playwright installation.
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.DEEPSWE_PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'..');
const output=path.join(root,'results/failure_analysis/20261022_standalone_report_n211_r01');
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const context=await browser.newContext({viewport:{width:1440,height:1080},offline:true,acceptDownloads:true});
  const page=await context.newPage(),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'deepswe-portable-'));
  fs.copyFileSync(path.join(root,'docs/deepswe_failure_manual_20261006.html'),path.join(temp,'report.html'));
  const performance=()=>page.evaluate(()=>JSON.parse(JSON.stringify(window.__deepswePerformance)));
  const settle=()=>page.waitForFunction(()=>window.__deepswePerformance?.pending===0);
  const scrollUnderToolbar=locator=>locator.evaluate(el=>{
    el.scrollIntoView({block:'start'});
    window.scrollBy(0,-(document.querySelector('.toolbar').getBoundingClientRect().height+8));
  });
  const waitForRendered=async panel=>page.waitForFunction(el=>el.dataset.rendered==='true',await panel.elementHandle());
  async function waitForTrace(panel,step){
    await waitForRendered(panel);
    await panel.locator(`.trace-event[data-trace-step="${step}"]`).waitFor();
    await settle();
  }
  async function assertSourceClosed(trial,kind){
    const panel=trial.locator(`.context-grid > details[data-embedded="${kind}"]`);
    const state=await panel.evaluate(el=>({
      open:el.open,
      height:el.getBoundingClientRect().height,
      summaryHeight:el.querySelector(':scope > summary').getBoundingClientRect().height,
      contentDisplay:getComputedStyle(el.querySelector('.source-inner')).display,
    }));
    assert.equal(state.open,false,`${kind} must stay closed when its neighbor is opened`);
    assert(state.height<=state.summaryHeight+3,`${kind} must retain its collapsed height; got ${state.height}px for a ${state.summaryHeight}px summary`);
    assert.equal(await panel.locator('.source-inner').isVisible(),false,`${kind} content must remain hidden`);
  }
  try{
    const file=pathToFileURL(path.join(temp,'report.html')).href;
    const start=Date.now();
    await page.goto(file,{waitUntil:'load'});
    await page.waitForFunction(()=>window.__deepswePerformance?.ready && document.querySelector('.trial[data-loaded="true"] .comparison'));
    await settle();
    const loadMs=Date.now()-start;
    const initial=await performance();
    assert.equal(initial.decodedCases.length,1,'Initial opening must decode only the first trial');
    assert.deepEqual(initial.decodedAssets,[],'Full source files must remain compressed until requested');
    assert.deepEqual(initial.decodedStories,[],'Trajectory excerpts must stay compressed until requested');
    assert.equal(await page.locator('.trace-event').count(),0,'No trajectory event may be rendered initially');
    assert.equal(initial.searchDecoded,false,'Search text must remain compressed until a query is entered');
    const index=await page.evaluate(()=>JSON.parse(document.getElementById('report-data').textContent));
    assert.equal(index.schema_version,'deepswe-portable-chunks.v2');
    assert.equal(index.encoding,'gzip-base64');
    assert.equal(Object.keys(index.cases).length,211);
    assert.equal(await page.locator('.trial').count(),211);
    assert.equal(await page.locator('.trial[open]').count(),1);
    assert.equal(await page.locator('html').getAttribute('lang'),'zh-CN');
    const first=page.locator('.trial').first();
    const firstId=await first.getAttribute('id');
    assert.deepEqual(initial.decodedCases,[firstId]);
    assert.equal(await first.locator('.gap-explorer .gap-table').count(),1);
    assert((await first.locator('.gap-table tbody tr').count())>=2,'Coverage table must show concrete combinations');
    const desktopColumns=await page.locator('.comparison').first().evaluate(el=>{
      const [a,b]=[...el.children].map(x=>x.getBoundingClientRect());return Math.abs(a.y-b.y)<2 && b.x>a.x+a.width-2;
    });
    assert(desktopColumns,'Desktop evidence must be side by side');
    await page.screenshot({path:path.join(output,'desktop-zh.png')});
    await first.evaluate(el=>el.scrollIntoView({block:'start'}));
    await page.screenshot({path:path.join(output,'desktop-comparison.png')});
    await page.click('#language-toggle');
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    assert.match(await page.locator('.panel-heading').first().innerText(),/observed failure/);
    assert.equal(await first.locator('[data-lang="zh"]:visible').count(),0);
    assert.match(await page.locator('#shown').innerText(),/Showing 211/);
    await page.selectOption('#status','supported');
    await page.waitForFunction(()=>[...document.querySelectorAll('.trial')].filter(x=>!x.hidden).length===88);
    assert.equal((await performance()).searchDecoded,false,'Category and language changes must not decode search text');
    await page.fill('#query','negative index');
    await page.waitForFunction(()=>window.__deepswePerformance?.searchDecoded && [...document.querySelectorAll('.trial')].some(x=>!x.hidden));
    await settle();
    assert.deepEqual((await performance()).decodedCases,[firstId],'Searching all trials must not decode their bodies');
    await page.click('#reset');
    await scrollUnderToolbar(first.locator('.gap-explorer'));
    await page.screenshot({path:path.join(output,'gap-table-desktop-en.png')});
    // The matrix opens the exact cited step in a readable transcript, on demand.
    const cited=first.locator('.gap-evidence [data-action="trace-step"]').first();
    const citedStep=await cited.getAttribute('data-step');
    await cited.click();
    const tracePanel=first.locator('[data-lazy="test-story"]');
    await waitForTrace(tracePanel,citedStep);
    assert.deepEqual((await performance()).decodedStories,[firstId]);
    assert.equal((await performance()).decodes[index.cases[firstId].story.chunk],1);
    assert((await tracePanel.locator('.recorded-quote').count())>0,'Transcript should show recorded agent text');
    assert(!/"(?:reasoning_content|tool_calls|observation)"\s*:/.test(await tracePanel.innerText()),'Transcript must render normal text, not an ATIF JSON dump');
    const stepButtons=tracePanel.locator('.trace-step-button');
    if((await stepButtons.count())>1){
      const second=stepButtons.nth(1),step=await second.getAttribute('data-step');
      await second.click();
      await waitForTrace(tracePanel,step);
      assert.equal(await tracePanel.locator('.trace-event').getAttribute('data-trace-step'),step);
      assert.equal(await second.getAttribute('aria-selected'),'true','Selected transcript step must be reflected in the outline');
    }
    await tracePanel.locator('.trace-execution > summary').click();
    await tracePanel.locator('.trace-execution[data-rendered="true"]').waitFor();
    await settle();
    assert.match(await tracePanel.locator('.trace-execution').innerText(),/Recorded actions/);
    assert.match(await tracePanel.locator('.trace-execution').innerText(),/Recorded feedback/);
    assert((await tracePanel.locator('.trace-execution .source-block').count())>0,'Execution details should expose a recorded action or output');
    await tracePanel.locator(':scope > summary').click();
    await tracePanel.locator(':scope > summary').click();
    assert.equal((await performance()).decodes[index.cases[firstId].story.chunk],1,'Reopening a trajectory must use cached decoded text');
    await scrollUnderToolbar(tracePanel);
    await page.screenshot({path:path.join(output,'trajectory-desktop-en.png')});
    await tracePanel.locator(':scope > summary').click();
    await page.fill('#query','zzzz_no_matching_trial_zzzz');
    await page.waitForFunction(()=>!document.getElementById('empty').hidden);
    assert(await page.locator('#empty').isVisible());
    await page.click('#reset');
    await page.fill('#query','wasmi-trap-coredumps');
    await page.waitForFunction(()=>[...document.querySelectorAll('.trial')].some(x=>!x.hidden) && [...document.querySelectorAll('.trial')].filter(x=>!x.hidden).every(x=>x.textContent.includes('wasmi-trap-coredumps')));
    assert.deepEqual((await performance()).decodedCases,[firstId],'A distant search hit must remain compressed');
    await page.click('#reset');
    await page.waitForFunction(()=>[...document.querySelectorAll('.trial')].every(x=>!x.hidden));
    // Opening an arbitrary distant trial must not materialize intervening cases.
    const distant=page.locator('.trial').last(),distantId=await distant.getAttribute('id');
    await distant.locator(':scope > summary').click();
    await page.waitForFunction(id=>document.getElementById(id)?.dataset.loaded==='true',distantId);
    await settle();
    const afterDistant=await performance();
    assert.deepEqual([...afterDistant.decodedCases].sort(),[firstId,distantId].sort());
    assert.deepEqual(afterDistant.decodedAssets,[]);
    // Interrupt bulk expansion while most bodies are still compressed.
    await page.click('#expand');
    await page.waitForFunction(()=>window.__deepswePerformance.decodedCases.length>2);
    await page.click('#collapse');
    await settle();
    const cancelled=await performance();
    assert(cancelled.decodedCases.length<211,'Collapse must cancel further batch loading');
    await page.waitForTimeout(120);
    assert.equal((await performance()).decodedCases.length,cancelled.decodedCases.length,'Cancelled batches must stay stopped');
    assert.equal(await page.locator('.trial[open]').count(),0);
    // Toggle and download compete for the same source chunk and must share one decode.
    await first.locator(':scope > summary').click();
    const patchAsset=index.cases[firstId].assets.patch;
    const downloadEvent=page.waitForEvent('download');
    await first.evaluate(el=>{
      el.querySelector('details[data-embedded="patch"]').open=true;
      el.querySelector('[data-action="download"][data-kind="patch"]').click();
    });
    const download=await downloadEvent;
    const downloaded=path.join(temp,'download.patch');await download.saveAs(downloaded);
    await first.locator('details[data-embedded="patch"] pre').waitFor();
    assert((await first.locator('details[data-embedded="patch"] pre').innerText()).includes('diff --git'));
    await assertSourceClosed(first,'issue');
    assert.equal(crypto.createHash('sha256').update(fs.readFileSync(downloaded)).digest('hex'),index.assets[patchAsset].sha256);
    await settle();
    const afterPatch=await performance();
    assert.deepEqual(afterPatch.decodedAssets,[patchAsset]);
    assert.equal(afterPatch.decodes[patchAsset],1,'Concurrent source actions must share one decode');
    await first.locator('details[data-embedded="patch"] > summary').click();
    await first.locator('details[data-embedded="patch"] > summary').click();
    await settle();
    assert.equal((await performance()).decodes[patchAsset],1,'Reopening source must use its cache');
    await first.locator('details[data-embedded="patch"] > summary').click();
    // Full issue and evaluation source use the same deferred source mechanism.
    for(const kind of ['issue','evaluation']){
      await first.locator(`details[data-embedded="${kind}"] > summary`).click();
      await first.locator(`details[data-embedded="${kind}"] pre`).waitFor();
      assert((await first.locator(`details[data-embedded="${kind}"] pre`).innerText()).length>0);
      await settle();
      assert.equal((await performance()).decodes[index.cases[firstId].assets[kind]],1);
      if(kind==='issue') await assertSourceClosed(first,'patch');
    }
    await page.click('#collapse');
    await page.fill('#query','wasmi-trap-coredumps');
    await page.waitForFunction(()=>[...document.querySelectorAll('.trial')].some(x=>!x.hidden) && [...document.querySelectorAll('.trial')].filter(x=>!x.hidden).every(x=>x.textContent.includes('wasmi-trap-coredumps')));
    await page.click('#expand');
    await page.waitForFunction(()=>[...document.querySelectorAll('.trial')].filter(x=>!x.hidden).every(x=>x.open && x.dataset.loaded==='true'));
    const linked=await page.locator('.trial:visible').first().getAttribute('id');
    await page.goto(`${file}?lang=en#${linked}`);
    await page.waitForFunction(id=>window.__deepswePerformance?.ready && document.getElementById(id)?.open && document.getElementById(id)?.dataset.loaded==='true',linked);
    await settle();
    assert.deepEqual((await performance()).decodedCases,[linked],'A deep link must decode only its target trial');
    assert.deepEqual((await performance()).decodedAssets,[]);
    assert.deepEqual((await performance()).decodedStories,[],'Deep linking must not load trajectory excerpts');
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    await page.screenshot({path:path.join(output,'desktop-en.png')});
    // Rendering all cards catches malformed data while preserving deferred full sources.
    await page.click('#expand');
    await page.waitForFunction(()=>[...document.querySelectorAll('.trial')].every(x=>x.dataset.loaded==='true' && x.querySelector('.comparison')),{},{timeout:60000});
    await settle();
    assert.equal(await page.locator('.comparison').count(),211);
    const fullyRendered=await performance();
    assert.equal(fullyRendered.decodedCases.length,211);
    assert.deepEqual(fullyRendered.decodedAssets,[],'Bulk expansion must leave complete source assets compressed');
    assert.deepEqual(fullyRendered.decodedStories,[],'Bulk expansion must leave trajectories compressed');
    assert.equal(await page.locator('[data-lazy="test-story"]').count(),211,'Every trial needs its own transcript panel');
    assert.equal(await page.locator('[data-lazy="test-story"][open]').count(),0,'Expanding trial bodies must leave transcript panels closed');
    assert.equal(await page.locator('.trace-event').count(),0,'Expanding all trial bodies must not render transcript events');
    assert.equal(await page.locator('.gap-table').count(),211,'Every trial needs its own coverage table');
    const tableShapes=await page.locator('.gap-table').evaluateAll(tables=>tables.map(table=>({columns:table.tHead.rows[0].cells.length,rows:table.tBodies[0].rows.length})));
    const columnCounts=[...new Set(tableShapes.map(shape=>shape.columns))].sort((a,b)=>a-b);
    const rowCounts=[...new Set(tableShapes.map(shape=>shape.rows))].sort((a,b)=>a-b);
    assert(columnCounts.length>=2,'Coverage tables must use varying columns for actual conditions');
    assert(rowCounts.length>=2,'Coverage tables must use varying scenario counts rather than a fixed 2 by 2 grid');
    assert(tableShapes.every(shape=>shape.columns>=3 && shape.rows>=2),'Coverage tables must contain concrete labeled scenarios');
    assert(Object.values(fullyRendered.decodes).every(n=>n===1),'A chunk must never be decoded twice');
    await page.click('#language-toggle');
    assert.equal(await page.locator('html').getAttribute('lang'),'zh-CN');
    assert.equal(await page.locator('.trial').count(),211);
    await page.click('#language-toggle');
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    assert.equal(await page.locator('.trial').count(),211);
    await page.click('#collapse');
    await page.setViewportSize({width:390,height:844});
    await page.goto(file+'?lang=zh');
    await page.waitForFunction(()=>window.__deepswePerformance?.ready && document.querySelector('.trial[data-loaded="true"] .comparison'));
    const mobile=await page.locator('.comparison').first().evaluate(el=>{
      const [a,b]=[...el.children].map(x=>x.getBoundingClientRect());return b.y>a.y+a.height-2 && Math.abs(a.x-b.x)<2;
    });
    assert(mobile,'Mobile evidence must stack');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page must not overflow horizontally');
    const mobileFirst=page.locator('.trial').first();
    await mobileFirst.locator('details[data-embedded="issue"] > summary').click();
    await mobileFirst.locator('details[data-embedded="issue"] pre').waitFor();
    await assertSourceClosed(mobileFirst,'patch');
    await mobileFirst.locator('details[data-embedded="issue"] > summary').click();
    await mobileFirst.locator('details[data-embedded="patch"] > summary').click();
    await mobileFirst.locator('details[data-embedded="patch"] pre').waitFor();
    await assertSourceClosed(mobileFirst,'issue');
    await mobileFirst.locator('details[data-embedded="patch"] > summary').click();
    await page.screenshot({path:path.join(output,'mobile-zh.png')});
    await page.click('#language-toggle');
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    await scrollUnderToolbar(mobileFirst.locator('.gap-explorer'));
    await page.screenshot({path:path.join(output,'gap-table-mobile-en.png')});
    await page.locator('.trial').first().locator('[data-lazy="test-story"] > summary').click();
    const mobileTrace=mobileFirst.locator('[data-lazy="test-story"]');
    await waitForRendered(mobileTrace);
    await mobileTrace.locator('.trace-event').waitFor();
    await settle();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Tables and transcript must fit the mobile page');
    const mobileSteps=page.locator('.trial').first().locator('.trace-step-button');
    if((await mobileSteps.count())>1){
      const next=mobileSteps.nth(1),step=await next.getAttribute('data-step');
      await next.click();
      await waitForTrace(mobileTrace,step);
      assert.equal(await page.locator('.trial').first().locator('.trace-event').getAttribute('data-trace-step'),step);
    }
    await mobileTrace.locator('.trace-execution > summary').click();
    await mobileTrace.locator('.trace-execution[data-rendered="true"]').waitFor();
    await settle();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Recorded actions and feedback must not overflow the mobile page');
    await scrollUnderToolbar(mobileTrace);
    await page.screenshot({path:path.join(output,'trajectory-mobile-en.png')});
    await page.locator('.trial').first().locator('[data-lazy="test-story"] > summary').click();
    await page.screenshot({path:path.join(output,'mobile-en.png')});
    await page.locator('.comparison').first().evaluate(el=>el.scrollIntoView({block:'start'}));
    await page.screenshot({path:path.join(output,'mobile-comparison.png')});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    const html=fs.readFileSync(path.join(temp,'report.html'));
    const result={status:'passed',browser:await browser.version(),html_sha256:crypto.createHash('sha256').update(html).digest('hex'),html_bytes:html.length,portable_file_offline:true,external_requests:0,trials_rendered:211,language_switch:true,search_and_filters:true,deep_links:true,embedded_download_hash:true,desktop_parallel_panels:true,mobile_stacked_panels:true,mobile_horizontal_overflow:false,issue_patch_independent_display:true,initial_load_ms:loadMs,initial_decoded_trials:initial.decodedCases.length,initial_decoded_assets:initial.decodedAssets.length,initial_decoded_stories:initial.decodedStories.length,initial_search_decoded:initial.searchDecoded,search_without_body_decoding:true,distant_trial_independent_decode:true,cancelled_bulk_trial_count:cancelled.decodedCases.length,bulk_expansion_cancelled:true,concurrent_chunk_deduplication:true,full_sources_deferred:true,coverage_tables:211,coverage_table_column_counts:columnCounts,coverage_table_row_counts:rowCounts,adaptive_coverage_tables:true,table_to_exact_trajectory_step:true,trajectory_step_navigation:true,trajectory_execution_feedback:true,trajectory_decode_cached:true,bulk_expansion_preserves_deferred_trajectories:true,mobile_trajectory_navigation:true,page_errors:errors,screenshots:['desktop-zh.png','desktop-en.png','mobile-zh.png','mobile-en.png','desktop-comparison.png','mobile-comparison.png','gap-table-desktop-en.png','gap-table-mobile-en.png','trajectory-desktop-en.png','trajectory-mobile-en.png']};
    fs.writeFileSync(path.join(output,'browser_checks.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result));
  } finally {await browser.close();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
