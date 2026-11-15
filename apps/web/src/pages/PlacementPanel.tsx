import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { EnvHost, EnvNetwork } from "@contracts";
import { joinList, t } from "../i18n";
import "./PlacementPanel.css";

type ContainerState = {
  service?: string;
  name?: string;
  state?: string;
  status?: string;
  health?: string;
};

type PlacementTarget = {
  provider?: string;
  node?: string;
  pool?: string;
  template_vmid?: number;
  worker_vmid_range?: string;
  worker_vcpus?: number;
  worker_memory_mib?: number;
  worker_disk_gib?: number;
};

type WorkerPlacement = {
  vmid?: number;
  name?: string;
  state?: string;
  vcpus?: number;
  memory_mib?: number;
  disk_gib?: number | null;
  nic_count?: number;
};

type ActualPlacement = PlacementTarget & { worker_vm?: WorkerPlacement };

function stateClass(state?: string): string {
  if (!state) return "status-NOT_TESTED";
  const value = (state ?? "").toLowerCase();
  if (/(fail|error|unhealthy|dead)/.test(value)) return "status-FAIL";
  if (/(running|healthy|ready)/.test(value)) return "status-PASS";
  if (/(partial|degraded)/.test(value)) return "status-PARTIAL";
  return "status-NOT_TESTED";
}

const STATE_KEYS = ["running", "healthy", "partial", "stopped", "error", "starting", "not_created"] as const;
function displayState(value?: string, loading = false, failed = false): string {
  if (!value) return loading ? t("pl.st.loading") : failed ? t("pl.st.failed") : t("pl.st.unknown");
  return (STATE_KEYS as readonly string[]).includes(value) ? t(`pl.st.${value as (typeof STATE_KEYS)[number]}`) : value;
}

function hostStateLabel(containerState: string | undefined, deploymentState: string | undefined,
                        loading: boolean, failed: boolean): string {
  if (containerState) return displayState(containerState);
  if (deploymentState === "not_created") return t("pl.st.not_created");
  if (loading) return t("pl.st.loading");
  if (failed || deploymentState === "error") return t("pl.st.failed");
  return t("pl.st.noData");
}

function SegmentLabel({ network }: { network: EnvNetwork }) {
  const category = network.internal === true ? "internal" : network.internal === false ? "external" : "unknown";
  return <span className={`placement-segment is-${category}`}>{t(`pl.seg.${category}`)}</span>;
}

