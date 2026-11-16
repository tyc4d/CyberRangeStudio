"""Final confirmation: parser oracle and refusal persistence, all data synthetic.

Run from apps/api with worktree contracts, CR_DATA_DIR in /tmp, and cache disabled.
No live deployment, network, payload, or LLM is allowed by these checks.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import socket
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from app import config, store
from app.deploy import manager
from app.iac import generator
from app.iac.test_generator import EXPOSED_PLAN
from app.poc import store as poc_store
from app.poc.export import bundle as B
from app.routers.poc import router

SID = "scn_review7"
SECRET = "review7-synthetic-credential-28d4"
ENCODED = base64.b64encode(SECRET.encode()).decode()
DOCUMENTS = {
    "tagged-scalar": "password: !!str " + SECRET,
    "binary-block": "password: !!binary |\n  " + ENCODED + "\n",
    "escaped-key": '"\\u0070assword": "' + SECRET + '"',
    "merge": "defaults: &d {password: " + SECRET + "}\ncopy: {<<: *d}\n",
    "nested-json-yaml": json.dumps({"example": "password: !!str " + SECRET}),
    "nested-yaml-json": yaml.safe_dump({"example": json.dumps({"password": SECRET})}),
    "double-json": json.dumps(json.dumps({"password": SECRET})),
    "prose-intro": "Configuration example follows.\npassword: !!str |\n  " + SECRET + "\n",
}
UNSAFE = {
    "malformed": 'password: [REDACTED] |\n  ' + SECRET,
    "unknown-tag": "password: !unknown " + SECRET,
    "public-alias-copy": "password: &p " + SECRET + "\npublic: *p\n",
    "cyclic": "&loop {child: *loop}",
}


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("review7 forbids live process/network/deploy/payload execution")

    for target in ("subprocess.run", "subprocess.Popen", "urllib.request.urlopen"):
        monkeypatch.setattr(target, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(manager, "_pve_guest_exec", forbidden)
    monkeypatch.setattr(manager, "probe_in_service", forbidden)


@pytest.fixture
def persisted(monkeypatch, tmp_path):
    """Real SQLite and files; only generated-artifact lookup is redirected."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_DB", tmp_path / "scenarios.db")
    monkeypatch.setattr(poc_store, "_DB", tmp_path / "poc.db")
    # Do not inspect process credentials. All test secrets are explicitly synthetic.
    monkeypatch.setattr(B, "_env_secret_values", lambda: [])
    ir = store.create({
        "schema_version": "1.0", "id": SID, "name": "Public QA scenario", "ir_version": 1,
        "description": "Public reproduction notes", "actions": [], "relations": [],
        "hosts": [], "environment_plan": copy.deepcopy(EXPOSED_PLAN),
    })
    _, report = generator.inspect_plan(EXPOSED_PLAN, SID)
    generated = {"compose": generator.compose_document(EXPOSED_PLAN, SID), "report": report}
    monkeypatch.setattr(generator, "get_generated", lambda sid: copy.deepcopy(generated))
    poc_store.save_manifest(SID, {"scenario_id": SID, "generated_at": "qa", "items": []})
    return ir, tmp_path


def set_description(text):
    ir = store.get(SID)
    ir["description"] = text
    store.update(SID, ir, note="QA fixture")
    return store.get(SID)


