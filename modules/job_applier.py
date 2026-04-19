"""
job_applier.py — Módulo 4: Automatización de postulaciones LinkedIn Easy Apply.

Usa Selenium (puro Python, sin DLLs) para:
  1. Hacer login en LinkedIn
  2. Navegar a cada oferta candidata con cover letter generada
  3. Completar el formulario Easy Apply con los datos de Alex
  4. Manejar preguntas inesperadas con Groq en tiempo real
  5. Registrar resultado (aplicado/error/skip) en SQLite
"""

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementNotInteractableException, StaleElementReferenceException,
)
from webdriver_manager.chrome import ChromeDriverManager

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from modules.cv_personalizer import answer_unexpected_question

logger = logging.getLogger(__name__)

WAIT = 8   # segundos máximos de espera para elementos


# ─── Base de datos ─────────────────────────────────────────────────────────────
def _update_job_status(job_id: int, status: str, error_msg: str = "") -> None:
    con = sqlite3.connect(config.DB_PATH)
    con.execute(
        "UPDATE jobs SET status = ?, application_date = ?, error_message = ? WHERE id = ?",
        (status, datetime.now().isoformat(), error_msg, job_id),
    )
    con.commit()
    con.close()


def _load_form_answers(job_id: int) -> dict:
    answers_file = config.COVER_LETTERS_DIR / f"{job_id}_form_answers.json"
    if answers_file.exists():
        return json.loads(answers_file.read_text(encoding="utf-8"))
    return {}


# ─── Driver ────────────────────────────────────────────────────────────────────
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
    driver.implicitly_wait(3)
    return driver


# ─── Login ─────────────────────────────────────────────────────────────────────
def linkedin_login(driver: webdriver.Chrome) -> bool:
    """
    Hace login en LinkedIn con las credenciales del .env.
    Retorna True si el login fue exitoso.
    """
    if not config.LINKEDIN_EMAIL or not config.LINKEDIN_PASSWORD:
        logger.error("Credenciales de LinkedIn no configuradas en .env")
        return False

    logger.info("Iniciando sesión en LinkedIn...")
    try:
        driver.get("https://www.linkedin.com/login")
        wait = WebDriverWait(driver, WAIT)

        wait.until(EC.presence_of_element_located((By.ID, "username")))
        driver.find_element(By.ID, "username").send_keys(config.LINKEDIN_EMAIL)
        time.sleep(0.5)
        driver.find_element(By.ID, "password").send_keys(config.LINKEDIN_PASSWORD)
        time.sleep(0.5)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(4)

        # Verificar login exitoso
        current_url = driver.current_url
        if "feed" in current_url or "mynetwork" in current_url or "jobs" in current_url:
            logger.info("  ✓ Login exitoso.")
            return True

        # Detectar CAPTCHA o verificación
        if "checkpoint" in current_url or "challenge" in current_url:
            logger.warning("Verificación adicional requerida. Esperando 60s para resolución manual...")
            time.sleep(60)
            current_url = driver.current_url
            return "feed" in current_url or "mynetwork" in current_url

        logger.error("  ✗ Login fallido. Verifica credenciales.")
        return False

    except TimeoutException:
        logger.error("Timeout durante el login.")
        return False
    except Exception as exc:
        logger.error("Error inesperado durante login: %s", exc)
        return False


# ─── Helpers de formulario ─────────────────────────────────────────────────────
def _fill_input(el, value: str) -> bool:
    """Limpia y rellena un campo de texto."""
    try:
        el.clear()
        el.send_keys(str(value))
        return True
    except (ElementNotInteractableException, StaleElementReferenceException):
        return False


