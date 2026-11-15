#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evaluador de aptitud de cultivos.

Entrada : coordenadas decimales (WGS84) + fecha(s) de siembra (+ cosecha opcional)
Fuentes : NASA POWER (clima diario)  y  SoilGrids v2.0 (suelo)
Catálogo: cultivos_unificado.csv (EcoCrop + NodDB)
Salida  : puntaje 0-100 por cultivo, factor limitante y recomendaciones.

Dos modos:
  * Evaluar un cultivo concreto (nombre científico):
        python evaluador_cultivos.py --lat 19.0833 --lon -96.15 \
            --siembra 2026-06-01 --cultivo "Zea mays"
  * Recomendar los mejores cultivos para ese lugar y fechas:
        python evaluador_cultivos.py --lat 19.0833 --lon -96.15 \
            --siembra 2026-06-01 --top 15 --tipo anual

Ventana de siembra (busca la mejor fecha, paso semanal):
        --siembra 2026-05-15 --siembra-fin 2026-07-15
Cosecha deseada (revisa si el ciclo cabe en el tiempo disponible):
        --siembra 2026-06-01 --cosecha 2026-10-15

Modo local (sin internet): usa CSV ya descargados en una carpeta. Las coordenadas
del CSV deben coincidir con --lat/--lon (tolerancia por defecto ±0.001°):
        python evaluador_cultivos.py --modo local --dir-datos datos_locales \
            --lat 19.0833 --lon -96.15 --siembra 2026-06-01 --top 15
        python evaluador_cultivos.py --modo local --listar-local   # ver qué hay en la carpeta

Dependencias:  pip install requests pandas numpy
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# Windows: la consola suele usar cp1252 y los símbolos (→ ≈ █ ⚠ ...) provocan UnicodeEncodeError.
# Se fuerza UTF-8 en la salida; en Linux/macOS ya lo es y esto no cambia nada.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# =========================================================================== #
# CONFIGURACIÓN
# =========================================================================== #
CATALOGO_DEFECTO = "cultivos_unificado.csv"
CACHE_DIR = Path(".cache_agro")

# --- NASA POWER ---
NASA_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M",
               "ALLSKY_SFC_SW_DWN"]
NASA_RETRASO_DIAS = 15        # NASA publica con retraso; no pedimos los últimos días
ANIOS_CLIMATOLOGIA = 5        # años históricos para estimar fechas futuras

# --- SoilGrids ---
SOIL_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
SOIL_PROPS = ["phh2o", "soc", "clay", "sand", "silt", "bdod", "nitrogen", "cec"]
SOIL_DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]
PESOS_PROF = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15, "30-60cm": 30}
PROF_RAIZ = ["0-5cm", "5-15cm", "15-30cm", "30-60cm"]   # textura
PROF_SUP = ["0-5cm", "5-15cm", "15-30cm"]               # fertilidad

# --- HTTP ---
TIMEOUT = 60
MAX_REINTENTOS = 6
BACKOFF_BASE = 4.0
BACKOFF_MAX = 120.0
RETRY_STATUS = {429, 500, 502, 503, 504}
PACING_SOIL = 13              # s entre propiedades en el modo de respaldo

# --- Pesos del puntaje (se renormalizan sobre los componentes disponibles) ---
PESOS = {
    "temperatura": 0.30, "frio": 0.10, "calor": 0.05, "lluvia": 0.20,
    "duracion": 0.05, "textura": 0.12, "fertilidad": 0.10, "nitrogeno": 0.08,
}
UMBRAL_LIMITANTE = 0.20       # si un componente baja de esto, el puntaje se topa
TOPE_LIMITANTE = 40.0
CLASES = [(75, "Muy apto"), (55, "Apto"), (35, "Marginal"), (0, "No recomendable")]

# --- Calibración del suelo (SUPUESTOS editables; escala de nivel 1=bajo..3=alto) ---
NIVEL_SOC = (8.0, 30.0)       # g/kg      -> nivel 1 .. 3
NIVEL_CEC = (8.0, 25.0)       # cmol(c)/kg
NIVEL_N = (0.8, 2.5)          # g/kg (N total)
SOC_ORGANICO = 120.0          # g/kg: por encima se considera suelo orgánico
NIVEL_REQ = {"low": 1.0, "moderate": 2.0, "high": 3.0}

ETIQ = {
    "temperatura": "Temperatura", "frio": "Frío/heladas", "calor": "Calor extremo",
    "lluvia": "Lluvia", "duracion": "Duración del ciclo", "textura": "Textura del suelo",
    "fertilidad": "Fertilidad", "nitrogeno": "Nitrógeno",
}


# =========================================================================== #
# UTILIDADES
# =========================================================================== #
def parse_fecha(txt: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(txt.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha inválida '{txt}'. Use AAAA-MM-DD o DD/MM/AAAA.")


def mover_anio(d: date, anio: int) -> date:
    try:
        return d.replace(year=anio)
    except ValueError:            # 29 de febrero
        return d.replace(year=anio, day=28)


def es_nulo(x) -> bool:
    return x is None or (isinstance(x, float) and np.isnan(x)) or (x is pd.NA)


def clasificar(puntaje: float) -> str:
    for minimo, nombre in CLASES:
        if puntaje >= minimo:
            return nombre
    return CLASES[-1][1]


# =========================================================================== #
# HTTP con reintentos y backoff exponencial
# =========================================================================== #
def _get(url: str, params: dict, como_json: bool):
    sesion = requests.Session()
    sesion.headers.update({"User-Agent": "evaluador-cultivos/1.0"})
    ultimo_error = None
    for intento in range(MAX_REINTENTOS + 1):
        espera = None
        try:
            r = sesion.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json() if como_json else r.text
            if r.status_code in RETRY_STATUS:
                ultimo_error = f"HTTP {r.status_code}"
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    espera = float(ra)
            else:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        except (requests.Timeout, requests.ConnectionError) as e:
            ultimo_error = f"{type(e).__name__}: {e}"
        except ValueError as e:
            ultimo_error = f"Respuesta no válida: {e}"
        if intento == MAX_REINTENTOS:
            break
        if espera is None:
            espera = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** intento))
        espera += random.uniform(0, 1.5)
        print(f"  [reintento {intento + 1}/{MAX_REINTENTOS}] {ultimo_error}; "
              f"esperando {espera:.0f} s...", file=sys.stderr)
        time.sleep(espera)
    raise RuntimeError(f"Petición fallida tras {MAX_REINTENTOS} reintentos: {ultimo_error}")


