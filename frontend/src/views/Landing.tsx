import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import { REPORT_TYPES } from '../data/reportData';

export default function Landing() {
  const navigate = useNavigate();
  const {
    meetings,
    selectedType,
    setSelectedType,
    startMeeting,
    openMeeting,
    statusText,
  } = useApp();

  const [topic, setTopic] = useState('');
  const [error, setError] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const recent = (meetings && meetings.length ? meetings : []).slice(0, 4);

  async function handleStart() {
    const value = topic.trim();
    if (!value) {
      setError(true);
      setTimeout(() => setError(false), 1000);
      return;
    }
    setSubmitting(true);
    try {
      const id = await startMeeting(value, selectedType);
      if (id) { setTopic(''); navigate(`/meeting/${id}`); }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="view active" id="view-landing">
      <div className="landing-hero">
        <div className="landing-title">Conclave</div>
        <div className="landing-sub">闭门会议式多智能体决策</div>
      </div>
      <div className="landing-input-wrap">
        <input
          className={`landing-input${error ? ' error' : ''}`}
          id="landing-topic-input"
          placeholder="输入你需要团队讨论的议题…"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleStart();
          }}
        />
        <button
          className="landing-start-btn"
          onClick={handleStart}
          disabled={submitting}
        >
          {submitting ? (
            <span style={{ opacity: 0.7 }}>创建中...</span>
          ) : (
            <>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><polyline points="9 18 15 12 9 6" /></svg>
              开始会议
            </>
          )}
        </button>
      </div>
      <div className="landing-types" id="landing-type-selector">
        {REPORT_TYPES.map((t) => (
          <span
            key={t.id}
            className={`landing-type${selectedType === t.id ? ' active' : ''}`}
            data-type={t.id}
            onClick={() => setSelectedType(t.id)}
          >
            {t.label}
          </span>
        ))}
      </div>
      <div className="landing-section">
        <div className="landing-section-title">最近</div>
        <div id="landing-recent">
          {recent.length === 0 ? (
            <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 14 }}>
              暂无最近会议
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>在上方输入议题，创建第一场会议</div>
            </div>
          ) : (
            recent.map((m) => (
              <div className="list-item" key={m.id} onClick={() => { openMeeting(m.id!); navigate(`/meeting/${m.id}`); }}>
                <span className="list-item-title">{m.title}</span>
                <span className="list-item-status">
                  <span className={`status-dot ${m.status}`} />
                  {statusText(m.status)}
                </span>
                <span className="list-item-date">{m.date}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