def _handle_label(driver: webdriver.Chrome, label_el, form_answers: dict, job_dict: dict) -> None:
    """Intenta responder el campo asociado a un label."""
    try:
        label_text = label_el.text.strip().lower()
    except StaleElementReferenceException:
        return

    # Mapeo label → respuesta pre-generada
    answer_map = {
        "por qué":       form_answers.get("por_que_interes", ""),
        "why":           form_answers.get("por_que_interes", ""),
        "años de exp":   form_answers.get("anos_experiencia_general", "2"),
        "years of exp":  form_answers.get("anos_experiencia_general", "2"),
        "python":        form_answers.get("anos_experiencia_python", "1"),
        "php":           form_answers.get("anos_experiencia_php", "2"),
        "javascript":    form_answers.get("anos_experiencia_javascript", "2"),
        "sql":           form_answers.get("anos_experiencia_sql", "2"),
        "inglés":        form_answers.get("nivel_ingles", "Intermedio"),
        "english":       form_answers.get("nivel_ingles", "Intermedio"),
        "disponibilidad":form_answers.get("disponibilidad", "Inmediata"),
        "availability":  form_answers.get("disponibilidad", "Inmediata"),
        "pretensión":    form_answers.get("pretension_salarial", "A convenir"),
        "salary":        form_answers.get("pretension_salarial", "A convenir"),
        "remoto":        form_answers.get("trabajo_remoto", "Sí"),
        "remote":        form_answers.get("trabajo_remoto", "Yes"),
        "fortaleza":     form_answers.get("fortaleza_principal", ""),
        "empresa":       form_answers.get("por_que_empresa", ""),
        "logro":         form_answers.get("mayor_logro", ""),
    }

    answer = ""
    for keyword, val in answer_map.items():
        if keyword in label_text and val:
            answer = str(val)
            break

    # Si no hay respuesta mapeada, consultar a Groq
    if not answer and label_text:
        answer = answer_unexpected_question(label_text, job_dict)
        logger.info("  Groq respondió pregunta inesperada: '%s'", label_text[:50])

    if not answer:
        return

    # Intentar rellenar el input asociado al label
    for_id = label_el.get_attribute("for")
    if for_id:
        try:
            inp = driver.find_element(By.ID, for_id)
            tag = inp.tag_name.lower()
            if tag == "select":
                sel = Select(inp)
                try:
                    sel.select_by_visible_text(answer)
                except Exception:
                    pass
            else:
                _fill_input(inp, answer)
            return
        except NoSuchElementException:
            pass

    # Fallback: buscar input/textarea visible cercano
    for sel in ["input[type='text']", "input[type='number']", "textarea"]:
        try:
            inputs = driver.find_elements(By.CSS_SELECTOR, sel)
            for inp in inputs:
                if inp.is_displayed() and not inp.get_attribute("value"):
                    _fill_input(inp, answer)
                    return
        except Exception:
            continue


# ─── Modal Easy Apply ──────────────────────────────────────────────────────────
def process_easy_apply_modal(driver: webdriver.Chrome, job_dict: dict) -> bool:
    """
    Procesa el modal de Easy Apply paso a paso.
    Retorna True si la postulación fue enviada.
    """
    form_answers = _load_form_answers(job_dict["id"])
    wait = WebDriverWait(driver, WAIT)
    max_steps = 10

    for step in range(max_steps):
        time.sleep(1.5)

        # Verificar si el modal sigue abierto
        modals = driver.find_elements(By.CSS_SELECTOR, "div.jobs-easy-apply-modal")
        if not modals:
            logger.info("  Modal cerrado.")
            return False

        # Rellenar labels visibles
        labels = driver.find_elements(By.CSS_SELECTOR, "label.artdeco-text-input--label")
        for label in labels:
            try:
                if label.is_displayed():
                    _handle_label(driver, label, form_answers, job_dict)
            except StaleElementReferenceException:
                continue

        # Cargar cover letter si hay textarea de motivación vacío
        try:
            textareas = driver.find_elements(
                By.CSS_SELECTOR, "textarea.jobs-easy-apply-form-element__textarea"
            )
            for ta in textareas:
                if ta.is_displayed() and not ta.get_attribute("value").strip():
                    if job_dict.get("cover_letter_path"):
                        cl_path = Path(job_dict["cover_letter_path"])
                        if cl_path.exists():
                            ta.clear()
                            ta.send_keys(cl_path.read_text(encoding="utf-8")[:3000])
                            logger.info("  ✓ Cover letter cargada.")
        except (NoSuchElementException, StaleElementReferenceException):
            pass

        # Buscar botón de acción (Siguiente → Revisar → Enviar)
        action_taken = False
        for aria_label in [
            "Continuar al siguiente paso", "Continue to next step",
            "Revisar su solicitud",        "Review your application",
        ]:
            try:
                btn = driver.find_element(
                    By.CSS_SELECTOR, f"button[aria-label='{aria_label}']"
                )
                if btn.is_enabled():
                    btn.click()
                    logger.debug("  → Paso %d: '%s'", step + 1, aria_label)
                    action_taken = True
                    break
            except NoSuchElementException:
                continue

        if action_taken:
            continue

        # Botón de envío final
        for aria_label in ["Enviar solicitud", "Submit application"]:
            try:
                btn = driver.find_element(
                    By.CSS_SELECTOR, f"button[aria-label='{aria_label}']"
                )
                if btn.is_enabled():
                    btn.click()
                    time.sleep(2)
                    logger.info("  ✅ Solicitud enviada.")
                    return True
            except NoSuchElementException:
                continue

        logger.warning("  Sin botón de acción encontrado en paso %d.", step + 1)
        break

    return False


