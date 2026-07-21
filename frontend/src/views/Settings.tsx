import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import {
  apiGetKeys,
  apiSaveKey,
  apiDeleteKey,
  apiGetPreferences,
  apiSetPreference,
  apiDeletePreference,
  apiGetTenant,
  apiTenantMembers,
  apiListTenants,
  apiSwitchTenant,
  apiCreateTenant,
  apiUpdateProfile,
  apiChangePassword,
  apiQueryBalanceForKey,
  type LlmKey,
  type TenantInfo,
  type TenantMember,
} from '../lib/api';
import { useToast } from '../components/Toast';

// Key 配置支持的 LLM Provider 列表
const KEY_PROVIDERS: { value: string; label: string; defaultBase?: string }[] = [
  { value: 'siliconflow', label: '硅基流动', defaultBase: 'https://api.siliconflow.cn/v1' },
  { value: 'deepseek', label: 'DeepSeek', defaultBase: 'https://api.deepseek.com/v1' },
  { value: 'openai', label: 'OpenAI', defaultBase: 'https://api.openai.com/v1' },
  { value: 'qwen', label: '通义千问', defaultBase: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'zhipu', label: '智谱 AI', defaultBase: 'https://open.bigmodel.cn/api/paas/v4' },
  { value: 'custom', label: '自定义 (OpenAI兼容)' },
];

type TabKey = 'general' | 'account' | 'keys' | 'prefs' | 'team';

