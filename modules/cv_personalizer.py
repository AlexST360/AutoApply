"""
cv_personalizer.py — Módulo 3: Personalización de materiales de postulación.

Usa Groq API (llama-3.3-70b-versatile) vía cliente httpx nativo para generar:
  1. Cover letter personalizada en español
  2. Sugerencias de ajuste al resumen profesional del CV
  3. Respuestas a preguntas típicas de formularios LinkedIn
"""

import json
import logging
import re
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from modules.groq_client import get_client

# ─── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ─── CV ────────────────────────────────────────────────────────────────────────
def _load_cv() -> str:
    try:
        return config.CV_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "CV no disponible."

CV_TEXT = _load_cv()

# ─── Cliente Groq ──────────────────────────────────────────────────────────────
client = get_client()

SYSTEM_BASE = """Eres un experto en redacción profesional y recursos humanos para el mercado
laboral tecnológico chileno. Generas materiales de postulación en español formal pero cercano,
adaptados al perfil del candidato y la oferta específica.

El candidato es Alex Ocampo Segundo:
- Desarrollador Full Stack / Automatización de Procesos
- Stack principal: Python, PHP, JavaScript, MySQL, Selenium/Playwright
- Experiencia: Fuentes Bros (8 meses, plataforma interna MVC PHP MySQL),
  Fiabilis Consulting (3 meses, automatización Python)
- Educación: Analista Programador INACAP 2022-2025
- Ubicación: Santiago, Chile
- Tono: profesional pero directo, sin exageraciones"""


def _extract_json(raw: str) -> str:
    """
    Extrae el primer bloque JSON válido de una respuesta del modelo.
    Maneja: bloques ```json ... ```, objetos { } sueltos y texto previo/posterior.
    """
    # Quitar bloque markdown si existe
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.split("```")[0]

    # Intentar extraer el primer objeto JSON con regex como fallback
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        return match.group(0)

    return raw.strip()


def _system_with_cv() -> str:
    """Retorna el system prompt con el CV incluido."""
    return f"{SYSTEM_BASE}\n\nCV COMPLETO:\n{CV_TEXT}"


# ─── Generadores individuales ──────────────────────────────────────────────────

def generate_cover_letter(job: dict) -> str:
    """Genera una cover letter personalizada para la oferta."""
    prompt = f"""Genera una carta de presentación profesional para Alex postulando a esta oferta.

OFERTA:
Título: {job['title']}
Empresa: {job['company']}
Ubicación: {job['location']}
Descripción: {job['description'][:2000]}

Requisitos de la carta:
- Extensión: 3-4 párrafos (250-350 palabras)
- Tono: profesional, directo, sin frases cliché
- Mencionar explícitamente la empresa y el cargo
- Destacar 2-3 logros o proyectos relevantes del CV
- Cierre con disponibilidad e interés concreto
- NO usar frases como "Me complace", "Apasionado", "Dinámico"
- Formato: texto listo para copiar, sin encabezados formales de carta

Genera solo el cuerpo del texto de la carta, comenzando con el saludo."""

    response = client.chat_completions_create(
        model=config.GROQ_MODEL,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": _system_with_cv()},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def generate_cv_adjustments(job: dict) -> str:
    """Genera sugerencias de ajuste al resumen profesional del CV."""
    prompt = f"""Analiza esta oferta y sugiere cómo Alex debería ajustar su resumen profesional
para maximizar su match con el puesto.

OFERTA:
Título: {job['title']}
Empresa: {job['company']}
Descripción: {job['description'][:2000]}

Entrega:
1. Versión ajustada del resumen (máximo 4 líneas)
2. Lista de 3-5 keywords de la oferta que Alex debería enfatizar
3. Una habilidad o aspecto del CV que debería destacar más para este rol

Responde en formato JSON:
{{
  "resumen_ajustado": "...",
  "keywords": ["...", "..."],
  "enfasis": "..."
}}"""

    response = client.chat_completions_create(
        model=config.GROQ_MODEL,
        max_tokens=800,
        messages=[
            {"role": "system", "content": _system_with_cv()},
            {"role": "user", "content": prompt},
        ],
    )
    raw = _extract_json(response.choices[0].message.content)
    return raw


def generate_form_answers(job: dict) -> dict:
    """
    Genera respuestas para preguntas típicas de formularios LinkedIn.
    Retorna dict con pregunta→respuesta.
    """
    prompt = f"""Para esta oferta, genera respuestas concretas y honestas a las preguntas
más comunes en formularios de LinkedIn Easy Apply.

OFERTA:
Título: {job['title']}
Empresa: {job['company']}
Descripción: {job['description'][:2000]}

Genera respuestas para TODAS estas preguntas en formato JSON:
{{
  "por_que_interes": "...",
  "anos_experiencia_general": "...",
  "anos_experiencia_python": "...",
  "anos_experiencia_php": "...",
  "anos_experiencia_javascript": "...",
  "anos_experiencia_sql": "...",
  "nivel_ingles": "...",
  "disponibilidad": "...",
  "pretension_salarial": "...",
  "por_que_empresa": "...",
  "mayor_logro": "...",
  "trabajo_remoto": "...",
  "fortaleza_principal": "..."
}}

Las respuestas deben ser:
- Cortas (1-3 oraciones máximo)
- Honestas y basadas en el CV real de Alex
- En español
- Sin exageración"""

    response = client.chat_completions_create(
        model=config.GROQ_MODEL,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": _system_with_cv()},
            {"role": "user", "content": prompt},
        ],
    )

    raw = _extract_json(response.choices[0].message.content)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Error parseando respuestas del formulario, usando valores por defecto.")
        return {
            "por_que_interes": f"Me interesa el rol de {job['title']} porque se alinea con mi experiencia en desarrollo Full Stack y automatización.",
            "anos_experiencia_general": "2 años",
            "anos_experiencia_python": "1 año",
            "nivel_ingles": "Intermedio",
            "disponibilidad": "Inmediata",
        }


