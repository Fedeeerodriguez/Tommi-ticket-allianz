"""Configuración del sistema. Lee de variables de entorno / .env, con defaults seguros.

Nada de secretos hardcodeados: todo sale del entorno. En Fase 1 casi todo tiene default
para poder correr el dry-run sin credenciales.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

RAIZ = Path(__file__).resolve().parent.parent


def _csv(nombre: str, default: str = "") -> list[str]:
    crudo = os.getenv(nombre, default)
    return [x.strip().lower() for x in crudo.split(",") if x.strip()]


def _bool(nombre: str, default: str = "false") -> bool:
    return os.getenv(nombre, default).strip().lower() in {"1", "true", "yes", "si", "sí"}


# --- Buzón único: hola@babilonia.ai (lee por IMAP, envía por SMTP en Fase 4) ---
BUZON = os.getenv("BUZON", "hola@babilonia.ai").strip().lower()
BABILONIA_ADDRESSES = _csv("BABILONIA_ADDRESSES", "hola@babilonia.ai")

# IMAP (lectura). Sin credenciales en Fase 1 → se usa el lector local de muestras.
IMAP_HOST = os.getenv("IMAP_HOST", "")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")  # app password
IMAP_CARPETA = os.getenv("IMAP_CARPETA", "INBOX")

# SMTP (envío, Fase 4).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Dominios/correos de Allianz para las reglas L1 (ajustar con los reales).
ALLIANZ_DOMINIOS = _csv("ALLIANZ_DOMINIOS", "allianz.com,allianz.com.mx")

# Base de datos: misma Supabase de Tommy, esquema aislado.
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_SCHEMA = os.getenv("DB_SCHEMA", "tickets_allianz")

# Notion (reusado del backend principal de Tommy). Acepta NOTION_TOKEN o NOTION_API_KEY.
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "") or os.getenv("NOTION_API_KEY", "")
NOTION_DB_TICKETS_ALLIANZ = os.getenv("NOTION_DB_TICKETS_ALLIANZ", "")
NOTION_DB_DAF = os.getenv("NOTION_DB_DAF", "")
NOTION_DB_ASESORES = os.getenv("NOTION_DB_ASESORES", "")
NOTION_DB_EMISIONES = os.getenv("NOTION_DB_EMISIONES", "")
NOTION_DB_COBRANZAS = os.getenv("NOTION_DB_COBRANZAS", "")
NOTION_DB_CLIENTES = os.getenv("NOTION_DB_CLIENTES", "")

# Supabase Storage para adjuntos (PDFs). En la DB solo va texto + referencia.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "tickets-allianz-adjuntos")

# LLM L2 (clasificación de lo ambiguo + resúmenes coloquiales). Claude Haiku.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODELO_L2 = os.getenv("MODELO_L2", "claude-haiku-4-5-20251001")

# Carpetas locales (dry-run / dev).
MUESTRAS_DIR = Path(os.getenv("MUESTRAS_DIR", str(RAIZ / "docs" / "muestras")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(RAIZ / "data")))

# Modo seguro: en dry-run NO se envía nada a nadie.
DRY_RUN = _bool("DRY_RUN", "true")

# Umbral de confianza por debajo del cual L1 deriva a L2 (LLM).
UMBRAL_LLM = float(os.getenv("UMBRAL_LLM", "0.6"))

# Retención: purgar/archivar registros más viejos que esto (días). 6 meses.
RETENCION_DIAS = int(os.getenv("RETENCION_DIAS", "180"))

# Intervalo de polling IMAP (segundos).
POLL_SEGUNDOS = int(os.getenv("POLL_SEGUNDOS", "90"))


def hay_imap() -> bool:
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def hay_llm() -> bool:
    return bool(ANTHROPIC_API_KEY)


def hay_db() -> bool:
    return bool(DATABASE_URL)


def hay_notion() -> bool:
    return bool(NOTION_TOKEN)
