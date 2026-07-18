"""Self-contained HTML heatmap generation."""

from __future__ import annotations

from html import escape
import json
import math
from pathlib import Path

from .storage import RunSummary, StoredSource


STYLE = """
:root { color-scheme: dark; --bg: #0d1117; --panel: #161b22; --border: #30363d;
  --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff; --cold: #f85149; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 ui-monospace,
  SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
header { position: sticky; top: 0; z-index: 2; padding: 18px 24px; background: rgba(13,17,23,.94);
  border-bottom: 1px solid var(--border); backdrop-filter: blur(8px); }
h1 { margin: 0 0 6px; font: 600 21px/1.2 system-ui, sans-serif; }
.meta, .summary { color: var(--muted); }
.layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); min-height: calc(100vh - 80px); }
nav { padding: 16px; border-right: 1px solid var(--border); overflow: auto; }
nav a { display: block; padding: 7px 9px; border-radius: 6px; color: var(--muted);
  text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
nav a:hover { color: var(--text); background: var(--panel); }
main { min-width: 0; padding: 20px 24px 80px; }
.file { margin-bottom: 30px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.file h2 { margin: 0; padding: 11px 14px; background: var(--panel); font-size: 14px; }
.file-stats { color: var(--muted); font-weight: normal; margin-left: 10px; }
.source { overflow-x: auto; }
.line { display: grid; grid-template-columns: 74px 58px minmax(max-content, 1fr); min-height: 22px; }
.line.executable { background: rgba(46, 160, 67, calc(.08 + var(--heat) * .5)); }
.line.unseen { background: rgba(248, 81, 73, .15); }
.count { padding: 1px 10px; text-align: right; color: var(--muted); border-right: 1px solid var(--border); }
.unseen .count { color: var(--cold); }
.number { padding: 1px 10px; text-align: right; color: #6e7681; user-select: none; }
code { display: block; padding: 1px 12px; white-space: pre; }
.warning { padding: 10px 14px; color: #d29922; border-top: 1px solid var(--border); }
@media (max-width: 800px) { .layout { grid-template-columns: 1fr; } nav { display: none; }
  main { padding: 12px; } }
"""


def _format_count(count: int) -> str:
    if count < 1_000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1_000:.1f}k"
    return f"{count / 1_000_000:.1f}m"


def _file_html(item: StoredSource, index: int) -> tuple[str, int, int]:
    executable = set(item.executable_lines)
    executed = sum(1 for line in executable if item.hits.get(line, 0) > 0)
    unseen = len(executable) - executed
    maximum = max((item.hits.get(line, 0) for line in executable), default=0)
    rendered_lines: list[str] = []
    for line_number, text in enumerate(item.source.splitlines(), start=1):
        count = item.hits.get(line_number, 0)
        is_executable = line_number in executable
        classes = ["line"]
        heat = 0.0
        if is_executable:
            classes.append("executable")
            if count == 0:
                classes.append("unseen")
            elif maximum:
                heat = math.log1p(count) / math.log1p(maximum)
        count_text = _format_count(count) if is_executable else ""
        rendered_lines.append(
            f'<div class="{" ".join(classes)}" style="--heat:{heat:.4f}">'
            f'<span class="count">{count_text}</span>'
            f'<span class="number">{line_number}</span>'
            f'<code>{escape(text)}</code></div>'
        )
    warning = (
        f'<div class="warning">{escape(item.parse_error)}</div>' if item.parse_error else ""
    )
    block = (
        f'<section class="file" id="file-{index}">'
        f'<h2>{escape(item.path)}<span class="file-stats">'
        f"{executed}/{len(executable)} executable lines observed"
        f"</span></h2><div class=\"source\">{''.join(rendered_lines)}</div>{warning}</section>"
    )
    return block, executed, unseen


def render_report(sources: list[StoredSource], latest: RunSummary | None) -> str:
    sections: list[str] = []
    nav: list[str] = []
    total_executed = 0
    total_unseen = 0
    for index, item in enumerate(sources):
        section, executed, unseen = _file_html(item, index)
        sections.append(section)
        nav.append(f'<a href="#file-{index}" title="{escape(item.path)}">{escape(item.path)}</a>')
        total_executed += executed
        total_unseen += unseen

    total = total_executed + total_unseen
    percent = 100.0 * total_executed / total if total else 0.0
    if latest:
        meta = (
            f"Latest run #{latest.id} · {escape(latest.context)} · exit {latest.exit_code} · "
            f"{escape(latest.started_at)} · <code>{escape(latest.command)}</code>"
        )
    else:
        meta = "No recorded runs"
    empty = (
        "<p>No source snapshots found. Run <code>runtimespy run -- python app.py</code> first.</p>"
        if not sources
        else ""
    )
    title = "RuntimeSpy execution heatmap"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>{STYLE}</style></head>
<body><header><h1>{title}</h1><div class="summary">{total_executed}/{total} executable lines
observed ({percent:.1f}%) · {total_unseen} unseen</div><div class="meta">{meta}</div></header>
<div class="layout"><nav>{''.join(nav)}</nav><main>{empty}{''.join(sections)}</main></div>
<script>document.querySelectorAll('nav a').forEach(a => a.addEventListener('click', () =>
history.replaceState(null, '', a.getAttribute('href'))));</script></body></html>"""


def write_report(
    sources: list[StoredSource], latest: RunSummary | None, destination: Path
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_report(sources, latest), encoding="utf-8")
    return destination.resolve()

