import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import { apiGetKeys, apiSaveKey, apiGetPreferences, apiSetPreference } from '../lib/api';
import { PROVIDERS } from '../data/mock';

interface LlmKey {
  provider?: string;
  name?: string;
}

// 复用模型中心的 provider 列表，避免两处不同步
const KEY_PROVIDERS: { value: string; label: string }[] = PROVIDERS.map((p) => ({
  value: p.id,
  label: p.name,
}));

export default function Settings() {
  const { theme, toggleTheme, logOpen, toggleLog, appendLog } = useApp();

  // Key 列表
  const [keys, setKeys] = useState<LlmKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysError, setKeysError] = useState<string | null>(null);

  // 偏好
  const [prefs, setPrefs] = useState<Record<string, any>>({});
  const [prefsLoading, setPrefsLoading] = useState(true);
  const [prefsError, setPrefsError] = useState<string | null>(null);

  // 添加 Key 表单
  const [searchParams] = useSearchParams();
  const initialProvider = searchParams.get('provider') || KEY_PROVIDERS[0].value;
  const [showForm, setShowForm] = useState(false);
  const [formProvider, setFormProvider] = useState(initialProvider);
  const [formName, setFormName] = useState('');
  const [formKey, setFormKey] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // 从模型中心跳转过来时（带 provider 参数），自动展开表单
  useEffect(() => {
    const p = searchParams.get('provider');
    if (p) setShowForm(true);
  }, [searchParams]);

  // 进入视图时加载已有 key 与偏好，失败显示错误但不抛错（静默模式不弹登录窗）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data: any = await apiGetKeys(true);
        const list = Array.isArray(data) ? data : (data?.keys ?? []);
        if (!cancelled) setKeys(list as LlmKey[]);
      } catch (e: any) {
        if (!cancelled) setKeysError('加载失败: ' + (e?.message || '未知错误'));
      } finally {
        if (!cancelled) setKeysLoading(false);
      }
      try {
        const data: any = await apiGetPreferences(true);
        if (!cancelled) setPrefs((data && typeof data === 'object') ? data : {});
      } catch (e: any) {
        if (!cancelled) setPrefsError('加载失败: ' + (e?.message || '未知错误'));
      } finally {
        if (!cancelled) setPrefsLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function reloadKeys() {
    try {
      const data: any = await apiGetKeys(true);
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
  }

  async function handleSaveKey() {
    const name = formName.trim();
    const key = formKey.trim();
    if (!name || !key) {
      setFormError('请填写名称和 Key');
      appendLog('请填写名称和 Key', 'warning');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await apiSaveKey(formProvider, name, key);
      appendLog('API Key 已保存', 'info');
      // 清空表单并收起
      setFormName('');
      setFormKey('');
      setShowForm(false);
      // 重新加载 key 列表
      await reloadKeys();
    } catch (e: any) {
      const msg = '保存失败: ' + (e?.message || '未知错误');
      setFormError(msg);
      appendLog(msg, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handlePrefChange(k: string, v: any) {
    // 乐观更新本地，再持久化；失败回滚并提示
    const prev = prefs[k];
    setPrefs((p) => ({ ...p, [k]: v }));
    try {
      await apiSetPreference(k, v);
      appendLog(`偏好已更新: ${k}`, 'info');
    } catch (e: any) {
      setPrefs((p) => ({ ...p, [k]: prev }));
      appendLog('偏好保存失败: ' + (e?.message || '未知错误'), 'error');
    }
  }

  const prefEntries = Object.entries(prefs);

  return (
    <div className="view active" id="view-settings">
      <div className="page-title" style={{ marginBottom: 32 }}>设置</div>
      <div style={{ maxWidth: 480 }}>
        {/* 深色模式 */}
        <div
          style={{
            padding: '16px 0',
            borderBottom: '1px solid var(--line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ fontSize: 14, color: 'var(--text)' }}>深色模式</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>切换界面明暗主题</div>
          </div>
          <button className="ctrl-btn" onClick={toggleTheme}>
            {theme === 'dark' ? '切换到浅色' : '切换到深色'}
          </button>
        </div>

        {/* 日志面板 */}
        <div
          style={{
            padding: '16px 0',
            borderBottom: '1px solid var(--line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ fontSize: 14, color: 'var(--text)' }}>日志面板</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>显示实时执行日志</div>
          </div>
          <button className="ctrl-btn" onClick={toggleLog}>
            {logOpen ? '关闭' : '打开'}
          </button>
        </div>

        {/* LLM API Key 配置 */}
        <div style={{ padding: '16px 0', borderBottom: '1px solid var(--line)' }}>
          <div style={{ fontSize: 14, color: 'var(--text)', marginBottom: 12 }}>LLM API Key 配置</div>
          <div id="llm-key-list" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {showForm && (
              <div className="llm-key-form">
                <select value={formProvider} onChange={(e) => setFormProvider(e.target.value)}>
                  {KEY_PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
                <input
                  type="text"
                  placeholder="名称（如：生产环境 Key）"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                />
                <input
                  type="password"
                  placeholder="API Key"
                  value={formKey}
                  onChange={(e) => setFormKey(e.target.value)}
                />
                {formError && (
                  <div style={{ fontSize: 12, color: 'var(--dot-error)' }}>{formError}</div>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="ctrl-btn" onClick={toggleForm} disabled={saving}>取消</button>
                  <button className="ctrl-btn primary" onClick={handleSaveKey} disabled={saving}>
                    {saving ? '保存中…' : '保存'}
                  </button>
                </div>
              </div>
            )}

            {keysLoading ? (
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>加载中…</div>
            ) : keysError ? (
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>{keysError}</div>
            ) : keys.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>暂无 API Key，请添加</div>
            ) : (
              keys.map((k, i) => (
                <div className="llm-key-item" key={(k.provider || 'unknown') + (k.name || '') + i}>
                  <div>
                    <span className="llm-key-provider">{k.provider || 'unknown'}</span>
                    <span className="llm-key-name">{k.name || ''}</span>
                  </div>
                  <span className="llm-key-status">已配置</span>
                </div>
              ))
            )}
          </div>
          <button className="ctrl-btn" style={{ marginTop: 12 }} onClick={toggleForm}>
            {showForm ? '取消添加' : '添加 Key'}
          </button>
        </div>

        {/* 偏好设置 */}
        <div style={{ padding: '16px 0', borderBottom: '1px solid var(--line)' }}>
          <div style={{ fontSize: 14, color: 'var(--text)', marginBottom: 12 }}>会议偏好</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }} id="prefs-list">
            {prefsLoading ? (
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>加载中…</div>
            ) : prefsError ? (
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>{prefsError}</div>
            ) : prefEntries.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>暂无偏好设置</div>
            ) : (
              prefEntries.map(([k, v]) => (
                <div className="pref-item" key={k}>
                  <span className="pref-label">{k}</span>
                  <span className="pref-value">{String(v)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
