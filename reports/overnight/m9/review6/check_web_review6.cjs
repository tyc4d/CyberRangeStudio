// Unchanged production callbacks, metrics and real ApiNotice retry construction.
// Deferred HTTP Promises only; no browser, server, network or LLM.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('/home/tyc4d/cr-project/apps/web/node_modules/typescript');
const root = path.resolve(__dirname, '../../../..');
const src = fs.readFileSync(path.join(root, 'apps/web/src/pages/PocPage.tsx'), 'utf8');
const ui = fs.readFileSync(path.join(root, 'apps/web/src/components/ui.tsx'), 'utf8');
function body(begin, end) {
  const a = src.indexOf(begin), b = src.indexOf(end, a + begin.length);
  if (a < 0 || b < 0) throw new Error('Production body not found: ' + begin);
  return src.slice(a + begin.length, b);
}
const calculate = new Function('plan', 'results', 'chain', 'report', body(
  'const fid = useMemo(() => {', '}, [plan, results, chain, report]);'));
const statusMap = new Function('chain', 'results', ts.transpileModule(body(
  'const statusByAction = useMemo(() => {', '}, [chain, results]);'),
  {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText);
const execute = new Function('api', 'ir', 'selected', 'abortRef', 'setStopped', 'setCancelling',
  'setLive', 'setResults', 'reportAct', 'setChain', 'setReport', `return (async () => {${body(
    'const execAct = useAction(async () => {', '\n  });\n  const exportAct')}})();`);
const chainCallback = new Function('api', 'ir', 'setChain', 'reportAct', `return (async () => {${body(
  'const chainAct = useAction(async () => {', '\n  });\n  const execAct')}})();`);
const reportCallback = new Function('api', 'ir', 'setReport', `return (async () => {${body(
  'const reportAct = useAction(async () => {', '});\n  const chainAct')}})();`);
const noticeSource = ui.slice(ui.indexOf('export function ApiNotice('), ui.indexOf('\nexport function Busy('))
  .replace(/^export /, '');
const noticeJS = ts.transpileModule(noticeSource, {compilerOptions: {
  target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React,
}}).outputText;
const ApiNotice = new Function('React', 'useT', 'Notice', 'TechDetails', 'validationMessages', 'knownErrorKey',
  noticeJS + '; return ApiNotice;')(
  {createElement: (type, props, ...children) => ({type, props: props || {}, children})},
  () => key => key, () => {}, () => {}, () => null, () => null);

let passed = 0, failed = 0;
function check(name, condition, detail) {
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(detail)}`);
  condition ? passed++ : failed++;
}
function deferred() {
  let resolve;
  const promise = new Promise(yes => {resolve = yes;});
  return {promise, resolve};
}
const ids = ['a1', 'a2'];
const plan = {items: ids.map(action_id => ({action_id, strategy: 'poc_exec'}))};
const rawPass = ids.map(action_id => ({action_id, status: 'PASS'}));
const rawFail = ids.map(action_id => ({action_id, status: 'FAIL'}));
const oldChain = {passes: false, objective_reached: false, per_action: rawPass, transfers: []};
const oldReport = {fidelity: {reproduced: ids, partial: [], not_reproduced: [], not_tested: []}};
const badReport = {fidelity: {reproduced: [], partial: [], not_reproduced: ids, not_tested: []}};
const initial = () => ({results: rawPass, chain: oldChain, report: oldReport});
const metric = s => calculate(plan, s.results, s.chain, s.report);
const badges = s => [...statusMap(s.chain, s.results).values()];
const noFalseVerification = s => metric(s).scenario.n === 0 && metric(s).unverified.n === 2;
function run(api, ir, s, reportAct) {
  return execute(api, ir, new Set(ids), {current: null}, () => {}, () => {}, () => {},
    value => s.results = value, reportAct, value => s.chain = value, value => s.report = value);
}

(async () => {
  // Ordinary UI path, no retry or programmatic click through a disabled button:
  // click chain, click execute while chain is still pending. The old chain response
  // is suppressed, but unconditionally launches a report read during the execute.
  // That report sees the old batch (R5 Python reachability control); its RESPONSE
  // arrives after execute + its newer report refresh have completed.
  {
    const ir = {id: 'normal-chain-then-execute'}, s = initial();
    const chain = deferred(), report = deferred(), execution = deferred();
    let reportReads = 0;
    const api = {poc: {chain: () => chain.promise, execute: () => execution.promise,
      report: () => ++reportReads === 1 ? report.promise : Promise.resolve(badReport)}};
    const reportAct = {run: () => reportCallback(api, ir, v => s.report = v)};
    const chainFlight = chainCallback(api, ir, v => s.chain = v, reportAct);
    const execFlight = run(api, ir, s, reportAct);
    chain.resolve(oldChain); await chainFlight;
    check('control older chain remains suppressed while execute is pending', s.chain === null, {chain: s.chain});
    console.log('OBSERVED report reads triggered by stale chain completion: ' + reportReads);
    execution.resolve(rawFail); await execFlight; await Promise.resolve();
    check('control execute and current report first show no verified actions', noFalseVerification(s), metric(s));
    report.resolve(oldReport); await Promise.resolve(); await Promise.resolve();
    check('late report begun during execute must not restore prior scenario verification', noFalseVerification(s),
      {metric: metric(s), results: s.results, reportReads});
  }

  // ApiNotice's existing error retry is another real path. Production constructs
  // an enabled retry button; the main chain button's execAct.busy guard does not
  // apply to this separate control. A prior report/chain error survives starting
  // execAct (each useAction owns its own error state).
  for (const kind of ['report', 'chain']) {
    const ir = {id: `retry-${kind}-during-execute`}, s = initial();
    const snapshot = deferred(), execution = deferred();
    let reportReads = 0;
    const api = {poc: {execute: () => execution.promise, chain: () => snapshot.promise,
      report: () => kind === 'report' && ++reportReads === 1 ? snapshot.promise : Promise.resolve(badReport)}};
    const reportAct = {run: () => reportCallback(api, ir, v => s.report = v)};
    const flight = run(api, ir, s, reportAct);
    const retry = ApiNotice({error: {kind: 'offline'}, what: kind,
      onRetry: kind === 'report' ? reportAct.run
        : () => chainCallback(api, ir, v => s.chain = v, reportAct)}).props.action;
    if (!retry || retry.props.disabled) {
      execution.resolve(rawFail); await flight; await Promise.resolve();
      check(`${kind} retry is prevented during execute`, noFalseVerification(s), metric(s));
      continue;
    }
    console.log(`OBSERVED ${kind} error retry is enabled during execute`);
    const retryFlight = retry.props.onClick();
    execution.resolve(rawFail); await flight; await Promise.resolve();
    check(`control ${kind} retry does not prevent execute storing FAIL`,
      s.results.every(r => r.status === 'FAIL') && noFalseVerification(s), metric(s));
    snapshot.resolve(kind === 'report' ? oldReport : oldChain); await retryFlight; await Promise.resolve();
    check(`late ${kind} retry snapshot cannot restore historical verification`, noFalseVerification(s),
      {metric: metric(s), badges: badges(s), results: s.results});
    if (kind === 'chain') check('late chain retry cannot restore historical PASS badges',
      !badges(s).includes('PASS'), badges(s));
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})().catch(error => {console.error(error); process.exitCode = 1;});
