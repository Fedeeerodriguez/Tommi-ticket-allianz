# Muestras de correos

Los `.eml` de esta carpeta son **SINTÉTICOS** (inventados) para probar el pipeline de
clasificación en dry-run mientras llegan los correos reales de `hola@babilonia.ai`.

Cuando tengamos muestras reales:
- Reemplazar/añadir aquí los `.eml` reales (anonimizados si hace falta).
- Ajustar `ALLIANZ_DOMINIOS` y las reglas de `app/clasificador/reglas.py` con lo que se observe.

Correr el clasificador:

```bash
python -m app.run_intake
```
