// Run production callbacks, fidelity and status maps; no React/browser/network.
// A later chain request can finish while a newer execute POST is still in transit.
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
const stop = new Function('api', 'ir', 'abortRef', 'setStopped', 'setCancelling', 'setTimeout',
  `return (async () => {${body('const stop = async () => {', '\n  };\n  const liveResults')}})();`);

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
const plan = {items: ids.map(action_id => ({action_id, strategy: 'poc_exec'}))};
const rawPass = ids.map(action_id => ({action_id, status: 'PASS'}));
const rawFail = ids.map(action_id => ({action_id, status: 'FAIL'}));
const rawBlocked = ids.map(action_id => ({action_id, status: 'BLOCKED'}));
// Genuine historical individual evidence is compatible with chain.passes=false.
const oldChain = {passes: false, objective_reached: false, per_action: rawPass, transfers: []};
const oldReport = {fidelity: {reproduced: ids, partial: [], not_reproduced: [], not_tested: []}};
const badReport = {fidelity: {reproduced: [], partial: [], not_reproduced: ids, not_tested: []}};
function initial() {return {results: rawPass, chain: oldChain, report: oldReport};}
function metric(s) {return calculate(plan, s.results, s.chain, s.report);}
function badges(s) {return [...statusMap(s.chain, s.results).values()];}
function run(api, ir, s, reportAct) {
  return execute(api, ir, new Set(ids), {current: null}, () => {}, () => {}, () => {},
    v => s.results = v, reportAct, v => s.chain = v, v => s.report = v);
}

(async () => {
  // Control: a response from a request started BEFORE the execute remains suppressed.
  {
    const ir = {id: 'same-ir-control'}, s = initial(), old = deferred();
    const flight = chainCallback({poc: {chain: () => old.promise}}, ir, v => s.chain = v, {run: async () => {}});
    await run({poc: {execute: async () => rawFail}}, ir, s, {run: async () => {s.report = badReport;}});
    old.resolve(oldChain); await flight;
    check('older chain request stays suppressed (R4 control)', !badges(s).includes('PASS'), {badges: badges(s)});
  }

  // Reachable UI order: execute click, then chain click (button only checks chainAct.busy).
  // The execute request has not reached run_job yet. Chain/report read the prior valid batch.
  // The new execute subsequently completes with FAIL, which must supersede those old snapshots.
  {
    const ir = {id: 'chain-after-execute-click'}, s = initial(), pending = deferred();
    let refreshes = 0;
    const api = {poc: {execute: () => pending.promise, chain: async () => oldChain,
      report: async () => (++refreshes === 1 ? oldReport : badReport)}};
    const reportAct = {run: () => reportCallback(api, ir, v => s.report = v)};
    const flight = run(api, ir, s, reportAct);
    await chainCallback(api, ir, v => s.chain = v, reportAct);
    await Promise.resolve();
    pending.resolve(rawFail); await flight; await Promise.resolve();
    check('completed newer execute retains its actual FAIL results after intervening chain/report',
      s.results?.every(r => r.status === 'FAIL') === true, {results: s.results, refreshes});
    check('chain/report issued during execute cannot leave historical PASS badges after FAIL response',
      !badges(s).includes('PASS'), {badges: badges(s)});
    check('historical chain/report cannot leave reproduced=2 and unverified=0 after FAIL response',
      metric(s).scenario.n === 0 && metric(s).unverified.n === 2, metric(s));
  }

  // A later request even invalidates execute when it FAILS and produces no usable snapshot.
  {
    const ir = {id: 'chain-error-during-execute'}, s = initial(), pending = deferred();
    const flight = run({poc: {execute: () => pending.promise}}, ir, s, {run: async () => {s.report = badReport;}});
    await chainCallback({poc: {chain: async () => {throw new Error('synthetic chain request failure');}}},
      ir, v => s.chain = v, {run: async () => {}}).catch(() => {});
    pending.resolve(rawBlocked); await flight;
    check('failed intervening chain request does not discard completed BLOCKED execution result',
      s.results?.every(r => r.status === 'BLOCKED') === true, {results: s.results, metric: metric(s)});
  }

  // Job identity controls against historical cancelled jobs and a newer unrelated terminal job.
  {
    const snapshots = [
      {job_state: 'running', jobs: [
        {job_id: 'historical', state: 'cancelled', cancel_requested: true},
        {job_id: 'target', state: 'running', cancel_requested: true},
        {job_id: 'newer', state: 'done', cancel_requested: false}],
        active_jobs: [{job_id: 'target', state: 'running'}]},
      {job_state: 'done', jobs: [
        {job_id: 'historical', state: 'cancelled', cancel_requested: true},
        {job_id: 'target', state: 'cancelled', cancel_requested: true},
        {job_id: 'newer', state: 'done', cancel_requested: false}], active_jobs: []},
    ];
    let polls = 0, stoppedAt = null;
    await stop({poc: {executeCancel: async () => ({cancelled: true}),
      executeStatus: async () => snapshots[polls++]}}, {id: 'identity-control'}, {current: {abort() {}}},
      value => {if (value) stoppedAt = polls;}, () => {}, resolve => resolve());
    check('historical cancelled job and newer done do not hide active cancelled target', stoppedAt === 2,
      {polls, stoppedAt});
  }
  {
    let stopped = false;
    await stop({poc: {executeCancel: async () => ({cancelled: true}), executeStatus: async () => ({
      job_state: 'done', jobs: [{job_id: 'target', state: 'done', cancel_requested: true}],
      active_jobs: [{job_id: 'target', state: 'running'}]})}}, {id: 'inconsistent-control'},
      {current: {abort() {}}}, value => {stopped ||= value;}, () => {}, resolve => resolve());
    check('active identity blocks contradictory terminal status', !stopped, {stopped});
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})().catch(error => {console.error(error); process.exitCode = 1;});
