"""
job_scorer.py — Módulo 2: Evaluador de compatibilidad oferta-CV.

Usa batch scoring: envía grupos de 10 ofertas en UN solo request a Groq,
reduciendo llamadas de N a ceil(N/10). Con 28 ofertas: 3 llamadas en vez de 28.
"""

import json
import logging
import re
import sqlite3
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from modules.groq_client import get_client

logger = logging.getLogger(__name__)

# ─── Cargar CV una sola vez ────────────────────────────────────────────────────
def _load_cv() -> str:
    try:
        return config.CV_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("CV no encontrado en %s", config.CV_PATH)
        return "CV no disponible."

CV_TEXT = _load_cv()
client  = get_client()

BATCH_SIZE = 10   # ofertas por request

# ─── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un experto en reclutamiento técnico especializado en tecnología en Chile.
Evalúas la compatibilidad entre un candidato y múltiples ofertas de trabajo.

PERFIL DEL CANDIDATO:
- Nivel: Junior / semi-senior (1 año de experiencia real)
- Stack: PHP, MySQL, MVC, Python, JavaScript, HTML/CSS
- Experiencia: plataforma web interna (PHP+MySQL), automatización Python+Selenium
- Laravel: básico-intermedio
- Sin experiencia en: React/Angular avanzado, .NET, cloud (AWS/Azure/GCP), DevOps, Salesforce, SAP
- Español nativo. Inglés: lectura técnica sí, conversación fluida NO

Criterios de score (0-100):
- 80-100: Pide PHP/Python/JS, nivel junior/semi, empresa chilena o LATAM
- 65-79:  Requisitos principales cubiertos, brechas menores
- 40-64:  Comparte parte del stack, faltan tecnologías clave
- 0-39:   Stack diferente, senior requerido, ventas/otro rubro, o inglés fluido obligatorio

Penalizaciones:
- Senior 5+ años requerido: -20 a -30 puntos
- Inglés conversacional obligatorio: -25 a -35 puntos

Bonus:
- Pide junior/semi/analista: +10 puntos
- Empresa en Chile/Santiago: +5 puntos

RESPONDE ÚNICAMENTE con un JSON array, sin texto adicional:
[
  {"id": <id>, "score": <0-100>, "justificacion": "<máx 80 palabras en español>"},
  ...
]"""


def _extract_json_array(raw: str) -> list:
    """Extrae el JSON array aunque venga con thinking tags, markdown o texto extra."""
    # Quitar bloques <think>...</think> (modelos de razonamiento como Nemotron)
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
    # Quitar bloques ```json ... ```
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # Buscar el primer array de objetos [{  (no array de enteros)
    start = raw.find("[{")
    if start == -1:
        start = raw.find("[")
    if start == -1:
        return json.loads(raw)

    # Avanzar hasta el ] que cierra el array (contando profundidad de brackets)
    depth = 0
    in_str = False
    escape = False
    for i, c in enumerate(raw[start:], start):
        if escape:
            escape = False
            continue
        if c == "\\" and in_str:
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])

    # Fallback: intentar desde el primer [
    return json.loads(raw[start:])


def score_batch(jobs: list[dict]) -> list[dict]:
    """
    Envía un grupo de ofertas en un solo request a Groq.
    Retorna lista de dicts {id, score, justificacion}.
    """
    lines = []
    for j in jobs:
        desc = (j.get("description") or "")[:300].replace("\n", " ")
        lines.append(
            f"[{j['id']}] Título: {j['title']} | Empresa: {j['company']} "
            f"| Ubicación: {j.get('location','')} | Desc: {desc}"
        )

    user_msg = (
        f"Evalúa estas {len(jobs)} ofertas contra el CV del candidato.\n\n"
        f"CV RESUMIDO:\n{CV_TEXT[:1500]}\n\n"
        f"OFERTAS:\n" + "\n".join(lines) +
        "\n\nResponde SOLO con el JSON array solicitado."
    )

    response = client.chat_completions_create(
        model=config.GROQ_MODEL,
        max_tokens=max(2048, 200 * len(jobs)),  # buffer extra para modelos que razonan
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )

    raw = response.choices[0].message.content.strip()
    logger.debug("Tokens batch — entrada: %d | salida: %d",
                 response.usage.prompt_tokens, response.usage.completion_tokens)
    logger.info("  Raw respuesta (primeros 300 chars): %s", raw[:300])

    return _extract_json_array(raw)


# ─── Proceso principal ─────────────────────────────────────────────────────────
def run_scoring(rescore: bool = False) -> int:
    """
    Evalúa todas las ofertas pendientes en batches de 10.
    28 ofertas → 3 llamadas a Groq en vez de 28.
    """
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    where = "WHERE status = 'found'" if not rescore else "WHERE status IN ('found', 'scored')"
    jobs = [dict(r) for r in con.execute(
        f"SELECT * FROM jobs {where} ORDER BY date_found DESC"
    ).fetchall()]
    con.close()

    if not jobs:
        logger.info("No hay ofertas pendientes de evaluación.")
        return 0

    # Dividir en grupos de BATCH_SIZE
    batches = [jobs[i:i+BATCH_SIZE] for i in range(0, len(jobs), BATCH_SIZE)]
    logger.info("Evaluando %d ofertas en %d batch(es) de %d...",
                len(jobs), len(batches), BATCH_SIZE)

    evaluated = 0

    for b_idx, batch in enumerate(batches, 1):
        logger.info("  Batch %d/%d (%d ofertas)...", b_idx, len(batches), len(batch))
        try:
            results = score_batch(batch)
        except Exception as exc:
            logger.error("  Error en batch %d: %s — saltando.", b_idx, exc)
            if b_idx < len(batches):
                time.sleep(3)
            continue

        if not isinstance(results, list):
            logger.error("  Batch %d: respuesta no es lista (%s) — saltando.", b_idx, type(results))
            continue

        # Indexar resultados por id para acceso rápido
        results_by_id = {r["id"]: r for r in results if isinstance(r, dict) and "id" in r}

        con = sqlite3.connect(config.DB_PATH)
        for job in batch:
            result = results_by_id.get(job["id"])
            if not result:
                logger.warning("  Sin resultado para id=%d (%s)", job["id"], job["title"][:40])
                continue

            score        = int(result.get("score", 0))
            justificacion = result.get("justificacion", "Sin justificación.")
            new_status   = "candidate" if score >= config.SCORE_THRESHOLD else "scored"

            con.execute(
                "UPDATE jobs SET score=?, score_justification=?, status=? WHERE id=?",
                (score, justificacion, new_status, job["id"]),
            )
            label = "✅ CANDIDATA" if new_status == "candidate" else "  descartada"
            logger.info("  → [%d] Score %d/100 %s | %s @ %s",
                        job["id"], score, label, job["title"][:40], job["company"][:25])
            evaluated += 1

        con.commit()
        con.close()

        if b_idx < len(batches):
            logger.info("  Esperando 3s antes del siguiente batch...")
            time.sleep(3)

    logger.info("Scoring completado. %d ofertas evaluadas.", evaluated)
    return evaluated


# ─── Punto de entrada directo ──────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    result = run_scoring()
    print(f"\nOfertas evaluadas: {result}")
