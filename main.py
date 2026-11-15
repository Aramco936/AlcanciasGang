import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from datos_nasa import (
    consultar_clima_historico,
    consultar_humedad_mundial,
    consultar_lluvia_mensual_gpm,
    diagnostico_imerg,
    ultimo_mes_imerg,
)

from asistente import ErrorAsistente, responder as responder_asistente
from evaluador_servicio import ErrorEvaluador, evaluar as evaluar_cultivo_servicio, listar_cultivos
from prediccion import predecir_punto
from rotaciones import construir_perfil, generar
from zonas import agrupar, consultar_climatologia

# Carga el archivo .env (junto a main.py) ANTES de que asistente.py lea OPENAI_API_KEY.
# Acepta "CLAVE=valor" y también "CLAVE = \"valor\"".
load_dotenv(Path(__file__).parent / ".env", override=True)

# Windows: evita errores de codificación al imprimir en la consola (cp1252). En Linux/macOS no cambia nada.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI(title="Planeador de rotaciones")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Máximo de consultas simultáneas a NASA
HILOS_NASA = 4 


#  FORMULARIO Y ROTACIONES  

class DatosCultivo(BaseModel):
    cultivo: str = ""
    tipo_suelo: str = ""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    nombre_lugar: str = ""


# Perfil climático ya calculado por punto (la consulta de 10 años x 20 parámetros tarda)
CACHE_PERFIL = {}


@app.post("/api/rotaciones")
def generar_rotaciones(datos: DatosCultivo):
    print(f"Python recibió: {datos.model_dump()}")
    clave = (round(datos.lat, 2), round(datos.lon, 2))
    try:
        if clave not in CACHE_PERFIL:
            clima = consultar_clima_historico(datos.lat, datos.lon)
            CACHE_PERFIL[clave] = {
                "perfil": construir_perfil(clima["datos"], datos.lat < 0),
                "parametros": clima["parametros"],
                "periodo": clima["periodo"],
            }
        c = CACHE_PERFIL[clave]
        return generar(c["perfil"], datos.cultivo, datos.tipo_suelo, datos.lat, c["parametros"], c["periodo"])
    except Exception as error:
        print(f"Error generando rotaciones: {error}")
        raise HTTPException(status_code=502, detail=str(error)[:300])


#   EVALUADOR DE CULTIVOS (clima NASA POWER + suelo SoilGrids contra el catálogo)
# Mismo motor que evaluador_cultivos.py por consola. Sin "cultivo" devuelve un ranking.

class SolicitudEvaluador(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    siembra: str = Field(min_length=8, max_length=10)
    siembra_fin: str | None = None
    cosecha: str | None = None
    cultivo: str | None = Field(default=None, max_length=120)
    tipo: str | None = Field(default=None, pattern="^(anual|perenne)$")
    categoria: str | None = Field(default=None, max_length=60)
    top: int = Field(default=15, ge=1, le=50)
    riego: bool = False
    anios_clima: int = Field(default=5, ge=1, le=15)
    modo: str = Field(default="api", pattern="^(api|local)$")
    tolerancia: float = Field(default=0.001, ge=0, le=1)


@app.get("/api/evaluador/cultivos")
def catalogo_evaluador():
    try:
        return listar_cultivos()
    except ErrorEvaluador as error:
        raise HTTPException(status_code=503, detail=str(error))


@app.post("/api/evaluador")
def evaluar_cultivos(solicitud: SolicitudEvaluador):
    datos = solicitud.model_dump()
    datos["cultivo"] = (datos["cultivo"] or "").strip() or None
    datos["categoria"] = (datos["categoria"] or "").strip() or None
    print(f"Evaluador recibió: {datos}")
    try:
        return evaluar_cultivo_servicio(datos)
    except ErrorEvaluador as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception as error:
        print(f"Error en el evaluador: {error}")
        raise HTTPException(status_code=502, detail="El evaluador falló de forma inesperada. Revisa la terminal del servidor.")

#   MODELOS PARA EL MAPA MUNDI  

class PaisMapa(BaseModel):
    id: str
    nombre: str
    lat: float
    lon: float


class SolicitudHumedad(BaseModel):
    paises: list[PaisMapa]


class SolicitudLluviaMensual(BaseModel):
    paises: list[PaisMapa]
    anio: int = Field(ge=1900, le=2100)
    mes: int = Field(ge=1, le=12)


#   CACHÉ EN MEMORIA Y EN DISCO  
# Se guarda en la carpeta "cache" para que no se pierda al reiniciar uvicorn.

CARPETA_CACHE = Path(__file__).parent / "cache"
CARPETA_CACHE.mkdir(exist_ok=True)
ARCHIVO_HUMEDAD = CARPETA_CACHE / "humedad.json"
ARCHIVO_LLUVIA = CARPETA_CACHE / "lluvia.json"
ARCHIVO_ZONAS = CARPETA_CACHE / "zonas.json"
ARCHIVO_PRED = CARPETA_CACHE / "prediccion.json"
CANDADO_ARCHIVO = threading.Lock()
VIDA_CACHE_LLUVIA = 7 * 24 * 3600  # la lluvia reciente puede completarse con los días


def cargar_json(ruta):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_json(ruta, datos):
    with CANDADO_ARCHIVO:
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(datos), encoding="utf-8")
        temporal.replace(ruta)


