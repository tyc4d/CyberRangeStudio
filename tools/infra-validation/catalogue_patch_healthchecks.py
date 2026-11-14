"""One-off catalogue edit: honest healthchecks for Solr/WordPress and version probes.

Kept in the repository so the change to components.json is reproducible and reviewable.
Run from the worktree root: python tools/infra-validation/catalogue_patch_healthchecks.py
"""
import json
from pathlib import Path

PATH = Path("apps/api/app/planner/catalogue/components.json")
components = json.loads(PATH.read_text(encoding="utf-8"))
by_id = {entry["id"]: entry for entry in components}

solr = by_id["vuln-log4shell-solr"]["container"]
solr["healthcheck"]["test"] = [
    "CMD-SHELL",
    "curl -fsS -o /dev/null \"http://$$(hostname -i | cut -d' ' -f1):8983/solr/demo/admin/ping\"",
]
solr["healthcheck"]["start_period"] = "90s"
solr["healthcheck"]["retries"] = 24
solr["healthcheck_note"] = (
    "The image first runs a temporary loopback-only Solr to load demo data; the check therefore "
    "targets the container's network address and the demo core, not 127.0.0.1."
)

wordpress = by_id["oss-wordpress"]
wordpress["container"]["healthcheck"]["test"] = [
    "CMD", "curl", "-sS", "-o", "/dev/null", "--max-time", "8", "--fail", "http://127.0.0.1:80/wp-login.php",
]
wordpress["container"]["healthcheck"]["timeout"] = "10s"
wordpress["behavior_probe"] = {
    "type": "http", "path": "/wp-login.php", "expect_status": [200, 302],
    "proves": ("web tier completed a real database handshake (WordPress answers HTTP 500 'Error establishing "
               "a database connection' when MySQL is unreachable or rejects the generated credentials)"),
}
wordpress["known_limits"] = (
    "Pages that call api.wordpress.org (installer language list, update checks) wait for a network "
    "timeout because the lab has no outbound access."
)

VERSION_PROBES = {
    "oss-nginx": (["nginx", "-v"], "1.31.8"),
    "oss-httpd": (["httpd", "-v"], "2.4.71"),
    "oss-postgres": (["postgres", "--version"], "16.16"),
    "oss-attacker": (["cat", "/etc/alpine-release"], "3.22"),
    "oss-mysql": (["mysqld", "--version"], "8.0.46"),
    "oss-mariadb": (["mariadbd", "--version"], "11.4.13"),
    "oss-redis": (["redis-server", "--version"], "v=7.4.12"),
    "oss-tomcat": (["catalina.sh", "version"], "Apache Tomcat/9.0.124"),
    "oss-wordpress": (["php", "-r", "include '/usr/src/wordpress/wp-includes/version.php'; echo $wp_version;"], "7.1.4"),
    "vuln-log4shell-solr": (["sh", "-c", "ls /opt/solr/server/lib/ext/log4j-core-*.jar"], "log4j-core-2.14.1.jar"),
    "vuln-struts2-s2-045": (["sh", "-c", "find / -name 'struts2-core-*.jar' 2>/dev/null | head -1"], "struts2-core-2.3.30.jar"),
}
for component_id, (command, expected) in VERSION_PROBES.items():
    by_id[component_id]["version_probe"] = {"command": command, "expect_substring": expected}

PATH.write_text(json.dumps(components, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("patched", len(VERSION_PROBES), "components")
