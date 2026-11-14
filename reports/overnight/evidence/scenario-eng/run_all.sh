#!/bin/sh
# Re-run every real-LLM evidence case with the current branch code. Usage: run_all.sh <out subdir>
P=/home/tyc4d/cr-project/.venv/bin/python; E=reports/overnight/evidence/scenario-eng
C=/home/tyc4d/cr-project/.worktrees/cti-research/fixtures/cti-candidates
Q=/home/tyc4d/cr-project/.worktrees/qa-admin/reports/overnight/evidence/qa-admin/round1
OUT=$E/$1
for c in aa22-320a-log4shell-horizon equifax-2017-struts-db aa23-158a-clop-moveit negative-insufficient-intel aa24-046a-former-employee-account; do
  echo "## $c"; $P $E/run_real.py $C/$c/report.md markdown single_pass $OUT/$c $c 2>&1 | tail -1
done
echo "## cisa-sample"; $P $E/run_real.py fixtures/sample-scenarios/cisa-aa22-320a.md markdown single_pass $OUT/cisa-aa22-320a-sample 2>&1 | tail -1
echo "## clop-sample"; $P $E/run_real.py fixtures/sample-scenarios/clop-moveit-advisory.md markdown single_pass $OUT/clop-moveit-sample 2>&1 | tail -1
echo "## stix-demo"; $P $E/run_real.py fixtures/sample-scenarios/demo-intrusion.stix.json stix2.1 single_pass $OUT/demo-intrusion-stix 2>&1 | tail -1
echo "## qa-admin-lifecycle"; $P $E/run_real.py $Q/admin-lifecycle-fixture.md markdown single_pass $OUT/qa-admin-lifecycle 2>&1 | tail -1
