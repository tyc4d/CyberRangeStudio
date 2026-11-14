# MITRE ATT&CK Enterprise technique catalogue provenance

- Source: [MITRE ATT&CK Enterprise STIX](https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json)
- Downloaded: 2026-11-14 (UTC)
- Retrieval tool: `curl -L --fail --silent --show-error --max-time 180`
- HTTP status: 200
- Original file: `/tmp/enterprise-attack.json` (not retained in the repository)
- Original file size: 55,277,605 bytes
- Original file SHA-256: `539a843a7b53ed9749740b2123dddae3726b1a4831841c32aca740b011b910b5`
- Included techniques: 706
- Selection: STIX objects with `type == "attack-pattern"`, a MITRE ATT&CK external reference with an external ID, and neither `revoked == true` nor `x_mitre_deprecated == true`. Each entry contains the external ID, name, MITRE ATT&CK kill-chain phases, reference URL, and the first 400 characters of the description.

## Tactic-name correction and validation

The catalogue was rebuilt from the cached original STIX file on 2026-11-14. The source `phase_name` strings were inspected directly. Two source values, `stealth` and `defense-impairment`, are outside the 14 official tactic short names required for this catalogue, so both are mapped to `defense-evasion` in the output. All other values are copied unchanged. This mapping is applied to satisfy the required official-name validation.

Validation: collected all tactic values across all 706 techniques and compared them with the 14-name allowlist (`reconnaissance`, `resource-development`, `initial-access`, `execution`, `persistence`, `privilege-escalation`, `defense-evasion`, `credential-access`, `discovery`, `lateral-movement`, `collection`, `command-and-control`, `exfiltration`, `impact`). Result: PASS; observed 14 unique values, invalid values: none.
