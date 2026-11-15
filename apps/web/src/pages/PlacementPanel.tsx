import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { EnvHost, EnvNetwork } from "@contracts";
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
  if (/(down|stopped|exited|not_created|none|absent)/.test(value)) return "status-NOT_TESTED";
  return "status-NOT_TESTED";
}

function displayState(value?: string, loading = false, failed = false): string {
  if (value === "not_created") return "未部署";
  if (!value) return loading ? "讀取中" : failed ? "查詢失敗" : "狀態未知";
  const labels: Record<string, string> = {
    running: "執行中", healthy: "健康", partial: "部分執行", stopped: "已停止",
    error: "錯誤", starting: "啟動中", not_created: "未部署",
  };
  return labels[value] ?? value;
}

function hostStateLabel(containerState: string | undefined, deploymentState: string | undefined,
                        loading: boolean, failed: boolean): string {
  if (containerState) return displayState(containerState);
  if (deploymentState === "not_created") return "未部署";
  if (loading) return "讀取中";
  if (failed || deploymentState === "error") return "查詢失敗";
  return "沒有容器資料";
}

function SegmentLabel({ network }: { network: EnvNetwork }) {
  const category = network.internal === true ? "internal" : network.internal === false ? "external" : "unknown";
  const label = network.internal === true ? "內部（規劃）" : network.internal === false ? "非內部（規劃）" : "屬性未確認";
  return <span className={`placement-segment is-${category}`}>
    {label}
  </span>;
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
  projectName,
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
  projectName: string;
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
  const isLocalDocker = backend === "local-docker";
  const worker = actual?.worker_vm;
  const workerExists = worker?.vmid !== undefined;
  const info = workerExists ? actual : target;
  const provider = info?.provider ?? (isProxmox ? "Proxmox VE" : isLocalDocker ? "本機環境" : statusLoading ? "讀取中" : "未回報");

  const placementLevels = isProxmox
    ? [
      { label: "平台", value: provider },
      { label: "節點", value: info?.node ?? (statusLoading ? "讀取中" : "未回報") },
      { label: "資源池", value: info?.pool ?? (statusLoading ? "讀取中" : "未回報") },
      { label: "Worker VM", value: worker?.vmid !== undefined
        ? `${worker.name ?? "情境工作機"} · VMID ${worker.vmid}`
        : state === "not_created" ? `未建立 · 可用範圍 ${info?.worker_vmid_range ?? "未提供"}`
          : statusLoading ? `查詢中 · 候選範圍 ${info?.worker_vmid_range ?? "未提供"}`
            : statusError || state === "error" ? "位置未確認 · 查詢失敗"
              : state === "running" ? "VM 執行中 · 身分資料未回報"
                : `位置未回報 · 候選範圍 ${info?.worker_vmid_range ?? "未提供"}` },
      { label: "執行方式", value: "容器在 Worker VM 內執行" },
    ]
    : isLocalDocker ? [
      { label: "平台", value: provider },
      { label: "執行層", value: "Docker Engine" },
      { label: "情境", value: projectName },
      { label: "執行方式", value: "服務以容器執行" },
    ] : [
      { label: "平台", value: provider },
      { label: "執行位置", value: statusLoading ? "查詢中" : statusError ? "查詢失敗" : "位置未回報" },
    ];

  const grouped = networks.map((network) => ({
    network,
    hosts: hosts.filter((host) => host.networks?.includes(network.id)),
  }));
  const knownNetworkIds = new Set(networks.map((network) => network.id));
  const unresolvedNetworkIds = [...new Set(hosts.flatMap((host) => host.networks ?? []).filter((id) => !knownNetworkIds.has(id)))];
  unresolvedNetworkIds.forEach((id) => grouped.push({
    network: { id, segment: "未解析網段" },
    hosts: hosts.filter((host) => host.networks?.includes(id)),
  }));
  const withoutSegment = hosts.filter((host) => !host.networks?.length);
  if (withoutSegment.length) grouped.push({ network: { id: "__unspecified__", segment: "位置未指定", internal: false }, hosts: withoutSegment });

  return (
    <section className="placement-panel card flush" aria-label="部署放置圖">
      <header className="placement-panel__header">
        <div>
          <div className="placement-eyebrow">執行位置與情境位置</div>
          <h2>伺服器放置圖</h2>
          <p>{workerExists ? "上方是 PVE 回報的實際執行資源；下方網段是核准拓樸中的邏輯位置。"
            : "上方顯示預定執行目標，尚未確認實際 VM；下方網段是核准拓樸中的邏輯位置。"}</p>
        </div>
        <div className="placement-live-state">
          <span className={`placement-dot ${stateClass(state)}`} />
          <span>{displayState(state, statusLoading, statusError)}</span>
        </div>
        <Link className="placement-edit-link" to="/topology">查看／調整拓樸</Link>
      </header>

      <div className="placement-workspace">
        <aside className="placement-infrastructure">
          <div className="placement-section-heading">
            <span className="placement-section-index">01</span>
            <div><h3>{workerExists ? "實際放置層級" : "預定放置層級"}</h3>
              <span>{workerExists ? "已建立 worker 的 PVE 位置" : "PVE 目標設定，未代表已建立 VM"}</span></div>
          </div>
          <ol className="placement-levels">
            {placementLevels.map((level, index) => (
              <li key={level.label} className={index === placementLevels.length - 1 ? "is-last" : ""}>
                <span className="placement-level-marker" />
                <div className="placement-level-copy">
                  <span>{level.label}</span>
                  <strong title={level.value}>{level.value}</strong>
                </div>
              </li>
            ))}
          </ol>

          {isProxmox && (
            <div className="placement-worker-spec">
              <div className="placement-worker-spec__title">{workerExists ? "實際 Worker 規格" : "預定 Worker 規格"}</div>
              <div><span>{worker?.vcpus ?? info?.worker_vcpus ?? "—"}</span> vCPU</div>
              <div><span>{worker?.memory_mib ?? info?.worker_memory_mib ?? "—"}</span> MiB 記憶體</div>
              <div><span>{worker?.disk_gib ?? info?.worker_disk_gib ?? "—"}</span> GiB 磁碟</div>
              <div className="placement-zero-nic">
                <span className={`placement-dot ${worker?.nic_count === 0 ? "status-PASS" : "status-NOT_TESTED"}`} />
                {worker ? (worker.nic_count === 0 ? "零網卡" : `${worker.nic_count} 張網卡`) : "啟動時檢查零網卡隔離"}
              </div>
            </div>
          )}
          <p className="placement-location-note">{isProxmox
            ? workerExists
              ? "目前 PVE 實際位置資料到節點與資源池為止；沒有機房或機櫃位置欄位。"
              : "目前顯示 PVE 預定節點與資源池；沒有機房或機櫃位置欄位。"
            : isLocalDocker
              ? "本機 Docker 不回報 VM 層級位置；情境主機位置依核准拓樸網段呈現。"
              : "尚未取得執行平台資料，這裡不推測實際放置位置。"}</p>
        </aside>

        <main className="placement-map">
          <div className="placement-section-heading">
            <span className="placement-section-index">02</span>
            <div><h3>情境伺服器位置</h3><span>依核准拓樸的網段與主機關係</span></div>
          </div>
          {hosts.length === 0 ? <div className="placement-empty">目前規劃沒有伺服器。</div> : (
            <div className="placement-zones">
              {grouped.map(({ network, hosts: zoneHosts }) => (
                <section key={network.id} className="placement-zone">
                  <header className="placement-zone__header">
                    <div>
                      <span className="placement-zone__kicker">網路區域</span>
                      <h4>{network.segment || network.id}</h4>
                      <code>{network.id === "__unspecified__" ? "未連結網段" : network.id}</code>
                    </div>
                    {network.id !== "__unspecified__" && <SegmentLabel network={network} />}
                  </header>
                  <div className="placement-zone__hosts">
                    {zoneHosts.length === 0 ? <div className="placement-zone__empty">此網段目前沒有主機。</div> : zoneHosts.map((host) => {
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
                            <span className="mono">{host.id}</span>
                            <span className="placement-host__service">{host.image_hint || host.services?.map((service) => service.name).join(" · ") || host.runtime || "未指定服務"}</span>
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
          {networks.length > 0 && <p className="placement-map__footnote">同一台主機若連接多個網段，會在每個網段位置各顯示一次。</p>}
        </main>

        <aside className="placement-inspector" aria-live="polite">
          <div className="placement-section-heading">
            <span className="placement-section-index">03</span>
            <div><h3>伺服器詳細資料</h3><span>選取網段中的主機查看</span></div>
          </div>
          {!selectedHost ? <div className="placement-empty">選取一台伺服器。</div> : (
            <>
              <div className="placement-inspector__identity">
                <span className={`placement-host__status ${stateClass(selectedHostState)}`} />
                <div><h4>{selectedHost.role || selectedHost.id}</h4><code>{selectedHost.id}</code></div>
              </div>
              <dl className="placement-details">
                <dt>目前狀態</dt><dd className={stateClass(selectedHostState)}>{displayState(selectedHostState)}</dd>
                <dt>服務容器</dt><dd>{selectedContainer?.name ?? hostStateLabel(undefined, state, statusLoading, statusError)}</dd>
                <dt>執行型態</dt><dd>{selectedHost.runtime === "vm" ? "虛擬機" : selectedHost.runtime === "container" ? "容器" : "未指定"}</dd>
                <dt>映像</dt><dd>{selectedHost.image_hint ?? selectedHost.guest?.image_ref ?? "未指定"}</dd>
                <dt>放置網段</dt><dd>{selectedHost.networks?.length
                  ? selectedHost.networks.map((id) => networksById.get(id)?.segment || id).join("、")
                  : "未指定"}</dd>
                {selectedContainer?.health && <><dt>容器健康</dt><dd>{selectedContainer.health}</dd></>}
                {selectedHost.guest?.os_family && <><dt>作業系統</dt><dd>{[selectedHost.guest.os_family, selectedHost.guest.os_release].filter(Boolean).join(" ")}</dd></>}
              </dl>
              <div className="placement-services">
                <h5>服務與埠</h5>
                {selectedHost.services?.length
                  ? selectedHost.services.map((service, index) => <div key={`${service.name}-${index}`} className="placement-service-row">
                    <span>{service.name}</span><code>{service.protocol ?? "tcp"}/{service.port}</code>
                  </div>)
                  : <span className="muted">未列出服務。</span>}
              </div>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