CACHE_HUMEDAD = cargar_json(ARCHIVO_HUMEDAD)          # {id_pais: humedad}
CACHE_LLUVIA_MENSUAL = cargar_json(ARCHIVO_LLUVIA)    # {clave: {"ts":..., "meses": {...}}}
CACHE_PRED = cargar_json(ARCHIVO_PRED)                # {"id|lat|lon|AAAA-MM": predicción} (se renueva cada mes)
CACHE_ZONAS = cargar_json(ARCHIVO_ZONAS)              # {"id|lat|lon": {temp, amplitud, lluvia, humedad, estacionalidad}}


def clasificar_humedad(humedad):
    if humedad is None:
        return None
    if humedad < 40:
        return "bajo"
    if humedad <= 70:
        return "medio"
    return "alto"


#   HUMEDAD MUNDIAL  

@app.post("/api/humedad-mundial")
def obtener_humedad_mundial(solicitud: SolicitudHumedad):

    def consultar_pais(pais):
        try:
            if pais.id not in CACHE_HUMEDAD:
                humedad = consultar_humedad_mundial(pais.lat, pais.lon)
                if humedad is not None:
                    CACHE_HUMEDAD[pais.id] = humedad
            else:
                humedad = CACHE_HUMEDAD[pais.id]

            return {
                "id": pais.id,
                "nombre": pais.nombre,
                "humedad": humedad,
                "nivel": clasificar_humedad(humedad),
                "motivo": None if humedad is not None else "NASA no tiene dato para este punto",
            }

        except Exception as error:
            print(f"Error consultando humedad de {pais.nombre}: {error}")
            return {
                "id": pais.id,
                "nombre": pais.nombre,
                "humedad": None,
                "nivel": None,
                "motivo": str(error)[:160],
            }

    with ThreadPoolExecutor(max_workers=HILOS_NASA) as executor:
        resultados = list(executor.map(consultar_pais, solicitud.paises))

    guardar_json(ARCHIVO_HUMEDAD, CACHE_HUMEDAD)
    return {"resultados": resultados}


#   LLUVIA MENSUAL GPM / IMERG  

# Último mes con datos COMPLETOS que NASA realmente tiene (se descubre solo).
LIMITE_REAL = {"valor": None}


def obtener_entrada(pais, anio):
    """Lluvia de los 12 meses de un año para un país (con caché)."""
    clave = f"{pais.id}|{pais.lat:.3f}|{pais.lon:.3f}|{anio}"
    entrada = CACHE_LLUVIA_MENSUAL.get(clave)
    if entrada and time.time() - entrada["ts"] <= VIDA_CACHE_LLUVIA:
        return entrada

    datos = consultar_lluvia_mensual_gpm(pais.lat, pais.lon, inicio=anio, fin=anio)
    meses = {
        str(d["mes"]): {
            "promedio_diario_mm": d["promedio_diario_mm"],
            "lluvia_acumulada_mm": d["lluvia_acumulada_mm"],
        }
        for d in datos["datos_mensuales"]
    }
    entrada = {"ts": time.time(), "meses": meses}
    if any(m["lluvia_acumulada_mm"] is not None for m in meses.values()):
        CACHE_LLUVIA_MENSUAL[clave] = entrada
    return entrada


