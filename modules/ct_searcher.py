"""
ct_searcher.py — Scraper de ofertas en Computrabajo Chile.

Estrategia rápida: extrae todos los datos desde la página de resultados con JS
(una sola llamada), sin visitar cada oferta individualmente.
Solo visita la oferta si la descripción capturada es demasiado corta.
"""

import logging
import random
import time
from datetime import datetime
from urllib.parse import quote_plus

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
from modules.job_searcher import save_job, _is_tech_job, _get_existing_urls, init_db

logger = logging.getLogger(__name__)



def _build_driver() -> webdriver.Chrome:
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
    driver.implicitly_wait(2)
    return driver


def _wait_for_el(driver: webdriver.Chrome, selectors: list[str], timeout: float = 8.0):
    """Espera hasta timeout segundos a que aparezca alguno de los selectores."""
    driver.implicitly_wait(0)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            for sel in selectors:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    return els[0]
            time.sleep(0.4)
    finally:
        driver.implicitly_wait(2)
    return None


def _ct_login(driver: webdriver.Chrome) -> bool:
    if not config.CT_EMAIL or not config.CT_PASSWORD:
        logger.error("Sin credenciales CT en .env — abortando.")
        return False

    logger.info("Iniciando sesión en Computrabajo...")
    try:
        # La página de login es candidato.cl.computrabajo.com
        driver.get("https://candidato.cl.computrabajo.com")

        # ── Paso 1: campo Email + botón "Continuar" ───────────────────────────
        email_el = _wait_for_el(driver, ["#Email", "input[name='Email']"], timeout=8.0)
        if not email_el:
            logger.error("  CT login: campo Email no encontrado. URL: %s", driver.current_url[:80])
            return False

        email_el.clear()
        email_el.send_keys(config.CT_EMAIL)
        time.sleep(0.3)

        continuar_btn = _wait_for_el(driver, ["#continueWithMailButton"], timeout=3.0)
        if not continuar_btn:
            logger.error("  CT login: botón Continuar no encontrado.")
            return False
        continuar_btn.click()

        # ── Paso 2: campo Password + link "Iniciar sesión" (es un <a>) ────────
        pass_el = _wait_for_el(driver, ["#password", "input[name='Password']"], timeout=6.0)
        if not pass_el:
            logger.error("  CT login: campo Password no apareció.")
            return False

        pass_el.clear()
        pass_el.send_keys(config.CT_PASSWORD)
        time.sleep(0.2)

        # El botón submit es <a id="btnSubmitPass">
        submit_el = _wait_for_el(driver, ["#btnSubmitPass", "a[btn-submit]"], timeout=3.0)
        if not submit_el:
            logger.error("  CT login: botón Iniciar sesión no encontrado.")
            return False
        submit_el.click()

        # ── Confirmar login: esperar que la URL cambie a candidato o cl.computrabajo ──
        deadline = time.time() + 8
        while time.time() < deadline:
            time.sleep(0.4)
            url = driver.current_url
            if "candidato.cl.computrabajo.com" in url and "login" not in url and "Account" not in url:
                logger.info("  Login CT exitoso. URL: %s", url[:60])
                return True
            if "cl.computrabajo.com" in url and "Account" not in url:
                logger.info("  Login CT exitoso. URL: %s", url[:60])
                return True

        logger.error("  Login CT fallido. URL final: %s", driver.current_url[:80])
        return False

    except Exception as exc:
        logger.error("Error login CT: %s", exc)
        return False


# ─── Extracción masiva con JS ──────────────────────────────────────────────────
_EXTRACT_JS = """
return Array.from(document.querySelectorAll(arguments[0])).slice(0, arguments[1]).map(el => {
    // título + URL
    var linkEl = el.querySelector('h2 a, h3 a, .title a, a.js_o, a[href*="oferta"], a[href*="empleo"]');
    if (!linkEl) linkEl = el.querySelector('a[href]');
    var href  = linkEl ? (linkEl.getAttribute('href') || '') : '';
    var title = linkEl ? linkEl.textContent.trim() : '';
    if (!title) {
        var h = el.querySelector('h2, h3, .title');
        if (h) title = h.textContent.trim();
    }

    // empresa — selector confirmado por debug HTML
    var compEl = el.querySelector('a[offer-grid-article-company-url]');
    var company = compEl ? compEl.textContent.trim() : '';
    // fallback: empresa anónima en el <p> de empresa
    if (!company) {
        var pEmp = el.querySelector('p.dFlex.vm_fx');
        if (pEmp) company = pEmp.textContent.trim();
    }

    // ubicación — está en p.fs16.fc_base.mt5 > span.mr10
    var locEl = el.querySelector('p.fs16.fc_base.mt5 span.mr10');
    var location = locEl ? locEl.textContent.trim() : '';

    // descripción — CT no muestra snippet en el listing, quedará vacía
    var desc = '';

    // vista? — skip si tiene el tag "Vista" visible
    var vistaTag = el.querySelector('span[viewed-offer-tag]');
    var vista = vistaTag ? !vistaTag.classList.contains('hide') : false;

    // fecha — CT usa p.fs13.fc_aux
    var dateEl = el.querySelector('p.fs13.fc_aux');
    var date = dateEl ? dateEl.textContent.trim() : '';

    return { href, title, company, location, desc, date, vista };
});
"""


