"""Evaluador de cultivos como servicio web.

Envuelve evaluador_cultivos.py (el mismo motor que se usa por línea de comandos) y devuelve
diccionarios listos para convertirse en JSON. El motor original termina el programa con
sys.exit() cuando algo falla; aquí esos errores se convierten en ErrorEvaluador para que
FastAPI pueda responder con un mensaje claro en vez de tumbar el servidor.

Archivos que necesita junto a main.py:
  cultivos_unificado.csv   catálogo de cultivos (o define EVALUADOR_CATALOGO con otra ruta)
  datos_locales/           solo para el modo "local" (o define EVALUADOR_DIR_DATOS)
"""
from __future__ import annotations

import io
import math
import os
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path

import numpy as np

import evaluador_cultivos as ev

BASE = Path(__file__).parent
CATALOGO = Path(os.getenv("EVALUADOR_CATALOGO", BASE / ev.CATALOGO_DEFECTO))
DIR_LOCAL = Path(os.getenv("EVALUADOR_DIR_DATOS", BASE / ev.DIR_LOCAL_DEFECTO))

# El caché de descargas (NASA / SoilGrids) vive junto al proyecto, no donde se lance uvicorn.
ev.CACHE_DIR = BASE / ".cache_agro"

_catalogo = {"mtime": None, "df": None}


