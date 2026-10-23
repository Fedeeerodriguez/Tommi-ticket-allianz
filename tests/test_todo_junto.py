"""Etapa 1 + Etapa 2 juntas: una semana simulada con los 4 recorridos intercalados.

Pasa por las mismas piezas que producción: el grafo (correo → etapa → motor), Telegram (falso),
el panel (HTTP), el escáner de recordatorios cada 30 min y el despacho en DRY_RUN.

  - Largo (GMMI): C1 → requerimiento → recordatorio → escalado → C4 → C5.
  - Elite (SVIP): emisión registrada → C2 + guía → Ceci la corrige y aprueba por Telegram →
    pago en el hilo → aviso de emisión.
  - Patrimonial (OPPT): C2 + guía → Ceci la aprueba desde el panel → "Pago enviado" a mano →
    aviso de emisión.
  - Trámite: acuse → requerimiento → nuestra respuesta → Allianz no responde (recordatorio a
    Ceci) → atendido.
"""
from collections import Counter
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import api, config
from app.acciones import despachar_pendientes, motor_etapas
from app.acciones.recordatorios import escanear_recordatorios
from app.db.repo import RepositorioSQLite
from app.enriquecimiento import identificar as ident_mod
from app.grafo import construir_grafo
from app.models import Correo
from app.rieles import telegram

from app.escenarios_etapas import (CORREOS, ELITE, GUIA_ELITE, GUIA_PATRI, LARGO, PATRI,
                                   SISTEMA, TRAM, buscar_notion, dia)
from test_telegram import BotFalso

UTC = timezone.utc


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("MOTOR_ETAPAS_PROCESOS", ["largo", "corto", "tramite"]),
                 ("MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"]), ("ESCALAR_A_ALLIANZ", True),
                 ("ALLIANZ_DEST", "allianz.mexico@allianz.com.mx"), ("CECI_WHATSAPP", "5500000000"),
                 ("TELEGRAM_APROBACIONES", True), ("TELEGRAM_BOT_TOKEN", "x"), ("TELEGRAM_CECI_CHAT_ID", "777"),
                 ("NOTION_TOKEN", ""), ("OPENAI_API_KEY", ""), ("DRY_RUN", True),
                 ("PANEL_URL", ""), ("API_TOKEN", ""), ("NOTION_DB_TICKETS_ALLIANZ", ""),
                 ("NOTION_DB_SEGUIMIENTO", "")):
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: buscar_notion)
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    monkeypatch.setattr(api, "_repo", repo)
    bot = BotFalso()
    monkeypatch.setattr(telegram, "_http", bot)
    reloj = [dia(19, 8)]
    monkeypatch.setattr(motor_etapas, "reloj", lambda: reloj[0])
    return repo, construir_grafo(repo), TestClient(api.app), bot, reloj


