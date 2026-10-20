"""Semana de prueba de las Etapas 1 y 2: los 4 recorridos intercalados, armados con las capturas
de Ceci (nombres de prueba). La usan el test de punta a punta (tests/test_todo_junto.py) y el
informe del replay (app/run_replay_etapas.py), porque en los correos reales de hola@ todavía no
hay ningún C2 del proceso corto ni ningún trámite (llegan a otros buzones).

  - Largo (GMMI): C1 → requerimiento → (recordatorio, escalado) → C4 → C5.
  - Elite (SVIP): emisión registrada → C2 + guía → Ceci la corrige y aprueba → pago en el hilo → emisión.
  - Patrimonial (OPPT): C2 + guía → Ceci la aprueba → "Pago enviado" en el panel → emisión.
  - Trámite: acuse → requerimiento → nuestra respuesta → (Allianz no responde) → atendido.
"""
from __future__ import annotations

from datetime import datetime, timezone

SISTEMA = "Allianz.Mexico@allianz.com.mx"
CALLCENTER = "callcenter.ahorro@allianz.com.mx"
OPTIMAXX = "notificaciones.optimaxx@allianz.com.mx"
_PIE = "\n Gracias,\n Allianz Mexico SA Compania de Seguros\n--- Este mensaje fue enviado desde el Service Management"

LARGO, TIT_L = "2576612", "1950110 HORTENCIA PRUEBA GAMA NUEVO NEGOCIO"
ELITE, TIT_E = "2567479", "[EXT] Emisión póliza No. Póliza: SVIP-21799 No. Solicitud: 25287681"
PATRI, TIT_P = "2590001", "[EXT] Emisión póliza No. Póliza: OPPT-51234 No. Solicitud: 25290001"
TRAM, TIT_T = "2587626", "[EXT] Aplicación de pago póliza OPPT-48211"

# Lo que devolvería Notion (Emisiones) para cada cliente de prueba.
FILAS_NOTION = [
    {"cliente_nombre": n, "nro_solicitud": s, "poliza": p, "telefono_cliente": tc, "telefono_asesor": "5598765432",
     "asesor_correo": "asesor1@babilonia.ai", "asesor_nombre": "Asesor Uno"}
    for n, s, p, tc in (("Hortencia Prueba Gama", 1950110, None, "5512345678"),
                        ("Guillermo Prueba Castro", 25287681, "SVIP-21799", "5522223333"),
                        ("Lucía Prueba Mora", 25290001, "OPPT-51234", "5533334444"),
                        ("Ana Ruiz Pérez", 25111111, "OPPT-48211", "5544445555"))
]

# Lo que Ceci completa en cada guía antes de aprobarla (monto y datos para depositar).
GUIA_ELITE = {"monto": "$50,000 MXN", "datos_deposito": "CLABE 012345678901234567 a nombre de Allianz México"}
GUIA_PATRI = {"monto": "$80,000 MXN", "datos_deposito": "CLABE 045678901234567890 a nombre de Allianz México"}


def buscar_notion(campo, op, valor, n):
    """Buscador con la misma firma que el de Notion (identificar.py)."""
    if campo == "nro_solicitud":
        return [f for f in FILAS_NOTION if str(f["nro_solicitud"]) == str(valor)], False
    return [f for f in FILAS_NOTION if f.get(campo) and str(valor).lower() in str(f[campo]).lower()], False


def dia(d: int, h: int) -> datetime:
    """Octubre 2026, hora de CDMX → UTC."""
    return datetime(2026, 10, d, h + 6, 0, tzinfo=timezone.utc)


def _hilo(tk, actor, titulo, msg):
    asunto = f"[Allianz México Ticket-{tk}] {actor} escribió un mensaje"
    cuerpo = (f"--- Por favor responda sobre esta línea ---\n Hola HOLA@BABILONIA.AI ,\n Nuevo mensaje\n"
              f" {actor} escribió un mensaje en {titulo}:\n\n{msg}\n{_PIE}")
    return asunto, cuerpo


