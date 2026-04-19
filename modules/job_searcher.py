"""
job_searcher.py — Módulo 1: Scraper de ofertas de trabajo en LinkedIn.

Usa Selenium (puro Python, sin DLLs) con ChromeDriver para buscar ofertas
con keywords configurables, extrae los datos relevantes y los guarda en SQLite.
"""

import logging
import random
import sqlite3
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ─── Base de datos ─────────────────────────────────────────────────────────────
def init_db() -> None:
    """Crea la tabla de ofertas si no existe y agrega columnas nuevas si faltan."""
    con = sqlite3.connect(config.DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            title               TEXT NOT NULL,
            company             TEXT,
            location            TEXT,
            description         TEXT,
            url                 TEXT UNIQUE,
            date_posted         TEXT,
            date_found          TEXT NOT NULL,
            score               INTEGER,
            score_justification TEXT,
            status              TEXT DEFAULT 'found',
            cover_letter_path   TEXT,
            application_date    TEXT,
            error_message       TEXT,
            source              TEXT DEFAULT 'linkedin'
        )
    """)
    # Migración: agregar source si la tabla ya existe sin esa columna
    cols = [r[1] for r in con.execute("PRAGMA table_info(jobs)").fetchall()]
    if "source" not in cols:
        con.execute("ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT 'linkedin'")
    con.commit()
    con.close()
    logger.info("Base de datos inicializada: %s", config.DB_PATH)


def save_job(job: dict) -> bool:
    """
    Inserta una oferta en la BD.
    Retorna True si fue insertada, False si ya existía (URL o título+empresa duplicados).
    """
    con = sqlite3.connect(config.DB_PATH)
    try:
        exists = con.execute(
            "SELECT 1 FROM jobs WHERE title = ? AND company = ?",
            (job["title"], job["company"]),
        ).fetchone()
        if exists:
            return False

        cursor = con.execute("""
            INSERT OR IGNORE INTO jobs
                (title, company, location, description, url, date_posted, date_found, source)
            VALUES
                (:title, :company, :location, :description, :url, :date_posted, :date_found, :source)
        """, {**job, "source": job.get("source", "linkedin")})
        inserted = cursor.rowcount > 0
        con.commit()
        return inserted
    finally:
        con.close()


# ─── Driver ────────────────────────────────────────────────────────────────────
def _build_driver() -> webdriver.Chrome:
    """Construye y retorna el driver de Chrome con las opciones configuradas."""
    options = Options()
    if config.BROWSER_HEADLESS:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=es-CL,es")
    options.add_argument("--window-size=1280,900")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(2)   # bajo para scraping (selectors con fallback)
    return driver


# ─── Login ─────────────────────────────────────────────────────────────────────
def _linkedin_login(driver: webdriver.Chrome) -> bool:
    """Login en LinkedIn antes de buscar. Retorna True si fue exitoso."""
    if not config.LINKEDIN_EMAIL or not config.LINKEDIN_PASSWORD:
        logger.warning("Sin credenciales LinkedIn — resultados pueden ser limitados.")
        return False

    logger.info("Iniciando sesión en LinkedIn...")
    try:
        driver.get("https://www.linkedin.com/login")

        # Esperar activamente hasta que #username aparezca (máx 15s)
        username_el = None
        for _ in range(15):
            els = driver.find_elements(By.ID, "username")
            if els:
                username_el = els[0]
                break
            time.sleep(1)

        if not username_el:
            # Puede que LinkedIn haya redirigido a otra variante del login
            logger.warning("  #username no encontrado. URL: %s | Title: %s",
                           driver.current_url[:60], driver.title[:40])
            return False

        username_el.send_keys(config.LINKEDIN_EMAIL)
        time.sleep(0.4)
        driver.find_element(By.ID, "password").send_keys(config.LINKEDIN_PASSWORD)
        time.sleep(0.4)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(5)

        url = driver.current_url
        if any(x in url for x in ("feed", "mynetwork", "jobs", "checkpoint")):
            logger.info("  Login exitoso.")
            return True

        logger.warning("  Login posiblemente fallido (URL: %s)", url[:60])
        return False

    except Exception as exc:
        logger.error("Error durante login: %s", exc)
        return False


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _get_text(driver: webdriver.Chrome, selectors: list[str], default: str = "") -> str:
    """Intenta cada selector y retorna el texto del primero que encuentre."""
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                return text
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    return default


def _scroll_down(driver: webdriver.Chrome, times: int = 1) -> None:
    """Hace scroll para forzar carga lazy de tarjetas."""
    for _ in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.3)
    driver.execute_script("window.scrollTo(0, 0);")


# ─── URLs ya guardadas en BD ───────────────────────────────────────────────────
def _get_existing_urls() -> set:
    """Retorna el set de URLs ya guardadas en la BD."""
    try:
        con = sqlite3.connect(config.DB_PATH)
        rows = con.execute("SELECT url FROM jobs WHERE url IS NOT NULL").fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ─── Filtro de relevancia ──────────────────────────────────────────────────────
# Palabras que deben aparecer en el título para considerarlo tech
_TECH_KEYWORDS = {
    "desarrollador", "developer", "programador", "programmer",
    "ingeniero", "engineer", "analista programador", "analista",
    "software", "fullstack", "full stack", "backend", "back-end",
    "frontend", "front-end", "web", "python", "php", "javascript",
    "automatización", "automation", "devops", "data", "sistemas",
    "soporte técnico", "técnico ti",
    "junior", "semi-senior",
}
_OFFPROFILE_KEYWORDS = {
    "brigadista", "geotécnico", "mecánico", "subjefe", "jefe de obra",
    "administrador de obra", "retail", "vendedor", "ejecutivo comercial",
    "kam ", "key account", "logística", "logistic", "conductor",
    "operario", "minería", "minero", "electricista", "bodeguero",
    "cajero", "enfermero", "médico", "doctor", "abogado",
    "práctica profesional", "practica profesional", "intern ", "pasantía",
    "estudiante en práctica", "alumno en práctica", "alumno/a en práctica",
    "estudiante de práctica", "en práctica (", "práctica (",
}

def _is_tech_job(title: str) -> bool:
    """Retorna True si el título sugiere un cargo de tecnología/software."""
    t = title.lower()
    # Descartar si contiene palabras claramente fuera del rubro
    if any(kw in t for kw in _OFFPROFILE_KEYWORDS):
        return False
    # Aceptar si contiene alguna palabra tech
    if any(kw in t for kw in _TECH_KEYWORDS):
        return True
    # Si no hay señal clara, aceptar igual (el scorer lo filtrará)
    return True


# ─── Scraper por keyword ────────────────────────────────────────────────────────
def scrape_jobs_for_keyword(
    driver: webdriver.Chrome,
    keyword: str,
    max_jobs: int = config.MAX_JOBS_PER_KEYWORD,
) -> list[dict]:
    """
    Busca ofertas en LinkedIn para un keyword dado.
    Retorna lista de dicts con los datos de cada oferta.
    """
    jobs = []
    search_url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={keyword.replace(' ', '%20')}"
        f"&geoId={config.LINKEDIN_GEO_ID}"
        "&f_E=2%2C3"       # Entry level + Associate (sin pasantías)
        "&f_TPR=r604800"   # última semana
        "&sortBy=DD"       # más recientes primero
    )

    logger.info("Buscando '%s'...", keyword)
    try:
        driver.get(search_url)
        time.sleep(1.5)
        _scroll_down(driver)
    except Exception as exc:
        logger.warning("Error cargando resultados para '%s': %s", keyword, exc)
        return jobs

    # Selector correcto para LinkedIn 2025
    all_cards = driver.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id]")
    logger.info("  %d tarjetas encontradas para '%s'", len(all_cards), keyword)

    # ── Pre-filtrar en UNA sola llamada JS (sin loop Selenium) ──────────────────
    existing_urls = _get_existing_urls()

    card_data = driver.execute_script("""
        return Array.from(document.querySelectorAll('li[data-occludable-job-id]'))
            .slice(0, arguments[0])
            .map(el => ({
                id:      el.getAttribute('data-occludable-job-id'),
                viewed:  el.innerHTML.toLowerCase().includes('viewed') ||
                         el.className.toLowerCase().includes('viewed'),
                classes: el.className
            }));
    """, max_jobs)

    cards_by_id = {c.get_attribute("data-occludable-job-id"): c for c in all_cards[:max_jobs]
                   if c.get_attribute("data-occludable-job-id")}

    cards_to_process = []
    skipped = 0
    for item in card_data:
        job_id = item.get("id")
        if not job_id:
            continue
        url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        if item.get("viewed"):
            logger.debug("  Saltando vista: id=%s", job_id)
            skipped += 1
            continue
        if url in existing_urls:
            logger.debug("  Saltando ya guardada: id=%s", job_id)
            skipped += 1
            continue
        card = cards_by_id.get(job_id)
        if card:
            cards_to_process.append((card, job_id, url))

    logger.info("  %d nuevas a procesar (%d saltadas)",
                len(cards_to_process), skipped)

    seen_ids = set()
    consecutive_errors = 0

    for i, (card, job_id, job_url) in enumerate(cards_to_process):
        # Pausa por errores consecutivos
        if consecutive_errors >= 3:
            logger.warning("  3 errores seguidos — pausando 15s...")
            time.sleep(15)
            consecutive_errors = 0

        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # Click y espera mínima
        loaded = False
        for attempt in range(2):
            try:
                card.click()
                time.sleep(random.uniform(0.5, 1.0))
                loaded = True
                break
            except (StaleElementReferenceException, Exception) as exc:
                logger.debug("  Tarjeta %d intento %d: %s", i + 1, attempt + 1, exc)
                time.sleep(0.5)

        if not loaded:
            consecutive_errors += 1
            logger.warning("  Tarjeta %d: no se pudo cargar tras 3 intentos.", i + 1)
            continue

        try:
            # Selectores validados en producción
            title = _get_text(driver, [
                "h1.t-24",
                "h1.job-details-jobs-unified-top-card__job-title",
                ".job-details-jobs-unified-top-card__job-title",
            ])
            company = _get_text(driver, [
                ".job-details-jobs-unified-top-card__company-name",
                ".job-details-jobs-unified-top-card__company-name a",
                "a.topcard__org-name-link",
            ])
            location = _get_text(driver, [
                ".job-details-jobs-unified-top-card__bullet",
                ".tvm__text--neutral",
                ".job-details-jobs-unified-top-card__primary-description-container",
            ])
            description = _get_text(driver, [
                ".jobs-description__content",
                ".jobs-description-content__text",
                "div#job-details",
            ])
            date_posted = _get_text(driver, [
                ".job-details-jobs-unified-top-card__posted-date",
                ".tvm__text--low-emphasis",
                "span.posted-time-ago__text",
            ])

            if not title:
                logger.debug("  Tarjeta %d (id=%s): sin título, saltando.", i + 1, job_id)
                consecutive_errors += 1
                continue

            # Filtrar títulos claramente fuera del perfil tech
            if not _is_tech_job(title):
                logger.info("  [%d] Saltando (no tech): %s", i + 1, title[:60])
                consecutive_errors = 0
                continue

            job = {
                "title":       title,
                "company":     company or "Empresa no especificada",
                "location":    location or config.SEARCH_LOCATION,
                "description": description[:5000],
                "url":         job_url,
                "date_posted": date_posted,
                "date_found":  datetime.now().isoformat(),
            }
            jobs.append(job)
            consecutive_errors = 0
            logger.info("  [%d] %s @ %s", i + 1, title[:50], company[:30])

        except Exception as exc:
            consecutive_errors += 1
            logger.warning("  Error tarjeta %d: %s", i + 1, exc)
            continue

    return jobs


# ─── Runner principal ──────────────────────────────────────────────────────────
def run_search() -> int:
    """
    Ejecuta la búsqueda para todos los keywords configurados.
    Retorna el total de ofertas nuevas guardadas.
    """
    init_db()
    total_new = 0
    driver = _build_driver()

    try:
        _linkedin_login(driver)

        for keyword in config.SEARCH_KEYWORDS:
            jobs = scrape_jobs_for_keyword(driver, keyword)
            for job in jobs:
                if save_job(job):
                    total_new += 1
                    logger.info("  Nueva: %s @ %s", job["title"], job["company"])
                else:
                    logger.debug("  Duplicada: %s", job["url"])
            time.sleep(1)   # pausa entre keywords

    finally:
        driver.quit()

    logger.info("Busqueda completada. %d ofertas nuevas guardadas.", total_new)
    return total_new


# ─── Punto de entrada directo ──────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    result = run_search()
    print(f"\nOfertas nuevas encontradas: {result}")
