#!/usr/bin/env bash
# Real cross-service dependency check for a deployed plan-wordpress-mysql.json scenario.
# Usage: dependency_probe.sh <compose project name, e.g. cr-demo-infra-eng-xxxxxxxx>
# Proves the web tier really uses the database: stop the DB -> web answers 500;
# start it again -> web recovers. Requests are sent from the attacker container's
# network namespace, i.e. over the lab network, not from the host.
set -u
P="$1"
HELPER="python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"

http() { # http <from-service> <url>
  docker run --rm --pull=never --network "container:$P-$1" --read-only --cap-drop=ALL --user 65532:65532 "$HELPER" python -c "
import urllib.request, urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
opener = urllib.request.build_opener(NoRedirect)
try:
    r = opener.open('$2', timeout=15); code, body = r.status, r.read(400).decode('utf-8', 'replace')
except urllib.error.HTTPError as e:
    code, body = e.code, e.read(400).decode('utf-8', 'replace')
except Exception as e:
    code, body = 'ERR', repr(e)
marker = 'Error establishing a database connection' if 'Error establishing a database connection' in body else ''
print('  $1 -> $2 :', code, marker)
"
}

echo "## 1. baseline (DB up): web answers through a real DB handshake"
http attacker http://web/wp-login.php
echo "## 2. the web container holds the generated DB settings (password value not printed)"
docker exec "$P-web" sh -c 'echo "  WORDPRESS_DB_HOST=$WORDPRESS_DB_HOST WORDPRESS_DB_USER=$WORDPRESS_DB_USER password_set=$([ -n "$WORDPRESS_DB_PASSWORD" ] && echo yes || echo no)"'
echo "## 3. the DB sees the web tier's credentials work (query run inside db with the same generated secret)"
docker exec "$P-db" sh -c 'mysql -h 127.0.0.1 --protocol=tcp -uapp -p"$MYSQL_PASSWORD" app -N -e "select concat(\"  connected as \", current_user(), \" to schema \", database())" 2>/dev/null'
echo "## 4. stop the DB container"
docker stop "$P-db" >/dev/null && echo "  db stopped"
http attacker http://web/wp-login.php
echo "## 5. start the DB again and wait until it is healthy"
docker start "$P-db" >/dev/null
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$P-db")" = healthy ] && break
  sleep 2
done
echo "  db health: $(docker inspect -f '{{.State.Health.Status}}' "$P-db")"
http attacker http://web/wp-login.php