class ErrorEvaluador(Exception):
    """Error que se puede mostrar tal cual al usuario."""


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _limpio(x):
    """Convierte numpy / fechas / NaN a tipos que json acepta."""
    if isinstance(x, dict):
        return {str(k): _limpio(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpio(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()[:10]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return None if (math.isnan(x) or math.isinf(x)) else x
    return x


def _ejecutar(funcion, *args, **kwargs):
    """Llama al motor original: atrapa sys.exit() y silencia sus print()."""
    try:
        with redirect_stdout(io.StringIO()):
            return funcion(*args, **kwargs)
    except SystemExit as salida:
        raise ErrorEvaluador(str(salida.code) if salida.code else "El evaluador terminó sin resultado.")
    except ErrorEvaluador:
        raise
    except Exception as error:
        raise ErrorEvaluador(str(error)[:600])


def _leer_catalogo():
    if not CATALOGO.exists():
        raise ErrorEvaluador(
            f"Falta el catálogo de cultivos '{CATALOGO.name}'. Cópialo junto a main.py "
            "(o define EVALUADOR_CATALOGO con su ruta) y reinicia el servidor.")
    mtime = CATALOGO.stat().st_mtime
    if _catalogo["mtime"] != mtime:
        _catalogo["df"] = _ejecutar(ev.cargar_catalogo, str(CATALOGO))
        _catalogo["mtime"] = mtime
    return _catalogo["df"]


def _fecha(txt, nombre):
    try:
        return ev.parse_fecha(txt)
    except Exception:
        raise ErrorEvaluador(f"La fecha de {nombre} no es válida. Usa el formato AAAA-MM-DD.")


# --------------------------------------------------------------------------- #
# Catálogo para el buscador del navegador
# --------------------------------------------------------------------------- #
def listar_cultivos() -> dict:
    cat = _leer_catalogo()
    cultivos, categorias = [], set()
    for _, fila in cat.iterrows():
        comun = fila.get("COMNAME")
        comun = "" if ev.es_nulo(comun) else ", ".join(x.strip() for x in str(comun).split(",")[:3] if x.strip())
        cat_txt = fila.get("CAT")
        cat_txt = "" if ev.es_nulo(cat_txt) else str(cat_txt)
        for parte in cat_txt.split(","):
            if parte.strip():
                categorias.add(parte.strip())
        cultivos.append({"cientifico": fila["ScientificName"], "comun": comun})
    return {"total": len(cultivos), "cultivos": cultivos, "categorias": sorted(categorias)}


# --------------------------------------------------------------------------- #
# Armado de resultados (misma información que imprime el programa de consola)
# --------------------------------------------------------------------------- #
def _textos_detalle(r: dict) -> dict:
    """Frase de detalle de cada componente (equivale a `det` de imprimir_detalle)."""
    c, m, anios = r["cultivo"], r["metricas"], r["anios_clima"]
    det = {
        "temperatura": f"media {m['t_media']:.1f} °C; óptimo {c['topmn']:.0f}–{c['topmx']:.0f} °C "
                       f"(absolutos {c['tmin']:.0f}–{c['tmax']:.0f})",
        "frio": f"{m['frac_frio'] * 100:.1f}% de noches < {m['umbral_frio']:.0f} °C"
                f"{'' if m['umbral_frio_real'] else ' (umbral aproximado con TMIN)'}",
        "calor": f"{m['frac_calor'] * 100:.1f}% de días > {c['tmax']:.0f} °C",
        "duracion": f"{r['dias_ciclo']} días disponibles; el cultivo necesita "
                    f"{c['gmin'] or '?'}–{c['gmax'] or '?'}",
    }
    if "p_total" in m and not np.isnan(m["p_total"]):
        rango = (f" (rango entre años {m['p_min']:.0f}–{m['p_max']:.0f})"
                 if len(anios) > 1 and r["modo_clima"] != "observado" else "")
        det["lluvia"] = f"{m['p_total']:.0f} mm en el ciclo{rango}; mínimo óptimo {c['ropmn']:.0f} mm"
    det.update(r["detalles_suelo"])
    return det


def _resultado(r: dict) -> dict:
    c = r["cultivo"]
    comp = r["componentes"]
    det = _textos_detalle(r)
    peso_total = sum(ev.PESOS[k] for k in comp)
    lim = r["limitante"]
    return _limpio({
        "cientifico": c["cientifico"], "comun": c["comun"], "familia": c["familia"],
        "categoria": c["categoria"], "ciclo_vida": c["ciclo_vida"],
        "puntaje": r["puntaje"], "clase": r["clase"],
        "siembra": r["siembra"], "cosecha_est": r["cosecha_est"],
        "dias_ciclo": r["dias_ciclo"], "ciclo_supuesto": r["ciclo_supuesto"],
        "modo_clima": r["modo_clima"], "anios_clima": r["anios_clima"],
        "limitante": {"clave": lim, "etiqueta": ev.ETIQ[lim], "valor": comp[lim]},
        "tope_aplicado": comp[lim] < ev.UMBRAL_LIMITANTE,
        "componentes": [
            {"clave": k, "etiqueta": ev.ETIQ[k], "valor": comp[k],
             "peso": round(100 * ev.PESOS[k] / peso_total),
             "detalle": det.get(k, ""),
             "limitante": k == lim and comp[k] < 0.75}
            for k in ev.PESOS if k in comp],
        "consejos": r["consejos"],
        "por_fecha": [{"fecha": f, "puntaje": p} for f, p in r["por_fecha"]],
        "requerimientos": {"temp_optima": [c["topmn"], c["topmx"]], "temp_absoluta": [c["tmin"], c["tmax"]],
                           "lluvia_min_mm": c["ropmn"], "ciclo_dias": [c["gmin"], c["gmax"]],
                           "texturas": c["texturas"], "fertilidad": c["fer"]},
        "metricas": r["metricas"],
        "datos_dudosos": c["datos_dudosos"],
    })


def _fila_ranking(r: dict) -> dict:
    c, lim = r["cultivo"], r["limitante"]
    return _limpio({
        "cientifico": c["cientifico"], "comun": c["comun"], "categoria": c["categoria"],
        "ciclo_vida": c["ciclo_vida"], "puntaje": r["puntaje"], "clase": r["clase"],
        "siembra": r["siembra"], "cosecha_est": r["cosecha_est"], "dias_ciclo": r["dias_ciclo"],
        "limitante": {"etiqueta": ev.ETIQ[lim], "valor": r["componentes"][lim]},
    })


def _encabezado(p, perfil, clima, nombres_clima, s0, s1, cosecha) -> dict:
    suelo = None
    if perfil:
        suelo = {k: perfil.get(k) for k in ("textura_usda", "grupo_textura", "ph", "soc", "nitrogeno",
                                            "cec", "arena", "limo", "arcilla", "nivel_fertilidad", "nivel_n")}
        suelo["textura"] = ev.NOMBRE_TEXTURA.get(perfil.get("grupo_textura"), None)
        suelo["avisos"] = ev.avisos_suelo(perfil)
    return _limpio({
        "lat": p["lat"], "lon": p["lon"], "siembra": s0, "siembra_fin": s1, "cosecha": cosecha,
        "riego": p["riego"], "modo": p["modo"],
        "clima": {"fuente": "NASA POWER", "ini": clima.ini, "fin": clima.fin, "archivos": nombres_clima},
        "suelo": suelo,
    })


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def evaluar(p: dict) -> dict:
    """p: lat, lon, siembra, [siembra_fin], [cosecha], [cultivo], [tipo], [categoria], [top],
    [riego], [anios_clima], [modo], [tolerancia].  Sin 'cultivo' devuelve un ranking."""
    s0 = _fecha(p["siembra"], "siembra")
    s1 = _fecha(p["siembra_fin"], "fin de la ventana") if p.get("siembra_fin") else None
    cosecha = _fecha(p["cosecha"], "cosecha") if p.get("cosecha") else None
    if s1 and s1 < s0:
        raise ErrorEvaluador("El fin de la ventana de siembra no puede ser anterior a la fecha de siembra.")
    if cosecha and s1:
        raise ErrorEvaluador("La fecha de cosecha solo se usa con una fecha de siembra única "
                             "(quita el fin de la ventana).")
    if cosecha and cosecha <= s0:
        raise ErrorEvaluador("La cosecha debe ser posterior a la siembra.")

    p = {"riego": False, "modo": "api", "anios_clima": ev.ANIOS_CLIMATOLOGIA, "top": 15,
         "tolerancia": ev.TOLERANCIA_DEFECTO, **p}
    cat = _leer_catalogo()
    fila = _ejecutar(ev.buscar_cultivo, cat, p["cultivo"]) if p.get("cultivo") else None

    # --- datos de clima y suelo ---
    nombres_clima = []
    try:
        if p["modo"] == "local":
            if not DIR_LOCAL.is_dir():
                raise ErrorEvaluador(f"No existe la carpeta de datos locales '{DIR_LOCAL.name}'.")
            inv = _ejecutar(ev.inventariar_local, DIR_LOCAL)
            df_c, nombres_clima = _ejecutar(ev.cargar_clima_local, inv, p["lat"], p["lon"], p["tolerancia"], DIR_LOCAL)
            suelo, _ = _ejecutar(ev.cargar_suelo_local, inv, p["lat"], p["lon"], p["tolerancia"], DIR_LOCAL)
            clima = ev.Clima(df_c)
        else:
            from datetime import timedelta
            hoy = date.today()
            disp = hoy - timedelta(days=ev.NASA_RETRASO_DIAS)
            ini = min(date(hoy.year - p["anios_clima"], 1, 1), s0)
            clima = ev.Clima(_ejecutar(ev.obtener_clima, p["lat"], p["lon"], ini, disp))
            suelo = _ejecutar(ev.obtener_suelo, p["lat"], p["lon"])
    except ErrorEvaluador as error:
        raise ErrorEvaluador(f"No pude obtener los datos: {error}")

    perfil = ev.perfil_suelo(suelo)
    encabezado = _encabezado(p, perfil, clima, nombres_clima, s0, s1, cosecha)
    kw = dict(s0=s0, s1=s1, cosecha=cosecha, riego=p["riego"], n_anios=p["anios_clima"])
    sin_datos = (f"No hay datos de clima suficientes para cubrir el ciclo en esas fechas. "
                 f"Los datos cargados cubren {clima.ini} → {clima.fin}.")

    # --- un cultivo ---
    if fila is not None:
        r = _ejecutar(ev.evaluar_cultivo, fila, clima, perfil, **kw)
        if r is None:
            raise ErrorEvaluador(sin_datos)
        return {"tipo": "cultivo", "encabezado": encabezado, "resultado": _resultado(r)}

    # --- ranking ---
    sub = cat
    if p.get("tipo"):
        patron = "annual" if p["tipo"] == "anual" else "perennial"
        sub = sub[sub["LISPA"].fillna("").str.contains(patron)]
    if p.get("categoria"):
        sub = sub[sub["CAT"].fillna("").str.contains(p["categoria"], case=False)]
    resultados = []
    with redirect_stdout(io.StringIO()):
        for _, f in sub.iterrows():
            r = ev.evaluar_cultivo(f, clima, perfil, **kw)
            if r and not r["cultivo"]["datos_dudosos"]:
                resultados.append(r)
    if not resultados:
        raise ErrorEvaluador(sin_datos if len(sub) else "Ningún cultivo del catálogo cumple esos filtros.")
    resultados.sort(key=lambda r: r["puntaje"], reverse=True)
    return {"tipo": "ranking", "encabezado": encabezado, "evaluados": len(resultados),
            "ranking": [_fila_ranking(r) for r in resultados[:p["top"]]]}
