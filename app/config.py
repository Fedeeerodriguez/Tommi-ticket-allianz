"""Configuración del sistema. Lee de variables de entorno / .env, con defaults seguros.

Nada de secretos hardcodeados: todo sale del entorno. En Fase 1 casi todo tiene default
para poder correr el dry-run sin credenciales.
"""
from __future__ import annotations

import os
import re
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
# Remitente de los correos que sale Tommy (default: el buzón único).
SMTP_REMITENTE = os.getenv("SMTP_REMITENTE", "") or BUZON
SMTP_NOMBRE = os.getenv("SMTP_NOMBRE", "Babilonia")
# Destino de los tickets que se levantan ante Allianz (Directorio Allianz, pendiente de confirmar).
# Sin esto, la acción 'enviar_a_allianz' queda BLOQUEADA (nunca adivina un destinatario).
ALLIANZ_DEST = os.getenv("ALLIANZ_DEST", "")

# Dominios/correos de Allianz para las reglas L1 (ajustar con los reales).
ALLIANZ_DOMINIOS = _csv("ALLIANZ_DOMINIOS", "allianz.com,allianz.com.mx")
# Ejecutivas comerciales de Allianz que trabajan de NUESTRO lado (reenvían tickets, suben documentos).
# Tal como aparecen en el asunto "<NOMBRE> escribió un mensaje" (se compara sin mayúsculas).
EJECUTIVAS_ALLIANZ = _csv("EJECUTIVAS_ALLIANZ", "PENNY YAMILI ORTIZ,BLANCA ISABEL XULUC")
# Directorio Allianz por tipo de trámite (JSON: {"cambio_conducto_cobro": "cliente.optimax@..."}).
# Pendiente la página de Allianz "trámite-por-trámite". Si un trámite no está acá, cae a ALLIANZ_DEST.
ALLIANZ_DIRECTORIO = os.getenv("ALLIANZ_DIRECTORIO", "")

# --- WATI (WhatsApp) — Fase D. Real solo con credenciales y DRY_RUN=false; si no, laboratorio. ---
WATI_API_URL = os.getenv("WATI_API_URL", "").rstrip("/")
# Se acepta pegado con o sin "Bearer " (así viene en n8n como WATI_TOKEN); el cliente HTTP lo agrega.
WATI_API_TOKEN = re.sub(r"^\s*bearer\s+", "", os.getenv("WATI_API_TOKEN", ""), flags=re.I).strip()
WATI_PLANTILLA_ASESOR = os.getenv("WATI_PLANTILLA_ASESOR", "avances")     # plantilla de avances (asesores)
WATI_PLANTILLA_CLIENTE = os.getenv("WATI_PLANTILLA_CLIENTE", "")          # solo cuando se le pide algo
WATI_PLANTILLA_CECI = os.getenv("WATI_PLANTILLA_CECI", "")               # intervención/visto bueno de Ceci
CECI_WHATSAPP = os.getenv("CECI_WHATSAPP", "")                           # número fijo de Ceci (pendiente)
# Avisos del motor por etapa (Etapas 1 y 2): una plantilla por destinatario, creadas en WATI el
# 20/10 (docs/TEXTOS_ETAPA2.md). Variables por NOMBRE (el despacho las arma):
#   equipo  (asesor y Ceci): {{ticket}} {{cliente}} {{tramite}} {{mensaje}}
#   cliente:                 {{nombre}} {{mensaje}}
#   guía de aportación:      {{nombre}} {{producto}} {{poliza}} {{monto}} {{datos_deposito}}
WATI_PLANTILLA_AVISO_EQUIPO = os.getenv("WATI_PLANTILLA_AVISO_EQUIPO", "tommy_aviso_equipo")
WATI_PLANTILLA_AVISO_CLIENTE = os.getenv("WATI_PLANTILLA_AVISO_CLIENTE", "tommy_actualizacion_cliente")
WATI_PLANTILLA_GUIA = os.getenv("WATI_PLANTILLA_GUIA", "tommy_guia_aportacion")
# Guías por producto (los pasos de Ceci): Patrimonial y Elite tienen la suya; el resto usa la general.
WATI_PLANTILLA_GUIA_PATRIMONIAL = os.getenv("WATI_PLANTILLA_GUIA_PATRIMONIAL", "tommy_guia_patrimonial")
WATI_PLANTILLA_GUIA_ELITE = os.getenv("WATI_PLANTILLA_GUIA_ELITE", "tommy_guia_elite")

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
# Base de REVISIÓN (sandbox): panel 'Ticket Allianz Seguimiento' donde el equipo evalúa las
# respuestas/acciones propuestas (Veredicto: Pendiente/Aprobado/Rechazado). Vacío = no sincroniza.
NOTION_DB_SEGUIMIENTO = os.getenv("NOTION_DB_SEGUIMIENTO", "")

