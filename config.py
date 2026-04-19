"""
config.py — Configuración centralizada de AutoApply.
Todas las constantes, rutas y parámetros del sistema.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# ─── Rutas base ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = BASE_DIR / "outputs"
COVER_LETTERS_DIR = OUTPUTS_DIR / "cover_letters"
DASHBOARD_DIR = BASE_DIR / "dashboard"
DB_PATH = DATA_DIR / "jobs.db"
CV_PATH = DATA_DIR / "cv_alex.txt"
LOG_DIR = BASE_DIR / "logs"

# Crear directorios si no existen
for d in [DATA_DIR, OUTPUTS_DIR, COVER_LETTERS_DIR, DASHBOARD_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Credenciales ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LINKEDIN_EMAIL    = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

# ─── Computrabajo ──────────────────────────────────────────────────────────────
CT_EMAIL    = os.getenv("CT_EMAIL", "")
CT_PASSWORD = os.getenv("CT_PASSWORD", "")
CT_BASE_URL = "https://cl.computrabajo.com"
CT_SEARCH_KEYWORDS = [
    "desarrollador",
    "programador",
    "desarrollador web",
    "desarrollador PHP",
    "desarrollador Laravel",
    "desarrollador Python",
    "desarrollador full stack",
    "analista programador",
    "analista desarrollador",
    "ingeniero de software",
    "desarrollador de aplicaciones",
]

# ─── Groq API ──────────────────────────────────────────────────────────────────
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL    = "llama-3.3-70b-versatile"

# ─── OpenRouter API (fallback cuando Groq llega al límite) ────────────────────
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL    = "arcee-ai/trinity-large-preview:free"

# ─── Búsqueda de empleos ───────────────────────────────────────────────────────
SEARCH_KEYWORDS = [
    # Amplio — captura todo tipo de cargo de desarrollo
    "desarrollador",
    "programador",
    "desarrollador web",
    "desarrollador software",
    "desarrollador de aplicaciones",

    # Stack de Alex
    "desarrollador PHP",
    "desarrollador Laravel",
    "desarrollador Python",
    "desarrollador JavaScript",
    "desarrollador MySQL",

    # Full stack / backend / frontend
    "desarrollador full stack",
    "desarrollador backend",
    "desarrollador frontend",

    # Títulos reales del mercado chileno
    "analista programador",
    "analista desarrollador",
    "analista de sistemas",
    "ingeniero de software",
    "soporte y desarrollo",
]
SEARCH_LOCATION = "Chile"
# GeoId de Chile en LinkedIn (fuerza resultados dentro del país)
LINKEDIN_GEO_ID  = "104621616"
MAX_JOBS_PER_KEYWORD = 15   # máximo de ofertas a scrapear por keyword
JOBS_PAGE_WAIT = 0.8        # segundos tras click (solo para scraping)

# ─── Scoring ───────────────────────────────────────────────────────────────────
SCORE_THRESHOLD = 65   # score mínimo para considerar candidata la oferta

# ─── Aplicación ────────────────────────────────────────────────────────────────
MAX_APPLICATIONS_PER_RUN = 10   # tope de postulaciones por ejecución
APPLICATION_WAIT = 5            # segundos entre postulaciones

# ─── Playwright ────────────────────────────────────────────────────────────────
BROWSER_HEADLESS = False   # True para modo sin interfaz gráfica
BROWSER_SLOW_MO  = 100     # ms entre acciones (simula comportamiento humano)
BROWSER_TIMEOUT  = 30_000  # ms timeout general

# ─── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE = LOG_DIR / "autoapply.log"

# ─── Datos personales de Alex (para formularios) ──────────────────────────────
ALEX_DATA = {
    "nombre":       "Alex Ocampo Segundo",
    "email":        "alex.segundo.st@gmail.com",
    "telefono":     "+56930188359",
    "ubicacion":    "Santiago, Chile",
    "github":       "github.com/AlexST360",
    "anos_exp_py":  "1",
    "anos_exp_php": "2",
    "anos_exp_js":  "2",
    "anos_exp_sql": "2",
    "nivel_ingles": "Intermedio (lectura y escritura; sin conversación fluida)",
    "disponibilidad": "Inmediata",
    "modalidad":    "Presencial / Híbrido / Remoto",
    "pretension_salarial": "A convenir",
}
