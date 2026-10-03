/* Compare source-control and generated test types without executing either. */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const ts = require(require.resolve('typescript', {paths: [process.cwd()]}));
const plan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const target = path.resolve(plan.target);
const configPath = ts.findConfigFile(path.dirname(target), ts.sys.fileExists, 'tsconfig.json');
if (!configPath) throw new Error('No containing TypeScript configuration');
const config = ts.readConfigFile(configPath, ts.sys.readFile);
if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, '\n'));
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, path.dirname(configPath));
const options = {...parsed.options, noEmit: true, incremental: false, composite: false};
const roots = [...new Set([...parsed.fileNames, target])];
function relative(file) { return path.relative(process.cwd(), path.resolve(file)); }
function compact(text, limit = 3000) {
  return {text: text.slice(0, limit), omitted_chars: Math.max(0, text.length - limit)};
}
function run(phase) {
  const overlays = new Map(phase.files.map(row => [path.resolve(row.target), fs.readFileSync(row.staged, 'utf8')]));
  const host = ts.createCompilerHost(options, true);
  const readFile = host.readFile.bind(host);
  host.readFile = file => overlays.has(path.resolve(file)) ? overlays.get(path.resolve(file)) : readFile(file);
  host.getSourceFile = (file, languageVersion, onError) => {
    const text = host.readFile(file);
    if (text === undefined) { if (onError) onError('Cannot read ' + file); return undefined; }
    return ts.createSourceFile(file, text, languageVersion, true);
  };
  const program = ts.createProgram({rootNames: roots, options, host});
  const source = program.getSourceFile(target);
  if (!source) throw new Error('Target source was not compiled');
  const checker = program.getTypeChecker();
  const names = new Set(plan.test_names);
  const regions = [];
  function locate(node) {
    if (ts.isCallExpression(node) && node.arguments.length && ts.isStringLiteralLike(node.arguments[0])
        && names.has(node.arguments[0].text)) {
      regions.push({name: node.arguments[0].text, start: node.getStart(source), end: node.end});
    }
    ts.forEachChild(node, locate);
  }
  locate(source);
  if (!regions.length) throw new Error('No exact generated test-name region in source');
  const inRegion = (start, end) => regions.some(row => row.start <= start && end <= row.end);
  const diagnostics = [...program.getSyntacticDiagnostics(source), ...program.getSemanticDiagnostics(source)]
    .filter(row => row.start !== undefined && inRegion(row.start, row.start + (row.length || 0)))
    .map(row => ({code: row.code, category: ts.DiagnosticCategory[row.category],
      message: ts.flattenDiagnosticMessageText(row.messageText, '\n'),
      start_utf16: row.start, end_utf16: row.start + (row.length || 0),
      line: source.getLineAndCharacterOfPosition(row.start).line + 1,
      source: source.text.slice(row.start, row.start + (row.length || 0))}));
  const calls = [];
  function visit(node) {
    if (ts.isCallExpression(node) && inRegion(node.getStart(source), node.end)) {
      const signature = checker.getResolvedSignature(node);
      const declaration = signature && signature.getDeclaration();
      const info = {source: compact(node.getText(source)), start_utf16: node.getStart(source), end_utf16: node.end,
        callee: node.expression.getText(source), resolved: Boolean(declaration),
        return_type: compact(checker.typeToString(checker.getTypeAtLocation(node))),
        arguments: node.arguments.map(argument => {
          const type = checker.getTypeAtLocation(argument);
          return {source: compact(argument.getText(source)), type: compact(checker.typeToString(type)),
            is_any: Boolean(type.flags & ts.TypeFlags.Any), is_unknown: Boolean(type.flags & ts.TypeFlags.Unknown)};
        })};
      if (signature) info.signature = compact(checker.signatureToString(signature));
      if (declaration) {
        const owner = declaration.getSourceFile();
        const start = declaration.getStart(owner);
        const end = declaration.body ? declaration.body.getStart(owner) : declaration.end;
        info.declaration = {path: relative(owner.fileName), source_sha256: sha(owner.text),
          start_utf16: start, end_utf16: end, header: compact(owner.text.slice(start, end))};
      }
      calls.push(info);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return {role: phase.role, source_sha256: sha(source.text), regions, diagnostics, calls,
    options_diagnostics: program.getOptionsDiagnostics().map(row => ({code: row.code,
      message: ts.flattenDiagnosticMessageText(row.messageText, '\n')})),
    loaded_sources: program.getSourceFiles().map(row => ({path: relative(row.fileName), sha256: sha(row.text)}))};
}
const phases = plan.phases.map(run);
const before = phases.find(row => row.role === 'control');
const after = phases.find(row => row.role === 'generated');
if (!before || !after) throw new Error('A control/generated pair is required');
const fingerprint = row => JSON.stringify([row.code, row.category, row.message, row.source]);
const remaining = new Map();
before.diagnostics.forEach(row => remaining.set(fingerprint(row), (remaining.get(fingerprint(row)) || 0) + 1));
const added = after.diagnostics.filter(row => {
  const key = fingerprint(row), count = remaining.get(key) || 0;
  if (count) { remaining.set(key, count - 1); return false; }
  return true;
});
const result = {version: 'typescript-paired-source-diagnostics.v1', status: 'compiler_completed',
  typescript_version: ts.version, compiler_module: require.resolve('typescript', {paths: [process.cwd()]}),
  configuration: {path: relative(configPath), sha256: sha(fs.readFileSync(configPath)),
    parse_errors: parsed.errors.map(row => ({code: row.code, message: ts.flattenDiagnosticMessageText(row.messageText, '\n')}))},
  target: relative(target), test_names: plan.test_names, phases, new_diagnostics: added,
  program_execution: false,
  limitation: 'Types describe the candidate API and may themselves be buggy. New diagnostics are counterevidence, not an independent proof that a test is invalid.'};
fs.writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({status: result.status, typescript_version: ts.version,
  baseline_diagnostics: before.diagnostics.length, generated_diagnostics: after.diagnostics.length,
  new_diagnostics: added.length}) + '\n');