export function PlacementPanel({
  hosts,
  networks,
  containers,
  target,
  actual,
  backend,
  state,
  statusLoading,
  statusError,
}: {
  hosts: EnvHost[];
  networks: EnvNetwork[];
  containers: ContainerState[];
  target?: PlacementTarget;
  actual?: ActualPlacement;
  backend?: string;
  state?: string;
  statusLoading: boolean;
  statusError: boolean;
}) {
  const [selectedHostId, setSelectedHostId] = useState(hosts[0]?.id ?? "");
  useEffect(() => {
    if (!hosts.some((host) => host.id === selectedHostId)) setSelectedHostId(hosts[0]?.id ?? "");
  }, [hosts, selectedHostId]);

  const networksById = useMemo(() => new Map(networks.map((network) => [network.id, network])), [networks]);
  const servicesByHost = useMemo(() => new Map(containers.filter((container) => container.service)
    .map((container) => [container.service!, container])), [containers]);
  const selectedHost = hosts.find((host) => host.id === selectedHostId);
  const selectedContainer = selectedHost ? servicesByHost.get(selectedHost.id) : undefined;
  const selectedHostState = selectedContainer?.state ?? (state === "not_created" ? "not_created" : undefined);
  const isProxmox = backend === "proxmox" || target?.provider === "Proxmox VE" || actual?.provider === "Proxmox VE";
  const isLocal = backend === "local-docker";
  const worker = actual?.worker_vm;
  const workerExists = worker?.vmid !== undefined;
  const info = workerExists ? actual : target;
  const nr = t("pl.tech.notReported");

  // Operator facts. Kept out of the main view: a user does not need them to read the range.
  const tech: [string, string][] = isProxmox ? [
    [t("pl.tech.platform"), info?.provider ?? "Proxmox VE"],
    [t("pl.tech.node"), info?.node ?? nr],
    [t("pl.tech.pool"), info?.pool ?? nr],
    [t("pl.tech.worker"), workerExists ? `${worker!.name ?? ""} · VMID ${worker!.vmid}` : `${t("pl.tech.notCreated")} · ${info?.worker_vmid_range ?? nr}`],
    [t("pl.tech.spec"), `${worker?.vcpus ?? info?.worker_vcpus ?? "—"} vCPU · ${worker?.memory_mib ?? info?.worker_memory_mib ?? "—"} MiB · ${worker?.disk_gib ?? info?.worker_disk_gib ?? "—"} GiB`],
    [t("pl.tech.nics"), worker?.nic_count !== undefined ? String(worker.nic_count) : nr],
  ] : isLocal ? [[t("pl.tech.platform"), t("pl.tech.local")]] : [];

  // Main-view location path. Without a worker, the last level says so plainly instead of showing a VMID range.
  const workerStep = workerExists
    ? { text: `${worker!.name || t("pl.tech.worker")} · VMID ${worker!.vmid}` }
    : { text: statusLoading ? t("pl.whereLoading") : state === "running" ? t("pl.whereUnknown") : t("pl.whereNotDeployed"), muted: true };
  const path: { text: string; muted?: boolean }[] = isProxmox ? [
    { text: info?.provider ?? "Proxmox VE" },
    { text: info?.node ?? t("pl.whereUnknown"), muted: !info?.node },
    { text: info?.pool ?? t("pl.whereUnknown"), muted: !info?.pool },
    workerStep,
  ] : isLocal ? [{ text: t("pl.whereLocal") }] : [];

  const grouped = networks.map((network) => ({
    network,
    hosts: hosts.filter((host) => host.networks?.includes(network.id)),
  }));
  const knownNetworkIds = new Set(networks.map((network) => network.id));
  const unresolvedNetworkIds = [...new Set(hosts.flatMap((host) => host.networks ?? []).filter((id) => !knownNetworkIds.has(id)))];
  unresolvedNetworkIds.forEach((id) => grouped.push({
    network: { id, segment: t("pl.seg.unresolved") },
    hosts: hosts.filter((host) => host.networks?.includes(id)),
  }));
  const withoutSegment = hosts.filter((host) => !host.networks?.length);
  // A host on several networks is drawn once per network. Say so, so it is not read as several machines.
  const repeated = hosts.some((host) => new Set(host.networks ?? []).size > 1);
  if (withoutSegment.length) grouped.push({ network: { id: "__unspecified__", segment: t("pl.seg.none"), internal: false }, hosts: withoutSegment });

  return (
    <section className="placement-panel card flush" aria-label={t("pl.aria")}>
      <header className="placement-panel__header">
        <div>
          <h2>{t("pl.title")}</h2>
          <p>{t("pl.desc")}</p>
        </div>
        <div className="placement-chips">
          <span className="placement-live-state">
            <span className={`placement-dot ${stateClass(state)}`} />
            <span>{displayState(state, statusLoading, statusError)}</span>
          </span>
        </div>
        <Link className="placement-edit-link" to="/topology">{t("pl.editTopology")}</Link>
      </header>

      {/* Where the range runs, as reported by the runtime: platform › node › pool › worker. Nothing is guessed. */}
      {(isProxmox || isLocal) && (
        <div className="placement-path" data-testid="placement-path" title={t("pl.where.hint")}>
          <span className="placement-path__label">{workerExists || isLocal ? t("pl.where") : t("pl.wherePlanned")}</span>
          <ol>
            {path.map((step, i) => <li key={i} className={step.muted ? "is-muted" : undefined}>{step.text}</li>)}
          </ol>
        </div>
      )}

      <div className="placement-workspace">
        <main className="placement-map">
          {hosts.length === 0 ? <div className="placement-empty">{t("pl.noHosts")}</div> : (
            <div className="placement-zones">
              {grouped.map(({ network, hosts: zoneHosts }) => (
                <section key={network.id} className="placement-zone">
                  <header className="placement-zone__header">
                    <div>
                      <span className="placement-zone__kicker">{t("pl.zone")}</span>
                      <h4>{network.segment || network.id}</h4>
                    </div>
                    {network.id !== "__unspecified__" && <SegmentLabel network={network} />}
                  </header>
                  <div className="placement-zone__hosts">
                    {zoneHosts.length === 0 ? <div className="placement-zone__empty">{t("pl.zoneEmpty")}</div> : zoneHosts.map((host) => {
                      const container = servicesByHost.get(host.id);
                      const hostState = container?.state ?? (state === "not_created" ? "not_created" : undefined);
                      const hostLabel = hostStateLabel(container?.state, state, statusLoading, statusError);
                      return (
                        <button key={host.id} type="button"
                          className={`placement-host ${selectedHostId === host.id ? "is-selected" : ""}`}
                          onClick={() => setSelectedHostId(host.id)} aria-pressed={selectedHostId === host.id}>
                          <span className={`placement-host__status ${stateClass(hostState)}`} />
                          <span className="placement-host__body">
                            <strong>{host.role || host.id}</strong>
                            <span className="placement-host__service">{host.services?.map((service) => service.name).join(" · ") || host.image_hint || t("pl.noService")}</span>
                          </span>
                          <span className={`placement-host__state ${stateClass(hostState)}`}>{hostLabel}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
          {repeated && <p className="placement-map__footnote" data-testid="multi-network-note">{t("pl.multiNet")}</p>}
        </main>

        <aside className="placement-inspector" aria-live="polite">
          <h3 className="placement-inspector__title">{t("pl.details")}</h3>
          {!selectedHost ? <div className="placement-empty">{t("pl.pick")}</div> : (
            <>
              <div className="placement-inspector__identity">
                <span className={`placement-host__status ${stateClass(selectedHostState)}`} />
                <div><h4>{selectedHost.role || selectedHost.id}</h4><code>{selectedHost.id}</code></div>
              </div>
              <dl className="placement-details">
                <dt>{t("pl.d.state")}</dt><dd className={stateClass(selectedHostState)}>{hostStateLabel(selectedContainer?.state, state, statusLoading, statusError)}</dd>
                <dt>{t("pl.d.runtime")}</dt><dd>{selectedHost.runtime === "vm" ? t("pl.d.vm") : selectedHost.runtime === "container" ? t("pl.d.container") : t("pl.d.unset")}</dd>
                <dt>{t("pl.d.image")}</dt><dd>{selectedHost.image_hint ?? selectedHost.guest?.image_ref ?? t("pl.d.unset")}</dd>
                <dt>{t("pl.d.zone")}</dt><dd>{selectedHost.networks?.length
                  ? joinList(selectedHost.networks.map((id) => networksById.get(id)?.segment || id))
                  : t("pl.d.unset")}</dd>
                {selectedContainer?.health && <><dt>{t("pl.d.health")}</dt><dd>{selectedContainer.health}</dd></>}
                {selectedHost.guest?.os_family && <><dt>{t("pl.d.os")}</dt><dd>{[selectedHost.guest.os_family, selectedHost.guest.os_release].filter(Boolean).join(" ")}</dd></>}
              </dl>
              <div className="placement-services">
                <h5>{t("pl.d.services")}</h5>
                {selectedHost.services?.length
                  ? selectedHost.services.map((service, index) => <div key={`${service.name}-${index}`} className="placement-service-row">
                    <span>{service.name}</span><code>{service.protocol ?? "tcp"}/{service.port}</code>
                  </div>)
                  : <span className="muted">{t("pl.d.noServices")}</span>}
              </div>
            </>
          )}
        </aside>
      </div>

      {tech.length > 0 && (
        <details className="placement-tech" data-testid="placement-tech">
          <summary>{t("pl.tech")}</summary>
          <dl className="placement-details">
            {tech.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd className="mono">{v}</dd></div>)}
          </dl>
          {!workerExists && isProxmox && <p className="muted">{t("pl.tech.planned")}</p>}
        </details>
      )}
    </section>
  );
}