def answer_unexpected_question(question: str, job: dict) -> str:
    """
    Genera respuesta para una pregunta inesperada durante el formulario.
    Usado por job_applier.py en tiempo real.
    """
    prompt = f"""Durante el proceso de postulación a esta oferta apareció una pregunta inesperada.
Genera una respuesta breve, honesta y profesional.

OFERTA: {job['title']} en {job['company']}

PREGUNTA DEL FORMULARIO:
{question}

Responde directamente (sin introducción), en máximo 2-3 oraciones, en español."""

    response = client.chat_completions_create(
        model=config.GROQ_MODEL,
        max_tokens=300,
        messages=[
            {"role": "system", "content": _system_with_cv()},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


# ─── Proceso principal ─────────────────────────────────────────────────────────

def _save_cover_letter(job_id: int, job_title: str, company: str, text: str) -> Path:
    """Guarda la cover letter en disco y retorna la ruta."""
    safe_name = f"{job_id}_{company[:20]}_{job_title[:20]}".replace(" ", "_").replace("/", "-")
    filename = config.COVER_LETTERS_DIR / f"{safe_name}.txt"
    filename.write_text(text, encoding="utf-8")
    return filename


def run_personalization() -> int:
    """
    Personaliza los materiales para todas las ofertas candidatas sin cover letter.
    Retorna cantidad de ofertas procesadas.
    """
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row

    jobs = con.execute(
        "SELECT * FROM jobs WHERE status = 'candidate' AND cover_letter_path IS NULL"
    ).fetchall()

    if not jobs:
        logger.info("No hay ofertas candidatas sin personalizar.")
        con.close()
        return 0

    logger.info("Personalizando materiales para %d ofertas...", len(jobs))
    processed = 0

    for job in jobs:
        job_dict = dict(job)
        logger.info("  Personalizando: %s @ %s", job_dict["title"], job_dict["company"])

        try:
            # 1. Cover letter
            cover_letter = generate_cover_letter(job_dict)
            cl_path = _save_cover_letter(
                job_dict["id"], job_dict["title"], job_dict["company"], cover_letter
            )
            logger.info("    ✓ Cover letter guardada: %s", cl_path.name)

            # 2. Ajustes al CV
            cv_adjustments = generate_cv_adjustments(job_dict)

            # 3. Respuestas al formulario
            form_answers = generate_form_answers(job_dict)
            form_answers_json = json.dumps(form_answers, ensure_ascii=False)

            # Actualizar BD
            con.execute(
                """UPDATE jobs
                   SET cover_letter_path = ?,
                       score_justification = score_justification || '\n\n--- AJUSTES CV ---\n' || ?
                   WHERE id = ?""",
                (str(cl_path), cv_adjustments, job_dict["id"]),
            )
            answers_file = config.COVER_LETTERS_DIR / f"{job_dict['id']}_form_answers.json"
            answers_file.write_text(form_answers_json, encoding="utf-8")

            con.commit()
            processed += 1

        except RuntimeError as exc:
            logger.error("  Error de API Groq para oferta %d: %s", job_dict["id"], exc)
        except Exception as exc:
            logger.error("  Error inesperado para oferta %d: %s", job_dict["id"], exc)

    con.close()
    logger.info("Personalización completada. %d ofertas procesadas.", processed)
    return processed


# ─── Punto de entrada directo ──────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    result = run_personalization()
    print(f"\nOfertas personalizadas: {result}")
