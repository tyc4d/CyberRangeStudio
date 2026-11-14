from app.cti.citations import evidence_record, grade_quote, verify_quote
from app.cti.parser import SourceUnit


def test_grade_quote_exact_and_whitespace_normalization():
    source = "The attacker exploited the public-facing application to gain access."
    assert grade_quote(source, source)["level"] == "exact"
    assert grade_quote("The attacker exploited\nthe public-facing   application", source)["level"] == "exact"


def test_grade_quote_strips_injected_attack_tag():
    source = "The attacker exploited the public-facing application."
    assert grade_quote("The attacker [T1190] exploited the public-facing application.", source)["level"] == "exact"


def test_grade_quote_paraphrase_with_overlapping_keywords_is_partial():
    result = grade_quote(
        "The adversary used stolen credentials to access the internal network through a compromised VPN gateway.",
        "The adversary leveraged stolen credentials and accessed an internal network after compromising a VPN gateway.",
    )
    assert result["level"] == "partial"
    assert result["score"] >= 0.6
    assert result["matched"]


def test_grade_quote_unrelated_text_is_none():
    assert grade_quote("Clouds gather over the quiet harbor.", "The database encrypts customer records at rest.")["level"] == "none"


def test_verify_quote_accepts_strong_but_rejects_partial():
    source = "The attacker exploited the public-facing application to gain access."
    units = [SourceUnit("p1", source, {"kind": "paragraph", "ref": "1"})]
    # Strong: differs only by a trailing stopword -> still verified.
    assert verify_quote("The attacker exploited the public-facing application to gain access and", units[0].locator, units, None)
    # M8: a changed tail content word (access -> entry) must NOT verify any more.
    assert not verify_quote("The attacker exploited the public-facing application to gain entry.", units[0].locator, units, None)
    # A paraphrase must not verify.
    assert not verify_quote("The adversary gained access through a compromised application.", units[0].locator, units, None)


def test_evidence_record_includes_grade_fields():
    source = "The attacker exploited the public-facing application."
    unit = SourceUnit("p1", source, {"kind": "paragraph", "ref": "1"})
    record = evidence_record("e1", "The attacker [T1190] exploited the public-facing application.", "p1", [unit], None)
    assert record["quote_match"] == "exact"
    assert record["match_score"] == 1.0
    assert record["quote_verified"] is True
    assert record["matched_text"] == source
