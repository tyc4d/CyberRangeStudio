"""Round-6 final gate. Synthetic structured credentials; no live runtime or LLM.

Unchanged production builder/checker. Existing fixture constructors only replace
artifact sources; the serializer, redactor and final scans remain real.
Run from apps/api with this worktree's contracts and -p no:cacheprovider.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest
import yaml

from app.deploy import manager
from app.poc.export import bundle as B

spec = importlib.util.spec_from_file_location(
    "round6_legacy", Path(__file__).parents[1] / "review/test_m9_review.py")
r1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r1)

SECRET = "round6-synthetic-credential-QA642"
ENCODED = base64.b64encode(SECRET.encode()).decode()
TAGGED_YAML = {
    "explicit-string": "password: !!str " + SECRET,
    "explicit-string-literal-block": "password: !!str |\n  " + SECRET + "\n",
    "explicit-string-folded-block": "password: !!str >\n  " + SECRET + "\n",
    "binary-block": "password: !!binary |\n  " + ENCODED + "\n",
}


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Round-6 forbids processes, HTTP, PVE and payload execution")
    for target in ("subprocess.run", "subprocess.Popen", "urllib.request.urlopen"):
        monkeypatch.setattr(target, forbidden)
    monkeypatch.setattr(manager, "_pve_guest_exec", forbidden)
    monkeypatch.setattr(manager, "probe_in_service", forbidden)


def reseal(files, path, body):
    """Change one ZIP member and its recorded digest, never rely on hash failure."""
    files = dict(files)
    files[path] = body
    manifest = json.loads(files["manifest.json"])
    for entry in manifest["files"]:
        if entry["path"] == path:
            entry["sha256"] = B._sha256(body)
    files["manifest.json"] = json.dumps(manifest).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dest:
        for name, value in files.items():
            dest.writestr(name, value)
    return out.getvalue()


@pytest.mark.parametrize("kind", TAGGED_YAML)
def test_tagged_yaml_builder_removes_real_parsed_secret_or_refuses(monkeypatch, kind):
    original = TAGGED_YAML[kind]
    parsed = yaml.safe_load(original)
    assert parsed["password"].strip() in (SECRET, SECRET.encode())
    try:
        data, manifest, zf = r1.build_in_memory_bundle(monkeypatch, description=original)
    except B.ExportError:
        return
    leaked = [name for name in zf.namelist()
              if any(value.encode() in zf.read(name) for value in (SECRET, ENCODED))]
    assert not leaked, {
        "kind": kind, "leaked_files": leaked,
        "contains_secrets": manifest["contains_secrets"],
        "verify_bundle": B.verify_bundle(data),
        "emitted_description": json.loads(zf.read("scenario/scenario.json"))["description"],
    }


# These are controls for the actual top-level parse. Each contains a real parsed
# password, including standard JSON/YAML escapes, types and multiline encodings.
JSON_VALUES = {
    "plain": SECRET,
    "multiline": "first\n" + SECRET + "\nlast",
    "encoded-value": ENCODED,
    "numeric": 987654321,
    "list": [SECRET],
    "mapping": {"value": SECRET},
    "safe-prefix-is-not-safe": "[REDACTED]" + SECRET,
}
YAML_MEMBERS = {
    "literal": "password: |\n  " + SECRET + "\n",
    "folded": "password: >-\n  first\n  " + SECRET + "\n",
    "quoted-multiline": 'password: "first\n  ' + SECRET + '"\n',
    "unicode-escaped-key": '"\\u0070assword": "' + SECRET + '"\n',
    "unicode-escaped-value": 'password: "' + "".join("\\u%04x" % ord(c) for c in SECRET) + '"\n',
    "numeric": "password: 987654321\n",
    "string-that-looks-boolean": 'password: !!str false\n',
    "list": "password: ['" + SECRET + "']\n",
    "mapping": "password: {value: '" + SECRET + "'}\n",
    **TAGGED_YAML,
}


@pytest.mark.parametrize("kind", JSON_VALUES)
@pytest.mark.parametrize("escape_key", [False, True], ids=["literal-key", "unicode-key"])
def test_checker_parses_actual_json_not_raw_token_spelling(monkeypatch, kind, escape_key):
    _, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {name: zf.read(name) for name in zf.namelist()}
    ir = json.loads(files["scenario/scenario.json"])
    ir["hosts"] = [{"id": "web", "password": JSON_VALUES[kind]}]
    text = json.dumps(ir)
    if escape_key:
        text = text.replace('"password"', '"\\u0070assword"')
    data = reseal(files, "scenario/scenario.json", text.encode())
    errors = B.verify_bundle(data)
    assert "secret material in scenario/scenario.json" in errors, (kind, errors)
    assert not any("sha256" in error for error in errors), errors


@pytest.mark.parametrize("kind", YAML_MEMBERS)
def test_checker_parses_actual_yaml_multiline_tags_and_encoding(monkeypatch, kind):
    _, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {name: zf.read(name) for name in zf.namelist()}
    assert yaml.safe_load(YAML_MEMBERS[kind])["password"] is not None
    data = reseal(files, "scenario/scenario.yaml", YAML_MEMBERS[kind].encode())
    errors = B.verify_bundle(data)
    assert "secret material in scenario/scenario.yaml" in errors, (kind, errors)
    assert not any("sha256" in error for error in errors), errors


@pytest.mark.parametrize("path", ["scenario/scenario.json", "scenario/scenario.yaml"])
@pytest.mark.parametrize("kind", TAGGED_YAML)
def test_checker_detects_original_valid_yaml_inside_description(monkeypatch, path, kind):
    _, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {name: zf.read(name) for name in zf.namelist()}
    ir = json.loads(files["scenario/scenario.json"])
    ir["description"] = TAGGED_YAML[kind]
    text = json.dumps(ir) if path.endswith(".json") else yaml.safe_dump(ir)
    data = reseal(files, path, text.encode())
    errors = B.verify_bundle(data)
    assert "secret material in " + path in errors, (kind, errors)
    assert not any("sha256" in error for error in errors), errors


@pytest.mark.parametrize("kind", JSON_VALUES)
def test_builder_actual_secret_fields_still_redact_encoded_or_multiline_values(monkeypatch, kind):
    try:
        data, manifest, zf = r1.build_in_memory_bundle(
            monkeypatch, hosts=[{"id": "web", "password": JSON_VALUES[kind]}])
    except B.ExportError:
        return
    scenario = json.loads(zf.read("scenario/scenario.json"))
    assert scenario["hosts"][0]["password"] in ("[REDACTED]", ["[REDACTED]"], {"value": "[REDACTED]"})
    assert manifest["contains_secrets"] is False
    assert B.verify_bundle(data) == []


@pytest.mark.parametrize("path", ["scenario/scenario.json", "scenario/scenario.yaml"])
def test_unparsable_actual_structured_file_is_rejected(monkeypatch, path):
    _, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {name: zf.read(name) for name in zf.namelist()}
    data = reseal(files, path, b'{"description": [')
    errors = B.verify_bundle(data)
    assert "secret material in " + path in errors
    assert not any("sha256" in error for error in errors), errors


def test_clean_public_text_and_bare_runtime_reference_still_export(monkeypatch):
    data, manifest, _ = r1.build_in_memory_bundle(
        monkeypatch, description="Public reproduction notes", hosts=[{"password": "${DB_PASSWORD}"}])
    assert manifest["contains_secrets"] is False
    assert B.verify_bundle(data) == []