def _normalize_url(href: str) -> str:
    if not href:
        return ""
    # Quitar fragment (#lc=... tracking param de CT)
    href = href.split("#")[0]
    if href.startswith("http"):
        return href
    return config.CT_BASE_URL + href



def scrape_ct_for_keyword(
    driver: webdriver.Chrome,
    keyword: str,
    max_jobs: int = config.MAX_JOBS_PER_KEYWORD,
) -> list[dict]:
    jobs = []
    existing_urls = _get_existing_urls()

    # CT Chile — probar formatos de URL de búsqueda
    slug = keyword.replace(" ", "-")
    search_urls = [
        f"{config.CT_BASE_URL}/trabajo/?q={quote_plus(keyword)}&l=Santiago+de+Chile",
        f"{config.CT_BASE_URL}/empleos-de-{quote_plus(slug)}?q={quote_plus(keyword)}",
        f"{config.CT_BASE_URL}/trabajo-de-{quote_plus(slug)}",
        f"{config.CT_BASE_URL}/buscar?q={quote_plus(keyword)}&where=Santiago+de+Chile",
    ]

    logger.info("CT buscando '%s'...", keyword)
    loaded = False
    for url in search_urls:
        try:
            driver.get(url)
            time.sleep(1.5)
            # Verificar si hay resultados o al menos la página cargó bien
            if driver.find_elements(By.CSS_SELECTOR, "article, .offerList, #offers, .offer"):
                loaded = True
                logger.debug("  CT URL OK: %s", url[:80])
                break
            logger.debug("  CT URL sin resultados: %s | title: %s", url[:60], driver.title[:40])
        except Exception as exc:
            logger.warning("  CT error URL %s: %s", url[:60], exc)

    if not loaded:
        logger.info("  CT: sin resultados para '%s' (título: %s)", keyword, driver.title[:50])
        return jobs

    # Probar selectores de tarjeta hasta encontrar uno con resultados
    card_sel = None
    driver.implicitly_wait(0)
    for sel in [
        "article.box_offer", "article[data-id]", "div.js_offer",
        "li.offer", ".offerList article", "div.offerList article",
        "#offers article", ".offers article", "article",
        "div[class*='offer']", "li[class*='offer']",
    ]:
        if driver.find_elements(By.CSS_SELECTOR, sel):
            card_sel = sel
            break
    driver.implicitly_wait(2)

    if not card_sel:
        logger.info("  CT: sin tarjetas para '%s' | URL: %s | título: %s",
                    keyword, driver.current_url[:60], driver.title[:40])
        return jobs

    # ── Extracción masiva en una sola llamada JS ──────────────────────────────
    raw_items = driver.execute_script(_EXTRACT_JS, card_sel, max_jobs)
    logger.info("  CT: %d items extraídos para '%s'", len(raw_items), keyword)

    for item in raw_items:
        title = (item.get("title") or "").strip()
        href  = _normalize_url(item.get("href") or "")

        if not title or not href:
            continue
        if item.get("vista"):
            logger.debug("  CT: saltando vista: %s", title[:50])
            continue
        if href in existing_urls:
            logger.debug("  CT: saltando ya guardada: %s", href[:60])
            continue
        if not _is_tech_job(title):
            logger.info("  CT: saltando (no tech): %s", title[:60])
            continue

        company  = (item.get("company")  or "Empresa no especificada").strip()
        location = (item.get("location") or "Santiago, Chile").strip()
        date     = (item.get("date")     or "").strip()

        # CT no muestra descripción en el listing — se deja vacía para que el scorer use título+empresa
        desc = ""

        job = {
            "title":       title,
            "company":     company,
            "location":    location,
            "description": desc,
            "url":         href,
            "date_posted": date,
            "date_found":  datetime.now().isoformat(),
            "source":      "computrabajo",
        }
        jobs.append(job)
        existing_urls.add(href)
        logger.info("  CT [+] %s @ %s", title[:50], company[:30])

    return jobs


def run_ct_search() -> int:
    """Busca en Computrabajo para todos los keywords. Retorna total nuevas guardadas."""
    init_db()
    total_new = 0
    driver = _build_driver()

    try:
        if not _ct_login(driver):
            logger.error("CT: login fallido — se omite búsqueda en Computrabajo.")
            return 0

        for keyword in config.CT_SEARCH_KEYWORDS:
            jobs = scrape_ct_for_keyword(driver, keyword)
            for job in jobs:
                if save_job(job):
                    total_new += 1
                    logger.info("  CT nueva: %s @ %s", job["title"], job["company"])
                else:
                    logger.debug("  CT duplicada: %s", job["url"])
            time.sleep(random.uniform(4, 8))  # pausa humana entre keywords

    finally:
        driver.quit()

    logger.info("CT búsqueda completada. %d ofertas nuevas guardadas.", total_new)
    return total_new


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    result = run_ct_search()
    print(f"\nOfertas CT nuevas: {result}")