def assert_parser_clean(obj, under_secret=False, depth=0):
    """Independent recursive parser oracle, without production secret-detection helpers."""
    assert depth < 100
    if isinstance(obj, dict):
        for key, value in obj.items():
            name = key.decode() if isinstance(key, bytes) else key
            assert_parser_clean(value, under_secret or name in {"password", "credentials", "token"}, depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            assert_parser_clean(value, under_secret, depth + 1)
    elif under_secret:
        assert obj in ("[REDACTED]", "", b"", None, True, False), repr(obj)
    elif isinstance(obj, (str, bytes)):
        assert (SECRET.encode() if isinstance(obj, bytes) else SECRET) not in obj
        assert (ENCODED.encode() if isinstance(obj, bytes) else ENCODED) not in obj
        try:
            parsed = yaml.safe_load(obj)
        except yaml.YAMLError:
            return  # Ordinary prose; emitted structured documents below must parse.
        if parsed != obj:
            assert_parser_clean(parsed, False, depth + 1)


def reseal(data, path, content):
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    files[path] = content
    manifest = json.loads(files["manifest.json"])
    for entry in manifest["files"]:
        if entry["path"] == path:
            entry["sha256"] = hashlib.sha256(content).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name, body in files.items():
            target.writestr(name, body)
    return output.getvalue()


@pytest.mark.parametrize("source", DOCUMENTS.values(), ids=DOCUMENTS)
def test_emitted_scenarios_are_independently_parser_clean(persisted, source):
    original = set_description(source)
    data, manifest = B.build_bundle(SID)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        actual_json = json.loads(archive.read("scenario/scenario.json"))
        actual_yaml = yaml.safe_load(archive.read("scenario/scenario.yaml"))
        assert actual_json == actual_yaml
        assert_parser_clean(actual_json["description"])
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
    assert manifest["contains_secrets"] is False
    assert B.verify_bundle(data) == []
    assert store.get(SID) == original  # Export redaction must not mutate source data.


@pytest.mark.parametrize("source", list(DOCUMENTS.values())[:5], ids=list(DOCUMENTS)[:5])
@pytest.mark.parametrize("path", ["scenario/scenario.yaml", "scenario/scenario.json"])
def test_verifier_rejects_parser_resolved_secrets_despite_correct_hash(persisted, source, path):
    with pytest.raises(AssertionError):
        assert_parser_clean(yaml.safe_load(source))
    data, _ = B.build_bundle(SID)
    # YAML member is the document itself; JSON member carries it as a description.
    body = source if path.endswith(".yaml") else json.dumps({"description": source})
    changed = reseal(data, path, body.encode())
    errors = B.verify_bundle(changed)
    assert "secret material in " + path in errors
    assert not any("sha256" in error for error in errors)
    assert SECRET not in " ".join(errors)


@pytest.mark.parametrize("source", UNSAFE.values(), ids=UNSAFE)
def test_export_refusal_keeps_source_prior_zip_and_record(persisted, source):
    _, data_dir = persisted
    first = B.export(SID)
    previous_path = Path(first["bundle_path"])
    previous_bytes = previous_path.read_bytes()
    original = set_description(source)
    original_manifest = poc_store.get_manifest(SID)
    with poc_store._conn() as connection:
        previous_rows = [tuple(row) for row in connection.execute("SELECT * FROM poc_exports")]
    before_files = sorted(p.relative_to(data_dir) for p in data_dir.rglob("*") if p.is_file())

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(f"/api/poc/{SID}/export", json={"format": "full"})
        assert response.status_code == 409
        assert SECRET not in response.text
        downloaded = client.get(f"/api/poc/{SID}/export/download")
        assert downloaded.status_code == 200
        assert downloaded.content == previous_bytes

    assert store.get(SID) == original
    assert poc_store.get_manifest(SID) == original_manifest
    assert previous_path.read_bytes() == previous_bytes
    assert B.latest_bundle(SID) == previous_path
    assert sorted(p.relative_to(data_dir) for p in data_dir.rglob("*") if p.is_file()) == before_files
    with poc_store._conn() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM poc_exports")] == previous_rows
    set_description("Public reproduction notes")
    after = B.export(SID)
    assert after["bundle_path"] != first["bundle_path"]
    assert previous_path.read_bytes() == previous_bytes
    assert B.verify_bundle(Path(after["bundle_path"])) == []


@pytest.mark.parametrize("fmt", ["full", "iac", "evidence"])
def test_clean_formats_still_export_and_keep_source(persisted, fmt):
    original = set_description("Public reproduction notes")
    exported = B.export(SID, fmt)
    assert B.verify_bundle(Path(exported["bundle_path"])) == []
    assert exported["manifest"]["contains_secrets"] is False
    if fmt == "evidence":
        assert exported["manifest"]["rebuildable"] is False
    assert store.get(SID) == original