def _tiene_dato(entrada, mes):
    return (
        isinstance(entrada, dict)
        and entrada["meses"].get(str(mes), {}).get("lluvia_acumulada_mm") is not None
    )


@app.post("/api/lluvia-mensual")
def obtener_lluvia_mensual(solicitud: SolicitudLluviaMensual):

    ultimo = ultimo_mes_imerg()
    if LIMITE_REAL["valor"]:
        ultimo = min(ultimo, LIMITE_REAL["valor"])

    anio, mes = solicitud.anio, solicitud.mes
    ajustado = (anio, mes) > ultimo
    if ajustado:
        anio, mes = ultimo

    def cargar_anio(anio_):
        def una(pais):
            try:
                return obtener_entrada(pais, anio_)
            except Exception as error:
                print(f"Error consultando lluvia de {pais.nombre}: {error}")
                return str(error)[:160]
        with ThreadPoolExecutor(max_workers=HILOS_NASA) as executor:
            return list(executor.map(una, solicitud.paises))

    entradas = cargar_anio(anio)
    buenas = [e for e in entradas if isinstance(e, dict)]
    umbral = max(1, min(3, len(buenas) // 2))

    # Si casi ningún país tiene datos de ese mes, NASA aún no lo publica:
    # se busca el último mes que sí tenga datos completos.
    if buenas and sum(_tiene_dato(e, mes) for e in buenas) < umbral:
        encontrado = None
        for m in range(mes - 1, 0, -1):
            if sum(_tiene_dato(e, m) for e in buenas) >= umbral:
                encontrado = (anio, m)
                break
        if encontrado is None and anio - 1 >= 2000:
            anteriores = cargar_anio(anio - 1)
            buenas_ant = [e for e in anteriores if isinstance(e, dict)]
            for m in range(12, 0, -1):
                if sum(_tiene_dato(e, m) for e in buenas_ant) >= umbral:
                    encontrado = (anio - 1, m)
                    entradas = anteriores
                    break
        if encontrado:
            anio, mes = encontrado
            ajustado = True
            LIMITE_REAL["valor"] = encontrado
            print(f"[IMERG] Último mes completo disponible: {mes}/{anio}")

    resultados = []
    for pais, entrada in zip(solicitud.paises, entradas):
        base = {"id": pais.id, "nombre": pais.nombre, "anio": anio, "mes": mes}
        if not isinstance(entrada, dict):
            resultados.append({**base, "promedio_diario_mm": None,
                               "lluvia_acumulada_mm": None, "motivo": entrada})
        elif _tiene_dato(entrada, mes):
            resultados.append({**base, **entrada["meses"][str(mes)]})
        else:
            resultados.append({**base, "promedio_diario_mm": None,
                               "lluvia_acumulada_mm": None,
                               "motivo": "NASA no tiene lluvia IMERG completa para este punto y mes"})

    guardar_json(ARCHIVO_LLUVIA, CACHE_LLUVIA_MENSUAL)

    return {
        "fuente": "NASA POWER - GPM IMERG",
        "variable": "IMERG_PRECTOT",
        "unidad": "mm",
        "tipo": "lluvia acumulada mensual estimada",
        "ajustado": ajustado,
        "anio_mostrado": anio,
        "mes_mostrado": mes,
        "resultados": resultados,
    }

#   ZONAS AGROCLIMÁTICAS (K-MEANS)  
# Se hace en dos pasos para que el mapa se vaya llenando por lotes como las demás capas:
#   1) /api/zonas-clima   -> clima de cada país (NASA POWER, con caché en disco)
#   2) /api/zonas-agrupar -> K-means con todos los países juntos (no consulta a NASA, es instantáneo)

class ValoresClima(BaseModel):
    temp: float
    amplitud: float
    lluvia: float
    humedad: float
    estacionalidad: float


class SolicitudAgrupar(BaseModel):
    puntos: dict[str, ValoresClima]
    k: int | None = Field(default=None, ge=2, le=8)  # None = se elige solo con silhouette


@app.post("/api/zonas-clima")
def obtener_clima_para_zonas(solicitud: SolicitudHumedad):

    def consultar_pais(pais):
        clave = f"{pais.id}|{pais.lat:.3f}|{pais.lon:.3f}"
        try:
            if clave not in CACHE_ZONAS:
                datos = consultar_climatologia(pais.lat, pais.lon)
                if datos is None:
                    return {"id": pais.id, "nombre": pais.nombre, "valores": None,
                            "motivo": "NASA no tiene dato para este punto"}
                CACHE_ZONAS[clave] = datos
            return {"id": pais.id, "nombre": pais.nombre, "valores": CACHE_ZONAS[clave], "motivo": None}
        except Exception as error:
            print(f"Error consultando clima de {pais.nombre}: {error}")
            return {"id": pais.id, "nombre": pais.nombre, "valores": None, "motivo": str(error)[:160]}

    with ThreadPoolExecutor(max_workers=HILOS_NASA) as executor:
        resultados = list(executor.map(consultar_pais, solicitud.paises))

    guardar_json(ARCHIVO_ZONAS, CACHE_ZONAS)
    return {"resultados": resultados}


@app.post("/api/zonas-agrupar")
def agrupar_zonas(solicitud: SolicitudAgrupar):
    puntos = {pid: v.model_dump() for pid, v in solicitud.puntos.items()}
    try:
        grupo = agrupar(puntos, solicitud.k)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"fuente": "NASA POWER - climatología (T2M, RH2M, PRECTOTCORR) + K-means", **grupo}


#   PREDICCIÓN: DÉFICIT HÍDRICO / SEQUÍA Y TENDENCIA CLIMÁTICA
# Una consulta mensual por país (NASA POWER) alimenta las dos capas del mapa. La tendencia "por zona"
# se promedia en el navegador con las zonas K-means que ya existen.

@app.post("/api/prediccion-clima")
def obtener_prediccion(solicitud: SolicitudHumedad):
    mes_actual = date.today().strftime("%Y-%m")

    def consultar_pais(pais):
        clave = f"{pais.id}|{pais.lat:.3f}|{pais.lon:.3f}|{mes_actual}"
        try:
            if clave not in CACHE_PRED:
                CACHE_PRED[clave] = predecir_punto(pais.lat, pais.lon)
            return {"id": pais.id, "nombre": pais.nombre, "valores": CACHE_PRED[clave], "motivo": None}
        except Exception as error:
            print(f"Error en predicción de {pais.nombre}: {error}")
            return {"id": pais.id, "nombre": pais.nombre, "valores": None, "motivo": str(error)[:160]}

    with ThreadPoolExecutor(max_workers=HILOS_NASA) as executor:
        resultados = list(executor.map(consultar_pais, solicitud.paises))

    guardar_json(ARCHIVO_PRED, CACHE_PRED)
    return {"fuente": "NASA POWER - series mensuales (T2M, T2M_MAX, T2M_MIN, PRECTOTCORR)", "resultados": resultados}


#   ASISTENTE (CHATBOT QUE EXPLICA LOS RESULTADOS)
# El navegador manda la pregunta + un resumen de lo que el usuario ve (rotaciones, capa del mapa,
# país tocado, zonas K-means, tendencias). asistente.py lo une con la metodología y consulta a OpenAI.

class TurnoChat(BaseModel):
    rol: str = Field(pattern="^(user|assistant)$")
    texto: str = Field(max_length=20000)   # las respuestas del bot se reenvían como historial; asistente.py las recorta


class SolicitudAsistente(BaseModel):
    mensajes: list[TurnoChat] = Field(min_length=1, max_length=40)
    contexto: dict = {}


@app.post("/api/asistente")
def preguntar_al_asistente(solicitud: SolicitudAsistente):
    try:
        texto = responder_asistente([m.model_dump() for m in solicitud.mensajes], solicitud.contexto)
        return {"respuesta": texto}
    except ErrorAsistente as error:
        raise HTTPException(status_code=503, detail=str(error))
    except Exception as error:
        print(f"Error en el asistente: {error}")
        raise HTTPException(status_code=502, detail="No pude contactar a la IA. Intenta de nuevo.")


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)


if __name__ == "__main__":
    # Permite arrancar con "python main.py" en Windows, Linux y macOS (equivale a "uvicorn main:app").
    import uvicorn

    os.chdir(Path(__file__).parent)
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
