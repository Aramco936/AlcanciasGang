"""Zonas agroclimáticas: K-means sobre la climatología de NASA POWER (T2M, RH2M, PRECTOTCORR).

Cada país (o punto) se describe con 5 números:
  temp            temperatura media anual (°C)
  amplitud        mes más cálido - mes más frío (°C)
  lluvia          lluvia anual (mm/año)
  humedad         humedad relativa anual (%)
  estacionalidad  coeficiente de variación de la lluvia de los 12 meses (0 = pareja, >1 = muy estacional)

K-means agrupa los países con clima parecido; el nombre de cada zona sale del centroide.
"""
import calendar
import math

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from datos_nasa import URL_CLIMATOLOGIA, _pedir, _valor_valido

MESES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DIAS = [calendar.monthrange(2023, m)[1] for m in range(1, 13)]  # año no bisiesto
CAMPOS = ("temp", "amplitud", "lluvia", "humedad", "estacionalidad")

# Se asignan de la zona más fría a la más cálida. Evitan el verde/amarillo/rojo de las capas de riesgo.
PALETA = ["#5c6bc0", "#26a69a", "#9ccc65", "#ffd54f", "#ff8a65", "#ec407a", "#ab47bc", "#8d6e63"]


def consultar_climatologia(lat, lon):
    """Una sola consulta de climatología (promedios de muchos años) de un punto."""
    parametros = {"parameters": "T2M,RH2M,PRECTOTCORR", "community": "AG",
                  "longitude": lon, "latitude": lat, "format": "JSON"}
    r = _pedir(URL_CLIMATOLOGIA, parametros, timeout=60)
    if not r.ok:
        raise RuntimeError(f"NASA {r.status_code}: {r.text[:200]}")
    p = r.json()["properties"]["parameter"]

    t = [p["T2M"].get(m) for m in MESES]
    ll = [p["PRECTOTCORR"].get(m) for m in MESES]  # mm/día de cada mes
    if not all(_valor_valido(x) for x in t + ll):
        return None

    rh = p["RH2M"].get("ANN")
    if not _valor_valido(rh):
        vals = [v for k, v in p["RH2M"].items() if k != "ANN" and _valor_valido(v)]
        if not vals:
            return None
        rh = sum(vals) / len(vals)

    media_ll = sum(ll) / 12
    cv = float(np.std(ll) / media_ll) if media_ll > 0 else 0.0
    return {
        "temp": round(sum(t) / 12, 2),
        "amplitud": round(max(t) - min(t), 2),
        "lluvia": round(sum(d * m for d, m in zip(ll, DIAS)), 1),
        "humedad": round(rh, 2),
        "estacionalidad": round(cv, 2),
    }


def _etiqueta(c):
    temp = ("Frío" if c["temp"] < 10 else "Templado" if c["temp"] < 18
            else "Cálido" if c["temp"] < 24 else "Muy cálido")
    agua = ("árido" if c["lluvia"] < 400 else "seco" if c["lluvia"] < 1000
            else "húmedo" if c["lluvia"] < 2000 else "muy húmedo")
    regimen = "lluvia muy estacional" if c["estacionalidad"] > 0.9 else "lluvia repartida en el año"
    return f"{temp} · {agua}", regimen


def agrupar(puntos, k=None, k_max=6):
    """puntos: {id: {temp, amplitud, lluvia, humedad, estacionalidad}}
    -> {"zonas": [...], "asignacion": {id: n_zona}, "k": int, "silueta": float}
    Si k es None se prueba de 3 a k_max y se queda el de mayor silhouette."""
    ids = list(puntos)
    if len(ids) < 4:
        raise ValueError("Se necesitan al menos 4 puntos con datos para formar zonas")

    X = np.array([[puntos[i]["temp"], puntos[i]["amplitud"], math.log1p(max(puntos[i]["lluvia"], 0)),
                   puntos[i]["humedad"], puntos[i]["estacionalidad"]] for i in ids], dtype=float)
    Xs = StandardScaler().fit_transform(X)  # sin esto la lluvia dominaría a la humedad

    tope = len(ids) - 1
    candidatos = [min(k, tope)] if k else list(range(3, min(k_max, tope) + 1))
    mejor = None
    for kk in candidatos:
        modelo = KMeans(n_clusters=kk, n_init=10, random_state=0).fit(Xs)
        if len(set(modelo.labels_)) < 2:
            continue
        s = float(silhouette_score(Xs, modelo.labels_))
        if mejor is None or s > mejor[0]:
            mejor = (s, modelo)
    if mejor is None:
        raise ValueError("No se pudieron formar zonas con estos datos")
    silueta, modelo = mejor

    grupos = {}
    for i, lab in zip(ids, modelo.labels_):
        grupos.setdefault(int(lab), []).append(i)

    # Centroides en unidades reales (promedio de los miembros de cada grupo)
    centroides = {lab: {c: round(sum(puntos[m][c] for m in miembros) / len(miembros), 1) for c in CAMPOS}
                  for lab, miembros in grupos.items()}

    # De frío/seco a cálido/húmedo para que el color tenga sentido
    orden = sorted(centroides, key=lambda lab: (centroides[lab]["temp"], centroides[lab]["lluvia"]))
    zonas, id_zona, repetidos = [], {}, {}
    for n, lab in enumerate(orden):
        nombre, regimen = _etiqueta(centroides[lab])
        repetidos[nombre] = repetidos.get(nombre, 0) + 1
        if repetidos[nombre] > 1:
            nombre += f" ({repetidos[nombre]})"
        id_zona[lab] = n
        zonas.append({"id": n, "nombre": nombre, "regimen": regimen, "color": PALETA[n % len(PALETA)],
                      "centroide": centroides[lab], "paises": len(grupos[lab])})

    asignacion = {i: id_zona[int(lab)] for i, lab in zip(ids, modelo.labels_)}
    return {"zonas": zonas, "asignacion": asignacion, "k": len(zonas), "silueta": round(silueta, 3)}