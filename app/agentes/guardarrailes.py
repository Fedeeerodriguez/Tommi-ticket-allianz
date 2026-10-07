"""Guardarraíles DETERMINÍSTICOS contra alucinaciones de los agentes LLM.

El prompt le pide a la IA que no invente, pero eso no alcanza: estas funciones revisan lo que
devolvió y, si rompe una regla dura, el borrador se DESCARTA (se usa la plantilla o no se manda
nada). Nunca se "corrige" el texto de la IA: o pasa entero, o no pasa.

Reglas que se verifican acá (motivo de cada una: casos reales calificados como "mala"):
  R1  Nombres: un mensaje no puede nombrar a nadie que no esté en la evidencia del ticket.
      En los asuntos de Allianz, "X escribió un mensaje" nombra a quien ESCRIBIÓ en Allianz,
      no al cliente → al cliente nunca se le habla con el nombre del autor.
  R2  Envíos: Babilonia nunca afirma haber enviado/adjuntado/entregado algo. El bot no adjunta
      nada y no tiene constancia de lo que mandó el cliente.
  R3  Plazos y montos: no se prometen fechas ni se mencionan importes que no estén en la
      evidencia.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

# Palabras con mayúscula que NO son nombres de personas (no se exige que estén en la evidencia).
_NO_NOMBRES = {
    "allianz", "babilonia", "mexico", "méxico", "tommy", "whatsapp", "hola", "gracias",
    "estimados", "estimado", "estimada", "saludos", "buen", "buenas", "buenos", "dia", "día",
    "tardes", "noches", "quedamos", "quedo", "ticket", "poliza", "póliza", "sra", "sr", "dr",
    "dra", "lic", "ing", "seguros", "compania", "compañía", "sa", "cv", "gmmi", "vipp", "plu",
    "op3d", "nuevo", "negocio", "favor", "por", "cualquier", "te", "le", "les", "su", "tu",
    "ya", "en", "el", "la", "los", "las", "un", "una", "referente", "respecto", "solicitamos",
    "agradecemos", "reiteramos", "confirmamos", "atentamente", "cordialmente", "equipo",
    "ejecutivo", "comercial", "pleno", "sureste", "internal", "rv", "re", "asunto", "de",
    "para", "enviado", "lunes", "martes", "miercoles", "miércoles", "jueves", "viernes",
    "sabado", "sábado", "domingo", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre", "pre", "remesa",
}

# R2 — afirmaciones de envío/entrega hechas por Babilonia.
_AFIRMA_ENVIO = re.compile(
    r"\b(?:hemos|ya|les|le)\s+(?:hemos\s+)?(?:enviad|remitid|entregad|adjuntad|cargad|subid|mandad)\w*"
    r"|\b(?:enviamos|adjuntamos|remitimos|entregamos|mandamos|anexamos)\b"
    r"|\bse\s+(?:envi[oó]|adjunt[oó]|entreg[oó]|remiti[oó]|mand[oó])\b"
    r"|\b(?:adjunto|anexo)\s+(?:encontrar|les|la|el)\b",
    re.IGNORECASE)

# R3 — montos de dinero.
_MONTO = re.compile(r"\$\s?\d[\d.,]*|\b\d[\d.,]*\s?(?:mxn|pesos|usd|d[oó]lares)\b", re.IGNORECASE)

# Autor en asuntos de Allianz: "[Allianz México Ticket-123] NOMBRE APELLIDO escribió un mensaje".
_AUTOR_ASUNTO = re.compile(r"\]\s*(.+?)\s+escribi[oó]\s+un\s+mensaje", re.IGNORECASE)

# Ruido de los correos de Allianz que no aporta al contenido.
_CORTES = re.compile(
    r"^\s*(?:De|From|Enviado el|Sent)\s*:|^-{3,}\s*Original|^_{5,}|Este mensaje fue enviado",
    re.IGNORECASE | re.MULTILINE)
_RUIDO = [
    re.compile(r"-{5,}\s*Por favor responda sobre esta l[ií]nea\s*-{5,}", re.IGNORECASE),
    re.compile(r"Hola\s+HOLA@BABILONIA\.AI\s*,?", re.IGNORECASE),
    re.compile(r"Gracias,?\s+Allianz\s+Mexico\s+SA\s+Compan[ií]a\s+de\s+Seguros", re.IGNORECASE),
    re.compile(r"^\s*Internal\s*", re.IGNORECASE),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def autor_del_asunto(asunto: Optional[str]) -> Optional[str]:
    """Quién escribió en Allianz según el asunto ("X escribió un mensaje"). None si no aplica."""
    m = _AUTOR_ASUNTO.search(asunto or "")
    if not m:
        return None
    autor = m.group(1).strip()
    return None if _norm(autor) in ("sistema", "") else autor


def limpiar_mensaje_allianz(cuerpo: Optional[str], limite: int = 1200) -> str:
    """Deja solo lo que Allianz escribió en este mensaje: sin avisos del sistema de tickets,
    sin el hilo citado ("De: … Enviado el: …") y acotado a `limite` caracteres."""
    texto = cuerpo or ""
    m = _CORTES.search(texto)
    if m and m.start() > 40:          # si el corte está al principio, no hay nada propio antes
        texto = texto[:m.start()]
    for r in _RUIDO:
        texto = r.sub(" ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:limite]


def _nombres(texto: str) -> list[str]:
    """Palabras con mayúscula que podrían ser nombres de personas (no al inicio de oración)."""
    salida = []
    for m in re.finditer(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})\b", texto or ""):
        previo = texto[:m.start()].rstrip()[-1:] or "."
        if previo in ".!?¡¿:\n-•*":
            continue                    # inicio de oración/viñeta: la mayúscula es gramatical
        palabra = m.group(1)
        if _norm(palabra) not in _NO_NOMBRES:
            salida.append(palabra)
    return salida


def nombres_sin_respaldo(texto: str, evidencia: Iterable[Optional[str]]) -> list[str]:
    """R1: nombres del texto que NO aparecen en ninguna evidencia del ticket."""
    ev = _norm(" ".join(e for e in evidencia if e))
    return [n for n in _nombres(texto) if _norm(n) not in ev]


def afirma_envio(texto: str) -> bool:
    """R2: True si el texto afirma que Babilonia envió/adjuntó/entregó algo."""
    return bool(_AFIRMA_ENVIO.search(texto or ""))


def montos_sin_respaldo(texto: str, evidencia: Iterable[Optional[str]]) -> list[str]:
    """R3: montos del texto que no figuran literalmente en la evidencia."""
    ev = re.sub(r"\s", "", " ".join(e for e in evidencia if e))
    return [m for m in _MONTO.findall(texto or "") if re.sub(r"\s", "", m) not in ev]


def _presenta_como_cliente(texto: str, autor: str) -> bool:
    """True si el texto llama "cliente/asegurado/Sr(a)." a quien escribió en Allianz."""
    t = _norm(texto)
    for p in autor.split():
        if len(p) > 2 and re.search(rf"\b(?:cliente|asegurad[oa]|sra?\.?)\s+{re.escape(_norm(p))}\b", t):
            return True
    return False


def validar_whatsapp(rol: str, texto: str, ctx: dict) -> Optional[str]:
    """Revisa un mensaje de WhatsApp para cliente/asesor. Devuelve el motivo del rechazo o None.

    Cliente: solo puede nombrar al cliente del ticket (nunca al autor de Allianz).
    Asesor: puede nombrar además al autor de Allianz (es útil saber quién respondió)."""
    cliente = ctx.get("cliente_nombre")
    autor = ctx.get("autor_mensaje_allianz")
    if rol == "cliente":
        evidencia = [cliente]
        if autor and any(_norm(p) in _norm(texto) for p in autor.split() if len(p) > 2):
            return f"menciona al autor de Allianz ({autor}) en un mensaje al cliente"
    else:
        evidencia = [cliente, autor, ctx.get("novedad_allianz")]
        # El asesor puede saber quién escribió en Allianz, pero nunca como "el cliente X".
        if autor and _presenta_como_cliente(texto, autor):
            return f"presenta a {autor} (empleado de Allianz) como cliente"
    sobran = nombres_sin_respaldo(texto, evidencia)
    if sobran:
        return f"nombra personas que no están en el ticket: {', '.join(sorted(set(sobran)))}"
    if afirma_envio(texto):
        return "afirma que Babilonia envió algo sin constancia"
    montos = montos_sin_respaldo(texto, [ctx.get("novedad_allianz")])
    if montos:
        return f"menciona montos que no están en el correo: {', '.join(montos)}"
    return None


def validar_cuerpo_allianz(cuerpo: str, ctx: dict, mensaje_allianz: str) -> Optional[str]:
    """Revisa el cuerpo de un correo a Allianz. Devuelve el motivo del rechazo o None."""
    evidencia = [mensaje_allianz, ctx.get("asunto"), ctx.get("cliente_nombre"),
                 ctx.get("poliza"), ctx.get("nro_ticket") and str(ctx.get("nro_ticket"))]
    evidencia += [str(h.get("detalle") or "") for h in (ctx.get("historial") or [])]
    # R1 bis: quien "escribió un mensaje" en Allianz es empleado de Allianz. Fuera del saludo
    # (primera línea), su nombre no puede aparecer: ahí la IA lo confundía con el cliente
    # ("el trámite del cliente Silvia Lilian García" en el ticket de Martha Zárate).
    autor = ctx.get("autor_mensaje_allianz")
    if autor:
        resto = _norm(cuerpo.split("\n", 1)[1] if "\n" in cuerpo else "")
        if any(re.search(rf"\b{re.escape(_norm(p))}\b", resto) for p in autor.split() if len(p) > 2):
            return f"menciona a {autor} (empleado de Allianz) como parte del caso"
    if afirma_envio(cuerpo):
        return "afirma que Babilonia envió/adjuntó documentación sin constancia"
    sobran = nombres_sin_respaldo(cuerpo, evidencia)
    if sobran:
        return f"nombra personas que no están en el ticket: {', '.join(sorted(set(sobran)))}"
    montos = montos_sin_respaldo(cuerpo, [mensaje_allianz])
    if montos:
        return f"menciona montos que no están en el correo de Allianz: {', '.join(montos)}"
    return None
