// What an instructor can actually connect to, separated from scenario-internal facts.
// Rules (owner-approved scope, 2026-11-16):
// - An entry is shown only when the backend reports it as bound right now (status.published_ports) and the range runs.
// - A bound port proves only the bind / port mapping. Without explicit reachability evidence from the backend
//   (`reachable: true`) the entry is "published, access not verified". Loopback is "deployment host only".
// - Internal hosts, services, ports and plan connections are always marked "range only".
// - On a runtime without an inbound path (Proxmox zero-NIC workers), the UI says there is no instructor entry and shows no
//   internal VM address, IP or port as if it were reachable. Addresses and credentials are never guessed.
// The component only reads. It sends no request of its own.
import { useState } from "react";
import type { EnvConnection, EnvHost, EnvNetwork } from "@contracts";
import { joinList, t } from "../i18n";

export interface PublishedPort {
  host_id?: string | null; container_port?: number | null; host_ip?: string | null; host_port?: number | null;
  /** Explicit evidence from the backend that the instructor side can reach this address. No backend sends it yet. */
  reachable?: boolean;
}

const isLoopback = (ip: string) => /^127\./.test(ip) || ip === "::1" || ip.toLowerCase() === "localhost";
/** 0.0.0.0 / :: are bind settings ("all interfaces"), never a destination a person can connect to. */
const isWildcard = (ip: string) => ["0.0.0.0", "::", "[::]"].includes(ip);

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ }
  };
  return <button className="small" onClick={copy} aria-label={t("ia.copy", { address: text })}>{done ? t("ia.copied") : t("iac.copy")}</button>;
}

