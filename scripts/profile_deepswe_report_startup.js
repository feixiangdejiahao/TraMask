// Profile the portable report without depending on a web server or external assets.
// Usage: node scripts/profile_deepswe_report_startup.js FILE.html OUTPUT.json
// DEEPSWE_PLAYWRIGHT_MODULE and PLAYWRIGHT_BROWSERS_PATH may select an existing installation.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.DEEPSWE_PLAYWRIGHT_MODULE || 'playwright');

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

async function sample(browser, file, cpuRate, ordinal) {
  const context = await browser.newContext({viewport: {width: 1440, height: 1080}, offline: true});
  const page = await context.newPage();
  const errors = [], externalRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (/^https?:/.test(request.url())) externalRequests.push(request.url()); });
  await context.addInitScript(() => {
    const state = window.__startupProfile = {json_parses: [], long_tasks: [], controls_ready_ms: null, first_trial_ready_ms: null};
    const parse = JSON.parse;
    JSON.parse = function (...args) {
      const start = performance.now();
      try { return Reflect.apply(parse, this, args); }
      finally { state.json_parses.push({start_ms: start, duration_ms: performance.now() - start, characters: typeof args[0] === 'string' ? args[0].length : null}); }
    };
    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) state.long_tasks.push({start_ms: entry.startTime, duration_ms: entry.duration});
      }).observe({type: 'longtask', buffered: true});
    } catch {}
    function check() {
      const query = document.getElementById('query'), language = document.getElementById('language-toggle');
      const shown = document.getElementById('shown');
      if (state.controls_ready_ms === null && query && language && shown && /(?:Showing|显示)\s*211\s*\//.test(shown.textContent) && !query.disabled && !language.disabled && query.getClientRects().length && language.getClientRects().length) state.controls_ready_ms = performance.now();
      if (state.first_trial_ready_ms === null && document.querySelector('.trial .comparison')) state.first_trial_ready_ms = performance.now();
    }
    new MutationObserver(check).observe(document, {childList: true, subtree: true, attributes: true});
    document.addEventListener('DOMContentLoaded', check);
  });
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: cpuRate});
  await cdp.send('Performance.enable');
  const wallStart = performance.now();
  try {
    await page.goto(pathToFileURL(file).href, {waitUntil: 'load', timeout: 120000});
    await page.waitForFunction(() => window.__startupProfile?.controls_ready_ms !== null && window.__startupProfile?.first_trial_ready_ms !== null, null, {timeout: 120000});
    // Give buffered paint and long-task entries a chance to arrive before sampling.
    await page.waitForTimeout(300);
    const captured = await page.evaluate(() => {
      const state = window.__startupProfile;
      const cutoff = Math.max(state.controls_ready_ms, state.first_trial_ready_ms);
      return {
        ...state,
        startup_cutoff_ms: cutoff,
        json_parses: state.json_parses.filter(item => item.start_ms <= cutoff),
        long_tasks: state.long_tasks.filter(item => item.start_ms <= cutoff),
        paints: Object.fromEntries(performance.getEntriesByType('paint').map(item => [item.name, item.startTime])),
        navigation: performance.getEntriesByType('navigation').map(item => ({dom_content_loaded_ms: item.domContentLoadedEventEnd, load_ms: item.loadEventEnd, response_end_ms: item.responseEnd}))[0],
        dom_nodes: document.querySelectorAll('*').length,
        comparison_panels: document.querySelectorAll('.comparison').length,
        decoding: window.__deepswePerformance ? {
          trials: window.__deepswePerformance.decodedCases.length,
          sources: window.__deepswePerformance.decodedAssets.length,
          trajectories: window.__deepswePerformance.decodedStories.length,
          search_index: window.__deepswePerformance.searchDecoded,
        } : null,
        memory: performance.memory ? {js_heap_used_bytes: performance.memory.usedJSHeapSize, js_heap_total_bytes: performance.memory.totalJSHeapSize} : null,
      };
    });
    // Validate that the measured controls actually respond, after collecting startup data.
    await page.locator('#language-toggle').click();
    await page.waitForFunction(() => document.documentElement.lang === 'en' && /^Showing\s*211\s*\//.test(document.getElementById('shown').textContent));
    await page.locator('#query').fill('zzzz_no_matching_trial_zzzz');
    await page.waitForFunction(() => document.getElementById('empty')?.hidden === false);
    const metrics = await cdp.send('Performance.getMetrics');
    const heap = metrics.metrics.find(item => item.name === 'JSHeapUsedSize')?.value;
    return {
      ordinal, cpu_throttling_rate: cpuRate,
      ...captured,
      json_parse_total_ms: captured.json_parses.reduce((sum, item) => sum + item.duration_ms, 0),
      json_parse_longest_ms: Math.max(0, ...captured.json_parses.map(item => item.duration_ms)),
      json_parse_max_characters: Math.max(0, ...captured.json_parses.map(item => item.characters || 0)),
      long_task_total_ms: captured.long_tasks.reduce((sum, item) => sum + item.duration_ms, 0),
      longest_task_ms: Math.max(0, ...captured.long_tasks.map(item => item.duration_ms)),
      cdp_js_heap_after_controls_bytes: heap ?? null,
      controls_functional: true, external_requests: externalRequests, page_errors: errors,
      harness_elapsed_ms: performance.now() - wallStart,
    };
  } finally { await context.close(); }
}