# ─── Aplicación a una oferta ───────────────────────────────────────────────────
def apply_to_job(driver: webdriver.Chrome, job_dict: dict) -> str:
    """
    Intenta aplicar a una oferta específica.
    Retorna: 'applied', 'skip', 'error'
    """
    logger.info("  → Navegando a: %s", job_dict["url"])
    try:
        driver.get(job_dict["url"])
        time.sleep(3)

        # Buscar botón Easy Apply
        easy_apply_btn = None
        for sel in [
            "button.jobs-apply-button--top-card",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='Solicitud sencilla']",
            ".jobs-s-apply button",
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                easy_apply_btn = els[0]
                break

        if not easy_apply_btn:
            logger.info("  ✗ Sin botón Easy Apply. Saltando.")
            return "skip"

        btn_text = easy_apply_btn.text.lower()
        if "applied" in btn_text or "aplicado" in btn_text:
            logger.info("  ✗ Ya aplicado anteriormente. Saltando.")
            return "skip"

        if not easy_apply_btn.is_enabled():
            logger.info("  ✗ Botón deshabilitado. Saltando.")
            return "skip"

        easy_apply_btn.click()
        time.sleep(2)

        success = process_easy_apply_modal(driver, job_dict)
        return "applied" if success else "error"

    except TimeoutException:
        logger.error("  Timeout navegando a la oferta.")
        return "error"
    except Exception as exc:
        logger.error("  Error inesperado: %s", exc)
        return "error"


# ─── Runner principal ──────────────────────────────────────────────────────────
def run_applications(max_apps: int = config.MAX_APPLICATIONS_PER_RUN) -> dict:
    """
    Ejecuta las postulaciones para las ofertas candidatas con cover letter lista.
    Retorna dict con contadores: applied, skip, error.
    """
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    jobs = con.execute(
        """SELECT * FROM jobs
           WHERE status = 'candidate' AND cover_letter_path IS NOT NULL
           ORDER BY score DESC LIMIT ?""",
        (max_apps,),
    ).fetchall()
    con.close()

    if not jobs:
        logger.info("No hay ofertas listas para postular.")
        return {"applied": 0, "skip": 0, "error": 0}

    counters = {"applied": 0, "skip": 0, "error": 0}
    logger.info("Postulando a %d ofertas...", len(jobs))

    driver = _build_driver()
    try:
        if not linkedin_login(driver):
            logger.error("No se pudo iniciar sesión. Abortando postulaciones.")
            return counters

        for job in jobs:
            job_dict = dict(job)
            logger.info(
                "\n[%d] %s @ %s (score: %d)",
                job_dict["id"], job_dict["title"],
                job_dict["company"], job_dict["score"],
            )

            result = apply_to_job(driver, job_dict)
            counters[result] += 1
            _update_job_status(job_dict["id"], result)

            label = {"applied": "✅ APLICADO", "skip": "⏭ Saltado", "error": "❌ Error"}[result]
            logger.info("  Resultado: %s", label)
            time.sleep(config.APPLICATION_WAIT)

    finally:
        driver.quit()

    logger.info(
        "\nPostulaciones completadas — Aplicadas: %d | Saltadas: %d | Errores: %d",
        counters["applied"], counters["skip"], counters["error"],
    )
    return counters


# ─── Punto de entrada directo ──────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    result = run_applications()
    print(f"\nResultados: {result}")
