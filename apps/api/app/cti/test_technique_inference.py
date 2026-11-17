"""The ATT&CK technique auto-suggestion is conservative and catalogue-valid.

It fills a technique only when none is stated, marks it 'inferred', and never emits
an id that is absent from the distilled ATT&CK catalogue.
"""
from app.cti.analysis import _suggest_technique
from app.cti.attack import lookup


def test_equifax_chain_maps_to_expected_techniques():
    chain = {
        "scan systems for Apache Struts vulnerability": "T1595",
        "discover vulnerable server running online dispute portal": "T1595",
        "exploit Apache Struts vulnerability to gain access and run commands": "T1190",
        "disguise activity using encrypted communication channels": "T1572",
        "issue system-level commands on the dispute portal": "T1059",
        "use unencrypted credentials to expand access to databases": "T1552",
        "run 9,000 queries to extract PII from databases": "T1213",
        "remove extracted PII using encrypted web protocols": "T1048",
    }
    for text, expected in chain.items():
        assert _suggest_technique(text) == expected, text


def test_suggestion_is_none_when_no_signal():
    assert _suggest_technique("the company issued a press release") is None
    assert _suggest_technique("") is None
    assert _suggest_technique("   ") is None


def test_every_rule_target_exists_in_catalogue():
    # Walk a representative input per rule; any suggestion returned must be a real catalogue id.
    samples = ["web shell", "scan", "exploit", "unencrypted password", "mimikatz",
               "valid account", "encrypted communication channel", "run command",
               "lateral movement", "data repository", "enumerate files", "network service",
               "alternative protocol", "disguise as normal traffic", "exfiltrate data", "obfuscate"]
    for s in samples:
        tid = _suggest_technique(s)
        if tid is not None:
            assert lookup(tid) is not None, f"{s} -> {tid} absent from catalogue"
