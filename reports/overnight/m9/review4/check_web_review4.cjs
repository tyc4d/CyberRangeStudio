// Execute unchanged production callbacks and metric/status calculations; no browser/network.
// Deferred Promises model ordinary in-flight HTTP requests and delayed responses.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('/home/tyc4d/cr-project/apps/web/node_modules/typescript');
const root = path.resolve(__dirname, '../../../..');
const src = fs.readFileSync(path.join(root, 'apps/web/src/pages/PocPage.tsx'), 'utf8');
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

let passed = 0, failed = 0;
function check(name, condition, detail) {
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(detail)}`);
  condition ? passed++ : failed++;
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
const ids = ['a1', 'a2'];
const ir = {id: 'synthetic-final-gate'};
const plan = {items: ids.map(action_id => ({action_id, strategy: 'poc_exec'}))};
const rawPass = ids.map(action_id => ({action_id, status: 'PASS'}));
const rawFail = ids.map(action_id => ({action_id, status: 'FAIL'}));
const goodChain = {passes: false, objective_reached: false, per_action: rawPass, transfers: []};
const blockedChain = {...goodChain, per_action: ids.map(action_id => ({action_id, status: 'BLOCKED'}))};
const goodReport = {fidelity: {reproduced: ids, partial: [], not_reproduced: [], not_tested: []}};
const badReport = {fidelity: {reproduced: [], partial: [], not_reproduced: ids, not_tested: []}};
const initial = () => ({results: rawPass, chain: goodChain, report: goodReport});
const metric = state => calculate(plan, state.results, state.chain, state.report);
const badges = state => [...statusMap(state.chain, state.results).values()];
const noPassMetric = state => {
  const f = metric(state);
  return (f.vuln?.n ?? 0) === 0 && (f.scenario?.n ?? 0) === 0 && f.unverified.n === 2;
};
function run(api, state, refresh = async () => {state.report = badReport;}) {
  return execute(api, ir, new Set(ids), {current: null}, () => {}, () => {}, () => {},
    value => state.results = value, {run: refresh},
    value => state.chain = value, value => state.report = value);
}

(async () => {
  const control = initial();
  check('valid historical individual proof is represented before rerun',
    metric(control).vuln.n === 2 && metric(control).chain.n === 0 && metric(control).unverified.n === 0,
    metric(control));

  // A rerun is already pending at the backend. Inspect state before its response arrives.
  const pending = deferred(), state = initial();
  const flight = run({poc: {execute: () => pending.promise}}, state);
  check('in-flight rerun invalidates prior vulnerability/scenario PASS counters', noPassMetric(state), metric(state));
  check('in-flight rerun must not retain prior action PASS badges', !badges(state).includes('PASS'), badges(state));
  pending.reject(new Error('synthetic cancelled/network failure'));
  await flight.catch(() => {});
  check('failed/aborted request does not leave prior PASS counters as current', noPassMetric(state), metric(state));
  check('failed/aborted request does not leave prior action PASS badges', !badges(state).includes('PASS'), badges(state));

  // Execute completion succeeds, but the refresh fails: the old raw results must not hide
  // the new failures. This is a control that current code does handle.
  const ordinary = initial();
  await run({poc: {execute: async () => rawFail}}, ordinary, async () => {});
  check('completed failing rerun without refresh never uses raw prior PASS', noPassMetric(ordinary), metric(ordinary));

  // The actual chain callback accepts a new BLOCKED roll-up and starts an asynchronous
  // report refresh. Until that refresh returns, scenario fidelity still has its old PASSes.
  const disagreement = initial(), refresh = deferred();
  await chainCallback({poc: {chain: async () => blockedChain}}, ir,
    value => disagreement.chain = value, {run: () => refresh.promise});
  check('current BLOCKED verification overrides stale report scenario-reproduced count',
    metric(disagreement).scenario.n === 0, metric(disagreement));
  refresh.resolve();

  // A prior GET /report is in flight. New execute + new report complete first;
  // the older response then arrives and overwrites the new report state.
  const oldReport = deferred(), reportRace = initial();
  const reportFlight = reportCallback({poc: {report: () => oldReport.promise}}, ir,
    value => reportRace.report = value);
  await run({poc: {execute: async () => rawFail}}, reportRace);
  oldReport.resolve(goodReport);
  await reportFlight;
  check('late report from preceding run cannot restore reproduced/unverified PASS counts',
    noPassMetric(reportRace), metric(reportRace));

  // A chain request issued before rerun can also return after the failing rerun.
  const oldChain = deferred(), chainRace = initial();
  const chainFlight = chainCallback({poc: {chain: () => oldChain.promise}}, ir,
    value => chainRace.chain = value, {run: async () => {chainRace.report = badReport;}});
  await run({poc: {execute: async () => rawFail}}, chainRace);
  oldChain.resolve(goodChain);
  await chainFlight;
  check('late chain from preceding run cannot restore action PASS badges',
    !badges(chainRace).includes('PASS'), {badges: badges(chainRace), results: chainRace.results});
  check('late chain from preceding run cannot remove newly failed actions from unverified count',
    metric(chainRace).unverified.n === 2, metric(chainRace));

  console.log(`${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})().catch(error => {console.error(error); process.exitCode = 1;});
