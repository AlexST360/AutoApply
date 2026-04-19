# AutoApply — Job Hunter Bot

Automatiza la búsqueda y evaluación de ofertas de trabajo en **LinkedIn** y **Computrabajo Chile**, con un dashboard web interactivo para gestionar candidaturas.

## ¿Qué hace?

- **Scraping** de ofertas en LinkedIn y Computrabajo usando Selenium
- **Scoring automático** con IA (OpenRouter / Groq) — evalúa cada oferta contra el perfil del candidato y le da un puntaje 0-100
- **Dashboard interactivo** en el browser para revisar candidatas, aprobarlas o descartarlas
- **Base de datos SQLite** local — sin servidores externos
- **Sin dependencias problemáticas** — funciona en Windows con Application Control activo (sin pydantic, sin playwright)

## Stack técnico

| Componente | Tecnología |
|---|---|
| Scraping | Python + Selenium + ChromeDriver |
| IA / Scoring | OpenRouter API (`arcee-ai/trinity-large-preview`) + Groq fallback |
| Base de datos | SQLite (built-in) |
| Dashboard | HTML + CSS + JS (single file, sin frameworks) |
| Servidor local | Python `http.server` (sin Flask) |

## Estructura

```
autoapply/
├── main.py                  # Orquestador principal
├── config.py                # Configuración centralizada
├── modules/
│   ├── job_searcher.py      # Scraper LinkedIn
│   ├── ct_searcher.py       # Scraper Computrabajo
│   ├── job_scorer.py        # Scoring con IA (batch de 10)
│   ├── tracker.py           # Generador de dashboard HTML
│   └── dashboard_server.py  # Servidor local con API REST mínima
├── data/                    # BD SQLite + CV (ignorado en git)
└── .env                     # Credenciales (ignorado en git)
```

## Instalación

```bash
git clone https://github.com/AlexST360/autoapply.git
cd autoapply
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus credenciales
```

## Uso

```bash
# Pipeline completo: buscar + evaluar + dashboard
python main.py

# Solo búsqueda (LinkedIn + Computrabajo)
python main.py search

# Solo scoring con IA
python main.py score

# Dashboard interactivo en el browser
python main.py serve
```

## Dashboard

El dashboard permite:
- Ver todas las ofertas con su score, estado y fuente (LinkedIn / CT)
- Filtrar por estado: Sin revisar · Aprobadas · Descartadas · Aplicadas
- **Aprobar o descartar** candidatas con un clic (persiste en BD)
- Abrir la oferta original en el browser

## Variables de entorno

```env
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...
CT_EMAIL=...
CT_PASSWORD=...
```

## Requisitos

- Python 3.10+
- Google Chrome instalado
- Windows (probado en Windows 11)
