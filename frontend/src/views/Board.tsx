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
     
  }, []);

  const filtered = useMemo(() => {
    const list = (meetings && meetings.length ? meetings : []).slice();
    const f = filter.trim();
    let items = list;
    if (f) {
      items = list.filter((m) =>
        (m.title && String(m.title).includes(f)) ||
        (m.topic && String(m.topic).includes(f)),
      );
    }
    const sorted = items.slice();
    if (sort === 'date') sorted.sort((a, b) => String(b.date).localeCompare(String(a.date)));
    if (sort === 'status') sorted.sort((a, b) => String(a.status).localeCompare(String(b.status)));
    if (sort === 'title') sorted.sort((a, b) => String(a.title).localeCompare(String(b.title)));
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
    <div className="view active board-view" id="view-board">
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

      {pageItems.length === 0 ? (
        <div className="board-empty">
          <div className="board-empty-title">
            {filter.trim() ? `未找到匹配「${filter.trim()}」的会议` : '暂无会议记录'}
          </div>
          <div className="board-empty-sub">
            {filter.trim() ? '尝试更换关键词或清除筛选' : '点击右上角「新建会议」开始'}
          </div>
        </div>
      ) : (
        <div className="board-table" id="board-list">
          {/* 表头行：中性灰底，列宽与数据行一致 */}
          <div className="board-row board-row-head">
            <span className="board-cell board-cell-title">议题</span>
            <span className="board-cell board-cell-status">状态</span>
            <span className="board-cell board-cell-progress">进度</span>
            <span className="board-cell board-cell-date">创建时间</span>
          </div>
          {pageItems.map((m) => (
            <div
              className="board-row"
              key={m.id}
              onClick={() => { openMeeting(m.id!); navigate(`/meeting/${m.id}`); }}
            >
              <span className="board-cell board-cell-title">
                <span className="board-cell-main">{m.title}</span>
                {m.topic && (
                  <span className="board-cell-sub">{m.topic}</span>
                )}
              </span>
              <span className="board-cell board-cell-status">
                <span className={`status-dot ${m.status}`} />
                {statusText(m.status)}
              </span>
              <span className="board-cell board-cell-progress">{m.progress || '—'}</span>
              <span className="board-cell board-cell-date">{m.date}</span>
            </div>
          ))}
        </div>
      )}

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
                className={`page-arrow${currentPage <= 1 ? ' disabled' : ''}`}
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
                className={`page-arrow${currentPage >= totalPages ? ' disabled' : ''}`}
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
