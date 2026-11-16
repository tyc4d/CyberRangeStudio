"""m9-export unit tests: bundle builds, manifest sha256s verify, no secrets, missing images listed.

The compose/report used here are the REAL generator outputs (compose_document / inspect_plan)
for fixture plans; only the on-disk lookup (generator.get_generated) and the stores are
redirected to temp locations so the test never writes into the repository.
"""
from __future__ import annotations

import copy
import base64
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

from app.iac import generator
from app.iac.test_generator import DEMO_PLAN, EXPOSED_PLAN
from app.poc.export import bundle as B

SID = "scn_export01"
PLAIN_PASSWORD = "Winter2024!Secret"
INLINE_PASSWORD = "Hunter2xyzzy"
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
ENV_TOKEN = "envtok-" + "9f8e7d6c5b4a39281706"

NOT_DEPLOYED_HOST = {"id": "erp", "role": "erp appliance", "image_hint": "sap-erp", "networks": ["inside"],
                     "deployable": False, "not_deployed_reason": "closed-source appliance; no image available"}
VM_HOST = {"id": "dc01", "role": "domain controller", "runtime": "vm", "networks": ["inside"],
           "guest": {"os_family": "windows", "os_release": "Windows Server 2022 eval",
                     "image_ref": "win2022-eval.qcow2", "image_digest": "sha256:" + "0" * 64,
                     "cpu": 2, "memory_mib": 4096, "disk_gib": 40}}


def _ir(plan):
    return {
        "schema_version": "1", "id": SID, "name": "Struts to DB", "ir_version": 3,
        "provenance": {"source": "test"},
        "actions": [{"id": "a1", "attack_technique": "T1190", "target_host_ref": "portal",
                     "description": f"attacker logs in with password={INLINE_PASSWORD} then pivots"},
                    {"id": "a2", "attack_technique": "T1078", "target_host_ref": "db"}],
        "relations": [{"kind": "dependency", "from_action": "a1", "to_action": "a2"}],
        "hosts": [{"id": "db", "credentials": {"username": "root", "password": PLAIN_PASSWORD}}],
        "evidence": [{"id": "e1", "quote": f"found key {AWS_KEY} in config"}],
        "environment_plan": plan,
    }


def _generated(plan):
    def fake(sid):
        _, report = generator.inspect_plan(plan, sid)
        return {"compose": generator.compose_document(plan, sid), "report": report}
    return fake


class ExportTestBase(unittest.TestCase):
    plan = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.ir = _ir(self.plan)
        self.patches = [
            patch("app.config.DATA_DIR", self.data),
            patch("app.poc.store._DB", self.data / "poc.db"),
            patch("app.store.get", side_effect=lambda sid: copy.deepcopy(self.ir) if sid == SID else None),
            patch.dict(os.environ, {"CR_TEST_API_TOKEN": ENV_TOKEN}),
        ]
        if self.plan is not None:
            self.patches.append(patch("app.iac.generator.get_generated", side_effect=_generated(self.plan)))
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def build(self):
        data, manifest = B.build_bundle(SID)
        zf = zipfile.ZipFile(io.BytesIO(data))
        return data, manifest, zf