# Supabase Storage para adjuntos (PDFs). En la DB solo va texto + referencia.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "tickets-allianz-adjuntos")

# LLM L2 (clasificación de lo ambiguo + resúmenes coloquiales).
# Decisión: reusar OpenAI del backend principal (gpt-4.1-mini). ANTHROPIC queda opcional.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODELO_L2 = os.getenv("MODELO_L2", "") or os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
# Generar mensajes coloquiales con LLM (M4). Si false, usa plantillas fijas (sin costo).
USAR_LLM_RESUMEN = _bool("USAR_LLM_RESUMEN", "true")

# Carpetas locales (dry-run / dev).
MUESTRAS_DIR = Path(os.getenv("MUESTRAS_DIR", str(RAIZ / "docs" / "muestras")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(RAIZ / "data")))

# Gmail API por OAuth (Plan B para Workspace: reemplaza IMAP+SMTP si hay token).
# El client OAuth se descarga de Google Cloud Console; el token lo genera
# `python -m app.google_oauth_setup` y queda en GOOGLE_TOKEN_JSON.
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", str(DATA_DIR / "google_credentials.json"))
GOOGLE_TOKEN_JSON = os.getenv("GOOGLE_TOKEN_JSON", str(DATA_DIR / "google_token.json"))
# En servidores headless (EasyPanel) no se puede abrir el navegador: se genera el token una
# vez en local y su CONTENIDO se pega en esta env var. Tiene prioridad sobre el archivo.
GOOGLE_TOKEN = os.getenv("GOOGLE_TOKEN", "")
GMAIL_QUERY = os.getenv("GMAIL_QUERY", "is:unread")
# Anti rate-limit de Gmail: cuántos correos baja por ciclo, pausa entre requests (ms), y si
# marca leídos los ya procesados (para drenar el backlog y NO re-bajarlos cada poll).
# Por seguridad, el default de marcar-leídos sigue a DRY_RUN: en DRY_RUN NO toca la casilla
# (así quien hoy maneja hola@ a mano sigue viendo los correos sin leer); en vivo sí los marca.
GMAIL_MAX_POR_CICLO = int(os.getenv("GMAIL_MAX_POR_CICLO", "40"))
GMAIL_PAUSA_MS = int(os.getenv("GMAIL_PAUSA_MS", "250"))
GMAIL_MARCAR_LEIDOS = _bool("GMAIL_MARCAR_LEIDOS", "false" if _bool("DRY_RUN", "true") else "true")

# Modo copiloto (primera parte en vivo): correo interno del equipo al que se manda el resumen
# de tickets + borradores propuestos. Vacío = desactivado. Es interno (envía SOLO a esta
# dirección), por eso funciona aunque DRY_RUN=true.
RESUMEN_EQUIPO_EMAIL = os.getenv("RESUMEN_EQUIPO_EMAIL", "")
RESUMEN_CADA_HORAS = int(os.getenv("RESUMEN_CADA_HORAS", "4"))  # cada cuánto manda el digest

# API del panel de seguimiento (la consume el frontend de Tomi; vive ACÁ, fuera de Tomi prod).
# API_TOKEN: si está seteado, exige `Authorization: Bearer <token>`. CORS_ORIGINS: orígenes del
# frontend permitidos (CSV). Vacío = permite todos (solo para dev).
API_TOKEN = os.getenv("API_TOKEN", "")
CORS_ORIGINS = _csv("CORS_ORIGINS", "")

# Modo seguro: en dry-run NO se envía nada a nadie.
DRY_RUN = _bool("DRY_RUN", "true")

# Umbral de confianza por debajo del cual L1 deriva a L2 (LLM).
UMBRAL_LLM = float(os.getenv("UMBRAL_LLM", "0.6"))

# Retención: purgar/archivar registros más viejos que esto (días). 6 meses.
RETENCION_DIAS = int(os.getenv("RETENCION_DIAS", "180"))

# SLA (Fase C): plazo por default cuando Allianz no especifica (horas hábiles) y con cuánta
# anticipación se avisa antes del vencimiento (horas).
SLA_DEFAULT_HORAS = int(os.getenv("SLA_DEFAULT_HORAS", "72"))
SLA_AVISO_HORAS = int(os.getenv("SLA_AVISO_HORAS", "24"))