# =========================================================================== #
# CLIMA: NASA POWER
# =========================================================================== #
def parsear_nasa(texto: str) -> pd.DataFrame:
    """CSV de NASA POWER -> DataFrame diario continuo indexado por fecha."""
    lineas = texto.splitlines()
    idx = next((i for i, l in enumerate(lineas) if l.strip().startswith("-END HEADER-")), -1)
    df = pd.read_csv(io.StringIO("\n".join(lineas[idx + 1:])))
    df = df.replace(-999, np.nan).replace(-999.0, np.nan)
    if {"YEAR", "MO", "DY"} <= set(df.columns):
        fechas = pd.to_datetime(dict(year=df.YEAR, month=df.MO, day=df.DY))
    else:
        fechas = pd.to_datetime(df["YEAR"].astype(int).astype(str)) + \
            pd.to_timedelta(df["DOY"] - 1, unit="D")
    df.index = fechas
    df = df.drop(columns=[c for c in ("YEAR", "MO", "DY", "DOY") if c in df.columns])
    return df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"))


def obtener_clima(lat, lon, ini: date, fin: date, usar_cache=True) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"nasa_{lat:.4f}_{lon:.4f}_{ini:%Y%m%d}_{fin:%Y%m%d}.csv"
    if usar_cache and f.exists():
        print(f"  Clima desde caché: {f}")
        return parsear_nasa(f.read_text(encoding="utf-8"))
    print(f"  Descargando NASA POWER {ini} → {fin} ...")
    texto = _get(NASA_URL, {
        "parameters": ",".join(NASA_PARAMS), "community": "AG",
        "longitude": lon, "latitude": lat,
        "start": f"{ini:%Y%m%d}", "end": f"{fin:%Y%m%d}", "format": "CSV",
    }, como_json=False)
    f.write_text(texto, encoding="utf-8")
    return parsear_nasa(texto)


