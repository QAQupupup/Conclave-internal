import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../state/AppContext';

type SortKey = 'date' | 'status' | 'title';

const PAGE_SIZE = 9;
const SORT_ORDER: SortKey[] = ['date', 'status', 'title'];
const SORT_LABELS: Record<SortKey, string> = {
  date: '最近创建',
  status: '按状态',
  title: '按标题',
};

export default function Board() {
  const { meetings, refreshBoard, openMeeting, statusText } = useApp();
  const navigate = useNavigate();

  const [filter, setFilter] = useState('');
  const [sort, setSort] = useState<SortKey>('date');
  const [page, setPage] = useState(1);

  useEffect(() => {
    refreshBoard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const list = (meetings && meetings.length ? meetings : []).slice();
    const f = filter.trim();
    let items = list;
    if (f) {
      items = list.filter((m: any) =>
        (m.title && String(m.title).includes(f)) ||
        (m.topic && String(m.topic).includes(f)),
      );
    }
    const sorted = items.slice();
    if (sort === 'date') sorted.sort((a: any, b: any) => String(b.date).localeCompare(String(a.date)));
    if (sort === 'status') sorted.sort((a: any, b: any) => String(a.status).localeCompare(String(b.status)));
    if (sort === 'title') sorted.sort((a: any, b: any) => String(a.title).localeCompare(String(b.title)));
    return sorted;
  }, [meetings, filter, sort]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const pageItems = filtered.slice(start, start + PAGE_SIZE);

  function cycleSort() {
    const idx = SORT_ORDER.indexOf(sort);
    setSort(SORT_ORDER[(idx + 1) % SORT_ORDER.length]);
  }

  function onFilter(value: string) {
    setFilter(value);
    setPage(1);
  }

  return (
    <div className="view active" id="view-board">
      <div className="board-header">
        <div className="page-title">会议看板</div>
        <div className="board-controls">
          <div className="board-search">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6.5" /><line x1="15.5" y1="15.5" x2="21" y2="21" /></svg>
            <input
              type="text"
              placeholder="搜索会议…"
              value={filter}
              onChange={(e) => onFilter(e.target.value)}
            />
          </div>
          <div className="sort-btn" onClick={cycleSort}>
            <span>{SORT_LABELS[sort]}</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
          </div>
          <button className="new-btn" onClick={() => navigate('/')}>新建会议</button>
        </div>
      </div>
      <div id="board-list">
        {pageItems.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 14 }}>
            未找到匹配的会议
          </div>
        ) : (
          pageItems.map((m: any) => (
            <div className="list-item" key={m.id} onClick={() => { openMeeting(m.id); navigate(`/meeting/${m.id}`); }}>
              <span className="list-item-title">{m.title}</span>
              <span
                className="list-item-topic"
                style={{ fontSize: 12, color: 'var(--text-3)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {m.topic}
              </span>
              <span className="list-item-status">
                <span className={`status-dot ${m.status}`} />
                {statusText(m.status)}
              </span>
              <span className="list-item-progress">{m.progress || ''}</span>
              <span className="list-item-date">{m.date}</span>
            </div>
          ))
        )}
      </div>
      <div className="pagination" id="board-pagination">
        {totalPages <= 1 ? (
          <>
            <div />
            <div className="page-size">共 {filtered.length} 条</div>
          </>
        ) : (
          <>
            <div className="page-nums">
              <span
                className="page-arrow"
                onClick={() => { if (currentPage > 1) setPage(currentPage - 1); }}
              >
                ‹
              </span>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
                <span
                  key={n}
                  className={`page-num${n === currentPage ? ' active' : ''}`}
                  onClick={() => setPage(n)}
                >
                  {n}
                </span>
              ))}
              <span
                className="page-arrow"
                onClick={() => { if (currentPage < totalPages) setPage(currentPage + 1); }}
              >
                ›
              </span>
            </div>
            <div className="page-size">{PAGE_SIZE}条/页 · 共{filtered.length}条</div>
          </>
        )}
      </div>
    </div>
  );
}
