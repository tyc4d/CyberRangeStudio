# Fixture provenance

`mitre-attack-apt29-external-remote-services.stix.json` is a compact bundle made from unchanged STIX objects selected from the official MITRE ATT&CK Enterprise dataset:

- Source feed: <https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json>
- Repository and usage information: <https://github.com/mitre-attack/attack-stix-data>
- Accessed: 2026-11-14
- Included objects: the ATT&CK `External Remote Services` attack-pattern, the APT29 intrusion-set, their explicit `uses` relationship, and the identity and marking-definition referenced by those objects.

The bundle wrapper has a fixture-specific ID. Its `uses` relationship records an ATT&CK association; it does not say that APT29 depended on the technique, nor does the dataset alone establish that the technique occurred in a particular incident.
