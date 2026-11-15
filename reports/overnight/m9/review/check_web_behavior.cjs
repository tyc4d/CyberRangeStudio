// Execute only the existing pure fidelity calculation; no browser, server, or API calls.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../../..');
const source = fs.readFileSync(path.join(root, 'apps/web/src/pages/PocPage.tsx'), 'utf8');
const begin = source.indexOf('const fid = useMemo(() => {') + 'const fid = useMemo(() => {'.length;
const end = source.indexOf('}, [plan, results, chain, report]);', begin);
if (begin < 26 || end < begin) throw new Error('fidelity calculation not found');
const calculate = new Function('plan', 'results', 'chain', 'report', source.slice(begin, end));
const plan = {items: [{action_id:'a1',strategy:'poc_exec'}, {action_id:'a2',strategy:'poc_exec'}]};
const independentPasses = [{action_id:'a1',status:'PASS'}, {action_id:'a2',status:'PASS'}];
const brokenChain = {passes:false, objective_reached:false, per_action:independentPasses,
  transfers:[{verified:false}]};
let failures = 0;
function check(name, safe, detail) {
  console.log(`${safe ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(detail)}`);
  if (!safe) failures++;
}
const broken = calculate(plan, independentPasses, brokenChain, null);
check('five metrics remain separate', ['deploy','vuln','chain','scenario','unverified'].every(k => k in broken), Object.keys(broken));
check('failed full chain is not shown as 2/2 passed', broken.chain.n !== broken.chain.total, {passes:brokenChain.passes,display:broken.chain});
const pending = calculate(plan, null, null, null);
check('not yet executed actions are counted as unverified', pending.unverified.n === 2, pending.unverified);
const noVerifier = calculate(plan, [], null, {fidelity:{not_tested:['a1','a2']}});
check('skipped actions remain visible as unverified', noVerifier.unverified.n === 2, noVerifier.unverified);
console.log(`${4 - failures} passed, ${failures} failed`);
process.exitCode = failures ? 1 : 0;
