"""Predicción de déficit hídrico / sequía y tendencia climática con series MENSUALES de NASA POWER.

Por punto se pide una sola consulta (T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, 1991 -> hoy) y de ahí salen:
  1) Déficit hídrico: balance = evapotranspiración (Hargreaves-Samani) - lluvia. Se proyectan los próximos
     12 meses = promedio de cada mes (últimos 30 años) + tendencia lineal común. Además se mide la sequía
     ACTUAL con un índice estandarizado del balance de los últimos 3 meses (parecido al SPEI-3).
  2) Tendencia climática: pendiente lineal de temperatura (°C/década), lluvia anual (%/década) y déficit.
Es extrapolación estadística, no un modelo climático.
"""
import calendar
import math
import warnings
from datetime import date

import numpy as np

from datos_nasa import _pedir, _valor_valido

URL_MENSUAL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
ANIO_INICIO = 1991
VENTANA = 30  # años usados para el promedio y la tendencia de cada mes
MES3 = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _ra(lat, mes):
    """Radiación extraterrestre (MJ/m²/día), FAO-56, a mitad de mes."""
    j = 30.4 * mes - 15
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    d = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(d))))
    return 37.586 * dr * (ws * math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.sin(ws))


def _pendiente(x, y):
    """Pendiente por año y si es significativa (|t| > 2, aprox. 95 %)."""
    b, a = np.polyfit(x, y, 1)
    se = math.sqrt(np.var(y - (a + b * x), ddof=2) / np.sum((x - x.mean()) ** 2))
    return float(b), bool(se > 0 and abs(b) / se > 2.0)


def _matriz(p, nombre, anios):
    serie = p.get(nombre, {})
    filas = []
    for a in anios:
        fila = []
        for m in range(1, 13):
            v = serie.get(f"{a}{m:02d}")
            fila.append(v if _valor_valido(v) else np.nan)
        filas.append(fila)
    return np.array(filas, dtype=float)


def predecir_punto(lat, lon):
    hoy = date.today()
    r = _pedir(URL_MENSUAL, {"parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR", "community": "AG",
                             "longitude": lon, "latitude": lat, "start": ANIO_INICIO, "end": hoy.year,
                             "format": "JSON"}, timeout=90)
    if not r.ok:
        raise RuntimeError(f"NASA {r.status_code}: {r.text[:200]}")
    p = r.json()["properties"]["parameter"]
    anios = list(range(ANIO_INICIO, hoy.year + 1))
    return _analizar(lat, anios, *(_matriz(p, n, anios) for n in ("T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR")), hoy)


def _analizar(lat, anios, T, Tx, Tn, Pr, hoy):
    ny = len(anios)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        dias = np.array([[calendar.monthrange(a, m)[1] for m in range(1, 13)] for a in anios])
        P = Pr * dias                                                        # mm/mes
        ra = np.array([_ra(lat, m) for m in range(1, 13)])
        ET = np.maximum(0.0023 * 0.408 * ra * (T + 17.8) * np.sqrt(np.maximum(Tx - Tn, 0)) * dias, 0)
        D = ET - P                                                           # > 0 = falta de agua
        ok = np.isfinite(D).all(axis=1)                                      # años completos
        if ok.sum() < 15:
            raise RuntimeError("NASA no tiene una serie mensual suficiente para este punto")

        # ---- tendencia climática (años completos) ----
        x = np.array(anios, dtype=float)[ok]
        t_ann, p_ann, cwd = T[ok].mean(axis=1), P[ok].sum(axis=1), np.maximum(D[ok], 0).sum(axis=1)
        bt, st = _pendiente(x, t_ann)
        bp, sp = _pendiente(x, p_ann)
        bc, _ = _pendiente(x, cwd)
        tendencia = {"t_dec": round(bt * 10, 2), "t_sig": st,
                     "p_pct_dec": round(bp * 10 / p_ann.mean() * 100, 1) if p_ann.mean() > 1 else 0.0, "p_sig": sp,
                     "cwd_dec": round(bc * 10, 1), "periodo": f"{int(x[0])}-{int(x[-1])}"}

        # ---- pronóstico de déficit: próximos 12 meses ----
        w = slice(max(0, ny - VENTANA), ny)
        Dw = D[w]
        xw = np.repeat(np.array(anios[w], dtype=float)[:, None], 12, axis=1)
        clim = np.nanmean(Dw, axis=0)
        A = Dw - clim
        fin = np.isfinite(A)
        b, a0 = np.polyfit(xw[fin], A[fin], 1)
        s = np.nanstd(A - (a0 + b * xw), axis=0, ddof=1)
        meses = []
        for k in range(12):
            m0, anio = (hoy.month - 1 + k) % 12, hoy.year + (hoy.month - 1 + k) // 12
            mu, sd = clim[m0] + a0 + b * anio, max(s[m0], 1.0)
            if not (np.isfinite(mu) and np.isfinite(sd)):
                meses.append(None)
                continue
            meses.append({"mes": m0 + 1, "anio": anio, "deficit": round(float(mu), 1),
                          "lo": round(float(mu - 1.28 * sd), 1), "hi": round(float(mu + 1.28 * sd), 1),
                          "p_deficit": round(0.5 * (1 + math.erf(float(mu / sd) / math.sqrt(2))), 2)})
        okw = ok[w]
        et_med, p_med = ET[w][okw].sum(axis=1).mean(), P[w][okw].sum(axis=1).mean()
        cwd_hist = np.maximum(Dw[okw], 0).sum(axis=1).mean()
        dp = sum(max(0.0, m["deficit"]) for m in meses if m)
        razon = dp / et_med if et_med > 1 else 0.0
        aridez = p_med / et_med if et_med > 1 else None

        # ---- sequía actual: balance de los últimos 3 meses vs. su historia ----
        plano = D.ravel()
        idx = np.flatnonzero(np.isfinite(plano))
        sequia = {"z": None, "categoria": "sin dato reciente", "periodo": ""}
        if len(idx):
            e = int(idx[-1])
            mm = e % 12
            sumas = np.array([plano[i * 12 + mm - 2:i * 12 + mm + 1].sum() for i in range(ny) if i * 12 + mm >= 2])
            sumas = sumas[np.isfinite(sumas)]
            if len(sumas) >= 15 and np.isfinite(plano[e - 2:e + 1]).all() and sumas.std() > 0:
                z = float((plano[e - 2:e + 1].sum() - sumas.mean()) / sumas.std(ddof=1))
                cat = ("sequía extrema" if z >= 2 else "sequía severa" if z >= 1.5 else "sequía moderada" if z >= 1
                       else "exceso de humedad" if z <= -1 else "sin sequía")
                sequia = {"z": round(z, 2), "categoria": cat,
                          "periodo": f"{MES3[(mm - 2) % 12]}-{MES3[mm]} {anios[0] + e // 12}"}

    return {"nivel": "bajo" if razon < 0.15 else "medio" if razon <= 0.45 else "alto",
            "deficit_pron": round(dp, 1), "deficit_hist": round(float(cwd_hist), 1),
            "cambio_pct": round((dp - cwd_hist) / cwd_hist * 100, 1) if cwd_hist > 20 else None,
            "aridez": round(float(aridez), 2) if aridez is not None else None,
            "sequia": sequia, "meses": meses, "tendencia": tendencia}
