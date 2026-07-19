/* 404 页面 */
import { useNavigate, useLocation } from 'react-router-dom';

export default function NotFound() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '60vh',
      gap: 16,
      padding: 32,
    }}>
      <div style={{ fontSize: 72, fontWeight: 700, color: 'var(--text-3)', lineHeight: 1 }}>404</div>
      <div style={{ fontSize: 16, color: 'var(--text-2)' }}>页面未找到</div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', fontFamily: 'var(--mono)', maxWidth: 480, textAlign: 'center', wordBreak: 'break-all' }}>
        {location.pathname}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button className="ctrl-btn primary" onClick={() => navigate('/')}>返回首页</button>
        <button className="ctrl-btn" onClick={() => navigate(-1)}>返回上一页</button>
      </div>
    </div>
  );
}