class ExposedPlanExportTests(ExportTestBase):
    plan = {**EXPOSED_PLAN, "hosts": EXPOSED_PLAN["hosts"] + [NOT_DEPLOYED_HOST]}

    def _seed_validation(self):
        from app.poc import store as poc_store
        ev_dir = self.data / "artifacts" / "poc"
        ev_dir.mkdir(parents=True)
        ev = ev_dir / "a1-response.txt"
        ev.write_bytes(b"OGNL 1337*1337=1787569\n")
        poc_store.save_plan(SID, {"scenario_id": SID, "generated_at": "t", "items": []})
        poc_store.save_run(SID, {
            "action_id": "a1", "status": "PASS", "payload_sha256": "ab" * 32, "target_ownership_verified": True,
            "started_at": "t0", "ended_at": "t1",
            "evidence": [
                {"kind": "exploit_effect", "path": str(ev), "sha256": hashlib.sha256(ev.read_bytes()).hexdigest(),
                 "redacted": False, "note": f"bearer token was {ENV_TOKEN}"},
                {"kind": "log", "path": "/etc/passwd", "sha256": "00" * 32, "redacted": False, "note": "outside"},
            ]})

    def test_bundle_has_owner_layout_and_manifest_sha256s_verify(self):
        self._seed_validation()
        data, manifest, zf = self.build()
        names = set(zf.namelist())
        for required in ("README.md", "manifest.json", "scenario/scenario.json", "scenario/scenario.yaml",
                         "scenario/attack-chain.json", "infrastructure/docker-compose.yml",
                         "infrastructure/.env.example", "validation/validation-plan.json",
                         "validation/results.json", "evidence/evidence-index.json"):
            self.assertIn(required, names)
        self.assertEqual(B.verify_bundle(data), [])
        listed = {f["path"]: f["sha256"] for f in manifest["files"]}
        self.assertEqual(set(listed), names - {"manifest.json"})
        for path, digest in listed.items():
            self.assertEqual(hashlib.sha256(zf.read(path)).hexdigest(), digest, path)
        self.assertEqual(json.loads(zf.read("manifest.json")), manifest)
        self.assertEqual(manifest["scenario_version"], 3)
        self.assertIs(manifest["contains_secrets"], False)
        from cr_contracts import iter_errors_shape
        self.assertEqual(iter_errors_shape("ExportManifest", manifest), [])

    def test_compose_is_the_real_generator_output(self):
        _, _, zf = self.build()
        self.assertEqual(zf.read("infrastructure/docker-compose.yml").decode(),
                         generator.compose_document(self.plan, SID))
        images = yaml.safe_load(zf.read("infrastructure/docker-compose.yml"))["services"]
        readme = zf.read("README.md").decode()
        for svc in images.values():
            self.assertIn(f"docker pull {svc['image']}", readme)

    def test_tampered_bundle_fails_verification(self):
        data, _, zf = self.build()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as w:
            for n in zf.namelist():
                body = zf.read(n)
                w.writestr(n, body + b"\n# tampered\n" if n == "scenario/scenario.yaml" else body)
            w.writestr("extra.txt", b"x")
        errors = B.verify_bundle(out.getvalue())
        self.assertIn("sha256 mismatch: scenario/scenario.yaml", errors)
        self.assertIn("unlisted file in bundle: extra.txt", errors)

    def test_no_secret_values_present(self):
        self._seed_validation()
        data, _, zf = self.build()
        for name in zf.namelist():
            body = zf.read(name).decode("utf-8")
            for secret in (PLAIN_PASSWORD, INLINE_PASSWORD, AWS_KEY, ENV_TOKEN):
                self.assertNotIn(secret, body, f"{secret!r} leaked into {name}")
        scenario = json.loads(zf.read("scenario/scenario.json"))
        self.assertEqual(scenario["hosts"][0]["credentials"]["password"], "[REDACTED]")
        self.assertIn("password=[REDACTED]", scenario["actions"][0]["description"])
        env = zf.read("infrastructure/.env.example").decode()
        self.assertIn("\nCR_DB_PASSWORD=\n", env)  # placeholder only, empty so compose's :? refuses to start
        self.assertIn("CR_BIND_IP=127.0.0.1", env)

    def test_missing_images_listed_and_not_rebuildable(self):
        _, manifest, zf = self.build()
        self.assertFalse(manifest["rebuildable"])
        erp = [m for m in manifest["missing_for_rebuild"] if "host erp" in m]
        self.assertEqual(len(erp), 1)
        self.assertIn("closed-source appliance", erp[0])
        readme = zf.read("README.md").decode()
        self.assertIn("環境可完全重建 (fully rebuildable) | **否**", readme)
        self.assertIn("描述檔可匯出 (descriptors exportable) | **是**", readme)

    def test_terraform_and_ansible_omitted_not_faked(self):
        _, manifest, zf = self.build()
        self.assertFalse([n for n in zf.namelist() if "terraform" in n or "ansible" in n])
        self.assertTrue(any(m.startswith("infrastructure/terraform/") for m in manifest["missing_for_rebuild"]))
        self.assertTrue(any(m.startswith("infrastructure/ansible/") for m in manifest["missing_for_rebuild"]))

    def test_evidence_index_verifies_hash_and_ignores_paths_outside_data_dir(self):
        self._seed_validation()
        _, _, zf = self.build()
        index = json.loads(zf.read("evidence/evidence-index.json"))
        self.assertFalse(index["raw_evidence_included"])
        inside, outside = index["items"]
        self.assertTrue(inside["present_on_exporting_host"] and inside["sha256_verified"])
        self.assertFalse(outside["present_on_exporting_host"] or outside["sha256_verified"])
        self.assertFalse([n for n in zf.namelist() if n.startswith("evidence/") and n != "evidence/evidence-index.json"])

    def test_absent_validation_artifacts_are_omitted_not_fabricated(self):
        _, _, zf = self.build()
        names = zf.namelist()
        for absent in ("validation/validation-plan.json", "validation/poc-manifest.json",
                       "validation/results.json", "validation/fidelity-report.json"):
            self.assertNotIn(absent, names)
        self.assertIn("validation-plan.json omitted", zf.read("README.md").decode())

    def test_secret_in_compose_aborts_export(self):
        real = _generated(self.plan)

        def leaky(sid):
            out = real(sid)
            out["compose"] += f"# {AWS_KEY}\n"
            return out
        with patch("app.iac.generator.get_generated", side_effect=leaky):
            with self.assertRaises(B.ExportError):
                B.build_bundle(SID)

    def test_export_writes_new_file_each_time_and_records_it(self):
        first = B.export(SID)
        second = B.export(SID)
        self.assertNotEqual(first["bundle_path"], second["bundle_path"])
        for result in (first, second):
            path = Path(result["bundle_path"])
            self.assertTrue(path.is_file())
            self.assertIn(self.data / "exports" / SID, path.parents)
            self.assertEqual(B.verify_bundle(path), [])
        rows = sqlite3.connect(self.data / "poc.db").execute(
            "SELECT bundle_path, rebuildable FROM poc_exports WHERE scenario_id=?", (SID,)).fetchall()
        self.assertEqual([r[0] for r in rows], [first["bundle_path"], second["bundle_path"]])
        self.assertEqual({r[1] for r in rows}, {0})

    def test_iac_variant_has_only_infrastructure_and_manifest(self):
        self._seed_validation()
        data, _ = B.build_bundle(SID, "iac")
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        self.assertIn("infrastructure/docker-compose.yml", names)
        self.assertEqual({n for n in names if not n.startswith("infrastructure/")}, {"manifest.json"})
        self.assertEqual(B.verify_bundle(data), [])

    def test_evidence_variant_has_only_validation_evidence_and_is_not_rebuildable(self):
        self._seed_validation()
        data, manifest = B.build_bundle(SID, "evidence")
        names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        self.assertEqual({n for n in names if not n.startswith(("validation/", "evidence/"))}, {"manifest.json"})
        self.assertIn("evidence/evidence-index.json", names)
        self.assertFalse(manifest["rebuildable"])
        self.assertTrue(manifest["missing_for_rebuild"][0].startswith("infrastructure/ — not included"))
        self.assertEqual(B.verify_bundle(data), [])

    def test_no_secret_values_in_any_variant(self):
        self._seed_validation()
        for fmt in ("full", "iac", "evidence", "bogus", None):
            data, _ = B.build_bundle(SID, fmt)
            zf = zipfile.ZipFile(io.BytesIO(data))
            for name in zf.namelist():
                body = zf.read(name).decode("utf-8")
                for secret in (PLAIN_PASSWORD, INLINE_PASSWORD, AWS_KEY, ENV_TOKEN):
                    self.assertNotIn(secret, body, f"{fmt}: {secret!r} leaked into {name}")

    def test_unknown_or_absent_format_is_full(self):
        for fmt in (None, "", "bogus", 3):
            self.assertEqual(B.normalize_format(fmt), "full")
        full = set(zipfile.ZipFile(io.BytesIO(B.build_bundle(SID)[0])).namelist())
        bogus = set(zipfile.ZipFile(io.BytesIO(B.build_bundle(SID, "bogus")[0])).namelist())
        self.assertEqual(full, bogus)
        self.assertIn("README.md", bogus)

    def test_latest_bundle_returns_newest_existing_export_or_none(self):
        self.assertIsNone(B.latest_bundle(SID))
        B.export(SID)
        second = B.export(SID, "iac")
        self.assertEqual(B.latest_bundle(SID), Path(second["bundle_path"]).resolve())
        self.assertTrue(second["bundle_path"].endswith("-iac.zip"))
        # a row pointing outside this scenario's export dir is never served
        from app.poc import store as poc_store
        poc_store.save_export(SID, "/etc/passwd", {"scenario_version": 3, "rebuildable": False})
        self.assertEqual(B.latest_bundle(SID), Path(second["bundle_path"]).resolve())

    def test_export_is_read_only_for_poc_state(self):
        """Regression: exporting must not create/overwrite a plan (service.report() used to call plan())."""
        from app.poc import store as poc_store
        B.build_bundle(SID)
        self.assertIsNone(poc_store.get_plan(SID))
        self._seed_validation()
        before = poc_store.get_plan(SID)
        B.build_bundle(SID)
        self.assertEqual(poc_store.get_plan(SID), before)

    def test_service_report_is_never_called(self):
        with patch("app.poc.service.report", side_effect=AssertionError("export must not call report()")), \
                patch("app.poc.service.plan", side_effect=AssertionError("export must not call plan()")):
            self._seed_validation()
            B.build_bundle(SID)

    def test_url_userinfo_and_secret_ref_defaults_are_redacted_and_scanned(self):
        synthetic = "m9-local-synthetic-pw-5521"
        self.ir["description"] = f"repo at https://qa-user:{synthetic}@example.invalid/private, db ${{DB_PASSWORD:-{synthetic}}}"
        self.ir["hosts"] = [{"id": "web", "password": "${DB_PASSWORD:-" + synthetic + "}"},
                            {"id": "app", "secret": "${APP_MODE:-" + synthetic + "}"},
                            {"id": "ok", "mode": "${CR_PG_AUTH_METHOD:-trust}"}]
        data, manifest, zf = self.build()
        leaking = [n for n in zf.namelist() if synthetic.encode() in zf.read(n)]
        self.assertEqual(leaking, [])
        scenario = json.loads(zf.read("scenario/scenario.json"))
        self.assertIn("https://[REDACTED]@example.invalid/private", scenario["description"])  # whole userinfo
        self.assertEqual(scenario["hosts"][0]["password"], "${DB_PASSWORD:-[REDACTED]}")
        self.assertEqual(scenario["hosts"][1]["secret"], "${APP_MODE:-[REDACTED]}")
        self.assertEqual(scenario["hosts"][2]["mode"], "${CR_PG_AUTH_METHOD:-trust}")  # non-secret default kept
        self.assertEqual(B.verify_bundle(data), [])

    def test_final_scan_flags_userinfo_and_secret_defaults(self):
        self.assertTrue(B.find_secrets("x https://u:p4ss@h.invalid/ y", []))
        self.assertTrue(B.find_secrets("${DB_PASSWORD:-hunter2}", []))
        self.assertFalse(B.find_secrets("https://[REDACTED]@h.invalid/ ${DB_PASSWORD:-[REDACTED]} "
                                        "${CR_BIND_IP:-127.0.0.1} ${CR_DB_PASSWORD:?set at deploy time}", []))

    def test_fresh_secret_syntax_is_redacted_and_rescanned(self):
        """R2-01: quoted userinfo, token-as-username, query tokens, every ${...} branch, nesting."""
        z = "m9-local-synthetic-cred-R2x9"
        self.ir["description"] = (f"a https://qa-user:{z}'ok@example.invalid/p b https://{z}@example.invalid/p "
                                  f"c https://example.invalid/?x=1&access_token={z}#frag d ${{SERVICE_TOKEN:={z}}} "
                                  f"e ${{CFG:-${{DB_PASSWORD:-{z}}}}}")
        self.ir["hosts"] = [{"id": "w1", "password": "${DB_PASSWORD:?" + z + "}"},
                            {"id": "w2", "password": "${DB_PASSWORD:-${FALLBACK:-" + z + "}}"},
                            {"id": "w3", "token": "prefix-${T}-" + z}]
        data, _, zf = self.build()
        self.assertEqual([n for n in zf.namelist() if z.encode() in zf.read(n)], [])
        hosts = json.loads(zf.read("scenario/scenario.json"))["hosts"]
        self.assertEqual([h.get("password", h.get("token")) for h in hosts],
                         ["${DB_PASSWORD:?[REDACTED]}", "${DB_PASSWORD:-[REDACTED]}", "[REDACTED]"])
        self.assertEqual(B.verify_bundle(data), [])

    def test_scanners_flag_each_fresh_form(self):
        z = "m9-local-synthetic-cred-R2x9"
        for text in (f"https://u:{z}'ok@h.invalid/", f"https://{z}@h.invalid/", f"https://h.invalid/?access_token={z}",
                     "${SERVICE_TOKEN:=" + z + "}", "${CFG:-${DB_PASSWORD:-" + z + "}}"):
            self.assertTrue(B.find_secrets(text, []), text)
        for field in ("${DB_PASSWORD:?" + z + "}", "${DB_PASSWORD:-${FALLBACK:-" + z + "}}", z, 12345):
            self.assertTrue(B.find_field_secrets({"hosts": [{"password": field}]}), field)
        self.assertFalse(B.find_field_secrets({"password": "${DB_PASSWORD:?[REDACTED]}", "user": z}))

    def test_verify_bundle_reports_secret_left_in_secret_field(self):
        data, manifest, zf = self.build()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as w:
            for n in zf.namelist():
                body = zf.read(n)
                if n == "scenario/scenario.json":
                    obj = json.loads(body)
                    obj["hosts"][0]["credentials"]["password"] = "${DB_PASSWORD:?leak-value}"
                    body = json.dumps(obj).encode()
                    for f in manifest["files"]:
                        if f["path"] == n:
                            f["sha256"] = hashlib.sha256(body).hexdigest()
                w.writestr(n, json.dumps(manifest).encode() if n == "manifest.json" else body)
        self.assertIn("secret material in scenario/scenario.json", B.verify_bundle(out.getvalue()))

    def test_r3_quoted_encoded_and_mapping_key_secrets_are_redacted(self):
        z = "m9-local-synthetic-cred-R3q7"
        self.ir["description"] = (f"a password='{z}' b password=\"{z}\" c apiKey: '{z}' "
                                  f"d https://example.invalid/?access_token=public'{z} "
                                  f"e https://example.invalid/?%61ccess_token={z}&page=2")
        self.ir["hosts"] = [{"id": "w1", "credentials": {z: "[REDACTED]", "username": "svc"}},
                            {"id": "w2", "clientSecret": z}]
        data, manifest, zf = self.build()  # must build (not refuse) and must not leak
        self.assertEqual([n for n in zf.namelist() if z.encode() in zf.read(n)], [])
        scenario = json.loads(zf.read("scenario/scenario.json"))
        self.assertIn("password='[REDACTED]'", scenario["description"])
        self.assertIn('password="[REDACTED]"', scenario["description"])
        self.assertIn("?%61ccess_token=[REDACTED]&page=2", scenario["description"])
        self.assertEqual(scenario["hosts"][0]["credentials"], {"[REDACTED-key-1]": "[REDACTED]", "username": "[REDACTED]"})
        self.assertEqual(scenario["hosts"][1]["clientSecret"], "[REDACTED]")
        self.assertEqual(B.verify_bundle(data), [])

    def test_r3_scanners_flag_each_form_and_never_echo_the_value(self):
        z = "m9-local-synthetic-cred-R3q7"
        for text in (f"password='{z}'", f'password="{z}"', f"https://h.invalid/?access_token=public'{z}",
                     f"https://h.invalid/?%61ccess_token={z}", f'{{"d": "password=\\"{z}\\""}}'):
            hits = B.find_secrets(text, [])
            self.assertTrue(hits, text)
            self.assertNotIn(z, " ".join(hits))
        hits = B.find_field_secrets({"credentials": {z: "[REDACTED]"}}) + B.find_field_secrets({"clientSecret": z})
        self.assertEqual(len(hits), 2)
        self.assertNotIn(z, " ".join(hits))
        # no false positives on benign text the bundle itself emits
        self.assertEqual(B.find_secrets("secret = false; token: null; `contains_secrets` 為 false; "
                                        "password: '[REDACTED]' ${CR_DB_PASSWORD:?set at deploy time}", []), [])

    def test_r4_structural_forms_are_redacted_precisely(self):
        import base64
        z = "m9-local-synthetic-cred-R4k3"
        basic = base64.b64encode(f"u:{z}".encode()).decode()
        cases = {
            json.dumps({"password": z, "user": "x"}): {"password": "[REDACTED]", "user": "x"},
            "'password': '" + z + "'": {"password": "[REDACTED]"},
            "Authorization: Basic " + basic: {"Authorization": "[REDACTED]"},
            "Cookie: session_id=" + z + "; theme=dark": {"Cookie": "[REDACTED]"},
            "//u:" + z + "@h.invalid/p": "//[REDACTED]@h.invalid/p",
            'https://u:pub"' + z + "@h.invalid/": "https://[REDACTED]@h.invalid/",
            "password='public'\"" + z + '"': "password='[REDACTED]'",
            "password='public''" + z + "'": "password='[REDACTED]'",
            "password=[REDACTED]" + z: "password=[REDACTED]",
            'password="${DB_PASSWORD}' + z + '"': 'password="[REDACTED]"',
            "https://h.invalid/?%61%63%63%65%73%73%5f%74%6f%6b%65%6e=" + z: "https://h.invalid/?%61%63%63%65%73%73%5f%74%6f%6b%65%6e=[REDACTED]",
        }
        for raw, expected in cases.items():
            cleaned = B.redact(raw, [])
            self.assertEqual(yaml.safe_load(cleaned) if isinstance(expected, dict) else cleaned, expected, raw)
            self.assertNotIn(z, cleaned)
            self.assertNotIn(basic, cleaned)
            self.assertEqual(B.find_field_secrets({"description": cleaned}), [], raw)
            self.assertTrue(B.find_secrets(raw, []) or B.find_field_secrets(B._embedded_structure(raw)), raw)
        self.assertEqual(B.redact({"%70%61%73%73%77%6f%72%64": z}, []), {"%70%61%73%73%77%6f%72%64": "[REDACTED]"})
        nested = B.redact(json.dumps({"nested": json.dumps({"token": z})}), [])
        self.assertNotIn(z, nested)
        self.assertIn("nested", nested)
        # safe references stay; generator compose refs allowed only in the compose scan
        self.assertEqual(B.find_secrets('password="${DB_PASSWORD}" token=${T:-[REDACTED]}', []), [])
        self.assertTrue(B.find_secrets("MYSQL_PASSWORD: ${CR_DB_PASSWORD:?set at deploy time}", []))
        self.assertEqual(B.find_secrets("MYSQL_PASSWORD: ${CR_DB_PASSWORD:?set at deploy time}", [], compose=True), [])

    def test_r5_multiline_values_are_redacted_whole_and_checked_by_parsing(self):
        z = "m9-local-synthetic-cred-R5m1"
        cases = {
            "password: |\n  " + z + "\n  second line\n": {"password": "[REDACTED]"},
            "password: >-\n  " + z + "\n": {"password": "[REDACTED]"},
            "password:\n  " + z + "\n": {"password": "[REDACTED]"},
            'password: "public\n  ' + z + '"\n': {"password": "[REDACTED]"},
            "password=public\\\n" + z + "\n": "password=[REDACTED]\n",
            "Intro.\ncreds:\n  password: |\n    " + z + "\nafter: ok\n":
                ["Intro.\n", {"creds": {"password": "[REDACTED]"}, "after": "ok"}],
        }
        for raw, expected in cases.items():
            cleaned = B.redact(raw, [])
            self.assertEqual(B._embedded_structure(cleaned) if isinstance(expected, (dict, list)) else cleaned,
                             expected, raw)
            self.assertNotIn(z, cleaned)
            self.assertEqual(B.find_field_secrets({"description": cleaned}), [], raw)
            self.assertTrue(B.find_secrets(raw, []) or B.find_field_secrets(B._embedded_structure(raw)), raw)
        # parse-based check: an embedded YAML secret key with a real value is a leak even with no label hit
        self.assertTrue(B.find_field_secrets({"description": "a: 1\npassword: >\n  " + z + "\n"}))
        self.assertEqual(B.find_field_secrets({"description": "a: 1\npassword: [REDACTED]\n"}), [])
        self.ir["description"] = "Intro.\npassword: |\n  " + z + "\nafter: ok\n"
        data, _, zf = self.build()
        self.assertEqual([n for n in zf.namelist() if z.encode() in zf.read(n)], [])
        self.assertIn("after: ok", json.loads(zf.read("scenario/scenario.json"))["description"])
        self.assertEqual(B.verify_bundle(data), [])

    def test_secret_default_in_compose_aborts_export(self):
        real = _generated(self.plan)

        def leaky(sid):
            out = real(sid)
            out["compose"] += "# ${DB_PASSWORD:-hunter2hunter2}\n"
            return out
        with patch("app.iac.generator.get_generated", side_effect=leaky):
            with self.assertRaises(B.ExportError):
                B.build_bundle(SID)

    def test_unknown_scenario_raises_key_error(self):
        with self.assertRaises(KeyError):
            B.build_bundle("scn_nope")