# Etapa 1 — motor por etapa del proceso largo (docs/PLAN_ETAPA1_PROCESO_LARGO.md). Apagado por
# default: con MOTOR_ETAPAS=1 el proceso largo deja de usar el motor viejo por tipo de correo.
MOTOR_ETAPAS = _bool("MOTOR_ETAPAS", "false")
# Encendido gradual (paso 8): a quién le salen avisos y recordatorios ("ceci,asesor" primero, después
# sumar "cliente"), y si la escalación arma el correo a Allianz con copia a la ejecutiva.
MOTOR_ETAPAS_ROLES = _csv("MOTOR_ETAPAS_ROLES", "ceci,asesor,cliente")
ESCALAR_A_ALLIANZ = _bool("ESCALAR_A_ALLIANZ", "false")
# Recordatorio: se vence a las N h hábiles (o antes, si el correo de Allianz da un plazo menor)
# y se escala (correo con copia a la ejecutiva + aviso a Ceci) M h hábiles después.
RECORDATORIO_HORAS_HABILES = int(os.getenv("RECORDATORIO_HORAS_HABILES", "72"))
ESCALA_HORAS_HABILES = int(os.getenv("ESCALA_HORAS_HABILES", "24"))
# Copia del correo de escalación a Allianz (cuando Allianz no responde). ⚠️ por confirmar con Fede.
ESCALA_CC = _csv("ESCALA_CC", "penny.ortiz@allianz.com.mx")
# Los recordatorios por WhatsApp solo salen en horario de oficina de CDMX (UTC-6, sin horario de
# verano desde 2022), de lunes a viernes. Fuera de horario esperan al siguiente escaneo.
HORARIO_AVISOS = os.getenv("HORARIO_AVISOS", "9-19")
UTC_OFFSET_MX = int(os.getenv("UTC_OFFSET_MX", "-6"))
# Buzones automáticos de Allianz (DAF, cobranzas, recordatorio de pago, emisiones). Con el motor
# por etapa, lo que mandan sin ser de un ticket NO crea ticket (fuera de alcance).
ALLIANZ_BUZONES_AVISOS = _csv("ALLIANZ_BUZONES_AVISOS",
                              "aviso.electronico,notificaciones.optimaxx,comunicados.agentes")
# Link al panel de tickets que va en los avisos a Ceci (opcional).
PANEL_URL = os.getenv("PANEL_URL", "")

# Etapa 2 — proceso corto y trámites (docs/PLAN_ETAPA2_CORTO_TRAMITES.md). Qué procesos maneja el
# motor por etapa: "largo" (Etapa 1) → sumar "corto" y "tramite". Los que no están siguen con el
# motor viejo.
MOTOR_ETAPAS_PROCESOS = _csv("MOTOR_ETAPAS_PROCESOS", "largo")
# Recordatorio de pago del proceso corto (desde que Ceci aprueba la guía de aportación).
# Productos del proceso corto que llevan recordatorio de pago. Patrimonial y Elite no: el cliente
# manda el comprobante por su cuenta (a cliente.inversion@ o al ticket), según la guía de Ceci.
RECORDATORIO_PAGO_PRODUCTOS = _csv("RECORDATORIO_PAGO_PRODUCTOS", "PLU3")
RECORDATORIO_PAGO_HORAS_HABILES = int(os.getenv("RECORDATORIO_PAGO_HORAS_HABILES",
                                                str(RECORDATORIO_HORAS_HABILES)))
# Aprobación de la guía de aportación por Telegram. Sin token/chat (o apagado) se aprueba desde el
# panel. Es un canal interno (solo Ceci): no depende de DRY_RUN; lo que sale al cliente sí.
TELEGRAM_APROBACIONES = _bool("TELEGRAM_APROBACIONES", "false")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CECI_CHAT_ID = os.getenv("TELEGRAM_CECI_CHAT_ID", "")

# Intervalo de polling IMAP (segundos).
POLL_SEGUNDOS = int(os.getenv("POLL_SEGUNDOS", "90"))


def hay_imap() -> bool:
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def hay_gmail_api() -> bool:
    """True si ya se autorizó la Gmail API (token en env var o en archivo)."""
    return bool(GOOGLE_TOKEN.strip()) or Path(GOOGLE_TOKEN_JSON).is_file()


def hay_smtp() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def hay_llm() -> bool:
    return bool(OPENAI_API_KEY)


def hay_db() -> bool:
    return bool(DATABASE_URL)


def hay_notion() -> bool:
    return bool(NOTION_TOKEN)


def hay_wati() -> bool:
    return bool(WATI_API_URL and WATI_API_TOKEN)


def hay_telegram() -> bool:
    """Aprobaciones por Telegram encendidas y configuradas."""
    return bool(TELEGRAM_APROBACIONES and TELEGRAM_BOT_TOKEN and TELEGRAM_CECI_CHAT_ID)


def directorio_allianz(clave: str) -> str:
    """Correo de Allianz para un trámite (del directorio); si no está, cae a ALLIANZ_DEST."""
    import json
    try:
        m = json.loads(ALLIANZ_DIRECTORIO) if ALLIANZ_DIRECTORIO else {}
    except Exception:  # noqa: BLE001
        m = {}
    return m.get(clave) or ALLIANZ_DEST
