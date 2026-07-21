#!/usr/bin/env python3
"""生成 Conclave 会议完整审计报告（HTML）。

用法：
    python scripts/generate_audit_report.py <meeting_id> [--api http://localhost:8000] [--out docs/audits]

功能：
    1. 调用后端 /meetings/{meeting_id}/audit 端点聚合 trace / events / cost / state
    2. 生成单文件 HTML 报告，包含降级事件高亮、LLM 调用链、成本明细
    3. 保存到 <out>/conclave-audit-<timestamp>-<meeting_id>/report.html

报告可离线打开，不依赖后端服务。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import urllib.request


DEFAULT_API = "http://localhost:8000"
DEFAULT_OUT = "docs/audits"


def _fetch_audit(api_base: str, meeting_id: str, token: str | None = None) -> dict[str, Any]:
    url = urljoin(api_base.rstrip("/") + "/", f"meetings/{meeting_id}/audit")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"无法从 {url} 获取审计数据: {e}") from e


def _escape(text: Any) -> str:
    return html.escape(str(text) if text is not None else "")


def _format_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _render_call(call: dict[str, Any], idx: int) -> str:
    call_id = _escape(call.get("call_id", f"call-{idx}"))
    stage = _escape(call.get("stage", ""))
    model = _escape(call.get("model", ""))
    provider = _escape(call.get("provider_id", ""))
    attempt = call.get("attempt", 1)
    validation = _escape(call.get("validation_status", ""))
    consistency = _escape(call.get("consistency_status", ""))
    latency = call.get("latency_ms", 0)
    tokens = call.get("total_tokens", 0)
    prompt = call.get("prompt", "")
    raw = call.get("raw_response", "")
    parsed = call.get("parsed_result")
    error = call.get("error_detail", "")

    status_badge = "badge-ok" if validation == "valid" else "badge-warn" if validation == "invalid" else "badge-error"

    prompt_html = f"<pre>{_escape(prompt[:8000])}{'...（截断）' if len(prompt) > 8000 else ''}</pre>"
    raw_html = f"<pre>{_escape(raw[:8000])}{'...（截断）' if len(raw) > 8000 else ''}</pre>"
    parsed_html = f"<pre>{_escape(_format_json(parsed))}</pre>" if parsed else "<p class=\"muted\">无解析结果</p>"
    error_html = f"<div class=\"error-box\"><strong>错误详情：</strong>{_escape(error)}</div>" if error else ""

    return f"""
    <details class="call-card">
      <summary>
        <span class="call-title">#{idx + 1} {stage} · {model}</span>
        <span class="meta">provider={provider} attempt={attempt} latency={latency}ms tokens={tokens}</span>
        <span class="badge {status_badge}">{validation}</span>
        <span class="badge {'badge-ok' if consistency == 'consistent' else 'badge-warn'}">{consistency}</span>
      </summary>
      <div class="call-body">
        {error_html}
        <div class="tab-group">
          <div class="tab-head">Prompt</div>
          <div class="tab-content">{prompt_html}</div>
          <div class="tab-head">Raw Response</div>
          <div class="tab-content">{raw_html}</div>
          <div class="tab-head">Parsed Result</div>
          <div class="tab-content">{parsed_html}</div>
        </div>
      </div>
    </details>
    """


def _render_event(event: dict[str, Any]) -> str:
    etype = _escape(event.get("type", ""))
    seq = event.get("seq", 0)
    ts = _escape(event.get("ts", ""))
    payload = event.get("payload", {})
    is_degradation = etype == "produce.degradation"
    cls = "event degradation" if is_degradation else "event"
    badge = '<span class="badge badge-error">降级</span>' if is_degradation else ""
    return f"""
    <div class="{cls}">
      <div class="event-header">
        <span class="event-type">{etype}</span>
        {badge}
        <span class="event-meta">seq={seq} · {ts}</span>
      </div>
      <pre>{_escape(_format_json(payload))}</pre>
    </div>
    """


def _render_cost_record(rec: dict[str, Any]) -> str:
    if "error" in rec:
        return f"<tr><td colspan=\"8\" class=\"error-text\">读取失败: {_escape(rec['error'])}</td></tr>"
    return f"""
    <tr>
      <td>{_escape(rec.get('stage', ''))}</td>
      <td>{_escape(rec.get('model', ''))}</td>
      <td>{rec.get('input_tokens', 0)}</td>
      <td>{rec.get('output_tokens', 0)}</td>
      <td>${rec.get('cost_usd', 0.0):.6f}</td>
      <td>{rec.get('latency_ms', 0)}ms</td>
      <td><span class="badge {'badge-ok' if rec.get('status') == 'ok' else 'badge-warn'}">{_escape(rec.get('status', ''))}</span></td>
      <td>{_escape(rec.get('created_at', ''))}</td>
    </tr>
    """


def _build_html(data: dict[str, Any]) -> str:
    meeting = data.get("meeting", {})
    trace = data.get("trace", {})
    events = data.get("events", {})
    cost_records = data.get("cost_records", [])
    stats = data.get("stats", {})

    topic = _escape(meeting.get("topic", "未知议题"))
    meeting_id = _escape(data.get("meeting_id", ""))
    generated_at = _escape(data.get("generated_at", ""))

    calls = trace.get("calls", [])
    calls_html = "\n".join(_render_call(c, i) for i, c in enumerate(calls)) if calls else "<p class=\"muted\">无 LLM 调用记录（可能使用了 StubLLM）</p>"

    degradation_events = events.get("degradation_events", [])
    degradation_html = "\n".join(_render_event(e) for e in degradation_events) if degradation_events else "<p class=\"muted\">无降级事件</p>"

    all_events = events.get("all", [])
    events_html = "\n".join(_render_event(e) for e in all_events) if all_events else "<p class=\"muted\">无事件记录</p>"

    cost_html = "\n".join(_render_cost_record(r) for r in cost_records) if cost_records else "<p class=\"muted\">无成本记录</p>"

    summary = trace.get("summary", {})

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Conclave 审计报告 · {topic}</title>
  <style>
    :root {{
      --bg: #f8f9fb;
      --surface: #ffffff;
      --ink: #111827;
      --muted: #6b7280;
      --rule: #e5e7eb;
      --accent: #2563eb;
      --accent2: #dc2626;
      --radius: 10px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.6;
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--rule);
      padding: 32px;
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .container {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px 32px 64px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 1.8rem; font-weight: 600; }}
    .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--rule);
      border-radius: var(--radius);
      padding: 20px;
    }}
    .card h3 {{ margin: 0 0 12px; font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
    .metric {{ font-size: 1.6rem; font-weight: 700; color: var(--ink); }}
    .section {{
      background: var(--surface);
      border: 1px solid var(--rule);
      border-radius: var(--radius);
      padding: 24px;
      margin-bottom: 24px;
    }}
    .section h2 {{ margin: 0 0 16px; font-size: 1.2rem; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      margin-left: 8px;
    }}
    .badge-ok {{ background: #d1fae5; color: #065f46; }}
    .badge-warn {{ background: #fef3c7; color: #92400e; }}
    .badge-error {{ background: #fee2e2; color: #991b1b; }}
    pre {{
      background: #f3f4f6;
      border-radius: 8px;
      padding: 12px;
      overflow-x: auto;
      font-size: 0.85rem;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .muted {{ color: var(--muted); }}
    .call-card {{
      border: 1px solid var(--rule);
      border-radius: 8px;
      margin-bottom: 12px;
      overflow: hidden;
    }}
    .call-card summary {{
      padding: 14px 16px;
      cursor: pointer;
      background: #fafafa;
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .call-title {{ font-weight: 600; }}
    .call-body {{ padding: 16px; }}
    .tab-head {{
      font-weight: 600;
      font-size: 0.85rem;
      color: var(--muted);
      margin: 16px 0 6px;
    }}
    .event {{
      border-left: 3px solid var(--rule);
      padding: 12px 16px;
      margin-bottom: 12px;
      background: #fafafa;
      border-radius: 0 8px 8px 0;
    }}
    .event.degradation {{
      border-left-color: var(--accent2);
      background: #fef2f2;
    }}
    .event-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }}
    .event-type {{ font-weight: 600; }}
    .event-meta {{ color: var(--muted); font-size: 0.85rem; margin-left: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--rule); }}
    th {{ color: var(--muted); font-weight: 500; background: #fafafa; }}
    .error-box {{
      background: #fee2e2;
      color: #991b1b;
      padding: 12px;
      border-radius: 8px;
      margin-bottom: 12px;
    }}
    .error-text {{ color: var(--accent2); }}
    .meta {{ color: var(--muted); font-size: 0.85rem; }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>Conclave 审计报告</h1>
      <div class="subtitle">{topic} · meeting_id={meeting_id} · 生成于 {generated_at}</div>
    </div>
  </header>

  <div class="container">
    <div class="grid">
      <div class="card"><h3>阶段</h3><div class="metric">{_escape(meeting.get('stage', 'N/A'))}</div></div>
      <div class="card"><h3>状态</h3><div class="metric">{_escape(meeting.get('status', 'N/A'))}</div></div>
      <div class="card"><h3>LLM 调用</h3><div class="metric">{stats.get('total_calls', 0)}</div></div>
      <div class="card"><h3>总 Tokens</h3><div class="metric">{stats.get('total_tokens', 0):,}</div></div>
      <div class="card"><h3>总成本</h3><div class="metric">${stats.get('total_cost_usd', 0.0):.6f}</div></div>
      <div class="card"><h3>降级事件</h3><div class="metric">{len(degradation_events)}</div></div>
    </div>

    <div class="section">
      <h2>会议状态快照</h2>
      <pre>{_escape(_format_json(meeting))}</pre>
    </div>

    <div class="section">
      <h2>Trace 摘要</h2>
      <pre>{_escape(_format_json(summary))}</pre>
    </div>

    <div class="section">
      <h2>降级事件（重点）</h2>
      {degradation_html}
    </div>

    <div class="section">
      <h2>LLM 调用链</h2>
      {calls_html}
    </div>

    <div class="section">
      <h2>成本明细</h2>
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr><th>Stage</th><th>Model</th><th>Input</th><th>Output</th><th>Cost</th><th>Latency</th><th>Status</th><th>Time</th></tr>
          </thead>
          <tbody>{cost_html}</tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>事件时间线</h2>
      {events_html}
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Conclave 会议审计报告")
    parser.add_argument("meeting_id", help="会议 ID")
    parser.add_argument("--api", default=DEFAULT_API, help=f"后端 API 地址（默认 {DEFAULT_API}）")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"输出目录（默认 {DEFAULT_OUT}）")
    parser.add_argument("--token", default="", help="API token（Bearer），留空则尝试无认证访问")
    args = parser.parse_args()

    print(f"[audit] 获取会议 {args.meeting_id} 的审计数据...")
    data = _fetch_audit(args.api, args.meeting_id, token=args.token or None)

    out_dir = Path(args.out) / f"conclave-audit-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{args.meeting_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.html"

    html_content = _build_html(data)
    report_path.write_text(html_content, encoding="utf-8")

    print(f"[audit] 报告已生成: {report_path.resolve()}")
    print(f"[audit] 降级事件数: {len(data.get('events', {}).get('degradation_events', []))}")
    print(f"[audit] LLM 调用数: {data.get('stats', {}).get('total_calls', 0)}")
    print(f"[audit] 总成本: ${data.get('stats', {}).get('total_cost_usd', 0.0):.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
