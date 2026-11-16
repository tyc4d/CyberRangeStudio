"""Independent M9 QA: contract assertions, no network/LLM/deployment/payload execution.

Run from apps/api with this worktree's contracts on PYTHONPATH and pytest -p no:cacheprovider.
Failures are deliberately visible regression evidence, not xfails. Artifacts are memory-only.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock
import zipfile
from urllib.error import HTTPError

import pytest
import yaml

from cr_contracts import iter_errors_shape
from app import config
from app.deploy import manager
from app.deploy.backends import local_docker
from app.iac import generator
from app.iac.test_generator import EXPOSED_PLAN
from app.poc import service, store as poc_store
from app.poc.chain.evidence import verify_execution
from app.poc.chain.validation import validate_chain
from app.poc.discovery.engine import DiscoveryEngine
from app.poc.discovery.ranking import score_candidate
from app.poc.export import bundle as B
from app.poc.runner import guard, runner, payloads
from app.poc.runner.models import ExecutionRequest

SID = 'm9-review-fixture'


@pytest.fixture(autouse=True)
def no_external_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('QA forbids real subprocess/network/runtime calls')
    monkeypatch.setattr('subprocess.run', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    monkeypatch.setattr(manager, '_pve_guest_exec', forbidden)
    monkeypatch.setattr(runner, '_write_artifact', lambda p, s: hashlib.sha256(s.encode()).hexdigest())


def request(action='a1', **updates):
    proof = payloads.KNOWN_POC_PROOFS[payloads.STRUTS_S2045_PROOF_ID]
    req = ExecutionRequest(action, SID, 'web', proof['source_url'], {}, proof['sha256'],
                           proof['exec_method'], proof['payload'], proof['expected_marker'],
                           target_host_ref='web', proof_id=payloads.STRUTS_S2045_PROOF_ID)
    return replace(req, **updates)


def effect_run(action='a1', status='PASS', note='OGNL response arithmetic verified', **updates):
    req = request(action)
    passed = status == 'PASS'
    result = {'action_id': action, 'status': status, 'target_ownership_verified': True,
              'poc': {'source_url': req.source_url, 'ref': {}, 'sha256': req.sha256},
              'payload_sha256': req.sha256, 'logs_path': 'poc-runs/fixture.log',
              'confidence': .99 if passed else 0., 'started_at': '2026-11-16T00:00:00Z',
              'ended_at': '2026-11-16T00:00:01Z',
              'stages': {'started': True, 'delivered': True, 'responded': True,
                         'vuln_behavior': passed, 'state_change': passed, 'action_complete': True},
              'evidence': [{'kind': 'exploit_effect', 'path': f'nonexistent-qa/{action}.txt',
                            'sha256': 'a' * 64, 'redacted': True, 'note': note}] if passed else []}
    result.update(updates)
    return result


def chain_fixture(count=2, relations=True):
    ids = [f'a{i+1}' for i in range(count)]
    ir = {'actions': [{'id': aid} for aid in ids], 'evidence': [{'id': 'ev1'}], 'relations': []}
    if relations:
        ir['relations'] = [{'kind': 'dependency', 'from_action': ids[i], 'to_action': ids[i+1],
                            'evidence_refs': ['ev1'], 'carried': 'cred'} for i in range(count - 1)]
    plan = {'items': [{'action_id': aid, 'strategy': 'poc_exec', 'preconditions': ['cred from predecessor']}
                      for aid in ids]}
    return ir, plan


@pytest.mark.parametrize('output', ['HTTP 200', 'OK', 'container-up', 'healthy', 'LLM says PASS',
                                  'REQUEST_ERROR=HTTPError:patched target'])
def test_control_liveness_or_failed_payload_never_passes(monkeypatch, output):
    monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
    monkeypatch.setattr(runner, '_probe_with_cancel', lambda *a: ({'returncode': 0, 'stdout': output, 'stderr': ''}, None))
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'FAIL'
    assert not result.stages.vuln_behavior


def test_control_registered_effect_can_pass_with_mocked_transport(monkeypatch):
    monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
    monkeypatch.setattr(runner, '_probe_with_cancel', lambda *a: ({'returncode': 0, 'stdout': payloads.STRUTS_S2045_MARKER, 'stderr': ''}, None))
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'PASS'
    assert any(e.kind == 'exploit_effect' for e in result.evidence)


def test_registered_payload_error_containing_marker_must_not_pass(monkeypatch):
    # urllib HTTPError.__str__ uses the HTTP reason phrase supplied by a target.
    # The pinned payload prints this exception; no payload or HTTP request is executed here.
    error = HTTPError('http://127.0.0.1:8080/', 500, payloads.STRUTS_S2045_MARKER, {}, None)
    error_output = 'REQUEST_ERROR=HTTPError:' + str(error)
    monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
    monkeypatch.setattr(runner, '_probe_with_cancel', lambda *a: ({'returncode': 0, 'stdout': error_output, 'stderr': ''}, None))
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'FAIL', f'{result.status=}; simulated pinned-payload output={error_output}'


@pytest.mark.parametrize('updates', [{'proof_id': None}, {'sha256': '0' * 64},
                                    {'payload': "print('VULHUB_HEADER=54289')"},
                                    {'expected_marker': 'HTTP 200'}, {'source_url': 'https://github.com/x/y'}])
def test_control_unvetted_or_changed_payload_cannot_execute(monkeypatch, updates):
    monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
    transport = Mock(side_effect=AssertionError('unvetted payload reached transport'))
    monkeypatch.setattr(runner, '_probe_with_cancel', transport)
    assert runner.SandboxRunner().execute(request(**updates)).status == 'BLOCKED'
    transport.assert_not_called()


def test_control_ownership_guard_precedes_adapter_and_transport(monkeypatch):
    def deny(*args):
        raise guard.TargetBlocked('not owned')
    monkeypatch.setattr(runner, 'assert_target_owned', deny)
    adapter, transport = Mock(), Mock()
    monkeypatch.setattr(runner, 'get_adapter', adapter)
    monkeypatch.setattr(runner, '_probe_with_cancel', transport)
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'BLOCKED' and not result.target_ownership_verified
    adapter.assert_not_called()
    transport.assert_not_called()


@pytest.mark.parametrize('vmid', sorted(guard.PROTECTED_VMIDS))
def test_control_protected_vmid_hard_blocked(vmid):
    with pytest.raises(guard.TargetBlocked, match='protected'):
        guard.assert_target_owned(SID, {'service_ref': 'web', 'vmid': vmid})


def setup_guard(monkeypatch, *, backend='local-docker', extra_network=False, labels=True):
    name = f'cr-demo-{SID}-web'
    compose = yaml.safe_dump({'services': {'web': {'container_name': name, 'networks': ['lab']}}})
    monkeypatch.setattr(guard, 'get_generated', lambda *a: {'compose': compose})
    monkeypatch.setattr(manager, 'deploy_backend', lambda: backend)
    monkeypatch.setattr(manager, 'records', lambda *a, **k: [{'id': 1, 'action': 'up', 'state': 'running',
        'details': {'backend': 'local-docker', 'host_isolation': {'isolated': True}}}])
    networks = {f'cr-demo-{SID}-lab': {}}
    if extra_network:
        networks['non-experiment-external-network'] = {}
    info = {'Id': 'b' * 64, 'State': {'Running': True},
            'Config': {'Labels': {'com.docker.compose.project': f'cr-demo-{SID}',
                                  'com.docker.compose.service': 'web'} if labels else {}},
            'NetworkSettings': {'Networks': networks}}
    def inspect(args):
        if args[0] == 'inspect':
            return [info]
        return [{'Internal': True, 'Options': {'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'},
                 'Containers': {'b' * 64: {}}}]
    monkeypatch.setattr(guard, '_docker_json', inspect)
    return info


def test_control_unowned_container_labels_rejected(monkeypatch):
    setup_guard(monkeypatch, labels=False)
    with pytest.raises(guard.TargetBlocked, match='labels'):
        guard.assert_target_owned(SID, 'web')


def test_control_absent_deployment_rejected(monkeypatch):
    setup_guard(monkeypatch)
    monkeypatch.setattr(manager, 'records', lambda *a, **k: [])
    with pytest.raises(guard.TargetBlocked):
        guard.assert_target_owned(SID, 'web')


def test_guard_rejects_any_additional_non_lab_network(monkeypatch):
    setup_guard(monkeypatch, extra_network=True)
    with pytest.raises(guard.TargetBlocked):
        guard.assert_target_owned(SID, 'web')


@pytest.mark.parametrize('isolation', [None, {}, {'checked': True, 'isolated': False, 'evidence': ['fixture']},
                                      {'checked': True, 'isolated': True, 'evidence': []}])
def test_control_pve_missing_confirmed_isolation_rejected(monkeypatch, isolation):
    setup_guard(monkeypatch, backend='proxmox')
    monkeypatch.setattr(manager, '_active_proxmox_deployment', lambda *a: {'vmid': 900100, 'details': {'isolation': isolation}})
    status = Mock()
    monkeypatch.setattr(manager, 'compose_ps_result', status)
    with pytest.raises(guard.TargetBlocked):
        guard.assert_target_owned(SID, 'web')
    status.assert_not_called()


def test_control_non_cr_range_vm_rejected_by_real_backend_ownership_check(monkeypatch):
    from app.deploy.backends.proxmox import ProxmoxBackend, ProxmoxBackendError
    backend = object.__new__(ProxmoxBackend)
    monkeypatch.setattr(backend, '_get', lambda *a: {'members': []})
    with pytest.raises(ProxmoxBackendError, match='cr-range'):
        backend._assert_owned(900100, SID, 'worker')


def setup_local_transport(monkeypatch, vulnerable):
    monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
    monkeypatch.setattr(manager, 'deploy_backend', lambda: 'local-docker')
    monkeypatch.setattr(manager, '_backend_conflict', lambda *a: None)
    monkeypatch.setattr(local_docker, 'get_generated', lambda *a: {'report': {'components': [
        {'host_id': 'web', 'vulnerable': vulnerable}]}})
    monkeypatch.setattr(local_docker, '_docker_context_preflight', lambda: ('docker', None))
    monkeypatch.setattr(local_docker, '_compose_prefix', lambda *a: (['docker', 'compose'], None))
    transport = Mock(return_value={'returncode': 0, 'stdout': 'HTTP 200', 'stderr': ''})
    monkeypatch.setattr(local_docker, '_run', transport)
    return transport


def test_control_d6_known_vulnerable_image_blocks_before_docker_run(monkeypatch):
    transport = setup_local_transport(monkeypatch, True)
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'BLOCKED'
    transport.assert_not_called()


def test_d6_blocks_attack_payload_even_for_non_vulnerable_image(monkeypatch):
    transport = setup_local_transport(monkeypatch, False)
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'BLOCKED', f'{result.status=}, {result.stages.delivered=}, docker_run_calls={transport.call_count}'
    transport.assert_not_called()


def test_pve_helper_has_explicit_cpu_memory_pid_caps(monkeypatch):
    monkeypatch.setattr(manager, 'deploy_backend', lambda: 'proxmox')
    monkeypatch.setattr(manager, '_backend_conflict', lambda *a: None)
    guest = Mock(return_value={'returncode': 0, 'stdout': '', 'stderr': ''})
    monkeypatch.setattr(manager, '_pve_guest_exec', guest)
    manager.probe_in_service(SID, 'web', request().payload)
    args = guest.call_args.args[1]
    assert guest.call_args.kwargs['require_isolation'] is True
    missing = [flag for flag in ['--memory', '--cpus', '--pids-limit'] if flag not in args]
    assert not missing, f'missing helper resource caps: {missing}'


def test_cancel_does_not_allow_delayed_launch_after_cleanup_returns(monkeypatch):
    cancelled, launch_permitted, delivered, finished = (threading.Event() for _ in range(4))
    def delayed_launch(*args, **kwargs):
        cancelled.set()  # Cancellation arrives while transport is still starting.
        launch_permitted.wait(1)
        delivered.set()  # Simulates a late Docker helper launch, after the cleanup scan.
        finished.set()
        return {'returncode': 0, 'stdout': 'late delivery', 'stderr': ''}
    def cleanup(*args):
        return 'cleanup did not remove a helper because identity was not uniquely proven'
    monkeypatch.setattr(manager, 'probe_in_service', delayed_launch)
    monkeypatch.setattr(runner, '_cleanup_probe', cleanup)
    result, note = runner._probe_with_cancel(request(cancel=cancelled), request().payload, timeout=2)
    launch_permitted.set()  # Guarantee the simulated helper launches strictly after wrapper return.
    assert finished.wait(1), 'test transport did not finish'
    assert result['returncode'] == 125
    assert not delivered.is_set(), f'late transport continued after cancellation; {note}'


def test_chain_independent_action_passes_do_not_prove_full_chain():
    ir, plan = chain_fixture(relations=False)
    result = validate_chain(SID, ir, plan, [effect_run('a1'), effect_run('a2')])
    assert result['passes'] is False, result


def test_chain_transfer_requires_consumed_state_not_note_keywords():
    ir, plan = chain_fixture()
    result = validate_chain(SID, ir, plan, [effect_run('a1', note='cred (text label only; actual proof is OGNL arithmetic)'), effect_run('a2')])
    assert result['passes'] is False, result


def test_chain_failure_propagates_transitively():
    ir, plan = chain_fixture(3)
    result = validate_chain(SID, ir, plan, [effect_run('a1', 'FAIL'), effect_run('a2', note='cred'), effect_run('a3')])
    assert result['per_action'][2]['status'] != 'PASS', result


def test_real_batch_orchestration_blocks_dependent_after_fail(monkeypatch):
    ir = struts_ir()
    ir['services'][0]['id'] = 'web'  # isolate dependency handling from the separate ID mapping defect
    ir['actions'].append({**ir['actions'][0], 'id': 'a2'})
    ir['relations'] = [{'kind': 'dependency', 'from_action': 'a1', 'to_action': 'a2', 'evidence_refs': ['e1']}]
    ir['evidence'] = [{'id': 'e1'}]
    monkeypatch.setattr(service.store, 'get', lambda *a: ir)
    for name in ['save_plan', 'create_job', 'set_job_state', 'save_run']:
        monkeypatch.setattr(poc_store, name, Mock())
    monkeypatch.setattr(poc_store, 'is_cancelled', lambda *a: False)
    attempts = []
    def execute(self, req):
        attempts.append(req.action_id)
        return runner.ExecutionResult(req.action_id, {}, 'FAIL' if req.action_id == 'a1' else 'PASS',
            runner.ExecStages(), 'memory-only.log', 0., True, req.sha256, 't0', 't1')
    monkeypatch.setattr(runner.SandboxRunner, 'execute', execute)
    results = service.execute(SID)
    assert not any(r['action_id'] == 'a2' and r['status'] == 'PASS' for r in results), f'{attempts=}, results={[(r["action_id"], r["status"]) for r in results]}'


def test_chain_uncited_failed_predecessor_cannot_leave_dependent_pass():
    ir, plan = chain_fixture()
    ir['relations'][0].pop('evidence_refs')
    plan['items'][1]['required_predecessors'] = ['a1']
    result = validate_chain(SID, ir, plan, [effect_run('a1', 'FAIL'), effect_run('a2')])
    assert result['per_action'][1]['status'] != 'PASS', result


def test_chain_checks_actual_time_order_not_list_position():
    ir, plan = chain_fixture()
    a = effect_run('a1', note='cred', started_at='2026-11-16T01:00:00Z', ended_at='2026-11-16T01:00:01Z')
    b = effect_run('a2', started_at='2026-11-16T00:00:00Z', ended_at='2026-11-16T00:00:01Z')
    result = validate_chain(SID, ir, plan, [a, b])
    assert result['order_ok'] is False and result['passes'] is False, result


def test_verification_rejects_missing_artifact_and_unregistered_payload():
    run = effect_run()
    run['poc'] = {'source_url': 'https://github.com/unvetted/unpinned', 'ref': {}, 'sha256': '0' * 64}
    run['payload_sha256'] = '0' * 64
    assert verify_execution(run) != 'PASS', run


def test_control_not_executable_never_passes():
    assert verify_execution(effect_run(), {'action_id': 'a1', 'strategy': 'not_executable'}) == 'NOT_TESTED'


def test_timeout_blocked_is_not_reinterpreted_as_exploit_fail(monkeypatch):
    monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
    monkeypatch.setattr(runner, '_probe_with_cancel', lambda *a: ({'returncode': 124, 'stdout': '', 'stderr': 'timeout'}, 'cleanup attempted'))
    result = runner.SandboxRunner().execute(request())
    assert result.status == 'BLOCKED'
    assert verify_execution(asdict(result)) == 'BLOCKED', asdict(result)


@pytest.mark.parametrize('success', [False, True])
def test_runner_output_matches_execution_result_schema(monkeypatch, success):
    if success:
        monkeypatch.setattr(runner, 'assert_target_owned', lambda *a: {'service_ref': 'web'})
        monkeypatch.setattr(runner, '_probe_with_cancel', lambda *a: ({'returncode': 0, 'stdout': payloads.STRUTS_S2045_MARKER, 'stderr': ''}, None))
    else:
        def deny(*args):
            raise guard.TargetBlocked('not owned')
        monkeypatch.setattr(runner, 'assert_target_owned', deny)
    result = asdict(runner.SandboxRunner().execute(request()))
    errors = iter_errors_shape('ExecutionResult', result)
    assert not errors, errors


def struts_ir():
    return {'id': SID, 'schema_version': '1.0', 'name': 'QA fixture',
            'provenance': {'input_kind': 'text', 'input_sha256': '0' * 64},
            'actions': [{'id': 'a1', 'name': 'Exploit Struts', 'attack_technique': 'T1190',
                         'target_host_ref': 'web', 'source': 'user', 'epistemic_status': 'supported'}],
            'relations': [], 'hosts': [{'id': 'web'}],
            'services': [{'id': 'svc-struts', 'host_ref': 'web', 'name': 'Struts', 'version': '2.3.30',
                          'catalogue_component': 'vuln-struts2-s2-045', 'cve': ['CVE-2017-5638']}],
            'environment_plan': {'hosts': [{'id': 'web', 'role': 'web', 'image_hint': 'vuln-struts2-s2-045',
                'services': [{'name': 'struts', 'port': 8080, 'protocol': 'tcp'}], 'networks': ['lab']}],
                'networks': [{'id': 'lab', 'internal': True}], 'connections': [], 'verify_blocked': []}}


def test_service_maps_ir_service_to_actual_compose_host(monkeypatch):
    ir = struts_ir()
    monkeypatch.setattr(service.store, 'get', lambda *a: ir)
    monkeypatch.setattr(poc_store, 'save_plan', lambda *a: None)
    batch = Mock(return_value=[])
    monkeypatch.setattr(runner, 'run_job', batch)
    service.execute(SID)
    req = batch.call_args.args[1][0]
    compose = yaml.safe_load(generator.compose_document(ir['environment_plan'], SID))
    assert req.service_ref in compose['services'], f'request.service_ref={req.service_ref}; compose services={list(compose["services"])}'


def test_plan_marks_no_verifier_not_executable_before_execution():
    ir = struts_ir()
    ir['services'][0].update(name='nginx', catalogue_component='oss-nginx', cve=['CVE-2099-0001'])
    ir['actions'][0]['name'] = 'Exploit nginx vulnerability'
    item = service._build_item(ir['actions'][0], ir)
    assert service._proof_for_service(ir['services'][0]) is None
    assert item['strategy'] == 'not_executable' and item.get('not_executable_reason'), item


def test_exploit_named_action_without_technique_still_requires_real_payload():
    ir = struts_ir()
    ir['actions'][0].pop('attack_technique')
    item = service._build_item(ir['actions'][0], ir)
    assert item['strategy'] == 'poc_exec', item


def test_discovery_resolves_service_through_normal_target_host_ref():
    ir = struts_ir()
    client = Mock()
    client.nvd_search.return_value = None
    client.exploitdb_search.return_value = []
    client.github_search.return_value = [{'source_url': 'https://github.com/qa/struts-poc', 'product': 'struts',
        'description': 'Struts CVE-2017-5638 exploit', 'language': 'Python'}]
    manifest = DiscoveryEngine(client).discover(SID, ir)
    assert manifest['items'], manifest


def test_discovery_is_persisted_for_export(monkeypatch):
    from app.poc import discovery
    monkeypatch.setattr(service, '_load_ir', lambda *a: struts_ir())
    manifest = {'scenario_id': SID, 'generated_at': 't', 'items': []}
    monkeypatch.setattr(discovery, 'discover', lambda *a: manifest)
    save = Mock()
    monkeypatch.setattr(poc_store, 'save_manifest', save)
    service.discover(SID)
    save.assert_called_once_with(SID, manifest)


def test_chain_is_persisted_for_export(monkeypatch):
    monkeypatch.setattr(service, '_load_ir', lambda *a: struts_ir())
    monkeypatch.setattr(service, 'plan', lambda *a: {'items': []})
    monkeypatch.setattr(service, '_executions', lambda *a: [])
    save = Mock()
    monkeypatch.setattr(poc_store, 'save_chain', save)
    result = service.chain(SID)
    save.assert_called_once_with(SID, result)


@pytest.mark.parametrize('target,vr,compatible', [('2.15.0', 'before 2.15.0', False), ('2.10.0', '2.0.0 through 2.14.1', True)])
def test_discovery_version_range_means_range_not_endpoint(target, vr, compatible):
    score = score_candidate({'product': 'Apache Log4j', 'version_range': vr, 'exec_method': 'python', 'trust': 'medium'},
                            {'product': 'Apache Log4j', 'version': target})['version']
    assert (score > .9) == compatible, f'{target=}, {vr=}, version_score={score}'


def build_in_memory_bundle(monkeypatch, description='', hosts=None):
    ir = {'id': SID, 'name': 'Synthetic secret QA', 'ir_version': 1, 'actions': [], 'relations': [],
          'description': description, 'environment_plan': EXPOSED_PLAN, 'hosts': hosts or []}
    _, report = generator.inspect_plan(EXPOSED_PLAN, SID)
    generated = {'compose': generator.compose_document(EXPOSED_PLAN, SID), 'report': report}
    monkeypatch.setattr(B.store, 'get', lambda *a: ir)
    monkeypatch.setattr(B.generator, 'get_generated', lambda *a: generated)
    monkeypatch.setattr(B, '_env_secret_values', lambda: [])
    monkeypatch.setattr(poc_store, 'get_plan', lambda *a: None)
    monkeypatch.setattr(poc_store, 'get_manifest', lambda *a: None)
    monkeypatch.setattr(poc_store, 'get_runs', lambda *a: [])
    monkeypatch.setattr(poc_store, 'get_chain', lambda *a: None)
    data, manifest = B.build_bundle(SID)
    return data, manifest, zipfile.ZipFile(io.BytesIO(data))


def test_control_export_real_compose_no_fabricated_iac_and_hashes(monkeypatch):
    data, manifest, zf = build_in_memory_bundle(monkeypatch)
    assert B.verify_bundle(data) == []
    assert zf.read('infrastructure/docker-compose.yml').decode() == generator.compose_document(EXPOSED_PLAN, SID)
    assert not any(n.startswith(('infrastructure/terraform/', 'infrastructure/ansible/')) for n in zf.namelist())
    assert manifest['contains_secrets'] is False


@pytest.mark.parametrize('kind', ['url-userinfo', 'compose-default'])
def test_export_removes_synthetic_credentials(monkeypatch, kind):
    synthetic = 'm9-qa-synthetic-password-724'
    if kind == 'url-userinfo':
        data, manifest, zf = build_in_memory_bundle(monkeypatch, description=f'https://qa-user:{synthetic}@example.invalid/private')
    else:
        data, manifest, zf = build_in_memory_bundle(monkeypatch, hosts=[{'id': 'web', 'password': '${DB_PASSWORD:-' + synthetic + '}'}])
    leaking_files = [n for n in zf.namelist() if synthetic.encode() in zf.read(n)]
    assert not leaking_files, f'contains_secrets={manifest["contains_secrets"]}, leaked synthetic credential in {leaking_files}; verify_bundle={B.verify_bundle(data)}'


def test_gui_stop_calls_backend_cancel_and_polls_job():
    root = Path(__file__).resolve().parents[4]
    page = (root / 'apps/web/src/pages/PocPage.tsx').read_text()
    api = (root / 'apps/web/src/lib/api.ts').read_text()
    assert '/execute/cancel' in page + api, 'Stop only aborts client fetch; backend cancel route is unused'
    assert '/execute/status' in page + api, 'Live backend stages are never polled'
