# Topology restyle to the X-Team / ShieldX look (owner, 2026-11-17)

Reference: docs/design/xteam-reference.png (the owner's liked style). Restyle the network topology view
apps/web/src/pages/TopologyPage.tsx (already a ReactFlow graph) + its palette (apps/web/src/lib/palette.ts) to
match it. This is a VISUAL restyle only — keep all data, interactions, i18n, approval flow, substitute/version
badges and the existing node/edge data model working.

Match these from the reference:
- Dark canvas with a subtle dot/line grid.
- ZONES as rounded, bordered containers (like Office(z2) / OPS(z3)) grouping their hosts, with a small zone
  label chip at the top-left of each group. Map our network segments to these zone groups.
- HOST nodes as compact dark cards: a product/role ICON (left), the host NAME with its node id in parentheses
  (e.g. "xt-userpc-01(n21)"), a small green status dot, and a second line with a LOCK icon + the host IP in a
  pill. Rounded corners, subtle border, blue/purple accent.
- A central GATEWAY/FIREWALL node (like xt-fortigate) and an Internet node (globe) as distinct shapes.
- EDGES: thin light-grey curved links labelled with the subnet CIDR (e.g. 192.168.100.0/24) along the edge.
- Accent palette: deep navy/indigo background, blue/purple node accents, green status dots, orange only for
  warnings (keep our honesty colours: orange for substitute/limit).
- Keep it legible and responsive (works at phone width too, per the finished mobile RWD).

Do NOT invent host data or fake IPs — render whatever the real environment plan provides; if a field (IP, zone)
is absent, degrade gracefully (no lock/IP pill if no IP). Keep substitute/version/not-deployed badges visible.
tsc clean, i18n zh-TW/en parity. Re-run the web typecheck. Commit on agent/topology-restyle. Report with
hc send t31 and a preview screenshot path if you can render one.
