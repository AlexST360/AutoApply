# ⚡ AutoApply

Sistema en Python que automatiza la búsqueda y postulación de empleos en LinkedIn, potenciado por Claude AI.

**Candidato:** Alex Ocampo Segundo — Desarrollador Full Stack / Automatización de Procesos — Santiago, Chile

---

## Arquitectura

```
autoapply/
├── main.py              # Orquestador principal
├── config.py            # Settings centralizados
├── .env.example         # Template de variables de entorno
├── modules/
│   ├── job_searcher.py  # Módulo 1: Scraper LinkedIn (Playwright)
│   ├── job_scorer.py    # Módulo 2: Scoring CV vs oferta (Claude API)
│   ├── cv_personalizer.py  # Módulo 3: Cover letters y respuestas (Claude)
│   ├── job_applier.py   # Módulo 4: Easy Apply automatizado (Playwright)
│   └── tracker.py       # Módulo 5: CLI + Dashboard HTML
├── data/
│   ├── cv_alex.txt      # CV en texto plano (contexto para Claude)
│   └── jobs.db          # SQLite (generado automáticamente)
├── outputs/
│   └── cover_letters/   # Cover letters y respuestas generadas
├── dashboard/
│   └── index.html       # Dashboard HTML (generado)
├── logs/
│   └── autoapply.log    # Log de ejecuciones
└── requirements.txt
```

---

## Instalación

### 1. Clonar / descargar el proyecto

```bash
cd autoapply
```

### 2. Crear entorno virtual (recomendado)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configurar credenciales

```bash
cp .env.example .env
```

Edita `.env` con tus datos reales:

```env
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_EMAIL=tu@email.com
LINKEDIN_PASSWORD=tu_contraseña
```

---

## Uso

### Pipeline completo (recomendado)

```bash
python main.py
```

Ejecuta en secuencia: búsqueda → scoring → personalización → postulación → dashboard.

### Módulos por separado

```bash
python main.py search         # Busca nuevas ofertas en LinkedIn
python main.py score          # Evalúa ofertas pendientes con Claude (score 0-100)
python main.py personalize    # Genera cover letters y respuestas para candidatas
python main.py apply          # Postula automáticamente via Easy Apply
```

### Tracker / Dashboard

```bash
python main.py tracker                  # Resumen general en consola
python main.py tracker list             # Listar todas las ofertas
python main.py tracker candidates       # Ofertas con score >= 65
python main.py tracker applied          # Postulaciones enviadas
python main.py tracker errors           # Errores a revisar
python main.py tracker detail 5         # Detalle de oferta #5
python main.py tracker dashboard        # Genera dashboard/index.html
```

Abre `dashboard/index.html` en tu navegador para ver la tabla visual.

---

## Flujo del pipeline

```
LinkedIn          Claude API            SQLite
   │                  │                    │
   ├─ search ─────────┤                    │
   │  (Playwright)     │                   ├─ status: found
   │                  │                    │
   │              score ────────────────── ├─ status: scored / candidate
   │              (cv_alex.txt cached)     │
   │                  │                    │
   │          personalize ─────────────── ├─ cover_letter_path saved
   │              (cover letter +          │
   │               form answers)          │
   │                  │                    │
   ├─ apply ──────────┤                    │
   │  (Easy Apply)     │                   ├─ status: applied / error / skip
   │                  │                    │
   └── dashboard ─────────────────────────┘
       (index.html)
```

---

## Configuración avanzada

Edita `config.py` para personalizar:

| Parámetro | Descripción | Default |
|-----------|-------------|---------|
| `SEARCH_KEYWORDS` | Keywords de búsqueda | "desarrollador full stack Chile", ... |
| `SCORE_THRESHOLD` | Score mínimo para candidatar | `65` |
| `MAX_JOBS_PER_KEYWORD` | Ofertas por keyword | `20` |
| `MAX_APPLICATIONS_PER_RUN` | Tope de postulaciones | `10` |
| `BROWSER_HEADLESS` | Modo sin interfaz | `False` |
| `CLAUDE_MODEL` | Modelo de Claude | `claude-sonnet-4-6` |

---

## Características técnicas

- **Prompt caching**: El CV de Alex se cachea entre llamadas a Claude, reduciendo costos ~80% en scoring y personalización masiva.
- **SQLite nativo**: Sin dependencias externas de base de datos.
- **Manejo de errores**: Cada módulo registra errores en log y BD sin interrumpir el pipeline.
- **Preguntas inesperadas**: Si Easy Apply presenta una pregunta no mapeada, Claude genera una respuesta en tiempo real.
- **Dashboard reactivo**: El HTML usa JavaScript vanilla para filtrar y buscar sin backend.

---

## Notas importantes

- LinkedIn puede bloquear cuentas con actividad automatizada excesiva. Usa `MAX_APPLICATIONS_PER_RUN` con moderación (≤10 por sesión).
- Si aparece un CAPTCHA, el sistema espera 60 segundos para resolución manual.
- Mantén `BROWSER_HEADLESS = False` inicialmente para monitorear el comportamiento.
- El CV en `data/cv_alex.txt` es el contexto principal para Claude. Mantenlo actualizado.

---

## Licencia

Uso personal. No distribuir credenciales.
