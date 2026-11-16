# Topology restyle — worker report (agent/topology-restyle, commit dace0a7)

Done: TopologyPage.tsx + palette.ts + theme.css (.topo-scoped) + i18n zh-TW/en restyled to the X-Team look.
- Dark navy dotted canvas; each plan network = rounded indigo zone group with a top-left chip (id + 隔離/可對外); external = dashed border.
- Hosts = compact cards: role icon, `role(id)`, status dot, image hint, service/substitute/version/entry/not-deployable badges (all kept).
- Central "存取邊界 / Access boundary" node (shield) with "default deny · N allow rules" from plan.access_rules; "外部 / Outside" globe node only when a non-isolated network exists.
- Gateway→zone curved light-grey links labelled with network.segment; host connections (purple arrows) and blocked paths (red dashed) kept; multi-homed hosts get a thin dashed link to their other zone.
- Approval gate, rules table, notes, reset layout untouched and working.

Honesty decisions (please confirm with owner if needed):
- The plan carries NO host IPs and segments are names ("scenario", "external"), not CIDRs. So: the lock+IP pill renders only if a host has an `ip` field (never today); edge labels show the segment exactly as given. Nothing invented.
- No real firewall host exists in the plan, so the central node is labelled as the planned access boundary (derived from access_rules), not a named device.
- Status dot = plan deployability (green deployable / orange stand-in / red cannot deploy / grey not stated), NOT live status; tooltip + legend say so.
- Substitute tags in the topology are orange per brief (studio-wide they stay purple).

Checks: `tsc --noEmit` clean; i18n:check — new keys in both locales (pre-existing list.more/lint.loopMore diffs unchanged). Not run: Playwright e2e suite.
Preview (rendered from a real saved scenario, scn_fa2301161837, API mocked read-only):
docs/design/preview/topology-desktop.png, topology-desktop-page.png, topology-phone-page.png
Known limit: at phone width the whole graph fits the box, so it is small until zoomed (no page overflow).