export function InstructorAccess({ backend, state, loading, failed, published, hosts, networks, connections, hasPlan }: {
  backend?: string;
  state?: string;
  loading: boolean;
  failed: boolean;
  /** Ports the backend reports as bound now. Undefined when the backend gave no list. */
  published?: PublishedPort[];
  hosts: EnvHost[];
  networks: EnvNetwork[];
  connections: EnvConnection[];
  hasPlan: boolean;
}) {
  const noInbound = backend === "proxmox";
  // Hosts are named by their short plan code (h1, h2…). The plan's role text can be a long sentence in any language;
  // it is shown as written, cut to two lines, with the full value in the title.
  const code = (id?: string | null) => id || "—";
  const roleOf = (id?: string | null) => (id ? hosts.find((h) => h.id === id)?.role ?? "" : "");
  const segment = (id: string) => networks.find((n) => n.id === id)?.segment || id;
  const endpoints = (published ?? []).filter((p) => p.host_ip && p.host_port);

  let entry: JSX.Element;
  if (noInbound) {
    entry = (
      <div className="notice warn" data-testid="instructor-no-entry" role="status">
        <div className="body"><div className="title">{t("ia.pve.title")}</div><div>{t("ia.pve.body")}</div><div className="muted">{t("ia.noGuess")}</div><div data-testid="instructor-next-step" style={{ marginTop: 6, fontWeight: 600 }}>{t("ia.pve.next")}</div></div>
      </div>
    );
  } else if (loading && !state) {
    entry = <div className="muted">{t("ia.checking")}</div>;
  } else if (failed && !state) {
    entry = <div className="muted">{t("ia.unknown")}</div>;
  } else if (state !== "running") {
    entry = <div className="muted">{t("ia.notRunning")}</div>;
  } else if (endpoints.length === 0) {
    entry = <div className="muted">{t("ia.noEndpoints")} {t("ia.noGuess")}</div>;
  } else {
    entry = (
      <div data-testid="published-ports">
        <table className="tbl">
          <thead><tr><th>{t("ia.col.address")}</th><th>{t("ia.col.target")}</th><th>{t("ia.col.scope")}</th><th>{t("ia.col.status")}</th><th /></tr></thead>
          <tbody>
            {endpoints.map((p, i) => {
              const address = `${p.host_ip}:${p.host_port}`;
              const host = hosts.find((h) => h.id === p.host_id);
              const svc = host?.services?.find((s) => s.port === p.container_port);
              const ip = String(p.host_ip);
              const scope = isWildcard(ip) ? "any" : isLoopback(ip) ? "local" : "lan";
              return (
                <tr key={i} data-testid="instructor-endpoint">
                  <td className="mono">{address}</td>
                  <td>{svc
                    ? t("ia.target", { host: code(p.host_id), service: svc.name, proto: svc.protocol ?? "tcp", port: p.container_port })
                    : t("ia.targetNoSvc", { host: code(p.host_id), proto: "tcp", port: p.container_port ?? "?" })}</td>
                  <td>
                    <span className="tag" data-scope={scope}>{t(`ia.scope.${scope}`)}</span>
                    <div className="muted" style={{ fontSize: 13 }}>{t(`ia.scope.${scope}.hint`)}</div>
                  </td>
                  <td>{p.reachable === true && scope !== "any"
                    ? <span className="tag supported" data-status="reachable" title={t("ia.st.reachable.hint")}>{t("ia.st.reachable")}</span>
                    : <span className="tag" data-status="unverified" title={t("ia.st.unverified.hint")}>{t("ia.st.unverified")}</span>}</td>
                  {/* A wildcard bind is not a destination, so it gets no copy button. */}
                  <td>{scope === "any" ? null : <CopyButton text={address} />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="muted" style={{ fontSize: 13, marginTop: 8 }}>{t("ia.note")}</div>
      </div>
    );
  }

  return (
    <section className="card instructor-access" data-testid="instructor-access" aria-labelledby="instructor-access-title">
      <h2 id="instructor-access-title">{t("ia.title")}</h2>
      <h3 style={{ marginTop: 12 }}>{t("ia.entry")}</h3>
      <p className="muted" style={{ margin: "2px 0 8px", fontSize: 13 }}>{t("ia.entry.desc")}</p>
      {entry}

      <details className="instructor-internal" data-testid="instructor-internal">
        <summary>
          {t("ia.internal")} <span className="tag" data-testid="internal-badge">{t("ia.internal.badge")}</span>
        </summary>
        <p className="muted" style={{ fontSize: 13 }}>{t("ia.internal.desc")}</p>
        {!hasPlan ? <div className="muted">{t("ia.noPlan")}</div> : (
          <>
            <table className="tbl">
              <thead><tr><th>{t("ia.col.host")}</th><th>{t("ia.col.network")}</th><th>{t("ia.col.services")}</th></tr></thead>
              <tbody>
                {hosts.map((h) => (
                  <tr key={h.id} data-testid="internal-host">
                    <td>
                      <div className="mono" style={{ fontWeight: 700 }}>{h.id}</div>
                      {h.role && <div className="muted clamp-2" title={h.role}>{h.role}</div>}
                    </td>
                    <td>{h.networks?.length ? joinList(h.networks.map(segment)) : "—"}</td>
                    <td>{h.services?.length
                      ? h.services.map((s, i) => <div key={i}>{s.name} <span className="mono">{s.protocol ?? "tcp"}/{s.port}</span></div>)
                      : <span className="muted">{t("ia.noServices")}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 style={{ margin: "12px 0 6px" }}>{t("ia.allowed", { n: connections.length })}</h3>
            <p className="muted" style={{ margin: "0 0 6px", fontSize: 13 }} data-testid="planned-note">{t("ia.plannedNote")}</p>
            {connections.length ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {connections.map((c, i) => (
                  <li key={i} data-testid="planned-connection" title={`${roleOf(c.from_host)} → ${roleOf(c.to_host)}`}>
                    <span className="mono">{code(c.from_host)} → {code(c.to_host)}</span>{" "}
                    <span className="mono">{c.port ? `${c.protocol ?? "tcp"}/${c.port}` : t("ia.anyPort")}</span>
                  </li>
                ))}
              </ul>
            ) : <div className="muted">{t("ia.noAllowed")}</div>}
          </>
        )}
      </details>
    </section>
  );
}