class DemoPlanRebuildableTests(ExportTestBase):
    plan = DEMO_PLAN

    def test_demo_plan_is_rebuildable_with_bundled_build_context(self):
        data, manifest, zf = self.build()
        self.assertTrue(manifest["rebuildable"], manifest["missing_for_rebuild"])
        # only the non-blocking "not generated by this project" notes remain
        self.assertTrue(all(m.startswith(("infrastructure/terraform/", "infrastructure/ansible/"))
                            for m in manifest["missing_for_rebuild"]))
        compose = yaml.safe_load(zf.read("infrastructure/docker-compose.yml"))
        self.assertEqual(compose["services"]["demo-api"]["build"]["context"], "./templates/demo-app")
        self.assertIn("infrastructure/templates/demo-app/Dockerfile", zf.namelist())
        self.assertIn("**是**", zf.read("README.md").decode().split("fully rebuildable")[1].split("\n")[0])
        self.assertEqual(B.verify_bundle(data), [])


class VmAndUngeneratedTests(ExportTestBase):
    plan = None  # compose cannot be generated for a plan with a VM host

    def setUp(self):
        super().setUp()
        self.ir["environment_plan"] = {**DEMO_PLAN, "hosts": DEMO_PLAN["hosts"] + [VM_HOST]}
        p = patch("app.iac.generator.get_generated", side_effect=FileNotFoundError(SID))
        p.start()
        self.patches.append(p)

    def test_vm_image_and_compose_listed_as_missing(self):
        data, manifest, zf = self.build()
        self.assertFalse(manifest["rebuildable"])
        missing = manifest["missing_for_rebuild"]
        self.assertTrue(any(m.startswith("VM image for host dc01") for m in missing), missing)
        self.assertTrue(any(m.startswith("infrastructure/docker-compose.yml: not generated") for m in missing))
        self.assertFalse([n for n in zf.namelist() if n.startswith("infrastructure/")])
        self.assertIn("scenario/scenario.json", zf.namelist())  # descriptors still exportable
        self.assertEqual(B.verify_bundle(data), [])