export default function Settings() {
  const { theme, toggleTheme, logOpen, toggleLog, appendLog, user, setUser } = useApp();
  const toast = useToast();

  const [activeTab, setActiveTab] = useState<TabKey>('general');
  const [searchParams] = useSearchParams();

  // ── Key 列表 ──
  const [keys, setKeys] = useState<LlmKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysError, setKeysError] = useState<string | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [checkingBalance, setCheckingBalance] = useState<string | null>(null);

  // ── 偏好 ──
  const [prefs, setPrefs] = useState<Record<string, any>>({});
  const [prefsLoading, setPrefsLoading] = useState(true);
  const [prefsError, setPrefsError] = useState<string | null>(null);
  const [editingPref, setEditingPref] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  // ── 添加 Key 表单 ──
  const [showForm, setShowForm] = useState(false);
  const [formProvider, setFormProvider] = useState(KEY_PROVIDERS[0].value);
  const [formName, setFormName] = useState('');
  const [formKey, setFormKey] = useState('');
  const [formBaseUrl, setFormBaseUrl] = useState('');
  const [formIsDefault, setFormIsDefault] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // ── 团队信息 ──
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [currentTenant, setCurrentTenant] = useState<TenantInfo | null>(null);
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [teamLoading, setTeamLoading] = useState(false);
  const [switchingTenant, setSwitchingTenant] = useState<number | null>(null);
  const [showCreateTeam, setShowCreateTeam] = useState(false);
  const [newTeamName, setNewTeamName] = useState('');
  const [creatingTeam, setCreatingTeam] = useState(false);

  // ── 修改显示名 ──
  const [editingDisplayName, setEditingDisplayName] = useState(false);
  const [displayNameInput, setDisplayNameInput] = useState('');
  const [savingDisplayName, setSavingDisplayName] = useState(false);

  // ── 修改密码 ──
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // 从模型中心跳转时自动展开 Key 表单
  useEffect(() => {
    const p = searchParams.get('provider');
    if (p) {
      setShowForm(true);
      setActiveTab('keys');
      const prov = KEY_PROVIDERS.find((x) => x.value === p);
      if (prov) setFormProvider(p);
    }
  }, [searchParams]);

  // 加载数据
  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Keys
      try {
        const data = await apiGetKeys(true);
        const list = Array.isArray(data) ? data : (data?.keys ?? []);
        if (!cancelled) setKeys(list as LlmKey[]);
      } catch (e: any) {
        if (!cancelled) setKeysError('加载失败: ' + (e?.message || '未知错误'));
      } finally {
        if (!cancelled) setKeysLoading(false);
      }
      // Preferences
      try {
        const data: any = await apiGetPreferences(true);
        if (!cancelled) setPrefs((data && typeof data === 'object') ? data : {});
      } catch (e: any) {
        if (!cancelled) setPrefsError('加载失败: ' + (e?.message || '未知错误'));
      } finally {
        if (!cancelled) setPrefsLoading(false);
      }
      // Tenants / Team
      try {
        const t = await apiListTenants();
        if (!cancelled) setTenants(t);
        if (user?.tenant_id) {
          try {
            const ct = await apiGetTenant(user.tenant_id as number);
            if (!cancelled) setCurrentTenant(ct);
            if (user.role === 'owner' || user.role === 'admin') {
              const m = await apiTenantMembers(user.tenant_id as number);
              if (!cancelled) setMembers(m.members || []);
            }
          } catch { /* silent */ }
        }
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
     
  }, [user?.tenant_id, user?.role]);

  // 初始化显示名输入框
  useEffect(() => {
    if (user?.display_name) setDisplayNameInput(user.display_name);
  }, [user?.display_name]);

  async function reloadKeys() {
    try {
      const data = await apiGetKeys(true);
      const list = Array.isArray(data) ? data : (data?.keys ?? []);
      setKeys(list as LlmKey[]);
      setKeysError(null);
    } catch (e: any) {
      setKeysError('加载失败: ' + (e?.message || '未知错误'));
    }
  }

  function toggleForm() {
    setShowForm((v) => !v);
    setFormError(null);
    if (!showForm) {
      const prov = KEY_PROVIDERS.find((p) => p.value === formProvider);
      setFormBaseUrl(prov?.defaultBase || '');
    }
  }

  function onProviderChange(val: string) {
    setFormProvider(val);
    const prov = KEY_PROVIDERS.find((p) => p.value === val);
    if (prov?.defaultBase) setFormBaseUrl(prov.defaultBase);
  }

  async function handleSaveKey() {
    const name = formName.trim();
    const key = formKey.trim();
    if (!name || !key) {
      setFormError('请填写名称和 API Key');
      appendLog('请填写名称和 API Key', 'warning');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await apiSaveKey(formProvider, name, key, formBaseUrl.trim(), formIsDefault);
      appendLog('API Key 已保存', 'info');
      toast.show('API Key 已保存', 'success');
      setFormName('');
      setFormKey('');
      setFormBaseUrl('');
      setShowForm(false);
      await reloadKeys();
    } catch (e: any) {
      const msg = '保存失败: ' + (e?.message || '未知错误');
      setFormError(msg);
      appendLog(msg, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteKey(k: LlmKey) {
    if (!confirm(`确定删除 Key "${k.name}" (${k.provider})？`)) return;
    setDeletingKey(`${k.provider}/${k.name}`);
    try {
      await apiDeleteKey(k.provider, k.name);
      appendLog(`已删除 Key: ${k.provider}/${k.name}`, 'info');
      toast.show('Key 已删除', 'success');
      await reloadKeys();
    } catch (e: any) {
      toast.show('删除失败: ' + (e?.message || '未知错误'), 'error');
    } finally {
      setDeletingKey(null);
    }
  }

  async function handleCheckBalance(k: LlmKey) {
    setCheckingBalance(`${k.provider}/${k.name}`);
    try {
      const result = await apiQueryBalanceForKey(k.provider, '', k.base_url);
      // 余额查询需要实际 key，这里仅提示功能入口
      toast.show('余额检测：请在会议创建时验证 Key 有效性', 'info');
    } catch (e: any) {
      toast.show('检测失败: ' + (e?.message || '未知错误'), 'error');
    } finally {
      setCheckingBalance(null);
    }
  }

  async function handleSwitchTenant(tenantId: number) {
    if (tenantId === user?.tenant_id) return;
    setSwitchingTenant(tenantId);
    try {
      const data = await apiSwitchTenant(tenantId);
      setUser(data.user);
      toast.show(`已切换到团队: ${data.user.tenant?.name || ''}`, 'success');
      await reloadKeys();
      const pdata: any = await apiGetPreferences(true);
      setPrefs((pdata && typeof pdata === 'object') ? pdata : {});
    } catch (e: any) {
      toast.show('切换失败: ' + (e?.message || '未知错误'), 'error');
    } finally {
      setSwitchingTenant(null);
    }
  }

  async function handleCreateTeam() {
    const name = newTeamName.trim();
    if (!name) { toast.show('请输入团队名称', 'warning'); return; }
    setCreatingTeam(true);
    try {
      const t = await apiCreateTenant(name);
      toast.show(`团队 "${t.name}" 创建成功，正在切换...`, 'success');
      setShowCreateTeam(false);
      setNewTeamName('');
      await handleSwitchTenant(t.id);
      const updated = await apiListTenants();
      setTenants(updated);
    } catch (e: any) {
      toast.show('创建失败: ' + (e?.message || '未知错误'), 'error');
    } finally {
      setCreatingTeam(false);
    }
  }

  async function handleSaveDisplayName() {
    const name = displayNameInput.trim();
    if (!name) { toast.show('显示名不能为空', 'warning'); return; }
    if (name === user?.display_name) { setEditingDisplayName(false); return; }
    setSavingDisplayName(true);
    try {
      const result = await apiUpdateProfile(name);
      setUser({ ...user!, display_name: result.display_name });
      toast.show('显示名已更新', 'success');
      setEditingDisplayName(false);
      appendLog(`显示名已更新为: ${result.display_name}`, 'info');
    } catch (e: any) {
      toast.show('更新失败: ' + (e?.message || '未知错误'), 'error');
    } finally {
      setSavingDisplayName(false);
    }
  }

  async function handleChangePassword() {
    setPasswordError(null);
    if (!oldPassword || !newPassword || !confirmPassword) {
      setPasswordError('请填写所有密码字段'); return;
    }
    if (newPassword.length < 6) {
      setPasswordError('新密码至少 6 位'); return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('两次输入的新密码不一致'); return;
    }
    setChangingPassword(true);
    try {
      await apiChangePassword(oldPassword, newPassword);
      toast.show('密码已修改，请重新登录', 'success');
      setShowPasswordForm(false);
      setOldPassword(''); setNewPassword(''); setConfirmPassword('');
      appendLog('密码已修改成功', 'info');
    } catch (e: any) {
      setPasswordError('修改失败: ' + (e?.message || '旧密码错误'));
    } finally {
      setChangingPassword(false);
    }
  }

  // ── 偏好操作 ──
  async function handlePrefChange(k: string, v: any) {
    const prev = prefs[k];
    setPrefs((p) => ({ ...p, [k]: v }));
    try {
      await apiSetPreference(k, v);
      toast.show(`偏好已更新: ${k}`, 'success');
    } catch (e: any) {
      setPrefs((p) => ({ ...p, [k]: prev }));
      toast.show('偏好保存失败: ' + (e?.message || '未知错误'), 'error');
    }
  }
  function startEditPref(k: string, currentVal: any) {
    setEditingPref(k);
    setEditValue(typeof currentVal === 'object' ? JSON.stringify(currentVal) : String(currentVal ?? ''));
  }
  function cancelEditPref() { setEditingPref(null); setEditValue(''); }
  async function saveEditPref(k: string) {
    let parsed: any = editValue;
    const trimmed = editValue.trim();
    if (trimmed === 'true') parsed = true;
    else if (trimmed === 'false') parsed = false;
    else if (trimmed === 'null') parsed = null;
    else if (!isNaN(Number(trimmed)) && trimmed !== '') parsed = Number(trimmed);
    else { try { parsed = JSON.parse(trimmed); } catch { /* keep string */ } }
    setEditingPref(null); setEditValue('');
    await handlePrefChange(k, parsed);
  }
  async function deletePref(k: string) {
    const prev = prefs[k];
    setPrefs((p) => { const n = { ...p }; delete n[k]; return n; });
    try { await apiDeletePreference(k); toast.show(`已删除偏好: ${k}`, 'success'); }
    catch (e: any) { setPrefs((p) => ({ ...p, [k]: prev })); toast.show('删除失败: ' + (e?.message || '未知错误'), 'error'); }
  }
  function isBoolPref(v: any): boolean { return typeof v === 'boolean'; }
  const prefEntries = Object.entries(prefs);

  // ── 角色标签 ──
  function roleLabel(role: string) {
    const map: Record<string, string> = { owner: '所有者', admin: '管理员', member: '成员', guest: '访客' };
    return map[role] || role;
  }

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'general', label: '通用' },
    { key: 'account', label: '账户' },
    { key: 'keys', label: 'API Keys' },
    { key: 'prefs', label: '会议偏好' },
    { key: 'team', label: '团队' },
  ];

  return (
    <div className="view active" id="view-settings">
      <div className="page-title" style={{ marginBottom: 24 }}>设置</div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--line)', marginBottom: 24 }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            style={{
              padding: '8px 16px',
              fontSize: 13,
              background: 'none',
              border: 'none',
              borderBottom: activeTab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              color: activeTab === t.key ? 'var(--text)' : 'var(--text-3)',
              cursor: 'pointer',
              fontWeight: activeTab === t.key ? 600 : 400,
              marginBottom: -1,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ maxWidth: 560 }}>
        {/* ═══ 通用 ═══ */}
        {activeTab === 'general' && (
          <>
            <Section title="界面" desc="调整界面外观和行为">
              <Row
                label="深色模式"
                hint="切换界面明暗主题"
                action={<button className="ctrl-btn" onClick={toggleTheme}>{theme === 'dark' ? '切换到浅色' : '切换到深色'}</button>}
              />
              <Row
                label="日志面板"
                hint="显示实时执行日志"
                action={<button className="ctrl-btn" onClick={toggleLog}>{logOpen ? '关闭' : '打开'}</button>}
              />
            </Section>
          </>
        )}

        {/* ═══ 账户 ═══ */}
        {activeTab === 'account' && (
          <>
            <Section title="账户信息" desc="您的登录账户详情">
              <div style={{ padding: '12px 0', fontSize: 13 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                  <span style={{ color: 'var(--text-3)' }}>用户名</span>
                  <span style={{ fontFamily: 'monospace' }}>{user?.username || '-'}</span>
                </div>

                {/* 显示名（可编辑） */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                  <span style={{ color: 'var(--text-3)' }}>显示名</span>
                  {editingDisplayName ? (
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <input
                        type="text"
                        value={displayNameInput}
                        onChange={(e) => setDisplayNameInput(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleSaveDisplayName(); if (e.key === 'Escape') { setEditingDisplayName(false); setDisplayNameInput(user?.display_name || ''); } }}
                        style={{ padding: '4px 8px', fontSize: 13, width: 160 }}
                        autoFocus
                      />
                      <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12 }} onClick={handleSaveDisplayName} disabled={savingDisplayName}>
                        {savingDisplayName ? '…' : '✓'}
                      </button>
                      <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12 }} onClick={() => { setEditingDisplayName(false); setDisplayNameInput(user?.display_name || ''); }}>✕</button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span>{user?.display_name || user?.username || '-'}</span>
                      <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 11, opacity: 0.7 }} onClick={() => setEditingDisplayName(true)}>编辑</button>
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                  <span style={{ color: 'var(--text-3)' }}>角色</span>
                  <span>{user?.role ? roleLabel(user.role as string) : '-'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
                  <span style={{ color: 'var(--text-3)' }}>当前团队</span>
                  <span>{user?.tenant?.name || '-'}</span>
                </div>
              </div>
            </Section>

            {/* 修改密码 */}
            <Section title="安全" desc="修改登录密码">
              {!showPasswordForm ? (
                <button className="ctrl-btn" onClick={() => setShowPasswordForm(true)}>修改密码</button>
              ) : (
                <div style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <input
                    type="password"
                    placeholder="当前密码"
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                  />
                  <input
                    type="password"
                    placeholder="新密码（至少 6 位）"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                  <input
                    type="password"
                    placeholder="确认新密码"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleChangePassword(); }}
                  />
                  {passwordError && (<div style={{ fontSize: 12, color: 'var(--dot-error, #e74c3c)' }}>{passwordError}</div>)}
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                    <button className="ctrl-btn" onClick={() => { setShowPasswordForm(false); setOldPassword(''); setNewPassword(''); setConfirmPassword(''); setPasswordError(null); }} disabled={changingPassword}>取消</button>
                    <button className="ctrl-btn primary" onClick={handleChangePassword} disabled={changingPassword}>
                      {changingPassword ? '提交中…' : '确认修改'}
                    </button>
                  </div>
                </div>
              )}
            </Section>
          </>
        )}

        {/* ═══ API Keys ═══ */}
        {activeTab === 'keys' && (
          <Section title="LLM API Key 配置" desc="管理各模型服务商的 API Key，Key 加密存储仅当前团队可见">
            <div id="llm-key-list" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {showForm && (
                <div className="llm-key-form" style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <select value={formProvider} onChange={(e) => onProviderChange(e.target.value)} style={{ flex: 1 }}>
                      {KEY_PROVIDERS.map((p) => (<option key={p.value} value={p.value}>{p.label}</option>))}
                    </select>
                    <input
                      type="text"
                      placeholder="名称（如：生产 Key）"
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      style={{ flex: 1 }}
                    />
                  </div>
                  <input
                    type="text"
                    placeholder="Base URL（可选，自定义兼容接口时填写）"
                    value={formBaseUrl}
                    onChange={(e) => setFormBaseUrl(e.target.value)}
                  />
                  <input
                    type="password"
                    placeholder="API Key"
                    value={formKey}
                    onChange={(e) => setFormKey(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSaveKey(); }}
                  />
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={formIsDefault} onChange={(e) => setFormIsDefault(e.target.checked)} />
                    设为该服务商默认 Key
                  </label>
                  {formError && (<div style={{ fontSize: 12, color: 'var(--dot-error, #e74c3c)' }}>{formError}</div>)}
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                    <button className="ctrl-btn" onClick={toggleForm} disabled={saving}>取消</button>
                    <button className="ctrl-btn primary" onClick={handleSaveKey} disabled={saving}>
                      {saving ? '保存中…' : '保存'}
                    </button>
                  </div>
                </div>
              )}

              {keysLoading ? (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '12px 0' }}>加载中…</div>
              ) : keysError ? (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '12px 0' }}>{keysError}</div>
              ) : keys.length === 0 ? (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '12px 0' }}>暂无 API Key，请添加</div>
              ) : (
                keys.map((k, i) => (
                  <div
                    className="llm-key-item"
                    key={k.id || (k.provider + k.name + i)}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13,
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="llm-key-provider" style={{ fontWeight: 600, fontSize: 12, padding: '1px 6px', background: 'var(--bg-raise, var(--bg))', borderRadius: 4 }}>{k.provider}</span>
                        <span className="llm-key-name" style={{ color: 'var(--text)' }}>{k.name}</span>
                        {k.is_default && (<span style={{ fontSize: 11, color: 'var(--accent, #335c8e)', padding: '1px 6px', border: '1px solid var(--accent, #335c8e)', borderRadius: 4 }}>默认</span>)}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'monospace' }}>{k.key_masked}</div>
                      {k.base_url && (<div style={{ fontSize: 11, color: 'var(--text-3)' }}>Base: {k.base_url}</div>)}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <button
                        className="ctrl-btn"
                        style={{ padding: '2px 8px', fontSize: 11, opacity: 0.7 }}
                        onClick={() => handleCheckBalance(k)}
                        disabled={checkingBalance === `${k.provider}/${k.name}`}
                        title="检测 Key 有效性"
                      >
                        {checkingBalance === `${k.provider}/${k.name}` ? '…' : '检测'}
                      </button>
                      <button
                        className="ctrl-btn"
                        style={{ padding: '2px 8px', fontSize: 11, opacity: 0.7 }}
                        onClick={() => handleDeleteKey(k)}
                        disabled={deletingKey === `${k.provider}/${k.name}`}
                        title="删除 Key"
                      >
                        {deletingKey === `${k.provider}/${k.name}` ? '删除中…' : '删除'}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
            {!showForm && (
              <button className="ctrl-btn" style={{ marginTop: 12 }} onClick={toggleForm}>添加 Key</button>
            )}
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 8, padding: '8px 12px', background: 'var(--bg-raise, var(--bg))', borderRadius: 6 }}>
              提示：API Key 使用 Fernet 对称加密存储，仅本团队成员可使用。系统 Key（tenant_id 为空）可被所有团队继承使用。
            </div>
          </Section>
        )}

        {/* ═══ 会议偏好 ═══ */}
        {activeTab === 'prefs' && (
          <Section title="会议偏好" desc="管理您的会议个性化设置">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }} id="prefs-list">
              {prefsLoading ? (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '8px 0' }}>加载中…</div>
              ) : prefsError ? (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '8px 0' }}>{prefsError}</div>
              ) : prefEntries.length === 0 ? (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '8px 0' }}>暂无偏好设置。偏好会在您使用会议功能时自动创建。</div>
              ) : (
                prefEntries.map(([k, v]) => (
                  <div className="pref-item" key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                    <span className="pref-label" style={{ minWidth: 140, fontSize: 13, color: 'var(--text-2)' }}>{k}</span>
                    {editingPref === k ? (
                      <>
                        <input type="text" value={editValue} onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') saveEditPref(k); if (e.key === 'Escape') cancelEditPref(); }}
                          style={{ flex: 1, padding: '4px 8px', fontSize: 13 }} autoFocus />
                        <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12 }} onClick={() => saveEditPref(k)}>✓</button>
                        <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12 }} onClick={cancelEditPref}>✕</button>
                      </>
                    ) : isBoolPref(v) ? (
                      <>
                        <button className={`ctrl-btn ${v ? 'primary' : ''}`} style={{ padding: '2px 10px', fontSize: 12 }} onClick={() => handlePrefChange(k, !v)}>
                          {v ? '已开启' : '已关闭'}
                        </button>
                        <span style={{ flex: 1 }} />
                        <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12, opacity: 0.6 }} onClick={() => deletePref(k)} title="删除">删除</button>
                      </>
                    ) : (
                      <>
                        <span className="pref-value" style={{ flex: 1, fontSize: 13, color: 'var(--text-3)', cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} onClick={() => startEditPref(k, v)}>
                          {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                        </span>
                        <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12 }} onClick={() => startEditPref(k, v)}>编辑</button>
                        <button className="ctrl-btn" style={{ padding: '2px 8px', fontSize: 12, opacity: 0.6 }} onClick={() => deletePref(k)} title="删除">删除</button>
                      </>
                    )}
                  </div>
                ))
              )}
            </div>
          </Section>
        )}

        {/* ═══ 团队 ═══ */}
        {activeTab === 'team' && (
          <>
            <Section title="当前团队" desc="您所在的团队信息">
              {currentTenant ? (
                <div style={{ padding: '8px 0', fontSize: 13 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                    <span style={{ color: 'var(--text-3)' }}>名称</span>
                    <span style={{ fontWeight: 600 }}>{currentTenant.name}</span>
                  </div>
                  {currentTenant.slug && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                      <span style={{ color: 'var(--text-3)' }}>标识</span>
                      <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{currentTenant.slug}</span>
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                    <span style={{ color: 'var(--text-3)' }}>方案</span>
                    <span>{currentTenant.plan || 'free'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--line-faint, var(--line))' }}>
                    <span style={{ color: 'var(--text-3)' }}>我的角色</span>
                    <span>{user?.role ? roleLabel(user.role as string) : '-'}</span>
                  </div>
                  {currentTenant.created_at && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                      <span style={{ color: 'var(--text-3)' }}>创建时间</span>
                      <span>{new Date(currentTenant.created_at).toLocaleDateString()}</span>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '12px 0' }}>未关联团队</div>
              )}
            </Section>

            {/* 创建团队 */}
            <Section title="创建团队" desc="创建一个新的独立工作空间，您将自动成为所有者">
              {!showCreateTeam ? (
                <button className="ctrl-btn" onClick={() => setShowCreateTeam(true)}>+ 创建新团队</button>
              ) : (
                <div style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <input
                    type="text"
                    placeholder="团队名称"
                    value={newTeamName}
                    onChange={(e) => setNewTeamName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleCreateTeam(); }}
                    autoFocus
                  />
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                    <button className="ctrl-btn" onClick={() => { setShowCreateTeam(false); setNewTeamName(''); }} disabled={creatingTeam}>取消</button>
                    <button className="ctrl-btn primary" onClick={handleCreateTeam} disabled={creatingTeam}>
                      {creatingTeam ? '创建中…' : '创建并切换'}
                    </button>
                  </div>
                </div>
              )}
            </Section>

            {/* 团队成员（仅 admin/owner 可见） */}
            {members.length > 0 && (
              <Section title="团队成员" desc={`共 ${members.length} 名成员`}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {members.map((m) => (
                    <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--line-faint, var(--line))', fontSize: 13 }}>
                      <div>
                        <span style={{ fontWeight: 500 }}>{m.display_name || m.username}</span>
                        {m.email && (<span style={{ color: 'var(--text-3)', marginLeft: 8, fontSize: 12 }}>{m.email}</span>)}
                      </div>
                      <span style={{
                        fontSize: 11, padding: '2px 8px', borderRadius: 4,
                        background: m.role === 'owner' ? 'rgba(51,92,142,0.12)' : 'var(--bg-raise, var(--bg))',
                        color: m.role === 'owner' ? 'var(--accent, #335c8e)' : 'var(--text-2)',
                      }}>{roleLabel(m.role)}</span>
                    </div>
                  ))}
                </div>
                {(user?.role === 'owner' || user?.role === 'admin') && (
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 8, padding: '8px 12px', background: 'var(--bg-raise, var(--bg))', borderRadius: 6 }}>
                    提示：成员邀请、角色变更、配额管理等功能正在开发中。当前版本中所有用户可通过创建团队建立独立工作空间。
                  </div>
                )}
              </Section>
            )}

            {/* 切换团队 */}
            {tenants.length > 1 && (
              <Section title="切换团队" desc="您属于多个团队，可在此切换">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {tenants.map((t) => (
                    <button
                      key={t.id}
                      className="ctrl-btn"
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '10px 12px', textAlign: 'left',
                        border: t.id === user?.tenant_id ? '1px solid var(--accent, #335c8e)' : '1px solid var(--line)',
                        background: t.id === user?.tenant_id ? 'rgba(51,92,142,0.06)' : 'transparent',
                      }}
                      onClick={() => handleSwitchTenant(t.id)}
                      disabled={switchingTenant !== null || t.id === user?.tenant_id}
                    >
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 500 }}>{t.name}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{t.slug} · {t.plan || 'free'}</div>
                      </div>
                      {t.id === user?.tenant_id ? (
                        <span style={{ fontSize: 12, color: 'var(--accent, #335c8e)' }}>当前</span>
                      ) : switchingTenant === t.id ? (
                        <span style={{ fontSize: 12, color: 'var(--text-3)' }}>切换中…</span>
                      ) : (
                        <span style={{ fontSize: 12, color: 'var(--text-3)' }}>切换</span>
                      )}
                    </button>
                  ))}
                </div>
              </Section>
            )}

            {(!user?.role || (user.role !== 'owner' && user.role !== 'admin')) && members.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 8, padding: '8px 12px', background: 'var(--bg-raise, var(--bg))', borderRadius: 6 }}>
                团队管理功能（成员邀请、角色变更、配额管理等）仅团队管理员可见。如需调整团队设置，请联系团队所有者。
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── 辅助组件 ──────────────────────────────
function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{title}</div>
        {desc && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{desc}</div>}
      </div>
      {children}
    </div>
  );
}

function Row({ label, hint, action }: { label: string; hint?: string; action: React.ReactNode }) {
  return (
    <div style={{
      padding: '12px 0', borderBottom: '1px solid var(--line-faint, var(--line))',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div>
        <div style={{ fontSize: 14, color: 'var(--text)' }}>{label}</div>
        {hint && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>}
      </div>
      {action}
    </div>
  );
}
