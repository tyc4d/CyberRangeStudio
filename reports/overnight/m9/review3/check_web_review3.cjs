// Execute actual production callback/calculations using synthetic data and no browser/network.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('/home/tyc4d/cr-project/apps/web/node_modules/typescript');
const root = path.resolve(__dirname, '../../../..');
const src = fs.readFileSync(path.join(root, 'apps/web/src/pages/PocPage.tsx'), 'utf8');
function body(begin, end) {
  const a = src.indexOf(begin);
  const b = src.indexOf(end, a + begin.length);
  if (a < 0 || b < 0) throw new Error('Production body not found');
  return src.slice(a + begin.length, b);
}
const calculate = new Function('plan', 'results', 'chain', 'report', body(
  'const fid = useMemo(() => {', '}, [plan, results, chain, report]);'));
const statusMap = new Function('chain', 'results', ts.transpileModule(body(
  'const statusByAction = useMemo(() => {', '}, [chain, results]);'),
  {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText);
const execute = new Function('api', 'ir', 'selected', 'abortRef', 'setStopped', 'setCancelling',
  'setLive', 'setResults', 'reportAct', 'setChain', 'setReport', `return (async () => {${body(
    'const execAct = useAction(async () => {', '\n  });\n  const exportAct') }})();`);
const stop = new Function('api', 'ir', 'abortRef', 'setCancelling', 'setStopped', 'setTimeout',
  `return (async () => {${body('const stop = async () => {', '\n  };\n  const liveResults')}})();`);
const liveResults = new Function('live', `return ${body(
  'const liveResults: ExecutionResult[] | null = ', '\n\n  // Per-action status')}`);

let passed = 0, failed = 0;
function check(name, condition, detail) {
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(detail)}`);
  condition ? passed++ : failed++;
}
const ids = ['a1', 'a2'];
const plan = {items: ids.map(action_id => ({action_id, strategy: 'poc_exec'}))};
const rawPass = ids.map(action_id => ({action_id, status: 'PASS'}));
const rawFail = ids.map(action_id => ({action_id, status: 'FAIL'}));
const goodChain = {passes: false, objective_reached: false,
  per_action: rawPass, transfers: []}; // Arithmetic individual PASSes never verify a chain.
const goodReport = {fidelity: {reproduced: ids, partial: [], not_reproduced: [], not_tested: []}};
const badReport = {fidelity: {reproduced: [], partial: [], not_reproduced: ids, not_tested: []}};

(async () => {
  check('control pending actions are unverified', calculate(plan, null, null, null).unverified.n === 2);
  check('control valid individual passes retain separate chain failure',
    calculate(plan, rawPass, goodChain, goodReport).chain.n === 0);
  // Re-run after a previously verified batch: execute callback updates raw results and report,
  // while it must invalidate/recompute the prior chain snapshot before treating it as current.
  const state = {chain: goodChain, report: goodReport, results: rawPass};
  const api = {poc: {execute: async () => rawFail}};
  await execute(api, {id: 'qa'}, new Set(ids), {current: null}, () => {}, () => {}, () => {},
    value => state.results = value, {run: async () => {state.report = badReport;}},
    value => state.chain = value, value => state.report = value);
  const now = calculate(plan, state.results, state.chain, state.report);
  check('failed rerun must not retain old chain PASSes in unverified metric', now.unverified.n === 2, now);
  const map = statusMap(state.chain, state.results);
  check('failed rerun action badges must not retain previous PASSes',
    ids.every(id => map.get(id) !== 'PASS'), [...map]);

  // Reverse disagreement: current chain invalidated evidence, but an older report was kept.
  const blockedChain = {...goodChain, per_action: ids.map(action_id => ({action_id, status: 'BLOCKED'}))};
  const disagreement = calculate(plan, rawPass, blockedChain, goodReport);
  check('stale reproduced report must not override current BLOCKED verification',
    disagreement.unverified.n === 2, disagreement);

  const currentStatus = {job_state: 'running', per_action: [{action_id: 'a1',
    stages: {started: true, delivered: false, responded: false, vuln_behavior: false,
      state_change: false, action_complete: false}}], logs_tail: ''};
  const rendered = liveResults(currentStatus);
  check('actual execute/status shape supplies visible live action stages',
    Array.isArray(rendered) && rendered.length === 1, {backend: currentStatus, liveResults: rendered});

  // Fresh terminal-state polling: accepted cancel must actually poll, persist through running,
  // and announce stopped only after terminal confirmation. Timer is synthetic and immediate.
  for (const mode of ['terminal', 'poll-error', 'never-terminal']) {
    const events = [];
    let polls = 0;
    const terminalApi = {poc: {
      executeCancel: async () => {events.push('cancel'); return {cancelled: true};},
      executeStatus: async () => {
        polls++;
        if (mode === 'poll-error') throw new Error('synthetic polling failure');
        const state = mode === 'terminal' && polls === 3 ? 'cancelled' : 'running';
        events.push(state);
        return {job_state: state};
      },
    }};
    await stop(terminalApi, {id: 'qa'}, {current: {abort: () => events.push('abort')}},
      v => events.push(`cancelling:${v}`), v => events.push(`stopped:${v}`),
      callback => {callback(); return 0;});
    check(`cancel polling is honest (${mode})`, mode === 'terminal'
      ? polls === 3 && events.indexOf('stopped:true') > events.indexOf('cancelled')
      : !events.includes('stopped:true'), {polls, events});
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})();
