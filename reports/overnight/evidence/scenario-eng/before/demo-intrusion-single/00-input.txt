# Demonstration CTI Incident Note

Analysts reconstructed the following four-step intrusion path from the available incident notes.

1. **Reconnaissance.** From the external network, the attacker first sent HTTP requests to `victim-web` over TCP/80 to identify the internet-facing web application; this reconnaissance preceded the exploitation activity and selected the exposed service as the target.

2. **Initial access.** Next, the attacker exploited a publicly disclosed CVE in the web service and obtained command execution through a web shell; the exposed application was the entry point for this initial access. The report does not identify the CVE or software version.

3. **Discovery.** With the web-shell foothold on `victim-web`, the attacker enumerated the internal network and identified `db` as an internal database host; `db` was not directly reachable from the external network.

4. **Collection.** Finally, the attacker used `victim-web` to connect to `db` over TCP/5432 and collect records. The web-shell foothold and discovery of `db` were prerequisites for this access because the database accepted connections only from the internal network.