class Clima:
    """Serie diaria + extracción de ventanas (observadas o climatológicas)."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.ini = df.index[0].date()
        self.fin = df.index[-1].date()
        self.arr = {k: df[k].to_numpy(float) for k in
                    ("T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M",
                     "ALLSKY_SFC_SW_DWN") if k in df.columns}

    def _ventana(self, inicio: date, dias: int):
        i0 = (inicio - self.ini).days
        i1 = i0 + dias
        if i0 < 0 or i1 > len(self.df):
            return None
        w = {k: a[i0:i1] for k, a in self.arr.items()}
        if np.isnan(w["T2M"]).mean() > 0.10:
            return None
        return w

    def ventanas(self, inicio: date, dias: int, n_anios: int):
        """Devuelve (modo, [ventanas], [años usados]) o (None, [], [])."""
        w = self._ventana(inicio, dias)
        if w is not None:
            return "observado", [w], [inicio.year]
        ws, anios = [], []
        for y in range(self.fin.year, self.ini.year - 1, -1):
            w = self._ventana(mover_anio(inicio, y), dias)
            if w is not None:
                ws.append(w)
                anios.append(y)
                if len(ws) >= n_anios:
                    break
        return ("climatologico", ws, anios) if ws else (None, [], [])


# =========================================================================== #
# SUELO: SoilGrids
# =========================================================================== #
def parsear_soilgrids(data: dict) -> pd.DataFrame:
    filas: dict = {}
    for capa in (data.get("properties") or {}).get("layers") or []:
        nombre = capa.get("name")
        d = (capa.get("unit_measure") or {}).get("d_factor") or 1
        for prof in capa.get("depths") or []:
            raw = (prof.get("values") or {}).get("mean")
            try:
                val = None if raw is None else float(raw) / float(d)
            except (TypeError, ValueError, ZeroDivisionError):
                val = None
            filas.setdefault(prof.get("label"), {})[nombre] = val
    if not filas:
        raise RuntimeError("SoilGrids no devolvió capas.")
    df = pd.DataFrame.from_dict(filas, orient="index").astype(float)
    orden = sorted(df.index, key=lambda s: int(re.match(r"(\d+)-", s).group(1)))
    return df.loc[orden][[p for p in SOIL_PROPS if p in df.columns]]


def _consulta_soil(lat, lon, props):
    return parsear_soilgrids(_get(SOIL_URL, {
        "lon": lon, "lat": lat, "property": props, "depth": SOIL_DEPTHS, "value": "mean"},
        como_json=True))


def obtener_suelo(lat, lon, usar_cache=True) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"soil_{lat:.4f}_{lon:.4f}.csv"
    if usar_cache and f.exists():
        print(f"  Suelo desde caché: {f}")
        return cargar_suelo_csv(str(f))
    print("  Consultando SoilGrids ...")
    try:
        df = _consulta_soil(lat, lon, SOIL_PROPS)
    except Exception as e:
        print(f"  [aviso] consulta combinada falló ({e}); propiedad por propiedad...",
              file=sys.stderr)
        partes = []
        for i, p in enumerate(SOIL_PROPS):
            if i:
                time.sleep(PACING_SOIL)
            try:
                partes.append(_consulta_soil(lat, lon, [p]))
            except Exception as e2:
                print(f"  [aviso] '{p}' omitida: {e2}", file=sys.stderr)
        if not partes:
            raise RuntimeError("No se obtuvo ningún dato de SoilGrids.")
        df = pd.concat(partes, axis=1)
    df.index.name = "depth"
    df.to_csv(f, encoding="utf-8")
    return df


def cargar_suelo_csv(ruta: str) -> pd.DataFrame:
    """Lee el CSV de soilgrids_suelo.py; 'soc_g_per_kg' -> 'soc'."""
    df = pd.read_csv(ruta, index_col=0)
    df.columns = [c.split("_")[0] for c in df.columns]
    return df.astype(float)


def _prom_pond(df, col, profs):
    if col not in df.columns:
        return np.nan
    p = [x for x in profs if x in df.index]
    v = df.loc[p, col].astype(float)
    w = pd.Series({x: PESOS_PROF[x] for x in p})
    m = v.notna()
    return float((v[m] * w[m]).sum() / w[m].sum()) if m.any() else np.nan


def textura_usda(arena, limo, arcilla) -> str:
    s, si, c = arena, limo, arcilla
    if si + 1.5 * c < 15:
        return "sand"
    if si + 1.5 * c >= 15 and si + 2 * c < 30:
        return "loamy sand"
    if (7 <= c < 20 and s > 52 and si + 2 * c >= 30) or (c < 7 and si < 50 and si + 2 * c >= 30):
        return "sandy loam"
    if 7 <= c < 27 and 28 <= si < 50 and s <= 52:
        return "loam"
    if (si >= 50 and 12 <= c < 27) or (50 <= si < 80 and c < 12):
        return "silt loam"
    if si >= 80 and c < 12:
        return "silt"
    if 20 <= c < 35 and si < 28 and s > 45:
        return "sandy clay loam"
    if 27 <= c < 40 and 20 < s <= 45:
        return "clay loam"
    if 27 <= c < 40 and s <= 20:
        return "silty clay loam"
    if c >= 35 and s > 45:
        return "sandy clay"
    if c >= 40 and si >= 40:
        return "silty clay"
    if c >= 40:
        return "clay"
    return "loam"


GRUPO_TEXTURA = {
    "sand": "light", "loamy sand": "light", "sandy loam": "light",
    "loam": "medium", "silt loam": "medium", "silt": "medium",
    "sandy clay loam": "medium", "clay loam": "medium", "silty clay loam": "medium",
    "clay": "heavy", "silty clay": "heavy", "sandy clay": "heavy",
}
ORDEN_TEXTURA = {"light": 0, "medium": 1, "heavy": 2}
NOMBRE_TEXTURA = {"light": "ligera (arenosa)", "medium": "media (franca)",
                  "heavy": "pesada (arcillosa)", "organic": "orgánica"}


def _nivel(x, rango):
    lo, hi = rango
    return float(np.clip(1 + (x - lo) / (hi - lo) * 2, 1, 3))


def perfil_suelo(df: pd.DataFrame) -> dict | None:
    """Resume SoilGrids en las variables que usa el catálogo."""
    arena = _prom_pond(df, "sand", PROF_RAIZ)
    limo = _prom_pond(df, "silt", PROF_RAIZ)
    arcilla = _prom_pond(df, "clay", PROF_RAIZ)
    soc = _prom_pond(df, "soc", PROF_SUP)
    n = _prom_pond(df, "nitrogen", PROF_SUP)
    cec = _prom_pond(df, "cec", PROF_SUP)
    p = {"arena": arena, "limo": limo, "arcilla": arcilla, "soc": soc, "nitrogeno": n,
         "cec": cec, "ph": _prom_pond(df, "phh2o", PROF_SUP),
         "bdod": _prom_pond(df, "bdod", PROF_SUP)}
    if all(np.isnan(v) for v in p.values()):
        return None
    if not any(np.isnan(v) for v in (arena, limo, arcilla)):
        p["textura_usda"] = textura_usda(arena, limo, arcilla)
        p["grupo_textura"] = "organic" if (not np.isnan(soc) and soc >= SOC_ORGANICO) \
            else GRUPO_TEXTURA[p["textura_usda"]]
    else:
        p["textura_usda"], p["grupo_textura"] = None, None
    niveles = [_nivel(x, r) for x, r in ((soc, NIVEL_SOC), (cec, NIVEL_CEC)) if not np.isnan(x)]
    p["nivel_fertilidad"] = float(np.mean(niveles)) if niveles else np.nan
    p["nivel_n"] = _nivel(n, NIVEL_N) if not np.isnan(n) else np.nan
    return p


# =========================================================================== #
# MODO LOCAL: CSV ya descargados (NasaPower.py / soilgrids_suelo.py)
# =========================================================================== #
DIR_LOCAL_DEFECTO = "datos_locales"
TOLERANCIA_DEFECTO = 0.001    # grados (~110 m). Las coordenadas deben coincidir.

_NUM = r"-?\d+(?:[._]\d+)?"
_RE_NASA_HEADER = re.compile(r"latitude\s+(-?\d+(?:\.\d+)?)\s+longitude\s+(-?\d+(?:\.\d+)?)", re.I)
_RE_SOIL_NOMBRE = re.compile(rf"lat({_NUM})_lon({_NUM})", re.I)
_RE_PAR_NOMBRE = re.compile(rf"({_NUM})_({_NUM})")


def _num(txt: str) -> float:
    return float(txt.replace("_", "."))


def _distancia_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return float(6371 * 2 * np.arcsin(np.sqrt(a)))


def inventariar_local(carpeta: Path) -> list[dict]:
    """Detecta por CONTENIDO qué CSV son de NASA POWER o SoilGrids y de qué coordenada.

    NASA : coordenadas desde la cabecera del propio archivo (con respaldo en el nombre).
    Suelo: coordenadas desde el nombre (soilgrids_lat19.0833_lon-96.15.csv o con '_' en
           lugar de '.'), porque el CSV no las incluye.
    Cualquier otro CSV (p. ej. el catálogo) se ignora.
    """
    inv = []
    for ruta in sorted(carpeta.rglob("*.csv")):
        try:
            with open(ruta, encoding="utf-8", errors="ignore") as fh:
                cabeza = fh.read(4000)
        except OSError:
            continue
        lat = lon = None
        if "NASA/POWER" in cabeza or "-BEGIN HEADER-" in cabeza:
            tipo = "nasa"
            m = _RE_NASA_HEADER.search(cabeza)
            if m:
                lat, lon = float(m.group(1)), float(m.group(2))
            else:
                m = _RE_PAR_NOMBRE.search(ruta.stem)
                if m:
                    lat, lon = _num(m.group(1)), _num(m.group(2))
        elif cabeza.lstrip().lower().startswith("depth"):
            tipo = "suelo"
            m = _RE_SOIL_NOMBRE.search(ruta.stem)
            if m:
                lat, lon = _num(m.group(1)), _num(m.group(2))
        else:
            continue
        inv.append({"tipo": tipo, "ruta": ruta, "lat": lat, "lon": lon})
    return inv


def listar_local(carpeta: Path):
    inv = inventariar_local(carpeta)
    if not inv:
        print(f"No hay CSV de NASA POWER ni SoilGrids en '{carpeta}'.")
        return
    print(f"Archivos reconocidos en '{carpeta}':")
    for e in inv:
        coord = f"lat {e['lat']}, lon {e['lon']}" if e["lat"] is not None else "SIN coordenadas"
        extra = ""
        if e["tipo"] == "nasa":
            try:
                df = parsear_nasa(e["ruta"].read_text(encoding="utf-8"))
                extra = f" | {df.index[0].date()} → {df.index[-1].date()}"
            except Exception:
                extra = " | (no se pudo leer)"
        print(f"  [{e['tipo']:<5}] {e['ruta'].name}  ({coord}){extra}")


def _coincidentes(inv, tipo, lat, lon, tol):
    return [e for e in inv if e["tipo"] == tipo and e["lat"] is not None
            and abs(e["lat"] - lat) <= tol and abs(e["lon"] - lon) <= tol]


def _error_sin_coincidencia(inv, tipo, lat, lon, tol, carpeta):
    etiqueta = "clima (NASA POWER)" if tipo == "nasa" else "suelo (SoilGrids)"
    msg = [f"No hay archivo local de {etiqueta} para lat {lat}, lon {lon} "
           f"(tolerancia ±{tol}°) en '{carpeta}'."]
    otros = [e for e in inv if e["tipo"] == tipo]
    if otros:
        msg.append("Archivos de ese tipo que sí hay (no coinciden):")
        for e in otros:
            if e["lat"] is None:
                msg.append(f"  - {e['ruta'].name}: no se pudo leer su coordenada")
            else:
                km = _distancia_km(lat, lon, e["lat"], e["lon"])
                msg.append(f"  - {e['ruta'].name}: lat {e['lat']}, lon {e['lon']} (a {km:.1f} km)")
    else:
        msg.append("No hay ningún archivo de ese tipo en la carpeta.")
    return RuntimeError("\n".join(msg))


def cargar_clima_local(inv, lat, lon, tol, carpeta) -> tuple[pd.DataFrame, list[str]]:
    """Une TODOS los CSV de NASA POWER con esa coordenada (p. ej. un archivo por año)."""
    cand = _coincidentes(inv, "nasa", lat, lon, tol)
    if not cand:
        raise _error_sin_coincidencia(inv, "nasa", lat, lon, tol, carpeta)
    dfs = [parsear_nasa(e["ruta"].read_text(encoding="utf-8")) for e in cand]
    df = pd.concat(dfs)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"))
    return df, [e["ruta"].name for e in cand]


def cargar_suelo_local(inv, lat, lon, tol, carpeta) -> tuple[pd.DataFrame, str]:
    cand = _coincidentes(inv, "suelo", lat, lon, tol)
    if not cand:
        raise _error_sin_coincidencia(inv, "suelo", lat, lon, tol, carpeta)
    cand.sort(key=lambda e: e["ruta"].stat().st_mtime, reverse=True)   # el más reciente
    if len(cand) > 1:
        print(f"  [aviso] {len(cand)} archivos de suelo coinciden; se usa el más reciente.",
              file=sys.stderr)
    return cargar_suelo_csv(str(cand[0]["ruta"])), cand[0]["ruta"].name


# =========================================================================== #
# CATÁLOGO
# =========================================================================== #
def cargar_catalogo(ruta: str) -> pd.DataFrame:
    if not Path(ruta).exists():
        sys.exit(f"No se encuentra el catálogo '{ruta}' (use --catalogo).")
    df = pd.read_csv(ruta)
    df["_clave"] = df["ScientificName"].str.strip().str.lower()
    return df


def buscar_cultivo(cat: pd.DataFrame, nombre: str) -> pd.Series:
    clave = nombre.strip().lower()
    exacto = cat[cat["_clave"] == clave]
    if len(exacto):
        return exacto.iloc[0]
    similares = cat[cat["_clave"].str.startswith(clave + " ")]["ScientificName"].tolist()
    if not similares:
        similares = difflib.get_close_matches(nombre.strip(), cat["ScientificName"].tolist(),
                                              n=6, cutoff=0.6)
    msg = f"Cultivo '{nombre}' no está en el catálogo."
    if similares:
        msg += "\n¿Quiso decir alguno de estos?\n  - " + "\n  - ".join(similares[:8])
    sys.exit(msg)


def preparar_cultivo(row: pd.Series) -> dict:
    """Limpia y valida los requerimientos de una fila del catálogo."""
    g = lambda k: None if es_nulo(row.get(k)) else row.get(k)
    topmn, topmx = sorted((float(row["TOPMN"]), float(row["TOPMX"])))
    topmx = max(topmx, topmn + 0.01)
    tmin = min(float(row["TMIN"]), topmn - 1.0)
    tmax = max(float(row["TMAX"]), topmx + 1.0)
    ktmp = None if es_nulo(row.get("KTMP")) else float(row["KTMP"])
    gmin = g("GMIN"); gmax = g("GMAX")
    gmin = float(gmin) if gmin and float(gmin) > 0 else None   # 0 = sin dato
    gmax = float(gmax) if gmax and float(gmax) > 0 else None
    texturas = [t.strip() for t in str(g("TEXT") or "").split(",") if t.strip()]
    nombres = [n.strip() for n in str(g("COMNAME") or "").split(",") if n.strip()]
    dem_n = g("demanda_N")
    return {
        "cientifico": row["ScientificName"],
        "comun": ", ".join(nombres[:3]),
        "categoria": g("CAT") or "", "ciclo_vida": g("LISPA") or "",
        "familia": (g("FAMNAME") or "").split(":")[-1],
        "topmn": topmn, "topmx": topmx, "tmin": tmin, "tmax": tmax, "ktmp": ktmp,
        "ropmn": float(row["ROPMN"]), "gmin": gmin, "gmax": gmax,
        "texturas": texturas, "fer": g("FER"),
        "demanda_n": float(dem_n) if dem_n is not None else None,
        "fija_n": g("fija_N"), "fija_n_puntaje": float(g("fija_N_puntaje") or 0.0),
        "datos_dudosos": bool(float(row["TOPMN"]) > float(row["TOPMX"]) or float(row["TOPMN"]) > 40),
    }


def duracion_ciclo(c: dict) -> tuple[int, bool]:
    """Días de ciclo estimados: punto medio GMIN-GMAX. Devuelve (días, es_supuesto)."""
    vals = [v for v in (c["gmin"], c["gmax"]) if v]
    if not vals:
        return 120, True
    return int(round(sum(vals) / len(vals))), False


# =========================================================================== #
# PUNTAJE
# =========================================================================== #
def componentes_suelo(c: dict, perfil: dict | None) -> dict:
    """Componentes que no dependen de la fecha. Cada uno -> (puntaje 0-1, detalle)."""
    out = {}
    if perfil is None:
        return out
    # --- Textura ---
    grupo = perfil.get("grupo_textura")
    if grupo and c["texturas"] and "wide" not in c["texturas"]:
        if grupo == "organic":
            s = 1.0 if "organic" in c["texturas"] else 0.5
        else:
            cls = [t for t in c["texturas"] if t in ORDEN_TEXTURA]
            if cls:
                dist = min(abs(ORDEN_TEXTURA[grupo] - ORDEN_TEXTURA[t]) for t in cls)
                s = {0: 1.0, 1: 0.6, 2: 0.2}[dist]
            else:
                s = None
        if s is not None:
            out["textura"] = (s, f"suelo {NOMBRE_TEXTURA[grupo]} ({perfil['textura_usda']}); "
                                 f"el cultivo prefiere: {', '.join(c['texturas'])}")
    # --- Fertilidad (FER vs. CIC + carbono orgánico) ---
    req = NIVEL_REQ.get(c["fer"])
    nf = perfil.get("nivel_fertilidad")
    if req and nf is not None and not np.isnan(nf):
        deficit = max(0.0, req - nf)
        out["fertilidad"] = (max(0.0, 1 - 0.35 * deficit),
                             f"nivel del suelo {nf:.1f}/3 (COS {perfil['soc']:.1f} g/kg, "
                             f"CIC {perfil['cec']:.1f}); el cultivo pide '{c['fer']}'")
    # --- Nitrógeno (demanda_N, aliviada por fijación biológica) ---
    nn = perfil.get("nivel_n")
    if c["demanda_n"] and nn is not None and not np.isnan(nn):
        dem_ef = max(1.0, c["demanda_n"] - c["fija_n_puntaje"])
        deficit = max(0.0, dem_ef - nn)
        extra = f", fijador de N ({c['fija_n']})" if c["fija_n_puntaje"] >= 0.5 else ""
        out["nitrogeno"] = (max(0.0, 1 - 0.35 * deficit),
                            f"N total {perfil['nitrogeno']:.2f} g/kg (nivel {nn:.1f}/3); "
                            f"demanda {c['demanda_n']:.0f}/3{extra}")
    return out


def puntuar_ventana(c: dict, w: dict, dias: int, riego: bool, dias_disp: int | None) -> dict:
    """Componentes de clima para UNA ventana (un año). Devuelve {nombre: (score, detalle)}."""
    t, tx, tn, p = w["T2M"], w["T2M_MAX"], w["T2M_MIN"], w["PRECTOTCORR"]
    out, m = {}, {}

    # Temperatura: trapecio EcoCrop sobre la media diaria
    s_dia = np.interp(t, [c["tmin"], c["topmn"], c["topmx"], c["tmax"]], [0, 1, 1, 0])
    out["temperatura"] = float(np.nanmean(s_dia))
    m["t_media"] = float(np.nanmean(t))

    # Frío: % de noches bajo la temperatura letal (KTMP; si falta, TMIN aproximado)
    umbral = c["ktmp"] if c["ktmp"] is not None else c["tmin"]
    frac = float(np.nanmean(tn < umbral))
    out["frio"] = max(0.0, 1 - (10.0 if c["ktmp"] is not None else 1.0) * frac)
    m.update(frac_frio=frac, umbral_frio=umbral, umbral_frio_real=c["ktmp"] is not None,
             tmin_abs=float(np.nanmin(tn)))

    # Calor: % de días con T2M_MAX por encima de TMAX
    frac_c = float(np.nanmean(tx > c["tmax"]))
    out["calor"] = max(0.0, 1 - 3.0 * frac_c)
    m["frac_calor"] = frac_c

    # Lluvia acumulada del ciclo vs. ROPMN
    ptot = float(np.nanmean(p) * len(p)) if np.isfinite(p).any() else np.nan
    m["p_total"] = ptot
    if not np.isnan(ptot):
        out["lluvia"] = 1.0 if riego else float(np.clip(ptot / c["ropmn"], 0, 1))
        m["deficit"] = max(0.0, c["ropmn"] - ptot)

    # Duración del ciclo (solo si el usuario dio fecha de cosecha)
    if dias_disp is not None and (c["gmin"] or c["gmax"]):
        if c["gmin"] and dias_disp < c["gmin"]:
            out["duracion"] = dias_disp / c["gmin"]
        elif c["gmax"] and dias_disp > c["gmax"]:
            out["duracion"] = max(0.0, 1 - (dias_disp - c["gmax"]) / c["gmax"])
        else:
            out["duracion"] = 1.0
    for k in ("RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"):
        if k in w and np.isfinite(w[k]).any():
            m[k] = float(np.nanmean(w[k]))
    return {"scores": out, "metricas": m}


def evaluar_en_fecha(c, clima: Clima, siembra: date, cosecha: date | None,
                     comp_suelo: dict, riego: bool, n_anios: int) -> dict | None:
    if cosecha:
        dias, supuesto = (cosecha - siembra).days + 1, False
    else:
        dias, supuesto = duracion_ciclo(c)
    modo, ventanas, anios = clima.ventanas(siembra, dias, n_anios)
    if not ventanas:
        return None
    res = [puntuar_ventana(c, w, dias, riego, dias if cosecha else None) for w in ventanas]
    comps = {}
    for k in res[0]["scores"]:
        vals = [r["scores"][k] for r in res if k in r["scores"]]
        comps[k] = float(np.mean(vals))
    met = {}
    for k in res[0]["metricas"]:
        vals = [r["metricas"][k] for r in res if k in r["metricas"]]
        met[k] = float(np.mean(vals)) if not isinstance(vals[0], bool) else vals[0]
    ps = [r["metricas"]["p_total"] for r in res if not np.isnan(r["metricas"]["p_total"])]
    met["p_min"], met["p_max"] = (min(ps), max(ps)) if ps else (np.nan, np.nan)
    met["tmin_abs"] = float(min(r["metricas"]["tmin_abs"] for r in res))

    detalles = {k: v[1] for k, v in comp_suelo.items()}
    for k, v in comp_suelo.items():
        comps[k] = v[0]

    # Puntaje total
    activos = {k: PESOS[k] for k in comps}
    total = sum(PESOS[k] * comps[k] for k in activos) / sum(activos.values())
    puntaje = 100 * total
    limitante = min(comps, key=comps.get)
    if comps[limitante] < UMBRAL_LIMITANTE:
        puntaje = min(puntaje, TOPE_LIMITANTE)
    return {
        "siembra": siembra, "dias_ciclo": dias, "ciclo_supuesto": supuesto,
        "cosecha_est": siembra + timedelta(days=dias - 1),
        "modo_clima": modo, "anios_clima": sorted(anios),
        "puntaje": round(puntaje, 1), "clase": clasificar(puntaje),
        "componentes": {k: round(v, 3) for k, v in comps.items()},
        "limitante": limitante, "metricas": met, "detalles_suelo": detalles,
    }


def fechas_candidatas(s0: date, s1: date | None) -> list[date]:
    if not s1 or s1 <= s0:
        return [s0]
    fechas, d = [], s0
    while d <= s1:
        fechas.append(d)
        d += timedelta(days=7)
    if fechas[-1] != s1:
        fechas.append(s1)
    return fechas


def evaluar_cultivo(row, clima, perfil, s0, s1=None, cosecha=None, riego=False,
                    n_anios=ANIOS_CLIMATOLOGIA) -> dict | None:
    """Evalúa un cultivo en todas las fechas candidatas y devuelve la mejor."""
    c = preparar_cultivo(row)
    comp_suelo = componentes_suelo(c, perfil)
    por_fecha = []
    for f in fechas_candidatas(s0, s1):
        r = evaluar_en_fecha(c, clima, f, cosecha, comp_suelo, riego, n_anios)
        if r:
            por_fecha.append(r)
    if not por_fecha:
        return None
    mejor = max(por_fecha, key=lambda r: r["puntaje"])
    mejor = dict(mejor)
    mejor.update(cultivo=c, por_fecha=[(r["siembra"], r["puntaje"]) for r in por_fecha],
                 consejos=generar_consejos(c, mejor, riego))
    return mejor


# =========================================================================== #
# RECOMENDACIONES EN TEXTO
# =========================================================================== #
def generar_consejos(c: dict, r: dict, riego: bool) -> list[str]:
    s, m, tips = r["componentes"], r["metricas"], []
    if c["datos_dudosos"]:
        tips.append("⚠ Los requerimientos de este cultivo en el catálogo parecen inconsistentes; "
                    "tome el resultado con cautela.")
    if c["ciclo_vida"].strip() == "perennial":
        tips.append("Cultivo perenne: el ciclo GMIN/GMAX es solo la temporada de crecimiento; "
                    "revise también heladas y sequía del resto del año.")
    if r["ciclo_supuesto"]:
        tips.append("No se encontró duración del ciclo en el catálogo; se asumieron 120 días.")
    if s.get("temperatura", 1) < 0.75:
        if m["t_media"] < c["topmn"]:
            tips.append(f"Temperatura media del ciclo ({m['t_media']:.1f} °C) por debajo del "
                        f"óptimo ({c['topmn']:.0f}–{c['topmx']:.0f} °C): pruebe una siembra en "
                        f"temporada más cálida.")
        elif m["t_media"] > c["topmx"]:
            tips.append(f"Temperatura media del ciclo ({m['t_media']:.1f} °C) por encima del "
                        f"óptimo ({c['topmn']:.0f}–{c['topmx']:.0f} °C): considere sombra, "
                        f"riego frecuente o una siembra en temporada más fresca.")
        else:
            tips.append("La temperatura sale del rango óptimo en parte del ciclo; "
                        "ajustar la fecha de siembra puede ayudar.")
    if s.get("frio", 1) < 0.8:
        tipo = "letales (KTMP)" if m["umbral_frio_real"] else "bajo el mínimo de crecimiento"
        tips.append(f"{m['frac_frio'] * 100:.0f}% de las noches caen bajo {m['umbral_frio']:.0f} °C "
                    f"({tipo}); la mínima registrada fue {m['tmin_abs']:.1f} °C. "
                    f"Riesgo de daño por frío: proteja el cultivo o adelante/atrase la siembra.")
    if s.get("calor", 1) < 0.8:
        tips.append(f"{m['frac_calor'] * 100:.0f}% de los días superan {c['tmax']:.0f} °C: "
                    f"riesgo de estrés por calor.")
    if "lluvia" in s and not riego and s["lluvia"] < 0.85:
        tips.append(f"Lluvia esperada {m['p_total']:.0f} mm contra {c['ropmn']:.0f} mm "
                    f"mínimos óptimos: faltan ≈{m['deficit']:.0f} mm. "
                    f"Planee riego complementario o captación de agua.")
    if s.get("duracion", 1) < 0.9:
        rango = f"{c['gmin'] or '?'}–{c['gmax'] or '?'}"
        tips.append(f"El tiempo disponible ({r['dias_ciclo']} días) no encaja con el ciclo del "
                    f"cultivo ({rango} días).")
    if s.get("textura", 1) < 0.8:
        tips.append("La textura del suelo no es la preferida: mejore drenaje o retención con "
                    "materia orgánica según el caso.")
    if s.get("fertilidad", 1) < 0.85:
        tips.append("Fertilidad natural algo menor a la que pide el cultivo: aplique composta/estiércol "
                    "y fertilización de acuerdo con análisis de suelo.")
    if s.get("nitrogeno", 1) < 0.85:
        tips.append("Hay déficit de nitrógeno frente a la demanda: abonos orgánicos o "
                    "rotación con una leguminosa.")
    return tips


# =========================================================================== #
# REPORTES
# =========================================================================== #
def avisos_suelo(p: dict | None) -> list[str]:
    """Variables que el catálogo no cubre; solo informativas."""
    if not p:
        return []
    out = []
    if not np.isnan(p["ph"]):
        if p["ph"] < 5.5:
            out.append(f"pH {p['ph']:.1f}: suelo ácido (encalar puede ayudar a muchos cultivos).")
        elif p["ph"] > 7.8:
            out.append(f"pH {p['ph']:.1f}: suelo alcalino (posible deficiencia de micronutrientes).")
    if not np.isnan(p["bdod"]) and p["bdod"] > 1.6:
        out.append(f"Densidad aparente {p['bdod']:.2f} kg/dm³: suelo compactado, limita raíces.")
    return out


def imprimir_encabezado(lat, lon, perfil, clima, s0, s1, cosecha, riego):
    print("=" * 78)
    print(f"Ubicación : lat {lat}, lon {lon}")
    ventana = f"{s0}" + (f" → {s1}" if s1 else "")
    print(f"Siembra   : {ventana}" + (f" | cosecha deseada: {cosecha}" if cosecha else ""))
    print(f"Clima     : NASA POWER {clima.ini} → {clima.fin}" + ("  | con riego" if riego else ""))
    if perfil:
        print(f"Suelo     : {NOMBRE_TEXTURA.get(perfil['grupo_textura'], 's/d')}"
              f" ({perfil['textura_usda']}), pH {perfil['ph']:.1f}, "
              f"COS {perfil['soc']:.1f} g/kg, N {perfil['nitrogeno']:.2f} g/kg, "
              f"CIC {perfil['cec']:.1f} cmol/kg")
        for a in avisos_suelo(perfil):
            print(f"            ↳ {a}")
    else:
        print("Suelo     : sin datos (¿agua o zona urbana?). Solo se evaluará el clima.")
    print("=" * 78)


def imprimir_detalle(r: dict):
    c = r["cultivo"]
    print(f"\n{c['cientifico']}  ({c['comun'] or 'sin nombre común'})")
    print(f"Familia: {c['familia'] or 's/d'} | Categoría: {c['categoria'] or 's/d'} | "
          f"Ciclo de vida: {c['ciclo_vida'] or 's/d'}")
    print("-" * 78)
    print(f"PUNTAJE: {r['puntaje']:.0f}/100 → {r['clase']}")
    print(f"Mejor siembra: {r['siembra']}  |  ciclo de {r['dias_ciclo']} días"
          f"{' (estimado)' if r['ciclo_supuesto'] else ''}  →  cosecha ≈ {r['cosecha_est']}")
    anios = r["anios_clima"]
    if r["modo_clima"] == "observado":
        print(f"Clima usado: datos reales de {r['siembra']} a {r['cosecha_est']}")
    else:
        print(f"Clima usado: promedio histórico de los años {', '.join(map(str, anios))} "
              f"(la fecha es futura)")
    if len(r["por_fecha"]) > 1:
        print("\nPuntaje por fecha de siembra:")
        for f, p in r["por_fecha"]:
            print(f"  {f}  {'█' * int(p / 4):<25} {p:.0f}")
    m = r["metricas"]
    det = {
        "temperatura": f"media {m['t_media']:.1f} °C; óptimo {c['topmn']:.0f}–{c['topmx']:.0f} °C "
                       f"(absolutos {c['tmin']:.0f}–{c['tmax']:.0f})",
        "frio": f"{m['frac_frio'] * 100:.1f}% de noches < {m['umbral_frio']:.0f} °C"
                f"{'' if m['umbral_frio_real'] else ' (umbral aproximado con TMIN)'}",
        "calor": f"{m['frac_calor'] * 100:.1f}% de días > {c['tmax']:.0f} °C",
        "lluvia": f"{m['p_total']:.0f} mm en el ciclo"
                  + (f" (rango entre años {m['p_min']:.0f}–{m['p_max']:.0f})"
                     if len(anios) > 1 and r['modo_clima'] != 'observado' else "")
                  + f"; mínimo óptimo {c['ropmn']:.0f} mm" if "p_total" in m else "",
        "duracion": f"{r['dias_ciclo']} días disponibles; el cultivo necesita "
                    f"{c['gmin'] or '?'}–{c['gmax'] or '?'}",
    }
    det.update(r["detalles_suelo"])
    print("\nComponentes (1.00 = ideal):")
    for k in PESOS:
        if k in r["componentes"]:
            marca = "  ◄ limitante" if k == r["limitante"] and r["componentes"][k] < 0.75 else ""
            print(f"  {ETIQ[k]:<20}{r['componentes'][k]:>5.2f}   {det.get(k, '')}{marca}")
    if r["consejos"]:
        print("\nRecomendaciones:")
        for t in r["consejos"]:
            print(f"  • {t}")


def imprimir_ranking(resultados: list[dict], top: int):
    print(f"\n{'#':>3}  {"Cultivo":<46}{'Puntaje':>8}  {'Clase':<16}{'Siembra':<12}Limitante")
    print("-" * 112)
    for i, r in enumerate(resultados[:top], 1):
        c = r["cultivo"]
        nom = c["cientifico"] + (f" ({c['comun'].split(',')[0]})" if c["comun"] else "")
        print(f"{i:>3}  {nom[:45]:<46}{r['puntaje']:>8.0f}  {r['clase']:<16}"
              f"{r['siembra']!s:<12}{ETIQ[r['limitante']]} ({r['componentes'][r['limitante']]:.2f})")
    print("\nUse --cultivo \"Nombre científico\" para ver el detalle de cualquiera.")


def serializable(r: dict) -> dict:
    d = {k: v for k, v in r.items() if k not in ("cultivo", "por_fecha")}
    d["cultivo"] = r["cultivo"]["cientifico"]
    d["nombre_comun"] = r["cultivo"]["comun"]
    d["por_fecha"] = [(str(f), p) for f, p in r["por_fecha"]]
    return json.loads(json.dumps(d, default=lambda o: str(o) if isinstance(o, date) else float(o),
                                 ensure_ascii=False))


# =========================================================================== #
# PRINCIPAL
# =========================================================================== #
def pedir(msg, conv=str):
    while True:
        try:
            return conv(input(msg).strip())
        except ValueError as e:
            print(f"  Valor inválido: {e}")


def main():
    ap = argparse.ArgumentParser(description="Evalúa o recomienda cultivos según clima y suelo.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--siembra", help="Fecha de siembra (AAAA-MM-DD o DD/MM/AAAA)")
    ap.add_argument("--siembra-fin", help="Fin de la ventana de siembra (busca la mejor fecha)")
    ap.add_argument("--cosecha", help="Fecha de cosecha deseada (opcional)")
    ap.add_argument("--cultivo", help="Nombre científico a evaluar (si se omite, recomienda)")
    ap.add_argument("--top", type=int, default=15, help="Cuántos cultivos mostrar al recomendar")
    ap.add_argument("--tipo", choices=["anual", "perenne"], help="Filtro al recomendar")
    ap.add_argument("--categoria", help="Filtro CAT al recomendar (ej. cereals, vegetables)")
    ap.add_argument("--riego", action="store_true", help="Asumir riego (no penaliza la lluvia)")
    ap.add_argument("--anios-clima", type=int, default=ANIOS_CLIMATOLOGIA)
    ap.add_argument("--catalogo", default=str(Path(__file__).with_name(CATALOGO_DEFECTO))
                    if Path(__file__).with_name(CATALOGO_DEFECTO).exists() else CATALOGO_DEFECTO)
    ap.add_argument("--modo", choices=["api", "local"], default="api",
                    help="api: descarga de NASA/SoilGrids | local: usa CSV de una carpeta")
    ap.add_argument("--dir-datos", default=None,
                    help=f"Carpeta con los CSV en modo local (defecto: ./{DIR_LOCAL_DEFECTO})")
    ap.add_argument("--tolerancia", type=float, default=TOLERANCIA_DEFECTO,
                    help="Diferencia máxima (grados) para considerar que las coordenadas coinciden")
    ap.add_argument("--listar-local", action="store_true",
                    help="Muestra los CSV reconocidos en la carpeta local y termina")
    ap.add_argument("--clima-csv", help="CSV de NASA POWER específico (ignora la búsqueda por coordenadas)")
    ap.add_argument("--suelo-csv", help="CSV de SoilGrids específico (ignora la búsqueda por coordenadas)")
    ap.add_argument("--sin-cache", action="store_true")
    ap.add_argument("--json", help="Guardar resultados en este archivo JSON")
    a = ap.parse_args()

    carpeta = Path(a.dir_datos) if a.dir_datos else (
        Path(__file__).with_name(DIR_LOCAL_DEFECTO) if Path(__file__).with_name(DIR_LOCAL_DEFECTO).is_dir()
        else Path(DIR_LOCAL_DEFECTO))
    if a.listar_local:
        if not carpeta.is_dir():
            sys.exit(f"No existe la carpeta '{carpeta}' (use --dir-datos).")
        return listar_local(carpeta)

    # --- Entradas (interactivo si faltan) ---
    if a.lat is None:
        a.lat = pedir("Latitud (decimal, ej. 19.0833): ", float)
    if a.lon is None:
        a.lon = pedir("Longitud (decimal, ej. -96.15): ", float)
    if not (-90 <= a.lat <= 90 and -180 <= a.lon <= 180):
        sys.exit("Coordenadas fuera de rango (lat -90..90, lon -180..180).")
    try:
        s0 = parse_fecha(a.siembra) if a.siembra else pedir("Fecha de siembra (AAAA-MM-DD): ", parse_fecha)
        s1 = parse_fecha(a.siembra_fin) if a.siembra_fin else None
        cosecha = parse_fecha(a.cosecha) if a.cosecha else None
    except ValueError as e:
        sys.exit(str(e))
    if s1 and s1 < s0:
        sys.exit("--siembra-fin no puede ser anterior a --siembra.")
    if cosecha and s1:
        sys.exit("Use --cosecha solo con una fecha de siembra única (sin --siembra-fin).")
    if cosecha and cosecha <= s0:
        sys.exit("La cosecha debe ser posterior a la siembra.")

    cat = cargar_catalogo(a.catalogo)
    fila = buscar_cultivo(cat, a.cultivo) if a.cultivo else None   # falla pronto si no existe

    # --- Recolección de datos ---
    print(f"\nRecolectando datos (modo {a.modo})...")
    try:
        inv = None
        if a.modo == "local" and not (a.clima_csv and a.suelo_csv):
            if not carpeta.is_dir():
                raise RuntimeError(f"No existe la carpeta de datos locales '{carpeta}' (use --dir-datos).")
            inv = inventariar_local(carpeta)

        if a.clima_csv:
            clima = Clima(parsear_nasa(Path(a.clima_csv).read_text(encoding="utf-8")))
            print(f"  Clima local: {Path(a.clima_csv).name}")
        elif a.modo == "local":
            df_c, nombres = cargar_clima_local(inv, a.lat, a.lon, a.tolerancia, carpeta)
            clima = Clima(df_c)
            print(f"  Clima local: {', '.join(nombres)}")
        else:
            hoy = date.today()
            disp = hoy - timedelta(days=NASA_RETRASO_DIAS)
            ini_clim = date(hoy.year - a.anios_clima, 1, 1)
            ini = min(ini_clim, s0)
            clima = Clima(obtener_clima(a.lat, a.lon, ini, disp, not a.sin_cache))

        if a.suelo_csv:
            suelo = cargar_suelo_csv(a.suelo_csv)
            print(f"  Suelo local: {Path(a.suelo_csv).name}")
        elif a.modo == "local":
            suelo, nombre = cargar_suelo_local(inv, a.lat, a.lon, a.tolerancia, carpeta)
            print(f"  Suelo local: {nombre}")
        else:
            suelo = obtener_suelo(a.lat, a.lon, not a.sin_cache)
    except Exception as e:
        sys.exit(f"Error al obtener datos: {e}")
    perfil = perfil_suelo(suelo)
    imprimir_encabezado(a.lat, a.lon, perfil, clima, s0, s1, cosecha, a.riego)

    kw = dict(s0=s0, s1=s1, cosecha=cosecha, riego=a.riego, n_anios=a.anios_clima)

    # --- Modo 1: un cultivo ---
    if fila is not None:
        r = evaluar_cultivo(fila, clima, perfil, **kw)
        if r is None:
            sys.exit("No hay datos climáticos suficientes para cubrir el ciclo en esas fechas. "
                     f"Los datos cargados cubren {clima.ini} → {clima.fin}.")
        imprimir_detalle(r)
        if a.json:
            Path(a.json).write_text(json.dumps(serializable(r), ensure_ascii=False, indent=2),
                                    encoding="utf-8")
        return

    # --- Modo 2: recomendar ---
    sub = cat
    if a.tipo:
        pat = "annual" if a.tipo == "anual" else "perennial"
        sub = sub[sub["LISPA"].fillna("").str.contains(pat)]
    if a.categoria:
        sub = sub[sub["CAT"].fillna("").str.contains(a.categoria, case=False)]
    print(f"Evaluando {len(sub)} cultivos...")
    resultados = []
    for _, row in sub.iterrows():
        r = evaluar_cultivo(row, clima, perfil, **kw)
        if r and not r["cultivo"]["datos_dudosos"]:
            resultados.append(r)
    if not resultados:
        sys.exit("Ningún cultivo pudo evaluarse: faltan datos climáticos para esas fechas. "
                 f"Los datos cargados cubren {clima.ini} → {clima.fin}.")
    resultados.sort(key=lambda r: r["puntaje"], reverse=True)
    imprimir_ranking(resultados, a.top)
    if a.json:
        Path(a.json).write_text(json.dumps([serializable(r) for r in resultados[:a.top]],
                                           ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON guardado en {a.json}")


if __name__ == "__main__":
    main()
