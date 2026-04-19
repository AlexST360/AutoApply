"""
main.py — Orquestador principal de AutoApply.

Permite ejecutar cada módulo por separado o el pipeline completo.

Uso:
  python main.py                     # pipeline completo
  python main.py search              # solo búsqueda
  python main.py score               # solo scoring
  python main.py personalize         # solo personalización
  python main.py apply               # solo postulaciones
  python main.py tracker [cmd]       # tracker / dashboard
  python main.py tracker dashboard   # generar HTML
  python main.py tracker candidates  # ver candidatas
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar errores con caracteres Unicode en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import config

# ─── Configurar logging ────────────────────────────────────────────────────────
def setup_logging() -> None:
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=log_format,
        handlers=handlers,
    )


# ─── Validaciones ──────────────────────────────────────────────────────────────
def check_config() -> bool:
    """Verifica que la configuración básica esté completa."""
    ok = True
    if not config.GROQ_API_KEY:
        print("  ⚠ GROQ_API_KEY no configurada en .env")
        ok = False
    if not config.LINKEDIN_EMAIL or not config.LINKEDIN_PASSWORD:
        print("  ⚠ Credenciales de LinkedIn no configuradas (requeridas para apply)")
    if not config.CV_PATH.exists():
        print(f"  ⚠ CV no encontrado en {config.CV_PATH}")
    return ok


# ─── Banner ────────────────────────────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════════════╗
║              ⚡  AutoApply — Job Hunter Bot                   ║
║         Alex Ocampo Segundo | Santiago, Chile                 ║
╚══════════════════════════════════════════════════════════════╝
"""


# ─── Módulos ───────────────────────────────────────────────────────────────────
def run_search() -> None:
    from modules.job_searcher import run_search as _search
    from modules.ct_searcher import run_ct_search as _ct_search
    print("\n▶ MÓDULO 1 — Búsqueda de ofertas")
    count_li = _search()
    print(f"  ✓ LinkedIn: {count_li} nuevas")
    # CT pausado temporalmente — reactivar cuando se levante el bloqueo de IP
    # count_ct = _ct_search()
    # print(f"  ✓ Computrabajo: {count_ct} nuevas")
    print(f"  ✓ Total: {count_li} ofertas nuevas encontradas.")


def run_scoring() -> None:
    from modules.job_scorer import run_scoring as _score
    print("\n▶ MÓDULO 2 — Evaluación de ofertas")
    count = _score()
    print(f"  ✓ {count} ofertas evaluadas.")


def run_personalization() -> None:
    from modules.cv_personalizer import run_personalization as _personalize
    print("\n▶ MÓDULO 3 — Personalización de materiales")
    count = _personalize()
    print(f"  ✓ {count} ofertas personalizadas.")


def run_applications() -> None:
    from modules.job_applier import run_applications as _apply
    print("\n▶ MÓDULO 4 — Postulaciones automáticas")
    results = _apply()
    print(f"  ✓ Aplicadas: {results['applied']} | Saltadas: {results['skip']} | Errores: {results['error']}")


def run_serve() -> None:
    from modules.dashboard_server import run_server
    run_server()


def run_tracker(args: list[str]) -> None:
    from modules.tracker import run_tracker as _tracker, generate_dashboard
    cmd = args[0] if args else "summary"
    job_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    _tracker(cmd, job_id)


def run_pipeline() -> None:
    """Busca ofertas nuevas, las evalúa y actualiza el dashboard."""
    from modules.tracker import generate_dashboard
    import sqlite3

    print(f"\n  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  Pipeline: search → score → dashboard\n")

    # 1. Buscar ofertas nuevas
    run_search()

    # 2. Evaluar solo las nuevas
    run_scoring()

    # 3. Dashboard actualizado
    path = generate_dashboard()

    # 4. Resumen final
    con = sqlite3.connect(config.DB_PATH)
    stats = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()}
    con.close()

    print(f"\n{'─'*50}")
    print(f"  Total ofertas:  {sum(stats.values())}")
    print(f"  Candidatas:     {stats.get('candidate', 0)}")
    print(f"  Evaluadas:      {stats.get('scored', 0)}")
    print(f"  Dashboard:      {path}")
    print(f"  Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*50}\n")


# ─── CLI ───────────────────────────────────────────────────────────────────────
HELP = """
Comandos disponibles:
  (sin args)        Pipeline completo: search → score → personalize → apply
  search            Solo búsqueda de ofertas
  score             Solo scoring con Claude
  personalize       Solo personalización de materiales
  apply             Solo postulaciones
  tracker           Resumen de estado
  tracker list      Listar todas las ofertas
  tracker candidates Listar ofertas candidatas
  tracker applied   Listar postulaciones enviadas
  tracker errors    Listar errores
  tracker detail N  Ver detalle de oferta #N
  tracker dashboard Generar dashboard HTML
  help              Mostrar esta ayuda
"""


def main() -> None:
    setup_logging()
    print(BANNER)

    args = sys.argv[1:]
    command = args[0] if args else ""
    sub_args = args[1:]

    if command == "help" or command == "--help":
        print(HELP)
        return

    if not check_config() and command not in ("tracker", "help"):
        print("\n  Configura las variables en .env antes de continuar.")
        print("  Copia .env.example → .env y completa tus datos.\n")
        return

    dispatch = {
        "search":      run_search,
        "score":       run_scoring,
        "personalize": run_personalization,
        "apply":       run_applications,
        "tracker":     lambda: run_tracker(sub_args),
        "serve":       run_serve,
    }

    if command in dispatch:
        dispatch[command]()
    elif command == "":
        run_pipeline()
    else:
        print(f"  Comando desconocido: '{command}'")
        print(HELP)


if __name__ == "__main__":
    main()
