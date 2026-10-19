"""Etapas del proceso Allianz — qué correo es y qué hay que hacer con él.

Reglas deterministas (sin IA) armadas con las capturas de Ceci (proceso largo, proceso corto y
trámites) + los correos reales de hola@babilonia.ai. Mapa completo: docs/REGLAS_ETAPAS.md.

Tres procesos:
  - largo   (Auto, Vida, GMM, OP3D Educación, HOFP Residencial): C1 apertura → C2 confirmación de
             datos → C3 requerimiento/autorizado → C4 documentos enviados → C5 atendida.
  - corto   (SVIP Elite, OPPT Patrimonial): emisión → confirmación + ticket (guía de aportación) →
             aviso de emisión.
  - tramite (los abrimos nosotros con un correo; el hilo se llama "[EXT] <nuestro asunto>").

Si ninguna regla aplica → REVISAR (va al panel). Nunca se adivina.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app import config


class Etapa(str, Enum):
    APERTURA = "apertura"                        # C1: se creó el ticket / se asignó número
    CONFIRMACION_DATOS = "confirmacion_datos"    # C2: "Le confirmamos que recibimos su solicitud"
    REQUERIMIENTO = "requerimiento"              # C3: una persona de Allianz pide algo
    AUTORIZADO = "autorizado"                    # C3: autorizado, pasa a cobro
    DOCUMENTOS_ENVIADOS = "documentos_enviados"  # C4: nosotros (o la ejecutiva) mandamos lo pedido
    ATENDIDA = "atendida"                        # C5: atendida / folio cerrado
    RECHAZADO = "rechazado"                      # Allianz rechaza el ticket (venció el plazo)
    DECLINADO = "declinado"                      # Selección de riesgos declina el riesgo
    CERRADO_INACTIVIDAD = "cerrado_inactividad"  # C3.1
    RECORDATORIO_ALLIANZ = "recordatorio_allianz"
    COPIA_EJECUTIVA = "copia_ejecutiva"          # Penny/Blanca reenvían el mismo mensaje (RV:)
    NOTA_EJECUTIVA = "nota_ejecutiva"            # la ejecutiva escribe algo propio
    REBOTE_TICKET_CERRADO = "rebote_ticket_cerrado"  # respondimos a un ticket ya cerrado
    EMISION_REGISTRADA = "emision_registrada"    # "¡Felicidades, su solicitud se registró!"
    POLIZA_EMITIDA = "poliza_emitida"            # "Aviso de emisión de póliza"
    REVISAR = "revisar"
    NO_APLICA = "no_aplica"


@dataclass(frozen=True)
class Accion:
    avisar: tuple[str, ...] = ()        # roles: "ceci", "asesor", "cliente"
    recordatorio: bool = False          # arranca el esquema 72 h hábiles (o el plazo del correo)
    cancela_recordatorio: bool = False  # llegó lo que se esperaba
    responder_allianz: bool = False     # hay que contestar en el hilo (con lo pedido)
    cerrar: bool = False
    aprobacion_telegram: bool = False   # guía de aportación: primero Ceci aprueba
    delicado: bool = False              # no sale nada automático al cliente
    nota: str = ""


LOS_3 = ("ceci", "asesor", "cliente")
_NADA = Accion(nota="Solo actualizar el estado del ticket.")

# (etapa, proceso) → acción. "*" = cualquier proceso.
ACCIONES: dict[tuple[Etapa, str], Accion] = {
    (Etapa.APERTURA, "largo"): Accion(LOS_3, nota="Cliente: 'estamos en proceso de autorización'. No responder a Allianz."),
    (Etapa.APERTURA, "tramite"): Accion(LOS_3, nota="Siempre con n° de ticket + cliente + asunto."),
    (Etapa.APERTURA, "*"): Accion(("ceci",), nota="Apertura en proceso no identificado."),
    (Etapa.CONFIRMACION_DATOS, "corto"): Accion(
        ("ceci",), aprobacion_telegram=True,
        nota="Guía de aportación → Ceci aprueba por Telegram → recién ahí a cliente y asesor."),
    (Etapa.CONFIRMACION_DATOS, "*"): _NADA,
    (Etapa.REQUERIMIENTO, "*"): Accion(
        LOS_3, recordatorio=True, responder_allianz=True,
        nota="Avisar QUÉ piden. El documento se manda como correo nuevo en el hilo (no reenviar)."),
    # Confirmado 19/10: C3 autorizado = Allianz autoriza el cobro; C5 atendida = ya se cobró.
    (Etapa.AUTORIZADO, "*"): Accion(LOS_3, cancela_recordatorio=True,
                                    nota="Autorizado para cobro: Allianz autorizó, sigue el cobro."),
    (Etapa.DOCUMENTOS_ENVIADOS, "*"): Accion(
        LOS_3, recordatorio=True, cancela_recordatorio=True,
        nota="Se cumplió el requerimiento; ahora esperamos a Allianz."),
    (Etapa.ATENDIDA, "largo"): Accion(LOS_3, cancela_recordatorio=True, cerrar=True,
                                      nota="Atendida y cobrada: fin del trámite."),
    (Etapa.ATENDIDA, "*"): Accion(LOS_3, cancela_recordatorio=True, cerrar=True),
    # Delicados: al cliente no le sale nada; el asesor lo contacta (confirmado 19/10).
    (Etapa.RECHAZADO, "*"): Accion(
        ("ceci", "asesor"), cancela_recordatorio=True, cerrar=True, delicado=True,
        nota="Allianz rechazó el ticket (venció el plazo). Asesor: contacta al cliente; "
             "para seguir hay que cotizar de nuevo."),
    (Etapa.DECLINADO, "*"): Accion(
        ("ceci", "asesor"), cancela_recordatorio=True, cerrar=True, delicado=True,
        nota="Selección de riesgos declinó el riesgo. Asesor: contacta al cliente."),
    (Etapa.CERRADO_INACTIVIDAD, "*"): Accion(LOS_3, cancela_recordatorio=True, cerrar=True),
    (Etapa.RECORDATORIO_ALLIANZ, "*"): Accion(nota="Recordatorio automático de Allianz: se ignora."),
    (Etapa.COPIA_EJECUTIVA, "*"): Accion(nota="Copia del mismo mensaje: ya se avisó con el original."),
    (Etapa.NOTA_EJECUTIVA, "*"): Accion(("ceci", "asesor"), nota="Comentario propio de la ejecutiva."),
    (Etapa.REBOTE_TICKET_CERRADO, "*"): Accion(
        ("ceci",), nota="Nuestra respuesta NO entró: el ticket ya estaba cerrado. Hay que abrir uno nuevo."),
    (Etapa.EMISION_REGISTRADA, "*"): Accion(nota="Registrar póliza y solicitud (sin avisar)."),
    (Etapa.POLIZA_EMITIDA, "*"): Accion(LOS_3, cancela_recordatorio=True, cerrar=True,
                                        nota="Póliza emitida: fin del proceso."),
    (Etapa.REVISAR, "*"): Accion(nota="Ninguna regla aplica: revisión humana en el panel."),
    (Etapa.NO_APLICA, "*"): Accion(),
}


def accion_para(etapa: Etapa, proceso: Optional[str]) -> Accion:
    return ACCIONES.get((etapa, proceso or "")) or ACCIONES[(etapa, "*")]


# --------------------------------------------------------------------------- productos
# prefijo → (proceso, ramo). Confirmados en el mapa del 09/10 salvo los marcados.
PRODUCTOS: dict[str, tuple[str, str]] = {
    "SVIP": ("corto", "Elite"),
    "OPPT": ("corto", "Patrimonial"),
    "OP3D": ("largo", "Educación"),
    "HOFP": ("largo", "Residencial"),
    "GMMI": ("largo", "Gastos médicos"),
    "GMLI": ("largo", "Gastos médicos"),
    "VIPP": ("largo", "Vida"),
    "PLU3": ("largo", "OptiMaxx Plus"),  # ⚠️ por confirmar con Ceci (¿corto como Elite?)
}
_RE_PREFIJO = re.compile(r"(?<![A-Z0-9])(" + "|".join(PRODUCTOS) + r")(?![A-Z0-9])")  # GMLI_1131 incluido
_NOMBRES_PRODUCTO = (
    (re.compile(r"optimaxx\s+elite", re.I), "SVIP"),
    (re.compile(r"patrimonial", re.I), "OPPT"),
    (re.compile(r"educaci[oó]n", re.I), "OP3D"),
    (re.compile(r"optimaxx\s+plus", re.I), "PLU3"),
)
# Póliza: prefijo conocido + separador (- / _) + número. "GMMI 98577" (con espacio) es solicitud.
_RE_POLIZA = re.compile(r"\b(" + "|".join(PRODUCTOS) + r")[-/_](\d{3,})(?:[-_]\d)?\b")

# --------------------------------------------------------------------------- patrones
_RE_TICKET = re.compile(r"Ticket[-\s#]*(\d{5,})", re.I)
_RE_REENVIO = re.compile(r"^\s*(?:RV|RE|FW|FWD|TR)\s*:", re.I)
_RE_ACTOR_ASUNTO = re.compile(r"\]\s*(.+?)\s+(escrib\w*\s+un\s+mensaje|cre[oó]\s+una\s+nueva\s+solicitud)", re.I)
_RE_TITULO_MSG = re.compile(r"escrib\w*\s+un\s+mensaje\s+en\s+(.+?)(?:<[^>\n]*>)?:[ \t]*\r?\n", re.I | re.S)
_RE_TITULO_CREO = re.compile(r"cre[oó]\s+(.+?)\s+en\s+tu\s+nombre", re.I | re.S)
_RE_FIN_MSG = re.compile(
    r"(\n\s*Gracias,\s*\n\s*Allianz\s+Mexico|Este\s+mensaje\s+fue\s+enviado\s+desde|\{\{#|\nVer\s+solicitud)", re.I)

_RE_CONFIRMAMOS = re.compile(r"le\s+confirmamos\s+que\s+recibimos\s+su\s+solicitud", re.I)
_RE_AUTO_RECIBIDO = re.compile(r"respuesta\s+autom[aá]tica\s+para\s+confirmar\s+que\s+hemos\s+recibido", re.I)
_RE_RECHAZO = re.compile(r"proced\w*\s+a\s+rechazar|(?:ticket|solicitud)\s+(?:queda\s+|ha\s+sido\s+|fue\s+)?rechazad", re.I)
_RE_DECLINADO = re.compile(r"\bdeclinad[oa]\b", re.I)
_RE_ATENDIDA = re.compile(r"\batendid[ao]\b", re.I)
_RE_CERRADO = re.compile(r"folio\s+cerrado|(?:ticket|folio)\s+queda\s+cerrado", re.I)
_RE_NEGACION = re.compile(r"\b(?:no|a[uú]n|todav[ií]a|sin|pendiente)\b", re.I)
_RE_AUTORIZADO = re.compile(
    r"\bautorizad[oa]\b|\bha\s+sido\s+autoriz|\bse\s+autoriz[oó]\b|"
    r"(?:pasa|turna\w*|envi\w*)\s+a\s+cobro|en\s+proceso\s+de\s+cobro", re.I)
_RE_INACTIVIDAD_CIERRE = re.compile(r"cerr\w*\s+(?:\w+\s+){0,3}por\s+(?:inactividad|falta\s+de\s+respuesta)", re.I)
_RE_RECORDATORIO = re.compile(
    r"recordatorio|por\s+cerrar|pr[oó]xim\w*\s+a\s+cerrar|por\s+inactividad|sin\s+respuesta", re.I)
_RE_ENVIO = re.compile(
    r"\b(?:anexo|adjunto|env[ií]o|remito|comparto)\s+(?:lo\s+solicitado|el|la|los|las)\b", re.I)
_RE_PIDE = re.compile(
    r"favor\s+de\s+(?:enviar|proporcionar|anexar|adjuntar|remitir|completar|firmar)|"
    r"le\s+(?:pedimos|solicitamos)|nos\s+(?:env[ií]e|proporcione)|env[ií]enos|"
    r"requerimos|es\s+necesario\s+(?:que\s+)?(?:env|adjunt|present)|"
    r"(?:tiene|cuenta\s+con)\s+\d+\s+d[ií]as|quedamos\s+(?:a\s+la\s+espera|atentos\s+a\s+su)|"
    r"no\s+(?:incluye|viene\s+adjunt|coincide)", re.I)
_RE_PLAZO = re.compile(
    r"(?:tiene|cuenta\s+con|plazo\s+de|dispone\s+de)\s+(\d+)\s+(d[ií]as?|horas?)(\s+h[aá]biles)?", re.I)
_RE_BRINDAR_RESPUESTA = re.compile(r"brindar\s+respuesta|dar\s+respuesta|su\s+apoyo\s+para\s+responder", re.I)
_RE_BOILERPLATE_RV = re.compile(
    r"^(?:internal|hola[^\n]*|buen[oa]s?\s+(?:d[ií]as?|tardes?)[^\n]*|comparto\s+para\s+(?:su|tu)\s+conocimiento[^\n]*|"
    r"para\s+(?:su|tu)\s+conocimiento[^\n]*|saludos\.?|gracias\.?)$", re.I)
_RE_FIRMA_EJECUTIVA = re.compile(r"\n[^\n]*\n\s*Ejecutiv[oa]\s+Comercial", re.I)


@dataclass
class EtapaCorreo:
    etapa: Etapa
    proceso: Optional[str] = None        # largo | corto | tramite
    producto: Optional[str] = None       # prefijo (SVIP, GMMI, ...)
    nro_ticket: Optional[str] = None
    nro_solicitud: Optional[str] = None
    poliza: Optional[str] = None         # normalizada: PLU3-429083
    cliente: Optional[str] = None
    actor: Optional[str] = None
    actor_tipo: Optional[str] = None     # sistema | allianz | ejecutiva | propio | externo
    titulo_hilo: Optional[str] = None
    mensaje: str = ""                    # solo lo que escribió el actor (sin plantilla ni historial)
    que_piden: Optional[str] = None
    plazo: Optional[tuple[int, str]] = None  # (15, "dias_habiles")
    motivo: str = ""
    accion: Accion = field(default_factory=Accion)

    def como_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("accion", "mensaje") and v not in (None, "")}
        d["etapa"] = self.etapa.value
        d["accion"] = {k: v for k, v in self.accion.__dict__.items() if v}
        return d


# --------------------------------------------------------------------------- utilidades
def a_texto(s: Optional[str]) -> str:
    """NFC + HTML → texto (Allianz manda NFD y las emisiones vienen en HTML)."""
    s = unicodedata.normalize("NFC", s or "")
    if re.search(r"<(?:html|body|table|p|div|span)\b", s, re.I):
        s = re.sub(r"(?is)<(style|head|script)\b.*?</\1>", " ", s)
        s = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", s)
        s = html.unescape(re.sub(r"(?s)<[^>]+>", " ", s))
    s = s.replace(" ", " ")
    return re.sub(r"[ \t]+", " ", s)


def _plano(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _direccion(remitente: str) -> str:
    m = re.search(r"<([^>]+)>", remitente or "")
    return (m.group(1) if m else (remitente or "")).strip().lower()


def _es_propia(direccion: str) -> bool:
    return direccion.lower() in set(config.BABILONIA_ADDRESSES) or direccion.lower().endswith("@babilonia.ai")


def _ejecutivas() -> set[str]:
    return {_plano(n).upper() for n in config.EJECUTIVAS_ALLIANZ}


def _tipo_actor(actor: Optional[str]) -> Optional[str]:
    if not actor:
        return None
    a = _plano(actor)
    if a.upper() == "SISTEMA":
        return "sistema"
    if "@" in a:
        return "propio" if _es_propia(a) else "externo"
    if a.upper() in _ejecutivas():
        return "ejecutiva"
    return "allianz"  # incluye "EXTERNO <nombre>" (proveedores de Allianz, ej. laboratorio)


def _producto(*textos: str) -> Optional[str]:
    for t in textos:
        if not t:
            continue
        m = _RE_PREFIJO.search(t.upper())
        if m:
            return m.group(1)
    for t in textos:
        for rx, pref in _NOMBRES_PRODUCTO:
            if t and rx.search(t):
                return pref
    return None


def _poliza(*textos: str) -> Optional[str]:
    for t in textos:
        m = _RE_POLIZA.search(t or "")
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return None


def _campo(texto: str, *nombres: str) -> Optional[str]:
    for n in nombres:
        m = re.search(rf"\b{n}\s*:\s*([^\n*]+)", texto, re.I)
        if m and m.group(1).strip():
            return _plano(m.group(1)).rstrip(" .")
    return None


def _cliente_de_titulo(titulo: str) -> Optional[str]:
    """'1950110 HORTENCIA GONZALEZ GAMA NUEVO NEGOCIO' / 'GMMI 98577 MARTHA ZARATE URIBE N'."""
    t = _plano(titulo)
    m = re.match(r"^(?:[A-Z0-9]{3,4}\s+)?\d{4,}\s+(.+?)(?:\s+nuevo\s+negocio|\s+N)?$", t, re.I)
    return m.group(1).strip() if m else None


def _solicitud(texto: str, titulo: str) -> Optional[str]:
    v = _campo(texto, r"N[UÚ]MERO\s+DE\s+SOLICITUD", r"No\.\s*Solicitud")
    if v and re.match(r"\d+", v):
        return re.match(r"\d+", v).group(0)
    m = re.match(r"^(?:[A-Z0-9]{3,4}\s+)?(\d{4,})\b", _plano(titulo))
    return m.group(1) if m else None


def _mensaje(texto: str, titulo_m: Optional[re.Match]) -> str:
    cuerpo = texto[titulo_m.end():] if titulo_m else texto
    fin = _RE_FIN_MSG.search(cuerpo)
    return (cuerpo[:fin.start()] if fin else cuerpo).strip()


def _que_piden(mensaje: str) -> str:
    # Se corta en la despedida. OJO: "Quedamos en espera de la información faltante: 1.- …" NO es
    # despedida, es el pedido (correo real del 2582367).
    t = re.split(r"\n\s*(?:sin\s+m[aá]s|atentamente|saludos|quedamos\s+(?:atent|a\s+sus|a\s+la\s+orden)|"
                 r"quedo\s+atent|en\s+caso\s+de\s+cualquier)", mensaje, maxsplit=1, flags=re.I)[0]
    t = re.sub(r"^\s*(?:buen[oa]?s?\s+d[ií]as?|buenas\s+tardes|hola[^\n]*|estimad[oa][^\n]*)[.:,]?\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*gracias\s+por[^\n.]*[.!]?\s*", "", t, flags=re.I)  # "Gracias por el envío de …"
    t = re.sub(r"^\s*(?:quedamos|quedo)\s+(?:en|a\s+la)\s+espera\s+de\s+(?:la\s+)?(?:informaci[oó]n|"
               r"documentaci[oó]n)?\s*(?:faltante|pendiente|siguiente)?\s*:?\s*", "", t, flags=re.I)
    return _plano(t)[:500]


def _plazo(mensaje: str) -> Optional[tuple[int, str]]:
    m = _RE_PLAZO.search(mensaje)
    if not m:
        return None
    unidad = "horas" if m.group(2).lower().startswith("hora") else "dias"
    return int(m.group(1)), unidad + ("_habiles" if m.group(3) else "")


def _afirmado(rx: re.Pattern, texto: str) -> bool:
    """El patrón aparece sin una negación en las ~25 letras previas ('aún no atendida')."""
    return any(not _RE_NEGACION.search(texto[max(0, m.start() - 25):m.start()]) for m in rx.finditer(texto))


# --------------------------------------------------------------------------- reglas
def _etapa_persona(msg: str, actor_tipo: str) -> tuple[Etapa, str]:
    """Mensaje escrito por una persona (Allianz, ejecutiva, nosotros o un externo)."""
    p = _plano(msg)
    if _RE_RECHAZO.search(p):
        return Etapa.RECHAZADO, "rechazo del ticket"
    if _RE_DECLINADO.search(p):
        return Etapa.DECLINADO, "riesgo declinado"
    if _RE_CERRADO.search(p) or _afirmado(_RE_ATENDIDA, p):
        return Etapa.ATENDIDA, "atendida / folio cerrado"
    if _afirmado(_RE_AUTORIZADO, p):
        return Etapa.AUTORIZADO, "autorizado"
    pide = bool(_RE_PIDE.search(p))
    if actor_tipo in ("propio", "externo", "ejecutiva") and not pide:
        return Etapa.DOCUMENTOS_ENVIADOS, f"mensaje de nuestro lado ({actor_tipo})"
    if _RE_ENVIO.search(p) and not pide:
        return Etapa.DOCUMENTOS_ENVIADOS, "anexa/envía lo solicitado"
    if pide:
        return Etapa.REQUERIMIENTO, "pide información/documentos"
    return Etapa.REVISAR, "mensaje de persona sin patrón conocido"


def _etapa_sistema(p: str) -> tuple[Etapa, str]:
    if _RE_CERRADO.search(p) or _afirmado(_RE_ATENDIDA, p):
        return Etapa.ATENDIDA, "sistema: atendida, ticket cerrado"
    if _RE_INACTIVIDAD_CIERRE.search(p):
        return Etapa.CERRADO_INACTIVIDAD, "sistema: cerrado por inactividad"
    if _RE_CONFIRMAMOS.search(p):
        return Etapa.CONFIRMACION_DATOS, "sistema: confirmación de datos"
    if _RE_AUTO_RECIBIDO.search(p):
        return Etapa.APERTURA, "sistema: acuse automático de nuestro correo (trámite)"
    if _RE_RECORDATORIO.search(p):
        return Etapa.RECORDATORIO_ALLIANZ, "sistema: recordatorio"
    return Etapa.REVISAR, "sistema sin patrón conocido"


def _proceso(producto: Optional[str], titulo: str, texto: str) -> Optional[str]:
    t = _plano(titulo)
    if re.match(r"\[EXT\]\s*Emisi[oó]n\s+p[oó]liza", t, re.I):
        return "corto"  # el ticket del proceso corto se abre con el correo de emisión
    if t.upper().startswith("[EXT]") or _RE_AUTO_RECIBIDO.search(texto):
        return "tramite"
    if producto:
        return PRODUCTOS[producto][0]
    return "largo" if t else None


def detectar_etapa(asunto: str, cuerpo: str, remitente: str) -> EtapaCorreo:
    asunto = _plano(a_texto(asunto))
    texto = a_texto(cuerpo)
    plano = _plano(texto)
    addr = _direccion(remitente)
    dom = addr.split("@")[-1]
    if not any(dom == d or dom.endswith("." + d) for d in config.ALLIANZ_DOMINIOS):
        return EtapaCorreo(Etapa.NO_APLICA, motivo="no viene de Allianz", accion=accion_para(Etapa.NO_APLICA, None))

    mt = _RE_TICKET.search(asunto) or _RE_TICKET.search(plano)
    ticket = mt.group(1) if mt else None

    # --- Notificaciones de emisión (no son tickets). "Solicitud de cotización N" = registrada sin póliza aún ---
    if re.match(r"emisi[oó]n\s+p[oó]liza", asunto, re.I) or re.search(r"su\s+solicitud\s+se\s+registr[oó]\s+correctamente", plano, re.I):
        prod = _producto(asunto, plano)
        ms = re.search(r"Solicitud\s*:?\s*(\d{5,})", f"{asunto} {plano}", re.I)
        mc = re.search(r"Estimado\(a\)\s+(.+?)\s*(?::|\ble\s+agradecemos)", plano)
        r = EtapaCorreo(Etapa.EMISION_REGISTRADA, PRODUCTOS.get(prod, (None,))[0], prod,
                        poliza=_poliza(asunto, plano), nro_solicitud=ms.group(1) if ms else None,
                        cliente=mc.group(1) if mc else None, motivo="correo de emisión registrada")
        r.accion = accion_para(r.etapa, r.proceso)
        return r
    if re.match(r"aviso\s+de\s+emisi[oó]n\s+de\s+p[oó]liza", asunto, re.I):
        prod = _producto(asunto)
        m = re.search(r"[-/_]\d{3,}(?:[-_]\d)?\s+(?:a\s+nombre\s+de\s+|de\s+)?(.+?)\.?$", asunto)
        r = EtapaCorreo(Etapa.POLIZA_EMITIDA, PRODUCTOS.get(prod, (None,))[0], prod,
                        poliza=_poliza(asunto, plano), cliente=m.group(1).strip() if m else None,
                        motivo="aviso de emisión de póliza")
        r.accion = accion_para(r.etapa, r.proceso)
        return r

    # --- Rebote: respondimos a un ticket que ya estaba cerrado ---
    if re.search(r"ticket\s+que\s+ya\s+se\s+encuentra\s+cerrado", plano, re.I):
        r = EtapaCorreo(Etapa.REBOTE_TICKET_CERRADO, nro_ticket=ticket, titulo_hilo=_campo(asunto, "Asunto"),
                        motivo="Allianz avisa que el ticket ya estaba cerrado")
        r.accion = accion_para(r.etapa, None)
        return r

    if not ticket:
        return EtapaCorreo(Etapa.NO_APLICA, motivo="Allianz sin ticket (comunicado/marketing)",
                           accion=accion_para(Etapa.NO_APLICA, None))

    # --- Reenvío de la ejecutiva (Penny/Blanca): RV: [Allianz México Ticket-N] ... ---
    if _RE_REENVIO.match(asunto) and not addr.startswith("allianz.mexico@"):
        propio = re.split(r"\n\s*(?:De|From)\s*:", texto, maxsplit=1)[0]
        propio = _RE_FIRMA_EJECUTIVA.split(propio)[0]
        lineas = [l.strip() for l in propio.splitlines() if l.strip()]
        sustancia = [l for l in lineas if not _RE_BOILERPLATE_RV.match(l)]
        etapa = Etapa.NOTA_EJECUTIVA if sustancia else Etapa.COPIA_EJECUTIVA
        r = EtapaCorreo(etapa, nro_ticket=ticket, actor=addr, actor_tipo="ejecutiva",
                        mensaje=_plano(" ".join(sustancia)),
                        motivo="reenvío de ejecutiva" + (" con comentario propio" if sustancia else ""))
        acc = accion_para(etapa, None)
        if _RE_BRINDAR_RESPUESTA.search(propio):  # Penny pide que respondamos en el ticket
            acc = Accion(("ceci",), nota="La ejecutiva pide responder directo en el ticket (con copia a ella).")
        r.accion = acc
        return r

    # --- Mensajes del sistema de tickets ---
    ma = _RE_ACTOR_ASUNTO.search(asunto)
    actor = _plano(ma.group(1)) if ma else None
    creo = bool(ma and re.match(r"cre", ma.group(2), re.I))
    mtit = _RE_TITULO_CREO.search(texto) if creo else _RE_TITULO_MSG.search(texto)
    titulo = _plano(re.sub(r"<[^>]*>", "", mtit.group(1))) if mtit else ""
    msg = "" if creo else _mensaje(texto, mtit)
    actor_tipo = _tipo_actor(actor)

    if creo:
        etapa, motivo = Etapa.APERTURA, "se creó la solicitud"
    elif actor_tipo == "sistema":
        etapa, motivo = _etapa_sistema(_plano(msg or plano))
    elif actor:
        etapa, motivo = _etapa_persona(msg or texto, actor_tipo)
    else:
        etapa, motivo = Etapa.REVISAR, "ticket sin actor reconocible en el asunto"

    prod = _producto(titulo, _campo(texto, r"TIPO\s+DE\s+SOLICITUD") or "", msg)
    proceso = _proceso(prod, titulo, plano)
    r = EtapaCorreo(
        etapa, proceso, prod, nro_ticket=ticket,
        nro_solicitud=_solicitud(texto, titulo),
        poliza=_poliza(msg, plano),
        cliente=(_campo(texto, r"NOMBRE\s+DEL\s+CONTRATANTE", "CONTRATANTE", r"DESCRIPCI[OÓ]N")
                 or _cliente_de_titulo(titulo)),
        actor=actor, actor_tipo=actor_tipo, titulo_hilo=titulo or None, mensaje=msg,
        motivo=motivo,
    )
    if etapa == Etapa.REQUERIMIENTO:
        r.que_piden, r.plazo = _que_piden(msg), _plazo(msg)
    r.accion = accion_para(etapa, proceso)
    return r
