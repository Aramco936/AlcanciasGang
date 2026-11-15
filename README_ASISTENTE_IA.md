# Planeador de rotaciones — asistente IA

## Qué incluye

- Chatbot en español conectado a la API de OpenAI (endpoint Chat Completions) mediante el backend FastAPI (`POST /api/asistente`).
- Contexto automático de lo que el usuario ve: formulario, rotaciones calculadas, capa activa del mapa y país tocado.
- Preguntas sugeridas y memoria de los últimos 12 turnos durante la sesión.
- La clave API se lee en el servidor (`OPENAI_API_KEY`); nunca se envía al navegador.

La IA interpreta los datos calculados por el proyecto. No sustituye el algoritmo de rotaciones ni consulta NASA por su cuenta.

> Aparte del chatbot, `rotaciones.py` puede redactar el texto de cada rotación con la API de Anthropic si defines `ANTHROPIC_API_KEY`. Si no la defines, usa una plantilla y todo funciona igual.

## Configuración

Desde la carpeta del proyecto (la que contiene `main.py`):

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
```

Edita `.env` y pega tu clave real. **Sin espacios alrededor del `=` y sin comillas:**

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
OPENAI_MAX_TOKENS=3000
```

`main.py` carga el `.env` automáticamente (python-dotenv); ya no hace falta `source .env`. Arranca con:

```bash
uvicorn main:app --reload
```

Abre `http://127.0.0.1:8000`.

## Variables de entorno

| Variable | Obligatoria | Descripción |
| --- | --- | --- |
| `OPENAI_API_KEY` | Sí | Clave de la API de OpenAI. |
| `OPENAI_MODEL` | No | Modelo a usar (por defecto `gpt-4o-mini`). Debe estar habilitado en tu organización. |
| `OPENAI_MAX_TOKENS` | No | Límite de tokens de la respuesta (por defecto 3000). En modelos de razonamiento incluye los tokens de razonamiento: si es muy bajo, la respuesta llega vacía. |
| `OPENAI_REASONING_EFFORT` | No | `minimal`, `low`, `medium` o `high`. Solo para modelos de razonamiento; si el modelo no lo soporta, no lo definas. |
| `ANTHROPIC_API_KEY` | No | Solo para que Claude redacte el texto de cada rotación. |

## Si el chat falla

Revisa la terminal de uvicorn: los errores de OpenAI se imprimen como `[Asistente] OpenAI <código>: ...`.

- **401**: clave incorrecta, revocada o con espacios/comillas en el `.env`.
- **404 / "model not found"**: el modelo de `OPENAI_MODEL` no está disponible para tu organización.
- **429**: sin créditos o límite de uso alcanzado.
- **"agotó su límite de tokens"**: sube `OPENAI_MAX_TOKENS` o baja `OPENAI_REASONING_EFFORT`.

## Seguridad y costos

- No pongas la clave API en `script.js`, `index.html` ni en ningún archivo público.
- No subas `.env` a GitHub (ya está en `.gitignore`). Si una clave se publicó o se compartió, revócala y genera otra.
- Las llamadas al chatbot consumen tokens y pueden generar cargos.
- Para desplegar públicamente, agrega autenticación, límites de solicitudes y restringe CORS (hoy `main.py` permite cualquier origen) en `/api/asistente`.
- Los datos agrícolas enviados como contexto se transmiten a OpenAI para generar la respuesta.

## Nota sobre la suscripción

La suscripción de ChatGPT y la facturación de la API son sistemas separados. Comprueba que tu organización de API tenga créditos o facturación habilitada antes de probar el chatbot.


---

## Evaluador de cultivo (nuevo)

La página incluye una sección **Evaluador de cultivo** que usa el mismo motor que `evaluador_cultivos.py` por consola.
Con el punto del mapa y una fecha de siembra responde con un puntaje de 0 a 100, el factor limitante, el detalle de cada
componente (temperatura, heladas, calor, lluvia, textura, fertilidad, nitrógeno, duración) y recomendaciones.
Tiene dos modos: **Evaluar un cultivo** (nombre científico) y **Recomendar cultivos** (ranking del catálogo).
El asistente de chat también recibe ese resultado y lo puede explicar.

### Archivos nuevos

| Archivo | Para qué sirve |
| --- | --- |
| `evaluador_cultivos.py` | El evaluador original (sin cambios). |
| `evaluador_servicio.py` | Adaptador: convierte el resultado a JSON y los `sys.exit()` en errores legibles. |
| `static/evaluador.js` | Interfaz del evaluador y resumen para el asistente. |
| `cultivos_unificado.csv` | **Debes copiarlo aquí** (junto a `main.py`): es el catálogo que lee el evaluador. |
| `datos_locales/` | Solo si usas “Archivos guardados” en opciones avanzadas (CSV de NASA POWER y SoilGrids). |

Variables opcionales: `EVALUADOR_CATALOGO` (ruta del catálogo) y `EVALUADOR_DIR_DATOS` (carpeta de datos locales).

### Endpoints

- `GET /api/evaluador/cultivos` lista los cultivos del catálogo y sus categorías.
- `POST /api/evaluador` evalúa. Con `cultivo` devuelve un cultivo; sin él, un ranking (`tipo`, `categoria`, `top`).

Las descargas de clima y suelo se guardan en `.cache_agro/`, así que repetir un punto es rápido. La primera consulta
de un lugar puede tardar uno o dos minutos porque SoilGrids limita las consultas.
Instala la dependencia nueva con `pip install -r requirements.txt` (agrega `pandas`).
