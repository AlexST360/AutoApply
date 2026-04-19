"""
tracker.py — Módulo 5: Tracker CLI y generador de dashboard HTML.

Funciones:
  - CLI para ver estado de aplicaciones (pending, applied, errors)
  - Generación de dashboard HTML con tabla dinámica
  - Logs detallados de cada ejecución
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ─── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ─── Consultas BD ──────────────────────────────────────────────────────────────
def get_stats() -> dict:
    """Retorna estadísticas generales de la BD."""
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row

    stats = {}
    try:
        # Total por status
        rows = con.execute(
            "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
        ).fetchall()
        stats["by_status"] = {row["status"]: row["count"] for row in rows}

        # Total general
        stats["total"] = sum(stats["by_status"].values())

        # Oferta mejor puntuada
        top = con.execute(
            "SELECT title, company, score FROM jobs WHERE score IS NOT NULL ORDER BY score DESC LIMIT 1"
        ).fetchone()
        stats["top_job"] = dict(top) if top else None

        # Última oferta encontrada
        last = con.execute(
            "SELECT date_found FROM jobs ORDER BY date_found DESC LIMIT 1"
        ).fetchone()
        stats["last_search"] = last["date_found"] if last else "Nunca"

    finally:
        con.close()

    return stats


def get_jobs_by_status(status: str = None, limit: int = 50) -> list[dict]:
    """
    Retorna lista de ofertas filtrando por status.
    Si status es None, retorna todas.
    """
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row

    try:
        if status:
            rows = con.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY date_found DESC, score DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM jobs ORDER BY date_found DESC, score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ─── CLI ───────────────────────────────────────────────────────────────────────
STATUS_EMOJI = {
    "found":     "🔍",
    "scored":    "📊",
    "candidate": "⭐",
    "applied":   "✅",
    "skip":      "⏭",
    "error":     "❌",
}

STATUS_LABEL = {
    "found":     "Encontradas",
    "scored":    "Evaluadas (descartadas)",
    "candidate": "Candidatas",
    "applied":   "Aplicadas",
    "skip":      "Saltadas",
    "error":     "Con error",
}


def print_summary() -> None:
    """Imprime resumen general en consola."""
    stats = get_stats()
    print("\n" + "=" * 60)
    print("  AutoApply — Estado de postulaciones")
    print("=" * 60)
    print(f"  Última búsqueda: {stats.get('last_search', 'Nunca')[:19]}")
    print(f"  Total de ofertas: {stats.get('total', 0)}")
    print()

    by_status = stats.get("by_status", {})
    for status, emoji in STATUS_EMOJI.items():
        count = by_status.get(status, 0)
        label = STATUS_LABEL.get(status, status)
        bar = "█" * min(count, 30)
        print(f"  {emoji} {label:<28} {count:>3}  {bar}")

    if stats.get("top_job"):
        top = stats["top_job"]
        print(f"\n  🏆 Mejor oferta: {top['title']} @ {top['company']} (score: {top['score']})")

    print("=" * 60)


def print_jobs_list(status: str = None) -> None:
    """Imprime tabla de ofertas para un status dado."""
    jobs = get_jobs_by_status(status, limit=20)
    label = STATUS_LABEL.get(status, "Todas") if status else "Todas"

    print(f"\n{'=' * 80}")
    print(f"  {label} ({len(jobs)} resultados)")
    print(f"{'=' * 80}")
    print(f"  {'#':<4} {'Score':<7} {'Status':<10} {'Cargo':<30} {'Empresa'}")
    print(f"  {'-' * 4} {'-' * 6} {'-' * 9} {'-' * 29} {'-' * 20}")

    for job in jobs:
        score = f"{job['score']}/100" if job.get("score") is not None else "  —   "
        status_icon = STATUS_EMOJI.get(job["status"], "?")
        title = (job["title"] or "—")[:28]
        company = (job["company"] or "—")[:20]
        print(f"  {job['id']:<4} {score:<7} {status_icon} {job['status']:<8} {title:<30} {company}")

    print()


def print_job_detail(job_id: int) -> None:
    """Imprime el detalle de una oferta específica."""
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    job = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    con.close()

    if not job:
        print(f"  Oferta #{job_id} no encontrada.")
        return

    job = dict(job)
    print(f"\n{'=' * 60}")
    print(f"  Oferta #{job['id']}: {job['title']}")
    print(f"{'=' * 60}")
    print(f"  Empresa:       {job['company']}")
    print(f"  Ubicación:     {job['location']}")
    print(f"  URL:           {job['url']}")
    print(f"  Estado:        {STATUS_EMOJI.get(job['status'], '?')} {job['status']}")
    print(f"  Score:         {job['score']}/100" if job.get("score") else "  Score:        —")
    print(f"  Encontrada:    {(job['date_found'] or '')[:19]}")
    print(f"  Aplicada:      {(job['application_date'] or '—')[:19]}")

    if job.get("score_justification"):
        print(f"\n  Evaluación Claude:\n  {job['score_justification'][:400]}")

    if job.get("cover_letter_path"):
        print(f"\n  Cover letter: {job['cover_letter_path']}")

    if job.get("error_message"):
        print(f"\n  Error: {job['error_message']}")

    print()


# ─── Dashboard HTML ────────────────────────────────────────────────────────────
def generate_dashboard() -> Path:
    """
    Genera dashboard/index.html con auto-refresh, links funcionales
    y filas expandibles con detalle de cada oferta.
    """
    jobs = get_jobs_by_status(limit=500)
    stats = get_stats()
    jobs_json = json.dumps(jobs, ensure_ascii=False, default=str)

    by_status = stats.get("by_status", {})
    total      = stats.get("total", 0)
    found      = by_status.get("found", 0)
    scored     = by_status.get("scored", 0)
    candidates = by_status.get("candidate", 0)
    approved   = by_status.get("approved", 0)
    discarded  = by_status.get("discarded", 0)
    applied    = by_status.get("applied", 0)
    skipped    = by_status.get("skip", 0)
    errors     = by_status.get("error", 0)
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AutoApply Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg:      #0d1117;
      --surface: #161b22;
      --border:  #30363d;
      --text:    #c9d1d9;
      --muted:   #8b949e;
      --green:   #3fb950;
      --blue:    #58a6ff;
      --yellow:  #d29922;
      --red:     #f85149;
      --purple:  #bc8cff;
      --orange:  #f0883e;
    }}
    body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}

    /* ── Header ── */
    header {{
      background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 14px 24px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }}
    header h1 {{ font-size: 1.1rem; font-weight: 700; color: #fff; }}
    .header-sub {{ font-size: 0.78rem; color: var(--muted); }}
    .refresh-info {{ margin-left: auto; font-size: 0.75rem; color: var(--muted); display: flex; align-items: center; gap: 8px; }}
    .dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--green); animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.3 }} }}
    .refresh-btn {{
      padding: 4px 12px; border-radius: 6px; border: 1px solid var(--border);
      background: transparent; color: var(--muted); cursor: pointer; font-size: 0.75rem;
    }}
    .refresh-btn:hover {{ background: var(--border); color: var(--text); }}

    /* ── Stats bar ── */
    .stats {{
      display: flex; flex-wrap: wrap; gap: 1px;
      background: var(--border); border-bottom: 1px solid var(--border);
    }}
    .stat {{
      flex: 1; min-width: 100px; padding: 14px 20px;
      background: var(--surface); text-align: center; cursor: pointer;
      transition: background .15s;
    }}
    .stat:hover {{ background: #1f2937; }}
    .stat.active {{ background: #1f2937; border-bottom: 2px solid var(--blue); }}
    .stat-val {{ font-size: 1.6rem; font-weight: 800; line-height: 1; }}
    .stat-lbl {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-top: 3px; }}
    .c-total  {{ color: var(--text); }}
    .c-found  {{ color: var(--muted); }}
    .c-scored {{ color: #6e7681; }}
    .c-cand   {{ color: var(--blue); }}
    .c-app    {{ color: var(--green); }}
    .c-err    {{ color: var(--red); }}

    /* ── Controls ── */
    .controls {{
      padding: 12px 24px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
      border-bottom: 1px solid var(--border);
    }}
    .controls-count {{ font-size: 0.8rem; color: var(--muted); }}
    .search-wrap {{ margin-left: auto; position: relative; }}
    .search-wrap input {{
      padding: 6px 12px 6px 32px; border-radius: 6px;
      border: 1px solid var(--border); background: var(--surface);
      color: var(--text); font-size: 0.82rem; width: 240px; outline: none;
    }}
    .search-wrap input:focus {{ border-color: var(--blue); }}
    .search-icon {{ position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--muted); font-size: 0.8rem; }}

    /* ── Table ── */
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    thead th {{
      background: var(--surface); color: var(--muted);
      font-size: 0.68rem; text-transform: uppercase; letter-spacing: .05em;
      padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 1; white-space: nowrap;
    }}
    tbody tr {{ border-bottom: 1px solid var(--border); cursor: pointer; }}
    tbody tr:hover td {{ background: #161b2288; }}
    tbody tr.expanded td {{ background: #161b22; }}
    td {{ padding: 10px 14px; vertical-align: middle; }}
    .td-id    {{ color: var(--muted); font-size: 0.75rem; width: 40px; }}
    .td-title {{ font-weight: 500; max-width: 280px; }}
    .td-title span {{ display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .td-company {{ white-space: nowrap; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }}
    .td-loc {{ color: var(--muted); font-size: 0.78rem; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .td-date {{ color: var(--muted); font-size: 0.75rem; white-space: nowrap; }}
    .td-link {{ white-space: nowrap; }}

    /* expand row */
    .detail-row td {{
      padding: 0; background: #0d1117;
      border-bottom: 2px solid var(--border);
    }}
    .detail-inner {{
      padding: 16px 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
      font-size: 0.8rem; line-height: 1.6;
    }}
    .detail-inner h4 {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 6px; }}
    .detail-inner p {{ color: var(--text); white-space: pre-wrap; word-break: break-word; }}
    .detail-link {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 14px; border-radius: 6px; border: 1px solid var(--blue);
      color: var(--blue); font-size: 0.78rem; text-decoration: none; margin-top: 10px;
    }}
    .detail-link:hover {{ background: #1d3557; }}

    /* badges */
    .badge {{
      display: inline-block; padding: 2px 8px; border-radius: 20px;
      font-size: 0.68rem; font-weight: 600; white-space: nowrap;
    }}
    .b-found     {{ background: #21262d; color: #8b949e; }}
    .b-scored    {{ background: #21262d; color: #6e7681; }}
    .b-candidate {{ background: #1d3557; color: var(--blue); }}
    .b-approved  {{ background: #0d2818; color: var(--green); font-weight:700; }}
    .b-discarded {{ background: #2d1a0f; color: #c07030; }}
    .b-applied   {{ background: #0d2818; color: var(--green); }}
    .b-skip      {{ background: #21262d; color: #6e7681; }}
    .b-error     {{ background: #2d0f0f; color: var(--red); }}

    /* action buttons */
    .act-btn {{
      padding: 3px 10px; border-radius: 5px; border: 1px solid; cursor: pointer;
      font-size: 0.7rem; font-weight: 600; background: transparent; margin-right: 4px;
    }}
    .act-approve  {{ border-color: var(--green); color: var(--green); }}
    .act-approve:hover  {{ background: #0d2818; }}
    .act-discard  {{ border-color: var(--red); color: var(--red); }}
    .act-discard:hover  {{ background: #2d0f0f; }}
    .act-restore  {{ border-color: var(--muted); color: var(--muted); }}
    .act-restore:hover  {{ background: #21262d; }}

    /* score bar */
    .score-wrap {{ display: flex; align-items: center; gap: 6px; min-width: 90px; }}
    .score-num {{ font-size: 0.78rem; font-weight: 700; width: 28px; text-align: right; }}
    .score-track {{ flex: 1; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }}
    .score-fill  {{ height: 100%; border-radius: 3px; }}

    /* cv badge */
    .cv-badge {{ font-size: 0.68rem; padding: 1px 6px; border-radius: 4px; background: #0d2818; color: var(--green); }}

    /* footer */
    .footer {{ padding: 16px 24px; text-align: center; color: var(--muted); font-size: 0.72rem; border-top: 1px solid var(--border); }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>

<header>
  <h1>&#9889; AutoApply</h1>
  <span class="header-sub">Alex Ocampo Segundo &mdash; Santiago, Chile</span>
  <div class="refresh-info">
    <span class="dot"></span>
    <button class="refresh-btn" onclick="location.reload()">Recargar</button>
  </div>
</header>

<div class="stats">
  <div class="stat active" data-filter="all" onclick="setFilter('all',this)">
    <div class="stat-val c-total">{total}</div>
    <div class="stat-lbl">Total</div>
  </div>
  <div class="stat" data-filter="found" onclick="setFilter('found',this)">
    <div class="stat-val c-found">{found}</div>
    <div class="stat-lbl">Sin evaluar</div>
  </div>
  <div class="stat" data-filter="scored" onclick="setFilter('scored',this)">
    <div class="stat-val c-scored">{scored}</div>
    <div class="stat-lbl">Descartadas</div>
  </div>
  <div class="stat" data-filter="candidate" onclick="setFilter('candidate',this)">
    <div class="stat-val c-cand">{candidates}</div>
    <div class="stat-lbl">Sin revisar</div>
  </div>
  <div class="stat" data-filter="approved" onclick="setFilter('approved',this)">
    <div class="stat-val" style="color:var(--green)">{approved}</div>
    <div class="stat-lbl">Aprobadas</div>
  </div>
  <div class="stat" data-filter="discarded" onclick="setFilter('discarded',this)">
    <div class="stat-val" style="color:var(--orange)">{discarded}</div>
    <div class="stat-lbl">Descartadas</div>
  </div>
  <div class="stat" data-filter="applied" onclick="setFilter('applied',this)">
    <div class="stat-val c-app">{applied}</div>
    <div class="stat-lbl">Aplicadas</div>
  </div>
  <div class="stat" data-filter="error" onclick="setFilter('error',this)">
    <div class="stat-val c-err">{errors}</div>
    <div class="stat-lbl">Errores</div>
  </div>
</div>

<div class="controls">
  <span class="controls-count" id="count-label"></span>
  <div class="search-wrap">
    <span class="search-icon">&#128269;</span>
    <input id="search" type="text" placeholder="Buscar cargo o empresa..." oninput="onSearch(this.value)">
  </div>
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th class="td-id">#</th>
        <th>Cargo</th>
        <th>Empresa</th>
        <th>Ubicacion</th>
        <th>Score</th>
        <th>Estado</th>
        <th>Fuente</th>
        <th>Fecha</th>
        <th>Acciones</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div id="empty" style="display:none;padding:40px;text-align:center;color:#6e7681">Sin resultados para este filtro.</div>
</div>

<div class="footer">AutoApply &mdash; Generado el {now} &mdash; {total} ofertas en base de datos</div>

<script>
const JOBS = {jobs_json};

const SCORE_COLOR = s => s >= 80 ? '#3fb950' : s >= 65 ? '#58a6ff' : s >= 40 ? '#d29922' : '#f85149';
const BADGES = {{
  found:     'b-found',
  scored:    'b-scored',
  candidate: 'b-candidate',
  approved:  'b-approved',
  discarded: 'b-discarded',
  applied:   'b-applied',
  skip:      'b-skip',
  error:     'b-error',
}};
const STATUS_LABEL = {{
  found: 'Sin evaluar', scored: 'Descartada', candidate: 'Sin revisar',
  approved: 'Aprobada', discarded: 'Descartada', applied: 'Aplicada',
  skip: 'Saltada', error: 'Error',
}};

const API = 'http://localhost:8765';
const USE_API = true;

async function setStatus(id, status, rowEl) {{
  if (!USE_API) return;
  try {{
    const r = await fetch(`${{API}}/api/jobs/${{id}}`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{status}})
    }});
    if (r.ok) {{
      const j = JOBS.find(x => x.id === id);
      if (j) j.status = status;
      render();
    }}
  }} catch(e) {{
    alert('Servidor no disponible. Corre: python main.py serve');
  }}
}}

let filter = 'all';
let query  = '';
let expanded = null;   // id de fila expandida

function filtered() {{
  return JOBS.filter(j => {{
    if (filter !== 'all' && j.status !== filter) return false;
    if (query) {{
      const q = query.toLowerCase();
      if (!(j.title||'').toLowerCase().includes(q) &&
          !(j.company||'').toLowerCase().includes(q)) return false;
    }}
    return true;
  }});
}}

function render() {{
  const tbody = document.getElementById('tbody');
  const empty = document.getElementById('empty');
  const label = document.getElementById('count-label');
  tbody.innerHTML = '';

  const rows = filtered();
  label.textContent = rows.length + ' oferta' + (rows.length !== 1 ? 's' : '');
  if (!rows.length) {{ empty.style.display='block'; return; }}
  empty.style.display = 'none';

  rows.forEach(j => {{
    const score = j.score != null ? j.score : null;
    const scoreHtml = score !== null
      ? `<div class="score-wrap">
           <span class="score-num" style="color:${{SCORE_COLOR(score)}}">${{score}}</span>
           <div class="score-track"><div class="score-fill" style="width:${{score}}%;background:${{SCORE_COLOR(score)}}"></div></div>
         </div>`
      : `<span style="color:#6e7681;font-size:.75rem">—</span>`;

    const badge   = BADGES[j.status] || '';
    const slabel  = STATUS_LABEL[j.status] || j.status;
    const date    = (j.date_found||'').substring(0,10);
    const srcLabel = j.source === 'computrabajo' ? '<span style="color:#f0883e;font-size:.68rem">CT</span>'
                   : '<span style="color:#58a6ff;font-size:.68rem">LI</span>';

    // Botones de acción según estado
    let actBtns = '';
    if (j.status === 'candidate') {{
      actBtns = `<button class="act-btn act-approve" onclick="event.stopPropagation();setStatus(${{j.id}},'approved',this)">✓ Aprobar</button>
                 <button class="act-btn act-discard" onclick="event.stopPropagation();setStatus(${{j.id}},'discarded',this)">✗ Descartar</button>`;
    }} else if (j.status === 'approved') {{
      actBtns = `<button class="act-btn act-discard" onclick="event.stopPropagation();setStatus(${{j.id}},'discarded',this)">✗ Descartar</button>
                 <button class="act-btn act-restore" onclick="event.stopPropagation();setStatus(${{j.id}},'candidate',this)">↩</button>`;
    }} else if (j.status === 'discarded') {{
      actBtns = `<button class="act-btn act-approve" onclick="event.stopPropagation();setStatus(${{j.id}},'approved',this)">✓ Aprobar</button>
                 <button class="act-btn act-restore" onclick="event.stopPropagation();setStatus(${{j.id}},'candidate',this)">↩</button>`;
    }}

    // Fila principal — click para expandir
    const tr = document.createElement('tr');
    tr.dataset.id = j.id;
    tr.innerHTML = `
      <td class="td-id">${{j.id}}</td>
      <td class="td-title"><span title="${{(j.title||'').replace(/"/g,'&quot;')}}">${{j.title||'—'}}</span></td>
      <td class="td-company" title="${{(j.company||'').replace(/"/g,'&quot;')}}">${{j.company||'—'}}</td>
      <td class="td-loc">${{(j.location||'').substring(0,35)}}</td>
      <td>${{scoreHtml}}</td>
      <td><span class="badge ${{badge}}">${{slabel}}</span></td>
      <td>${{srcLabel}}</td>
      <td class="td-date">${{date}}</td>
      <td style="white-space:nowrap">${{actBtns}}</td>
    `;
    tr.addEventListener('click', () => toggleDetail(j, tr));
    tbody.appendChild(tr);
  }});
}}

function toggleDetail(j, tr) {{
  // Cerrar fila anterior si es diferente
  const prev = document.getElementById('detail-' + expanded);
  if (prev) prev.remove();

  if (expanded === j.id) {{ expanded = null; tr.classList.remove('expanded'); return; }}
  expanded = j.id;
  tr.classList.add('expanded');

  const desc   = (j.description||'Sin descripción').substring(0,600);
  const just   = (j.score_justification||'').substring(0,400) || '—';
  const srcName = j.source === 'computrabajo' ? 'Computrabajo' : 'LinkedIn';
  const loginNote = j.source === 'computrabajo'
    ? ' <span style="color:#8b949e;font-size:.68rem">(requiere login CT)</span>' : '';
  const urlBtn = j.url
    ? `<a class="detail-link" href="${{j.url}}" target="_blank" rel="noopener noreferrer">
         &#128279; Abrir en ${{srcName}}
       </a>${{loginNote}}`
    : '<span style="color:#6e7681;font-size:.78rem">Sin URL disponible</span>';

  const detail = document.createElement('tr');
  detail.id = 'detail-' + j.id;
  detail.className = 'detail-row';
  detail.innerHTML = `
    <td colspan="9">
      <div class="detail-inner">
        <div>
          <h4>Descripcion del puesto</h4>
          <p>${{desc}}${{j.description && j.description.length > 600 ? '...' : ''}}</p>
          ${{urlBtn}}
        </div>
        <div>
          <h4>Evaluacion Claude / Groq</h4>
          <p>${{just}}</p>
          ${{j.cover_letter_path ? '<br><h4>Cover Letter</h4><p style="color:#3fb950">' + j.cover_letter_path.split(/[/\\\\]/).pop() + '</p>' : ''}}
          ${{j.error_message ? '<br><h4 style="color:#f85149">Error</h4><p style="color:#f85149">' + j.error_message + '</p>' : ''}}
        </div>
      </div>
    </td>
  `;
  tr.after(detail);
}}

function setFilter(f, el) {{
  filter = f;
  document.querySelectorAll('.stat').forEach(s => s.classList.remove('active'));
  el.classList.add('active');
  expanded = null;
  render();
}}

function onSearch(val) {{
  query = val.trim();
  expanded = null;
  render();
}}

render();
</script>
</body>
</html>"""

    output_path = config.DASHBOARD_DIR / "index.html"
    output_path.write_text(html + "\n", encoding="utf-8")
    logger.info("Dashboard generado: %s", output_path)
    return output_path


# ─── CLI principal ─────────────────────────────────────────────────────────────
def run_tracker(command: str = "summary", job_id: int = None) -> None:
    """
    Ejecuta el comando del tracker.

    Comandos:
      summary   — Resumen general
      list      — Listar todas
      candidates — Listar candidatas
      applied   — Listar aplicadas
      errors    — Listar errores
      detail N  — Detalle de oferta #N
      dashboard — Generar dashboard HTML
    """
    if command == "summary":
        print_summary()
    elif command == "list":
        print_jobs_list()
    elif command == "candidates":
        print_jobs_list("candidate")
    elif command == "applied":
        print_jobs_list("applied")
    elif command == "errors":
        print_jobs_list("error")
    elif command == "detail" and job_id:
        print_job_detail(job_id)
    elif command == "dashboard":
        path = generate_dashboard()
        print(f"\n  Dashboard generado: {path}")
        print("  Abre el archivo en tu navegador para verlo.\n")
    else:
        print("\nUso: python tracker.py [summary|list|candidates|applied|errors|detail N|dashboard]\n")


# ─── Punto de entrada directo ──────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=config.LOG_LEVEL)

    args = sys.argv[1:]
    cmd = args[0] if args else "summary"
    jid = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    run_tracker(cmd, jid)
