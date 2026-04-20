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
- Nivel: Junior / semi-senior (1 año de experiencia real en total)
- Stack: PHP, MySQL, MVC, Python, JavaScript, HTML/CSS
- Experiencia: plataforma web interna (PHP+MySQL), automatización Python+Selenium
- Laravel: básico-intermedio
- SIN experiencia en: React/Angular avanzado, .NET, cloud (AWS/Azure/GCP), DevOps, Salesforce, SAP
- Español nativo. Inglés: lectura técnica sí, CONVERSACIÓN FLUIDA NO

CRITERIOS DE SCORE (0-100):
- 80-100: Pide PHP/Python/JS, nivel junior/semi, empresa chilena
- 65-79:  Requisitos principales cubiertos, brechas menores aceptables
- 40-64:  Parte del stack coincide pero faltan tecnologías importantes
- 0-39:   Descalificador presente (ver abajo)

DESCALIFICADORES ABSOLUTOS → score máximo 25:
Aplica score ≤ 25 si la oferta menciona CUALQUIERA de estos:
- Requiere 3 o más años de experiencia (ej: "3+ años", "mínimo 3 años", "al menos 4 años")
- Requiere inglés fluido/conversacional/nativo de forma obligatoria
- Stack principal es .NET, Java Enterprise, Salesforce, SAP, o similar sin PHP/Python
- Cargo senior o lead como requisito excluyente
- Rol completamente diferente (ventas, soporte no técnico, etc.)

PENALIZACIONES (pueden acumularse):
- "2 años requeridos" cuando dice MÍNIMO excluyente: -25 pts
- Menciona tecnologías que no domina como OBLIGATORIAS (React, Angular, AWS): -15 pts
- Inglés mencionado como deseable (no obligatorio): -5 pts

BONUS:
- Título incluye "junior", "semi-senior", "trainee", "analista": +10 pts
- Empresa en Chile/Santiago explícito: +5 pts
- Stack coincide en ≥2 tecnologías clave: +10 pts

RESPONDE ÚNICAMENTE con un JSON array, sin texto adicional:
[
  {"id": <id>, "score": <0-100>, "justificacion": "<máx 80 palabras en español>"},
  ...
]"""


# ─── Hard disqualifiers (chequeo local, sin IA) ────────────────────────────────
_DISQUALIFIERS = [
    # Experiencia >= 3 años explícita
    (re.compile(
        r'(\b[3-9]|\b1\d)\s*\+?\s*años?\s+(?:de\s+)?(?:experiencia|exp\.?)\b'
        r'|mínimo\s+[3-9]\s*años?\s+(?:de\s+)?(?:experiencia|exp\.?)'
        r'|al\s+menos\s+[3-9]\s*años?\s+(?:de\s+)?(?:experiencia|exp\.?)'
        r'|experiencia\s+(?:de\s+)?[3-9]\s*\+?\s*años?'
        r'|\b[3-9]\+?\s*years?\s+(?:of\s+)?experience',
        re.I), "requiere 3+ años de experiencia"),
    # Inglés fluido obligatorio
    (re.compile(
        r'inglés?\s+(?:fluido|conversacional|nativo|avanzado)\s*(?:\(obligatorio\)|obligatorio|excluyente|requerido)?'
        r'|(?:inglés?\s+)?(?:fluent|conversational|native)\s+english\s*(?:required|mandatory)?'
        r'|dominio\s+(?:del\s+)?inglés?\s+(?:fluido|avanzado|conversacional)',
        re.I), "inglés fluido requerido"),
    # Stack totalmente diferente como principal
    (re.compile(
        r'\b\.NET\b.*(?:requerido|obligatorio|excluyente|indispensable)'
        r'|(?:requerido|obligatorio|excluyente|indispensable).*\b\.NET\b',
        re.I), "stack .NET como excluyente"),
    (re.compile(
        r'\bSalesforce\b.*(?:developer|desarrollador|requerido|obligatorio)'
        r'|(?:developer|desarrollador)\s+Salesforce',
        re.I), "Salesforce como stack principal"),
]


def _check_disqualifiers(description: str) -> tuple[bool, str]:
    """Retorna (disqualified, reason). Chequea reglas duras sin IA."""
    desc = description or ""
    for pattern, reason in _DISQUALIFIERS:
        if pattern.search(desc):
            return True, reason
    return False, ""


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

        # Intentar match por id; si el modelo devolvió IDs distintos (1,2,3...) usar posición
        results_by_id = {r["id"]: r for r in results if isinstance(r, dict) and "id" in r}
        id_match_count = sum(1 for job in batch if job["id"] in results_by_id)
        use_position = id_match_count == 0 and len(results) == len(batch)
        if use_position:
            logger.warning("  Batch %d: IDs no coinciden — usando match por posición (%d resultados).",
                           b_idx, len(results))

        con = sqlite3.connect(config.DB_PATH)
        for pos, job in enumerate(batch):
            if use_position:
                result = results[pos] if pos < len(results) else None
            else:
                result = results_by_id.get(job["id"])
            if not result:
                logger.warning("  Sin resultado para id=%d (%s)", job["id"], job["title"][:40])
                continue

            raw_score = result.get("score", 0)
            try:
                score = int(str(raw_score).strip().split()[0].rstrip('.,:;'))
            except (ValueError, IndexError):
                score = 0
            justificacion = result.get("justificacion", "Sin justificación.")

            # Hard disqualifier override — prevalece sobre el score de la IA
            disq, disq_reason = _check_disqualifiers(job.get("description", ""))
            if disq:
                score = min(score, 20)
                justificacion = f"⛔ AUTO-DESC: {disq_reason}. {justificacion}"
                logger.info("  → [%d] DESCALIFICADOR detectado: %s", job["id"], disq_reason)

            new_status = "candidate" if score >= config.SCORE_THRESHOLD else "scored"

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