class FailClosedStructureTests(ExportTestBase):
    plan = EXPOSED_PLAN
    synthetic = "m9-structured-synthetic-credential-R6f8"

    def assert_resolved_secret_values_removed(self, obj, under_secret=False, depth=0):
        """Independent oracle: real YAML also reads JSON and resolves encoded strings recursively."""
        self.assertLess(depth, 128)
        if isinstance(obj, dict):
            for key, value in obj.items():
                name = key.decode() if isinstance(key, bytes) else key
                self.assert_resolved_secret_values_removed(
                    value, under_secret or name in {"password", "credentials", "token"}, depth + 1)
        elif isinstance(obj, list):
            for value in obj:
                self.assert_resolved_secret_values_removed(value, under_secret, depth + 1)
        elif under_secret:
            self.assertIn(obj, ("[REDACTED]", "", b"", None, True, False))
        elif isinstance(obj, str):
            resolved = yaml.safe_load(obj)
            if resolved != obj:
                self.assert_resolved_secret_values_removed(resolved, False, depth + 1)

    def reseal(self, zf, path, body):
        files = {name: zf.read(name) for name in zf.namelist()}
        files[path] = body
        manifest = json.loads(files["manifest.json"])
        for entry in manifest["files"]:
            if entry["path"] == path:
                entry["sha256"] = hashlib.sha256(body).hexdigest()
        files["manifest.json"] = json.dumps(manifest).encode()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as dest:
            for name, value in files.items():
                dest.writestr(name, value)
        return out.getvalue()

    def test_resolved_tags_aliases_and_nested_documents_are_clean_in_both_emitted_formats(self):
        z = self.synthetic
        encoded = base64.b64encode(z.encode()).decode()
        inputs = [
            "password: !!str " + z,
            "password: !!str |\n  " + z + "\n",
            "password: !!str >\n  " + z + "\n",
            "password: !!binary |\n  " + encoded + "\n",
            '"\\u0070assword": !!str false\n',
            "!!binary cGFzc3dvcmQ=: !!str " + z,
            "credentials:\n  public: &value " + z + "\n  password: *value\n",
            "defaults: &creds {password: " + z + "}\ncopy: {<<: *creds}\n",
            "password: !!set {" + z + ": null}",
            "password: !!omap [{value: " + z + "}]",
            json.dumps({"nested": "password: !!binary " + encoded}),
            yaml.safe_dump({"nested": json.dumps({"password": z})}),
            json.dumps(json.dumps({"password": z})),
        ]
        for source in inputs:
            with self.subTest(source=source):
                self.ir["description"] = source
                data, manifest, zf = self.build()
                for name in ("scenario/scenario.json", "scenario/scenario.yaml"):
                    outer = (json.loads(zf.read(name)) if name.endswith(".json")
                             else yaml.safe_load(zf.read(name)))
                    self.assertNotIn(z, outer["description"])
                    self.assertNotIn(encoded, outer["description"])
                    self.assert_resolved_secret_values_removed(outer)
                    self.assertEqual(B.find_field_secrets(outer), [])
                self.assertIs(manifest["contains_secrets"], False)
                self.assertEqual(B.verify_bundle(data), [])

    def test_secret_aliases_cannot_keep_a_public_copy_of_the_original_value(self):
        for value in ("!!str " + self.synthetic,
                      "!!binary " + base64.b64encode(self.synthetic.encode()).decode()):
            for document in ("public: &value " + value + "\npassword: *value\n",
                             "password: &value " + value + "\npublic: *value\n"):
                with self.subTest(document=document):
                    self.ir["description"] = document
                    with self.assertRaises(B.ExportError) as raised:
                        self.build()
                    self.assertNotIn(self.synthetic, str(raised.exception))

    def test_malformed_embedded_documents_are_refused_and_verifier_flags_them_with_correct_hash(self):
        _, _, zf = self.build()
        for source in (
            "password: [REDACTED] " + self.synthetic,
            "password: [REDACTED] |\n  " + self.synthetic + "\n",
            "password: !unknown " + self.synthetic,
            '{"password": "[REDACTED]",',
            "Intro.\npassword: [REDACTED] >\n  " + self.synthetic,
            "&loop {node: *loop}",
            "node: " + "[" * 80 + "null" + "]" * 80,
        ):
            with self.subTest(source=source):
                self.ir["description"] = source
                with self.assertRaises(B.ExportError) as raised:
                    self.build()
                self.assertNotIn(self.synthetic, str(raised.exception))
                for path in ("scenario/scenario.json", "scenario/scenario.yaml"):
                    ir = json.loads(zf.read("scenario/scenario.json"))
                    ir["description"] = source
                    body = (json.dumps(ir) if path.endswith(".json") else yaml.safe_dump(ir)).encode()
                    errors = B.verify_bundle(self.reseal(zf, path, body))
                    self.assertIn("secret material in " + path, errors)
                    self.assertFalse(any("sha256" in error for error in errors), errors)
                    self.assertNotIn(self.synthetic, " ".join(errors))

    def test_corrupt_or_unredacted_reserialization_is_refused(self):
        for bad_output in ("password: [REDACTED] |\n  " + self.synthetic,
                           "password: !!binary " + base64.b64encode(self.synthetic.encode()).decode()):
            with self.subTest(output=bad_output):
                self.ir["description"] = "password: !!str " + self.synthetic
                with patch.object(B.yaml, "safe_dump", return_value=bad_output):
                    with self.assertRaises(B.ExportError):
                        self.build()

    def test_verifier_resolves_real_yaml_bytes_aliases_and_scalar_encodings(self):
        _, _, zf = self.build()
        encoded = base64.b64encode(self.synthetic.encode()).decode()
        for document in (
            "password: !!binary " + encoded,
            "public: &value " + self.synthetic + "\npassword: *value",
            '"\\u0070assword": !!str false',
            "!!binary cGFzc3dvcmQ=: !!str " + self.synthetic,
        ):
            with self.subTest(document=document):
                path = "scenario/scenario.yaml"
                errors = B.verify_bundle(self.reseal(zf, path, document.encode()))
                self.assertIn("secret material in " + path, errors)
                self.assertFalse(any("sha256" in error for error in errors), errors)

    def test_public_documents_prose_and_runtime_references_remain_exportable(self):
        cases = [
            "Public reproduction notes\nNo credentials are required.",
            '"Public reproduction notes"',
            "release: 2026-11-16\nsteps: [inspect, reproduce]\n",
            "defaults: &defaults {name: public}\ncopy: {<<: *defaults}\n",
            "password: ${DB_PASSWORD}\n",
            "password: '[REDACTED]'\n",
            json.dumps({"steps": ["inspect", "reproduce"], "port": 8080}),
        ]
        for source in cases:
            with self.subTest(source=source):
                self.ir["description"] = source
                data, _, zf = self.build()
                self.assertEqual(B.verify_bundle(data), [])
                description = json.loads(zf.read("scenario/scenario.json"))["description"]
                self.assertNotEqual(description, B.REDACTED)
                # Preserve the decoded content, including the generator-independent public values.
                expected = yaml.safe_load(source)
                actual = yaml.safe_load(description)
                self.assertEqual(actual, expected)

    def test_legacy_unquoted_marker_is_normalized_without_a_false_refusal(self):
        self.ir["description"] = "password: [REDACTED]\n"
        data, _, zf = self.build()
        description = json.loads(zf.read("scenario/scenario.json"))["description"]
        self.assert_resolved_secret_values_removed(yaml.safe_load(description))
        self.assertEqual(B.verify_bundle(data), [])


if __name__ == "__main__":
    unittest.main()
