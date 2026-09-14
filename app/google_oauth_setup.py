"""Autorización OAuth de la Gmail API (se corre UNA sola vez) — Plan B.

Lee el client OAuth de `GOOGLE_CREDENTIALS_JSON` (descargado de Google Cloud Console, tipo
"App de escritorio") y abre el navegador para que el dueño de hola@babilonia.ai autorice el
acceso. Guarda el token en `GOOGLE_TOKEN_JSON`; a partir de ahí el lector/emisor lo usan y lo
refrescan solos, sin volver a pedir consentimiento.

    python -m app.google_oauth_setup
"""
from __future__ import annotations

from pathlib import Path

from app import config
from app.google_auth import SCOPES


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Falta instalar dependencias: pip install google-auth-oauthlib google-api-python-client")
        return 1

    cred = Path(config.GOOGLE_CREDENTIALS_JSON)
    if not cred.is_file():
        print(f"No encuentro el archivo de credenciales OAuth en:\n  {cred}\n")
        print("Descargalo de Google Cloud Console (APIs y servicios → Credenciales →")
        print("Crear credenciales → ID de cliente OAuth → tipo 'App de escritorio'),")
        print(f"y guardalo con ese nombre/ruta, o seteá GOOGLE_CREDENTIALS_JSON en el .env.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(cred), SCOPES)
    creds = flow.run_local_server(port=0)
    destino = Path(config.GOOGLE_TOKEN_JSON)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nOK: token guardado en {destino}")
    print("Ya podés correr la validación (lectura por Gmail API) o el scheduler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