def _confirmacion(nombre, sol, tipo):
    return (f"Estimado cliente,\nLe confirmamos que recibimos su solicitud para trámite que se describe a "
            f"continuación:\n * OFICINA SOLICITANTE: Centro\n * NOMBRE DEL CONTRATANTE: {nombre}\n"
            f" * NÚMERO DE SOLICITUD: {sol}\n * TIPO DE SOLICITUD: {tipo}, Nuevo negocio")


# (cuándo, remitente, asunto, cuerpo)
CORREOS = [
    (dia(19, 9), SISTEMA, f"[Allianz México Ticket-{LARGO}] Sistema creó una nueva solicitud en su nombre",
     "Sistema creó HORTENCIA PRUEBA GAMA en tu nombre\n NÚMERO DE SOLICITUD: 1950110\n "
     "NOMBRE DEL CONTRATANTE: HORTENCIA PRUEBA GAMA\n TIPO DE SOLICITUD: GMMI"),
    (dia(19, 9), OPTIMAXX, "Emisión póliza No. Póliza: SVIP-21799 No. Solicitud: 25287681",
     "<html><body><p>¡Felicidades, su solicitud se registró correctamente!</p><p>Número de póliza: SVIP-21799.</p>"
     "<p>Estimado(a) GUILLERMO PRUEBA CASTRO le agradecemos la confianza</p></body></html>"),
    (dia(19, 10), CALLCENTER, *_hilo(TRAM, "Sistema", TIT_T,
                                     "Esta es una respuesta automática para confirmar que hemos recibido su solicitud.")),
    (dia(19, 10), SISTEMA, *_hilo(ELITE, "Sistema", TIT_E, _confirmacion("GUILLERMO PRUEBA CASTRO", 25287681, "SVIP"))),
    (dia(19, 11), SISTEMA, *_hilo(LARGO, "RAUL MARIN", TIT_L,
                                  "Buen día\nFavor de enviar la carta laboral firmada.\nSaludos")),
    (dia(19, 12), CALLCENTER, *_hilo(TRAM, "OSBALDO PINEDA", TIT_T,
                                     "Buen día.\nRevisamos su pago y observamos que no incluye la fecha de pago.\n"
                                     "Por favor, envíenos el estado de cuenta.\nQuedamos atentos a su respuesta.")),
    (dia(19, 13), SISTEMA, *_hilo(PATRI, "Sistema", TIT_P, _confirmacion("LUCIA PRUEBA MORA", 25290001, "OPPT"))),
    (dia(20, 10), CALLCENTER, *_hilo(TRAM, "integraciones@babilonia.ai", TIT_T,
                                     "Buen día, anexo el estado de cuenta con la fecha de pago.")),
    (dia(20, 11), SISTEMA, *_hilo(ELITE, "hola@babilonia.ai", TIT_E,
                                  "Buen día, anexo comprobante de pago y estado de cuenta del cliente.")),
    (dia(22, 11), OPTIMAXX, "Aviso de emisión de póliza SVIP/21799 a nombre de Guillermo Prueba Castro.",
     "<html><body>Estimado(a) JOSE RAMON MIER, carátula de la póliza SVIP-21799-0</body></html>"),
    (dia(26, 10), SISTEMA, *_hilo(LARGO, "hola@babilonia.ai", TIT_L, "Anexo lo solicitado. Saludos")),
    (dia(26, 12), CALLCENTER, *_hilo(TRAM, "OSBALDO PINEDA", TIT_T, "Le informamos que su solicitud fue atendida.")),
    (dia(27, 10), SISTEMA, *_hilo(LARGO, "RAUL MARIN", TIT_L,
                                  "Le informamos que su solicitud fue atendida.\nFolio cerrado.")),
    (dia(27, 11), OPTIMAXX, "Aviso de emisión de póliza OPPT/51234 a nombre de Lucia Prueba Mora.",
     "<html><body>Estimado(a) JOSE RAMON MIER, carátula de la póliza OPPT-51234-0</body></html>"),
]

# Lo que hace Ceci a mano (cuándo, qué, ticket, campos de la guía). El test lo hace por Telegram y el panel.
ACCIONES_CECI = [
    (dia(19, 11), "aprobar_guia", ELITE, GUIA_ELITE),
    (dia(20, 10), "aprobar_guia", PATRI, GUIA_PATRI),
    (dia(21, 10), "pago_enviado", PATRI, None),
]
HASTA = dia(28, 12)
