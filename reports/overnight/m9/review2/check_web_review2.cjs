// Read and execute existing pure UI calculation/stop handler; no server/browser/API calls.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../../..');
const source = fs.readFileSync(path.join(root, 'apps/web/src/pages/PocPage.tsx'), 'utf8');
function body(beginText, endText) {
  const begin = source.indexOf(beginText);
  const end = source.indexOf(endText, begin + beginText.length);
  if (begin < 0 || end < 0) throw new Error('Existing production function was not found');
  return source.slice(begin + beginText.length, end);
}
const calculate = new Function('plan', 'results', 'chain', 'report', body(
  'const fid = useMemo(() => {', '}, [plan, results, chain, report]);'));
let passed = 0, failed = 0;
function check(name, condition, details) {
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(details)}`);
  if (condition) passed++; else failed++;
}
const plan = {items: ['a1', 'a2'].map(action_id => ({action_id, strategy:'poc_exec'}))};
const raw = ['a1','a2'].map(action_id => ({action_id, status:'PASS'}));
const partial = {passes:false, objective_reached:false, per_action: raw.map(r => ({...r, status:'PARTIAL'})), transfers:[]};
const report = {fidelity:{reproduced:[],partial:['a1','a2'],not_tested:[],not_reproduced:[]}};
const invalidated = calculate(plan, raw, partial, report);
check('unverified count includes artifact/identity-invalidated raw PASSes', invalidated.unverified.n === 2, invalidated);
check('unverified arithmetic chain remains zero of one', invalidated.chain.n === 0 && invalidated.chain.total === 1, invalidated.chain);
const pending = calculate(plan, null, null, null);
check('pending actions remain visible', pending.unverified.n === 2, pending.unverified);

const stopBody = body('const stop = async () => {', '\n  };\n  const liveResults');
const stop = new Function('api','ir','abortRef','setCancelling','setStopped', `return (async () => {${stopBody}})();`);
(async () => {
  for (const mode of ['request-failed', 'cancel-rejected', 'cancel-requested']) {
    const calls = [];
    const api = {poc:{executeCancel: async () => {
      calls.push('cancel');
      if (mode === 'request-failed') throw new Error('Synthetic network error');
      return {cancelled: mode === 'cancel-requested'};
    }}};
    await stop(api, {id:'qa'}, {current:{abort:() => calls.push('abort')}},
      v => calls.push(`cancelling:${v}`), v => calls.push(`stopped:${v}`));
    // No terminal job state or cleanup proof has been supplied in any of these cases.
    check(`stop does not announce stopped without terminal confirmation (${mode})`,
      !calls.includes('stopped:true'), calls);
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})();