(async () => {
  const [fileArgument, outputArgument] = process.argv.slice(2);
  if (!fileArgument || !outputArgument) throw new Error('Usage: node scripts/profile_deepswe_report_startup.js FILE.html OUTPUT.json');
  const file = path.resolve(fileArgument), output = path.resolve(outputArgument), html = fs.readFileSync(file);
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox'], ...(process.env.DEEPSWE_CHROMIUM_EXECUTABLE ? {executablePath: process.env.DEEPSWE_CHROMIUM_EXECUTABLE} : {})});
  const result = {
    measured_at: new Date().toISOString(), file, html_bytes: html.length,
    html_sha256: crypto.createHash('sha256').update(html).digest('hex'),
    browser: await browser.version(),
    method: 'Eight independent offline browser contexts, alternating CPU rates (five 1x and three 4x); browser launch excluded. MutationObserver readiness checks include layout reads. Parse instrumentation records time spent inside JSON.parse. Long tasks overlap startup through the later readiness marker. Browser caches are not artificially flushed between samples. Functional language/search checks run after startup capture. Timings describe this machine and are not a universal latency guarantee.',
    definitions: {controls_ready_ms: 'Visible enabled search and language controls with an initialized 211-trial result count.', first_trial_ready_ms: 'First trial comparison DOM inserted; paint is reported separately.'},
    samples: [], summary: {},
  };
  try {
    const rates = [1, 4, 1, 4, 1, 4, 1, 1];
    for (let index = 0; index < rates.length; index++) {
      const row = await sample(browser, file, rates[index], index + 1);
      result.samples.push(row);
      console.log(JSON.stringify({sample: index + 1, cpu: rates[index], controls_ms: row.controls_ready_ms, first_trial_ms: row.first_trial_ready_ms, parse_ms: row.json_parse_total_ms}));
    }
    for (const rate of [1, 4]) {
      const rows = result.samples.filter(item => item.cpu_throttling_rate === rate), metrics = {};
      for (const field of ['controls_ready_ms', 'first_trial_ready_ms', 'json_parse_total_ms', 'json_parse_longest_ms', 'json_parse_max_characters', 'long_task_total_ms', 'longest_task_ms', 'dom_nodes', 'cdp_js_heap_after_controls_bytes']) {
        const values = rows.map(item => item[field]).filter(Number.isFinite);
        metrics[field] = {median: median(values), min: values.length ? Math.min(...values) : null, max: values.length ? Math.max(...values) : null};
      }
      result.summary[`cpu_${rate}x`] = {samples: rows.length, ...metrics};
    }
    if (result.samples.some(item => item.page_errors.length || item.external_requests.length)) throw new Error('Report produced errors or external requests; inspect individual samples.');
    if (result.samples.some(item => item.decoding && (item.decoding.trials !== 1 || item.decoding.sources !== 0 || item.decoding.trajectories !== 0 || item.decoding.search_index))) throw new Error('Startup decoded evidence beyond the first trial.');
    result.status = 'passed';
  } catch (error) { result.status = 'failed'; result.error = error.stack; process.exitCode = 1; }
  finally {
    fs.mkdirSync(path.dirname(output), {recursive: true});
    fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
    await browser.close();
    console.log(JSON.stringify({status: result.status, output, summary: result.summary}));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
