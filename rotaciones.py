"""Perfil climático por estación (NASA POWER, 20 parámetros) -> probabilidad de éxito
por cultivo -> 3 rotaciones de 4 cultivos por cada estación de inicio -> texto explicativo."""
import csv
import itertools
import json
import math
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date

import requests

ESTACIONES = ["invierno", "primavera", "verano", "otoño"]
_MES_A_ESTACION = {12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3}


def estacion_de_mes(mes, sur):
    if sur:  # en el hemisferio sur las estaciones se invierten
        mes = (mes + 5) % 12 + 1
    return _MES_A_ESTACION[mes]


def _norm(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


RUTA_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cultivos.csv")


def _num(texto):
    x = float(str(texto).replace(",", ".").strip())
    return int(x) if x == int(x) else x


def cargar_cultivos(ruta=RUTA_CSV):
    """Lee cultivos.csv (una fila por cultivo). Edita el CSV para cambiar rangos, agregar
    cultivos o asignar imagen (columna 'imagen' = nombre del archivo dentro de static/img/)."""
    cultivos = []
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        muestra = f.readline()
        f.seek(0)
        sep = ";" if muestra.count(";") > muestra.count(",") else ","  # Excel en español a veces guarda con ;
        for fila in csv.DictReader(f, delimiter=sep):
            cultivos.append(dict(
                id=fila["id"].strip(), nombre=fila["nombre"].strip(), familia=fila["familia"].strip(),
                t_opt=(_num(fila["t_opt_min"]), _num(fila["t_opt_max"])),
                t_letal=_num(fila["t_letal"]), t_calor=_num(fila["t_calor"]),
                agua=_num(fila["agua_mm"]), luz=_num(fila["luz_kwh"]), hongos=_num(fila["hongos"]),
                suelos=set(fila["suelos"].split()), n=fila["nitrogeno"].strip(),
                ingreso=_num(fila["ingreso"]),
                imagen=(fila.get("imagen") or "").strip() or fila["id"].strip() + ".jpg"))
    return cultivos


# columnas de cultivos.csv: id, nombre, familia, t_opt_min, t_opt_max (°C ideales), t_letal (Tmin que daña),
# t_calor (Tmax de estrés), agua_mm (por ciclo), luz_kwh (kWh/m²/día), hongos (0-1),
# suelos (separados por espacio), nitrogeno (fija / exigente / neutro), ingreso (1-5), imagen
CULTIVOS = cargar_cultivos()
ALIAS = {"tomate": "jitomate", "elote": "maiz", "frijoles": "frijol", "patata": "papa", "garbanzos": "garbanzo",
         "chicharos": "chicharo", "arveja": "chicharo", "cacahuete": "cacahuate", "mani": "cacahuate",
         "pimiento": "chile"}


def reconocer_cultivo(texto):
    t = _norm(texto)
    if not t:
        return None
    t = ALIAS.get(t, t)
    for i, c in enumerate(CULTIVOS):
        if t == c["id"] or t == _norm(c["nombre"]) or (len(t) >= 4 and (t in c["id"] or c["id"] in t)):
            return i
    return None


def _ok(v):
    return isinstance(v, (int, float)) and v > -900


# ---------- 1. PERFIL CLIMÁTICO POR ESTACIÓN ----------
def construir_perfil(datos, sur):
    """datos: {parametro: {YYYYMMDD: valor}} -> por estación: medias de TODOS los parámetros
    y las series diarias de Tmin/Tmax para calcular probabilidades."""
    series = [defaultdict(list) for _ in range(4)]
    for param, valores in datos.items():
        for fecha, v in valores.items():
            if _ok(v):
                series[estacion_de_mes(int(fecha[4:6]), sur)][param].append(v)
    if not any(s.get("T2M") for s in series):
        raise ValueError("NASA no tiene datos para este punto (¿está en el mar?)")
    return [{"medias": {p: sum(v) / len(v) for p, v in s.items() if v},
             "tmin": s.get("T2M_MIN", []), "tmax": s.get("T2M_MAX", [])} for s in series]


def _frac(lista, umbral, menor):
    if not lista:
        return 0.0
    return sum((x <= umbral) if menor else (x >= umbral) for x in lista) / len(lista)


# ---------- 2. PROBABILIDAD DE ÉXITO DE CADA CULTIVO ----------
def evaluar(c, est, suelo):
    m = est["medias"]
    t = m.get("T2M", 20)
    lo, hi = c["t_opt"]
    d = max(lo - t, t - hi, 0)
    p_frio = _frac(est["tmin"], c["t_letal"], True)
    p_calor = _frac(est["tmax"], c["t_calor"], False)
    lluvia = m.get("PRECTOTCORR", 2) * 91.25
    oferta = (lluvia + 150 * m.get("GWETROOT", .5)) * {"arenoso": .85, "arcilloso": 1.1}.get(suelo, 1)
    r = oferta / c["agua"]
    sol = m.get("ALLSKY_SFC_SW_DWN", 5)
    rh = m.get("RH2M", 60)
    sub = {
        "temp": math.exp(-0.5 * (d / 3) ** 2),
        "frio": (1 - p_frio) ** 3,
        "calor": (1 - p_calor) ** 2,
        "agua": min(1, r) ** 0.8 if r < 1 else (1 if r <= 2.5 else max(.6, 1 - .15 * (r - 2.5))),
        "luz": min(1, sol / c["luz"]) ** 1.5,
        "hum": max(.5, 1 - c["hongos"] * max(0, rh - 75) / 40),
        "suelo": 1 if (not suelo or suelo == "franco" or suelo in c["suelos"]) else .85,
    }
    textos = {
        "temp": f"la temperatura media ({t:.0f} °C) queda fuera de su rango ideal ({lo}–{hi} °C)",
        "frio": f"el {p_frio * 100:.0f}% de las noches baja de {c['t_letal']} °C y no lo soportaría",
        "calor": f"el {p_calor * 100:.0f}% de los días supera {c['t_calor']} °C",
        "agua": (f"la lluvia esperada (~{lluvia:.0f} mm) no cubre su demanda (~{c['agua']} mm)" if r < 1
                 else "hay exceso de agua y riesgo de encharcamiento"),
        "luz": f"hay poca radiación solar ({sol:.1f} kWh/m²/día)",
        "hum": f"la humedad alta ({rh:.0f}%) favorece los hongos",
        "suelo": f"el suelo {suelo} no es el ideal para este cultivo",
    }
    peor = min(sub, key=sub.get)
    if c["id"] == "barbecho":  # descanso del suelo: opción de respaldo cuando nada crece bien
        return {"prob": .35, "peor": "", "limitante": "", "datos": {"t": t, "p_frio": 0, "lluvia": lluvia}}
    return {"prob": math.prod(sub.values()), "peor": textos[peor] if sub[peor] < .75 else "",
            "limitante": textos[peor], "datos": {"t": t, "p_frio": p_frio, "lluvia": lluvia}}


def _motivo(c, ev):
    if c["id"] == "barbecho":
        return "ningún cultivo tiene buenas probabilidades en esta estación; se deja descansar el suelo con cobertura"
    d = ev["datos"]
    return (f"temperatura media de {d['t']:.0f} °C (ideal {c['t_opt'][0]}–{c['t_opt'][1]} °C), "
            f"{d['p_frio'] * 100:.0f}% de noches bajo {c['t_letal']} °C y ~{d['lluvia']:.0f} mm de lluvia "
            f"para una demanda de ~{c['agua']} mm")


# ---------- 3. ROTACIONES ----------
def _puntuar(combo, orden, prob, fam_actual):
    ps = [prob[e][i] for e, i in zip(orden, combo)]
    total = .6 * sum(ps) / 4 + .4 * min(ps)
    for k in range(4):
        a, b = CULTIVOS[combo[k]], CULTIVOS[combo[(k + 1) % 4]]
        if a["id"] == b["id"]:
            total -= .4
        elif a["familia"] == b["familia"]:
            total -= .25
        if a["n"] == "fija" and b["n"] == "exigente":
            total += .06
        elif a["n"] == "exigente" and b["n"] == "fija":
            total += .03
        elif a["n"] == "exigente" and b["n"] == "exigente":
            total -= .04
    total += .03 * (len({CULTIVOS[i]["familia"] for i in combo}) - 1)
    total -= .1 * (4 - len(set(combo)))
    total += .01 * sum(CULTIVOS[i]["ingreso"] for i in combo) / 4
    if fam_actual and CULTIVOS[combo[0]]["familia"] == fam_actual:
        total -= .3
    return total


def _reglas(combo):
    reglas = []
    for k in range(4):
        a, b = CULTIVOS[combo[k]], CULTIVOS[combo[(k + 1) % 4]]
        if a["n"] == "fija" and b["n"] == "exigente":
            reglas.append(f"{a['nombre']} fija nitrógeno en el suelo y {b['nombre'].lower()}, que lo consume mucho, lo aprovecha")
        elif a["n"] == "exigente" and b["n"] == "fija":
            reglas.append(f"tras {a['nombre'].lower()}, que agota nitrógeno, {b['nombre'].lower()} ayuda a reponerlo")
    fams = sorted({CULTIVOS[i]["familia"] for i in combo} - {"ninguna"})
    reglas.append(f"se alternan {len(fams)} familias botánicas ({', '.join(fams)}), lo que corta el ciclo de plagas y enfermedades")
    return reglas


def _texto(orden, combo, evs, reglas, nota):
    frases = [f"En {ESTACIONES[e]}: {CULTIVOS[i]['nombre']} ({evs[e][i]['prob'] * 100:.0f}% de éxito), con "
              f"{_motivo(CULTIVOS[i], evs[e][i])}." for e, i in zip(orden, combo)]
    return (nota + " " if nota else "") + " ".join(frases) + " Por qué esta rotación: " + "; ".join(reglas[:3]) + "."


def generar(perfil, cultivo_actual, tipo_suelo, lat, parametros, periodo):
    sur = lat < 0
    suelo = _norm(tipo_suelo)
    if suelo not in ("arcilloso", "arenoso", "limoso", "franco"):
        suelo = ""
    evs = [[evaluar(c, perfil[e], suelo) for c in CULTIVOS] for e in range(4)]
    prob = [[ev["prob"] for ev in fila] for fila in evs]

    idx_actual = reconocer_cultivo(cultivo_actual)
    fam_actual = CULTIVOS[idx_actual]["familia"] if idx_actual is not None else None
    nota = (f"Como hoy tienes {CULTIVOS[idx_actual]['nombre'].lower()} ({fam_actual}), la rotación empieza con otra "
            f"familia para no repetir plagas.") if idx_actual is not None else ""

    pool = {e: sorted(range(len(CULTIVOS)), key=lambda i: -prob[e][i])[:9] for e in range(4)}
    estaciones = {}
    for inicio in range(4):
        orden = [(inicio + k) % 4 for k in range(4)]
        cand = sorted(((_puntuar(cb, orden, prob, fam_actual), cb) for cb in itertools.product(*(pool[e] for e in orden))),
                      reverse=True)
        for tope in (1, 2, 3):  # rotaciones distintas entre sí
            elegidas = []
            for pt, cb in cand:
                if all(sum(a == b for a, b in zip(cb, o[1])) <= tope for o in elegidas):
                    elegidas.append((pt, cb))
                    if len(elegidas) == 3:
                        break
            if len(elegidas) == 3:
                break
        rotaciones = []
        for n, (pt, cb) in enumerate(elegidas, 1):
            reglas = _reglas(cb)
            rotaciones.append({
                "id": f"{ESTACIONES[inicio]}-{n}",
                "puntaje": round(100 * max(0, min(.99, pt / 1.1))),
                "cultivos": [{"estacion": ESTACIONES[e], "id": CULTIVOS[i]["id"], "nombre": CULTIVOS[i]["nombre"],
                              "imagen": CULTIVOS[i]["imagen"], "prob": round(100 * prob[e][i]),
                              "motivo": _motivo(CULTIVOS[i], evs[e][i]), "aviso": evs[e][i]["peor"]}
                             for e, i in zip(orden, cb)],
                "reglas": reglas,
                "texto": _texto(orden, cb, evs, reglas, nota),
            })
        evitar = [{"nombre": CULTIVOS[i]["nombre"], "imagen": CULTIVOS[i]["imagen"], "prob": round(100 * prob[inicio][i]),
                   "motivo": evs[inicio][i]["limitante"]}
                  for i in sorted(range(len(CULTIVOS)), key=lambda i: prob[inicio][i])[:3] if prob[inicio][i] < .4 and CULTIVOS[i]["id"] != "barbecho"]
        estaciones[ESTACIONES[inicio]] = {"rotaciones": rotaciones, "evitar": evitar}

    clima = []
    for e in range(4):
        m = perfil[e]["medias"]
        clima.append({"estacion": ESTACIONES[e], "t_media": round(m.get("T2M", 0), 1),
                      "t_min": round(m.get("T2M_MIN", 0), 1), "t_max": round(m.get("T2M_MAX", 0), 1),
                      "lluvia_mm": round(m.get("PRECTOTCORR", 0) * 91.25), "rh": round(m.get("RH2M", 0)),
                      "solar": round(m.get("ALLSKY_SFC_SW_DWN", 0), 1),
                      "suelo": round(m.get("GWETROOT", 0) * 100),
                      "p_helada": round(100 * _frac(perfil[e]["tmin"], 2, True))})

    resultado = {"clima": clima, "estaciones": estaciones, "hemisferio": "sur" if sur else "norte",
                 "estacion_actual": ESTACIONES[estacion_de_mes(date.today().month, sur)],
                 "parametros_usados": len(parametros), "periodo": periodo,
                 "cultivo_reconocido": idx_actual is not None or not cultivo_actual,
                 "redactado_por": "plantilla"}
    try:
        if _redactar_con_llm(resultado):
            resultado["redactado_por"] = "Claude (IA)"
    except Exception as error:
        print(f"[LLM] No se pudo redactar con IA, se usa la plantilla: {error}")
    return resultado


# ---------- 4. TEXTO EXPLICATIVO CON IA (opcional) ----------
def _redactar_con_llm(resultado):
    """Si existe ANTHROPIC_API_KEY, Claude redacta la explicación de cada rotación a partir
    de los hechos calculados. Si no hay clave, se queda el texto de plantilla."""
    clave = os.getenv("ANTHROPIC_API_KEY")
    if not clave:
        return False
    hechos = {r["id"]: {"puntaje": r["puntaje"], "cultivos": r["cultivos"], "reglas": r["reglas"]}
              for est in resultado["estaciones"].values() for r in est["rotaciones"]}
    prompt = ("Eres un agrónomo que explica a agricultores. Para CADA rotación escribe 3 o 4 frases en español "
              "sencillo que expliquen por qué ese cultivo va en esa estación (clima, heladas, lluvia) y por qué "
              "el orden ayuda al suelo y a las plagas. Usa SOLO los datos dados; no inventes cifras. "
              "Responde únicamente un JSON {\"id\": \"texto\"} sin markdown.\n\n" + json.dumps(hechos, ensure_ascii=False))
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=90,
                      headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 4000,
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    texto = re.sub(r"^```(?:json)?|```$", "", r.json()["content"][0]["text"].strip()).strip()
    textos = json.loads(texto)
    cambiados = 0
    for est in resultado["estaciones"].values():
        for rot in est["rotaciones"]:
            if isinstance(textos.get(rot["id"]), str):
                rot["texto"] = textos[rot["id"]]
                cambiados += 1
    return cambiados > 0