def test_una_semana_con_los_cuatro_recorridos(mundo):
    repo, grafo, panel, bot, reloj = mundo
    rutas, recordatorios = [], []

    def avanzar(hasta):  # el worker: recordatorios cada 30 min
        t = reloj[0]
        while t + timedelta(minutes=30) <= hasta:
            t += timedelta(minutes=30)
            reloj[0] = t
            r = escanear_recordatorios(repo, t)
            recordatorios.extend((t, a["ticket_id"], a["rol"], a.get("etapa")) for a in r["plan"])
        reloj[0] = max(reloj[0], hasta)

    def tk(nro):
        return repo.buscar_ticket(nro, None, None)

    def guia(nro):
        return repo.listar_aprobaciones(tk(nro)["id"])[0]

    for i, (cuando, remitente, asunto, cuerpo) in enumerate(CORREOS):
        avanzar(cuando)
        out = grafo.invoke({"correo": Correo(f"m{i}", remitente, remitente.split("@")[1], ["hola@babilonia.ai"],
                                             [], asunto, cuerpo, fecha=cuando), "despachar": False})
        rutas.append((asunto[:40], out.get("fin"), [r for r in out["ruta"] if r in ("decidir", "decidir_etapa",
                                                                                     "emision")]))
        telegram.enviar_pendientes(repo)  # el job de Telegram

        if cuando == dia(19, 10) and remitente == SISTEMA:  # llegó el C2 de Elite
            # Ceci ve la guía en Telegram, revisa el n° de solicitud y la aprueba con el botón.
            ap = guia(ELITE)
            assert f"número de solicitud: {GUIA_ELITE['solicitud']}." in ap["texto"] and ap["telegram_msg_id"]
            bot.updates = [{"update_id": 2, "callback_query": {
                "id": "c2", "data": f"ap:{ap['id']}:1", "from": {"username": "ceci"},
                "message": {"message_id": int(ap["telegram_msg_id"]), "chat": {"id": 777}}}}]
            res = telegram.procesar_updates(repo)
            assert sorted(a["rol"] for a in res["plan"]) == ["asesor", "cliente"]

        if cuando == dia(20, 10):  # Ceci aprueba la guía de Patrimonial desde el panel
            r = panel.post(f"/api/tickets-allianz/aprobacion/{guia(PATRI)['id']}",
                           json={"accion": "aprobar", "usuario": "Ceci", **GUIA_PATRI})
            assert r.status_code == 200, r.text

        if cuando == dia(20, 11):  # Patrimonial: el pago va por correo nuevo → se marca en el panel
            avanzar(dia(21, 10))
            r = panel.post(f"/api/tickets-allianz/{tk(PATRI)['id']}/etapa",
                           json={"etapa": "documentos_enviados", "usuario": "Ceci"})
            assert r.status_code == 200, r.text

    avanzar(dia(28, 12))

    # ------------------------------------------------------------ ruteo
    assert all(fin != "error" for _, fin, _ in rutas)
    assert [r for r in rutas if r[2] == ["decidir"]] == []          # nada cayó al motor viejo
    emision_registrada = rutas[1]
    assert emision_registrada[1] == "emision_sin_ticket"            # C1 del corto: solo se registra
    tickets = {t["nro_ticket"]: t for t in repo.listar_tickets()}
    assert set(tickets) == {LARGO, ELITE, PATRI, TRAM}              # 4 tickets, ni uno de más

    # ------------------------------------------------------------ cómo terminó cada uno
    fin = {n: (t["proceso"], t["etapa"], t["estado"]) for n, t in tickets.items()}
    assert fin == {LARGO: ("largo", "atendida", "resuelto"), ELITE: ("corto", "poliza_emitida", "resuelto"),
                   PATRI: ("corto", "poliza_emitida", "resuelto"), TRAM: ("tramite", "atendida", "resuelto")}
    assert repo.listar_recordatorios(estados=["activo", "escalado"]) == []

    def avisos(nro):
        return Counter((a["etapa"], a["destinatario"]) for a in repo.listar_avisos(tickets[nro]["id"])
                       if not a["etapa"].startswith(("recordatorio_", "escalado_")))

    los3 = lambda *etapas: Counter({(e, r): 1 for e in etapas for r in ("ceci", "asesor", "cliente")})  # noqa: E731
    assert avisos(LARGO) == los3("apertura", "requerimiento", "documentos_enviados", "atendida")
    assert avisos(ELITE) == los3("documentos_enviados", "poliza_emitida") + Counter(
        {("guia_aportacion", "cliente"): 1, ("guia_aportacion", "asesor"): 1})  # Ceci la vio en Telegram
    assert avisos(PATRI) == avisos(ELITE)
    assert avisos(TRAM) == los3("apertura", "requerimiento", "documentos_enviados", "atendida")

    # ------------------------------------------------------------ la guía salió como la aprobó Ceci
    def a_cliente(nro, etapa):
        return next(a["texto"] for a in repo.listar_avisos(tickets[nro]["id"])
                    if a["etapa"] == etapa and a["destinatario"] == "cliente")

    for nro, g in ((ELITE, GUIA_ELITE), (PATRI, GUIA_PATRI)):
        assert f"número de solicitud: {g['solicitud']}." in a_cliente(nro, "guia_aportacion")
    assert {(guia(n)["estado"], guia(n)["resuelto_por"]) for n in (ELITE, PATRI)} == \
        {("aprobada", "telegram:ceci"), ("aprobada", "panel:Ceci")}
    assert "«Aplicación de pago póliza OPPT-48211»" in a_cliente(TRAM, "atendida")

    # ------------------------------------------------------------ recordatorios: los que tocaban, una vez
    por = Counter((n, rol, etapa) for _, tid, rol, etapa in recordatorios
                  for n, t in tickets.items() if t["id"] == tid)
    assert por == Counter({
        # Largo: el cliente no mandó la carta en 3 días hábiles → recordatorio; +1 día hábil → escalado.
        (LARGO, "cliente", "recordatorio_requerimiento"): 1, (LARGO, "asesor", "recordatorio_requerimiento"): 1,
        (LARGO, "asesor", "escalado_requerimiento"): 1, (LARGO, "ceci", "escalado_requerimiento"): 1,
        # Trámite: le respondimos el martes y Allianz no contestó → a Ceci (vie); +1 día hábil → correo a
        # Allianz para que Ceci lo apruebe + aviso a Ceci (lun 10:00). Allianz atiende a las 12:00.
        (TRAM, "ceci", "recordatorio_esperando_allianz"): 1, (TRAM, "ceci", "escalado_esperando_allianz"): 1,
        (TRAM, "allianz", "escalado_esperando_allianz"): 1,
        # Patrimonial: pago marcado el miércoles; la emisión tarda → lo mismo (lun / mar 10:00), y la
        # emisión llega el martes a las 11:00.
        (PATRI, "ceci", "recordatorio_esperando_allianz"): 1, (PATRI, "ceci", "escalado_esperando_allianz"): 1,
        (PATRI, "allianz", "escalado_esperando_allianz"): 1,
    })
    assert all(dia(19, 9) <= t <= dia(28, 12) and 9 <= (t - timedelta(hours=6)).hour < 19
               for t, *_ in recordatorios)  # siempre en horario de oficina de CDMX
    # Las dos escalaciones quedaron esperando a Ceci, pero Allianz respondió antes: se descartaron solas.
    escalaciones = [a for n in (TRAM, PATRI) for a in repo.listar_acciones(tickets[n]["id"])
                    if a["tipo_accion"] == "escalar_allianz"]
    assert [a["estado"] for a in escalaciones] == ["omitida", "omitida"]

    # ------------------------------------------------------------ despacho (DRY_RUN): nada se pierde
    desp = despachar_pendientes(repo)
    assert set(desp["conteo"]) == {"simulada"}, desp["conteo"]      # todo compuesto, nada salió (DRY_RUN)
    assert desp["conteo"]["simulada"] == sum(len(repo.listar_avisos(t["id"])) for t in tickets.values()) - 2
    assert despachar_pendientes(repo)["conteo"] == {}               # y no se vuelve a despachar nada

    # ------------------------------------------------------------ el panel: a Ceci no le queda nada
    assert panel.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()["items"] == []
