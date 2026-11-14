#!/usr/bin/env bash
# End-to-end demo: CTI report -> analysis -> dependencies -> topology -> IaC -> deploy -> validate -> teardown.
# Requires the API running on $API (default 8077) with a real OPENAI_API_KEY, and local Docker.
# Honest by design: it reproduces the ENVIRONMENT and benign connectivity, not real exploits.
set -u
API="${API:-http://localhost:8077}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPORT="${REPORT:-$ROOT/fixtures/sample-scenarios/demo-intrusion.md}"
OUT="${OUT:-$ROOT/docs/e2e-evidence}"
mkdir -p "$OUT"
jqp() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

say() { printf '\n=== %s ===\n' "$1"; }

say "1. analyze"
CONTENT=$(python3 -c "import json;print(json.dumps(open('$REPORT').read()))")
ID=$(curl -s -X POST "$API/api/ingest/analyze" -H 'Content-Type: application/json' \
  -d "{\"input_kind\":\"markdown\",\"method\":\"single_pass\",\"name\":\"e2e demo\",\"content\":$CONTENT}" \
  | tee "$OUT/01-analysis.json" | jqp "d['id']")
echo "scenario=$ID"
curl -s "$API/api/scenario/$ID" | jqp "'actions=%d relations=%s'%(len(d['actions']),[r['kind'] for r in d['relations']])"

say "2. confirm dependency relations (analyst step, module 3)"
# Confirm each dependency relation so topology may open the lateral path (temporal never opens one).
curl -s "$API/api/scenario/$ID" > "$OUT/_ir.json"
python3 - "$ID" "$API" <<'PY'
import json,sys,urllib.request
sid,api=sys.argv[1],sys.argv[2]
ir=json.load(open(f"{__import__('os').environ.get('OUT','.')}/_ir.json")) if False else json.load(open("docs/e2e-evidence/_ir.json"))
for r in ir.get("relations",[]):
    if r.get("kind")=="dependency":
        body=json.dumps({"confirmed":True}).encode()
        req=urllib.request.Request(f"{api}/api/scenario/{sid}/relations/{r['id']}",data=body,method="PATCH",
                                   headers={"Content-Type":"application/json"})
        try: urllib.request.urlopen(req); print("confirmed",r['id'])
        except Exception as e: print("confirm failed",r['id'],e)
PY

say "3. dependencies"
curl -s -X POST "$API/api/planning/$ID/dependencies" | tee "$OUT/03-dependencies.json" \
  | jqp "'services=%s'%[(s.get('name'),s.get('catalogue_component'),s.get('is_substitute')) for s in (d.get('scenario',d.get('ir',d)).get('services',[]))]"

say "4. topology"
curl -s -X POST "$API/api/planning/$ID/topology" | tee "$OUT/04-topology.json" \
  | jqp "'nets=%s conns=%s'%([(n['id'],n.get('internal')) for n in d.get('scenario',d.get('ir',d)).get('environment_plan',{}).get('networks',[])],[(c['from_host'],c['to_host'],c.get('port')) for c in d.get('scenario',d.get('ir',d)).get('environment_plan',{}).get('connections',[])])"

say "4b. approve topology (human gate; deployment is refused without it)"
curl -s -X POST "$API/api/planning/$ID/topology/approve" -H 'Content-Type: application/json' \
  -d '{"approved":true,"approved_by":"e2e-demo","note":"approved for local isolated PoC"}' \
  | jqp "'approved=%s digest=%s'%(d.get('approval',{}).get('approved'),d.get('approval',{}).get('connections_digest','')[:12])"

say "5. IaC generate"
curl -s -X POST "$API/api/iac/$ID/generate" | tee "$OUT/05-iac.json" >/dev/null
curl -s "$API/api/iac/$ID" | python3 -c "import sys,json,re;d=json.load(sys.stdin);c=d.get('compose','') or d.get('compose_yaml','');open('docs/e2e-evidence/05-docker-compose.yml','w').write(c);print('images:',sorted(set(re.findall(r'image:\s*(\S+)',c))))"

say "6. deploy up (requires images present locally)"
curl -s -X POST "$API/api/deploy/$ID/up" -H 'Content-Type: application/json' -d '{"test_approved":true}' \
  | tee "$OUT/06-deploy-up.json" | jqp "'state=%s'%d.get('state')"
# wait (up to ~40s) for containers to report healthy before validating
for i in $(seq 1 20); do
  H=$(curl -s "$API/api/deploy/$ID/health" | jqp "d.get('healthy')")
  [ "$H" = "True" ] && break; sleep 2
done
curl -s "$API/api/deploy/$ID/health" | tee "$OUT/06-health.json" | jqp "'healthy=%s containers=%s'%(d.get('healthy'),[(c.get('name'),c.get('state'),c.get('health')) for c in d.get('containers',[])])"

say "7. validate (benign checks)"
curl -s -X POST "$API/api/validate/$ID/run" | tee "$OUT/07-validation.json" \
  | jqp "'levels=%s'%d.get('levels')"

say "8. teardown"
curl -s -X POST "$API/api/deploy/$ID/down" | jqp "'down state=%s'%d.get('state')"
echo "scenario_id=$ID" > "$OUT/scenario_id.txt"
echo "evidence in $OUT"
