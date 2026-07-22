import { useState, useEffect, useCallback } from 'react';
import type { ToastKind } from '../components/Toast';
import {
  apiListDockerHosts,
  apiCreateDockerHost,
  apiUpdateDockerHost,
  apiDeleteDockerHost,
  apiHealthCheckHost,
  apiHealthCheckAllHosts,
  apiGetDockerPresets,
  apiGetDockerSetupScript,
  apiGetHostContainers,
  DockerHost,
  DockerHostInput,
} from '../lib/api';
import { useApp, type ConfirmOptions } from '../state/AppContext';
import type { ContainerInfo } from '../types/meeting';
import './DevOpsPanel.css';

/** 从 catch 的 unknown 错误中提取 message */
function getErrMessage(e: unknown, fallback: string): string {
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

/** Docker 主机预设配置项 */
interface DockerPreset {
  key: string;
  config: {
    label?: string;
    description?: string;
    connection_type?: string;
    docker_host?: string;
    ssh_user?: string;
    ssh_port?: number;
    region?: string;
    tags?: string[];
    tls_verify?: boolean;
  };
}

const CONNECTION_TYPE_LABELS: Record<string, string> = {
  local: '本地 Socket',
  tcp: 'TCP 无加密',
  tcp_tls: 'TCP + TLS',
  ssh_key: 'SSH 密钥',
  ssh_password: 'SSH 密码',
  docker_context: 'Docker Context',
};

function HealthBadge({ status }: { status: string }) {
  const cls = status === 'healthy' ? 'badge-ok' : status === 'unhealthy' ? 'badge-err' : 'badge-pending';
  const txt = status === 'healthy' ? '在线' : status === 'unhealthy' ? '离线' : '未检测';
  return <span className={`badge ${cls}`}>{txt}</span>;
}

function ConnTypeBadge({ type }: { type: string }) {
  return <span className="badge badge-info">{CONNECTION_TYPE_LABELS[type] || type}</span>;
}

export default function DevOpsPanel() {
  const { toast, requestConfirm } = useApp();
  const [hosts, setHosts] = useState<DockerHost[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [showScript, setShowScript] = useState(false);
  const [setupScript, setSetupScript] = useState('');
  const [presets, setPresets] = useState<DockerPreset[]>([]);
  const [connectionTypes, setConnectionTypes] = useState<string[]>([]);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [selectedHost, setSelectedHost] = useState<DockerHost | null>(null);
  const [hostContainers, setHostContainers] = useState<ContainerInfo[]>([]);
  const [showContainers, setShowContainers] = useState(false);

  const loadHosts = useCallback(async () => {
    try {
      const data = await apiListDockerHosts();
      setHosts(data.hosts);
    } catch (e: unknown) {
      toast?.(getErrMessage(e, '加载主机列表失败'), 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadHosts();
    apiGetDockerPresets().then(d => {
      setPresets((d.presets || []) as DockerPreset[]);
      setConnectionTypes(d.connection_types || []);
    }).catch(() => {});
  }, [loadHosts]);

  const handleHealthCheck = async (id: number) => {
    setCheckingId(id);
    try {
      await apiHealthCheckHost(id);
      toast?.('健康检查完成', 'success');
      await loadHosts();
    } catch (e: unknown) {
      toast?.(getErrMessage(e, '健康检查失败'), 'error');
    } finally {
      setCheckingId(null);
    }
  };

  const handleCheckAll = async () => {
    try {
      const r = await apiHealthCheckAllHosts();
      toast?.(`已检查 ${r.checked} 台主机`, 'success');
      await loadHosts();
    } catch (e: unknown) {
      toast?.(getErrMessage(e, '批量检查失败'), 'error');
    }
  };

  const handleDelete = async (host: DockerHost) => {
    const ok = await requestConfirm({
      title: '删除主机',
      message: `确定要删除主机 "${host.name}" 吗？此操作不可恢复。`,
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      await apiDeleteDockerHost(host.id);
      toast?.('主机已删除', 'success');
      await loadHosts();
    } catch (e: unknown) {
      toast?.(getErrMessage(e, '删除失败'), 'error');
    }
  };

  const handleToggleEnabled = async (host: DockerHost) => {
    try {
      await apiUpdateDockerHost(host.id, { enabled: !host.enabled });
      await loadHosts();
    } catch (e: unknown) {
      toast?.(getErrMessage(e, '更新失败'), 'error');
    }
  };

  const handleViewContainers = async (host: DockerHost) => {
    setSelectedHost(host);
    setShowContainers(true);
    try {
      const r = await apiGetHostContainers(host.id);
      setHostContainers(r.containers || []);
    } catch (e: unknown) {
      setHostContainers([]);
      toast?.(getErrMessage(e, '获取容器列表失败'), 'error');
    }
  };

  const handleLoadScript = async () => {
    setShowScript(true);
    if (!setupScript) {
      try {
        const r = await apiGetDockerSetupScript();
        setSetupScript(r.script);
      } catch (e: unknown) {
        toast?.(getErrMessage(e, '加载脚本失败'), 'error');
      }
    }
  };

  const healthyCount = hosts.filter(h => h.health_status === 'healthy').length;
  const totalContainers = hosts.reduce((s, h) => s + h.running_containers, 0);
  const totalDeployments = hosts.reduce((s, h) => s + (h.deployed_meetings?.length || 0), 0);

  if (loading) {
    return <div className="devops-loading">加载中...</div>;
  }

  return (
    <div className="devops-panel">
      <div className="devops-header">
        <div>
          <h1>运维面板</h1>
          <p className="devops-subtitle">管理 Docker 主机集群、部署调度、服务监控</p>
        </div>
        <div className="devops-actions">
          <button className="btn btn-secondary" onClick={handleLoadScript}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
            远程主机配置脚本
          </button>
          <button className="btn btn-secondary" onClick={handleCheckAll}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
            全部健康检查
          </button>
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            添加主机
          </button>
        </div>
      </div>

      {/* 概览卡片 */}
      <div className="devops-stats">
        <div className="stat-card">
          <div className="stat-value">{hosts.length}</div>
          <div className="stat-label">注册主机</div>
        </div>
        <div className="stat-card stat-ok">
          <div className="stat-value">{healthyCount}</div>
          <div className="stat-label">在线主机</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totalContainers}</div>
          <div className="stat-label">运行容器</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totalDeployments}</div>
          <div className="stat-label">部署服务</div>
        </div>
      </div>

      {/* 调度策略说明 */}
      <div className="scheduling-info">
        <h3>部署调度策略</h3>
        <div className="strategy-cards">
          <div className="strategy-card">
            <div className="strategy-name">最少负载</div>
            <div className="strategy-desc">自动选择运行容器数最少的健康主机</div>
          </div>
          <div className="strategy-card">
            <div className="strategy-name">标签匹配</div>
            <div className="strategy-desc">根据任务标签（gpu/high-mem等）选择匹配主机</div>
          </div>
          <div className="strategy-card">
            <div className="strategy-name">本地优先</div>
            <div className="strategy-desc">优先本地部署，本地满载后自动分发到远程</div>
          </div>
          <div className="strategy-card">
            <div className="strategy-name">手动指定</div>
            <div className="strategy-desc">创建会议时指定目标主机，不自动调度</div>
          </div>
        </div>
      </div>

      {/* 主机列表 */}
      <div className="hosts-section">
        <h3>Docker 主机列表</h3>
        {hosts.length === 0 ? (
          <div className="empty-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <p>暂无注册的 Docker 主机</p>
            <p className="empty-hint">添加远程 Linux 服务器，将生成的服务分布式部署到多台机器</p>
            <button className="btn btn-primary" onClick={() => setShowAdd(true)}>添加第一台主机</button>
          </div>
        ) : (
          <div className="hosts-grid">
            {hosts.map(h => (
              <div key={h.id} className={`host-card ${!h.enabled ? 'disabled' : ''}`}>
                <div className="host-card-header">
                  <div className="host-name-row">
                    <span className="host-name">{h.name}</span>
                    {h.is_default && <span className="badge badge-default">默认</span>}
                    <HealthBadge status={h.health_status} />
                  </div>
                  <div className="host-conn">
                    <ConnTypeBadge type={h.connection_type} />
                    {h.region && <span className="host-region">{h.region}</span>}
                  </div>
                </div>
                {h.description && <p className="host-desc">{h.description}</p>}
                <div className="host-meta">
                  {h.docker_host && (
                    <div className="meta-item">
                      <span className="meta-label">地址</span>
                      <span className="meta-value mono">{h.docker_host}</span>
                    </div>
                  )}
                  {h.docker_version && (
                    <div className="meta-item">
                      <span className="meta-label">Docker</span>
                      <span className="meta-value">{h.docker_version}</span>
                    </div>
                  )}
                  {(h.cpu_cores > 0 || h.memory_gb > 0) && (
                    <div className="meta-item">
                      <span className="meta-label">资源</span>
                      <span className="meta-value">{h.cpu_cores} CPU · {h.memory_gb}GB RAM</span>
                    </div>
                  )}
                  <div className="meta-item">
                    <span className="meta-label">容器</span>
                    <span className="meta-value">{h.running_containers} 运行 / {h.total_containers} 总计</span>
                  </div>
                  {h.tags.length > 0 && (
                    <div className="meta-item tags-row">
                      {h.tags.map(t => <span key={t} className="tag">{t}</span>)}
                    </div>
                  )}
                  {h.last_error && h.health_status === 'unhealthy' && (
                    <div className="meta-item error-text">{h.last_error.slice(0, 200)}</div>
                  )}
                  {h.last_health_check && (
                    <div className="meta-item">
                      <span className="meta-label">最后检查</span>
                      <span className="meta-value">{new Date(h.last_health_check).toLocaleString('zh-CN')}</span>
                    </div>
                  )}
                </div>
                <div className="host-actions">
                  <button
                    className="btn btn-sm"
                    onClick={() => handleHealthCheck(h.id)}
                    disabled={checkingId === h.id}
                  >
                    {checkingId === h.id ? '检查中...' : '健康检查'}
                  </button>
                  <button className="btn btn-sm" onClick={() => handleViewContainers(h)}>容器</button>
                  <button className="btn btn-sm" onClick={() => handleToggleEnabled(h)}>
                    {h.enabled ? '禁用' : '启用'}
                  </button>
                  <button className="btn btn-sm btn-danger" onClick={() => handleDelete(h)}>删除</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 添加主机弹窗 */}
      {showAdd && <AddHostModal
        presets={presets}
        connectionTypes={connectionTypes}
        onClose={() => setShowAdd(false)}
        onCreated={() => { setShowAdd(false); loadHosts(); toast?.('主机添加成功', 'success'); }}
        toast={toast}
        requestConfirm={requestConfirm}
      />}

      {/* 配置脚本弹窗 */}
      {showScript && <ScriptModal
        script={setupScript}
        onClose={() => setShowScript(false)}
      />}

      {/* 容器列表弹窗 */}
      {showContainers && selectedHost && (
        <div className="modal-overlay" onClick={() => setShowContainers(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedHost.name} - 容器列表</h2>
              <button className="modal-close" onClick={() => setShowContainers(false)}>×</button>
            </div>
            <div className="modal-body">
              {hostContainers.length === 0 ? (
                <p className="empty-hint">暂无容器或无法连接</p>
              ) : (
                <table className="containers-table">
                  <thead>
                    <tr><th>ID</th><th>名称</th><th>镜像</th><th>状态</th><th>端口</th></tr>
                  </thead>
                  <tbody>
                    {hostContainers.map((c) => (
                      <tr key={c.id}>
                        <td className="mono">{c.id}</td>
                        <td>{c.name}</td>
                        <td className="mono-small">{c.image}</td>
                        <td>{c.status}</td>
                        <td className="mono-small">{c.ports}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── 添加主机弹窗 ─── */
function AddHostModal({ presets, connectionTypes, onClose, onCreated, toast }: {
  presets: DockerPreset[];
  connectionTypes: string[];
  onClose: () => void;
  onCreated: () => void;
  toast?: (msg: string, kind?: ToastKind, duration?: number) => void;
  requestConfirm?: (opts: ConfirmOptions) => Promise<boolean>;
}) {
  const [selectedPreset, setSelectedPreset] = useState<string>('ssh_key_root');
  const [form, setForm] = useState<DockerHostInput>({
    name: '',
    description: '',
    connection_type: 'ssh_key',
    docker_host: '',
    ssh_user: 'root',
    ssh_port: 22,
    ssh_key_content: '',
    ssh_password: '',
    tls_verify: true,
    tags: [],
    region: 'remote',
    cpu_cores: 0,
    memory_gb: 0,
    max_containers: 20,
    enabled: true,
    is_default: false,
  });
  const [tagInput, setTagInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const applyPreset = (key: string) => {
    setSelectedPreset(key);
    const preset = presets.find((p) => p.key === key);
    if (!preset) return;
    const cfg = preset.config;
    setForm(prev => ({
      ...prev,
      connection_type: cfg.connection_type || 'local',
      docker_host: cfg.docker_host || '',
      ssh_user: cfg.ssh_user || '',
      ssh_port: cfg.ssh_port || 22,
      region: cfg.region || 'remote',
      tags: cfg.tags || [],
      tls_verify: cfg.tls_verify !== false,
    }));
    setTagInput('');
  };

  useEffect(() => {
    if (presets.length > 0) applyPreset('ssh_key_root');
  }, [presets]);

  const update = (k: keyof DockerHostInput, v: string | number | boolean | string[]) => setForm(prev => ({ ...prev, [k]: v }) as DockerHostInput);

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !form.tags?.includes(t)) {
      update('tags', [...(form.tags || []), t]);
      setTagInput('');
    }
  };

  const removeTag = (t: string) => {
    update('tags', (form.tags || []).filter(x => x !== t));
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) { toast?.('请输入主机名', 'error'); return; }
    if (form.connection_type !== 'local' && !form.docker_host) { toast?.('请输入 Docker Host 地址', 'error'); return; }
    setSubmitting(true);
    try {
      await apiCreateDockerHost(form);
      onCreated();
    } catch (e: unknown) {
        toast?.(getErrMessage(e, '添加失败'), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const showField = (key: string) => {
    const map: Record<string, string[]> = {
      docker_host: ['tcp', 'tcp_tls', 'ssh_key', 'ssh_password'],
      ssh_user: ['ssh_key', 'ssh_password'],
      ssh_port: ['ssh_key', 'ssh_password'],
      ssh_key_content: ['ssh_key'],
      ssh_password: ['ssh_password'],
      tls_verify: ['tcp_tls'],
    };
    const types = map[key];
    if (!types) return true;
    return types.includes(form.connection_type);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>添加 Docker 主机</h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {/* 预设选择 */}
          <div className="form-section">
            <label className="form-label">选择配置模板</label>
            <div className="presets-grid">
              {presets.map((p) => (
                <button
                  key={p.key}
                  className={`preset-card ${selectedPreset === p.key ? 'selected' : ''}`}
                  onClick={() => applyPreset(p.key)}
                >
                  <div className="preset-label">{p.config?.label || p.key}</div>
                  <div className="preset-desc">{p.config?.description || ''}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">主机名 *</label>
              <input className="form-input" value={form.name} onChange={e => update('name', e.target.value)} placeholder="如: prod-server-01" />
            </div>
            <div className="form-group">
              <label className="form-label">区域</label>
              <input className="form-input" value={form.region} onChange={e => update('region', e.target.value)} placeholder="local/remote/cloud" />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">描述</label>
            <input className="form-input" value={form.description || ''} onChange={e => update('description', e.target.value)} placeholder="这台主机的用途描述" />
          </div>

          {showField('docker_host') && (
            <div className="form-group">
              <label className="form-label">Docker Host 地址 *</label>
              <input className="form-input mono" value={form.docker_host || ''} onChange={e => update('docker_host', e.target.value)} placeholder="ssh://root@192.168.1.100:22" />
            </div>
          )}

          {showField('ssh_user') && (
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">SSH 用户</label>
                <input className="form-input" value={form.ssh_user || ''} onChange={e => update('ssh_user', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">SSH 端口</label>
                <input className="form-input" type="number" value={form.ssh_port || 22} onChange={e => update('ssh_port', parseInt(e.target.value) || 22)} />
              </div>
            </div>
          )}

          {showField('ssh_key_content') && (
            <div className="form-group">
              <label className="form-label">SSH 私钥内容</label>
              <textarea
                className="form-textarea mono-small"
                rows={5}
                value={form.ssh_key_content || ''}
                onChange={e => update('ssh_key_content', e.target.value)}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...&#10;-----END OPENSSH PRIVATE KEY-----"
              />
              <div className="form-hint">粘贴私钥内容（~/.ssh/id_rsa 或 ed25519 文件内容）。确保公钥已添加到远程主机的 ~/.ssh/authorized_keys</div>
            </div>
          )}

          {showField('ssh_password') && (
            <div className="form-group">
              <label className="form-label">SSH 密码</label>
              <input className="form-input" type="password" value={form.ssh_password || ''} onChange={e => update('ssh_password', e.target.value)} />
            </div>
          )}

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">CPU 核心数</label>
              <input className="form-input" type="number" value={form.cpu_cores || 0} onChange={e => update('cpu_cores', parseInt(e.target.value) || 0)} placeholder="0=自动检测" />
            </div>
            <div className="form-group">
              <label className="form-label">内存 GB</label>
              <input className="form-input" type="number" value={form.memory_gb || 0} onChange={e => update('memory_gb', parseInt(e.target.value) || 0)} placeholder="0=自动检测" />
            </div>
            <div className="form-group">
              <label className="form-label">最大容器数</label>
              <input className="form-input" type="number" value={form.max_containers || 20} onChange={e => update('max_containers', parseInt(e.target.value) || 20)} />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">标签（用于调度匹配）</label>
            <div className="tags-input">
              {(form.tags || []).map(t => (
                <span key={t} className="tag tag-removable" onClick={() => removeTag(t)}>{t} ×</span>
              ))}
              <input
                className="tag-input-field"
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
                placeholder="输入标签后回车添加（如 gpu/high-mem/china-net）"
              />
            </div>
          </div>

          <div className="form-checks">
            <label className="check-item">
              <input type="checkbox" checked={form.enabled !== false} onChange={e => update('enabled', e.target.checked)} />
              <span>启用此主机</span>
            </label>
            <label className="check-item">
              <input type="checkbox" checked={form.is_default === true} onChange={e => update('is_default', e.target.checked)} />
              <span>设为默认部署目标</span>
            </label>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>取消</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? '添加中...' : '添加主机'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── 配置脚本弹窗 ─── */
function ScriptModal({ script, onClose }: { script: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(script).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>远程主机一键配置脚本</h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="script-instructions">
            <p>在目标 Linux 服务器上以 root 身份运行以下命令，一键完成 Docker 安装和远程访问配置：</p>
            <div className="quick-install">
              <code>curl -fsSL https://get.docker.com | bash && systemctl enable --now docker && usermod -aG docker $USER</code>
            </div>
            <p className="form-hint">或者复制下方完整脚本（含 TCP 配置、用户创建、镜像预拉取）：</p>
          </div>
          <div className="script-actions">
            <button className="btn btn-primary btn-sm" onClick={handleCopy}>
              {copied ? '已复制!' : '复制脚本'}
            </button>
          </div>
          <pre className="script-code">{script || '加载中...'}</pre>
          <div className="script-steps">
            <h4>配置步骤：</h4>
            <ol>
              <li>SSH 登录到目标 Linux 服务器（Ubuntu/Debian/CentOS 均可）</li>
              <li>粘贴脚本内容到终端，回车执行</li>
              <li>脚本会自动安装 Docker、配置服务、创建 conclave 用户</li>
              <li>执行完成后，回到此面板点击"添加主机"，选择"SSH 密钥"模板</li>
              <li>填入服务器 IP 和 SSH 私钥内容，点击健康检查验证连接</li>
            </ol>
            <h4>7 种连接方式对应的 SSH 配置：</h4>
            <table className="config-table">
              <thead>
                <tr><th>方式</th><th>DOCKER_HOST</th><th>需要的额外配置</th><th>适用场景</th></tr>
              </thead>
              <tbody>
                <tr><td>本地 Socket</td><td>（空，使用默认）</td><td>无</td><td>本机 Docker Desktop</td></tr>
                <tr><td>本地 TCP</td><td>tcp://127.0.0.1:2375</td><td>开启 Docker TCP 监听</td><td>本地开发调试</td></tr>
                <tr><td>远程 TCP+TLS</td><td>tcp://server:2376</td><td>CA/Cert/Key 证书</td><td>公网生产环境</td></tr>
                <tr><td>SSH Root 密钥</td><td>ssh://root@server:22</td><td>SSH 私钥</td><td>推荐远程方案</td></tr>
                <tr><td>SSH Ubuntu</td><td>ssh://ubuntu@server:22</td><td>SSH 私钥 + docker 组</td><td>AWS/GCP 云服务器</td></tr>
                <tr><td>SSH 密码</td><td>ssh://user@server:22</td><td>SSH 密码</td><td>内网测试</td></tr>
                <tr><td>Docker Context</td><td>（使用 context 名）</td><td>本地已配置 context</td><td>多主机切换</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
