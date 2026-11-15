import calendar
import re
import threading
import time
from collections import defaultdict
from datetime import date, timedelta

import requests

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
URL_CLIMATOLOGIA = "https://power.larc.nasa.gov/api/temporal/climatology/point"
PARAMETROS = "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M"

SESION = requests.Session()

# Límite GLOBAL de consultas simultáneas a NASA (humedad + lluvia juntas).
# Si NASA responde 429 muy seguido, baja este número a 1.
_SEMAFORO_NASA = threading.Semaphore(2)
_PAUSA_ENTRE_CONSULTAS = 0.25


def _pedir(url, parametros, timeout, intentos=5):
    """GET con reintentos para errores temporales (429, 5xx, red).
    Devuelve la respuesta aunque sea 4xx (como 422) para poder leer el mensaje."""
    ultimo_error = "sin respuesta"
    for n in range(intentos):
        espera = 3 * (n + 1)
        try:
            with _SEMAFORO_NASA:
                respuesta = SESION.get(url, params=parametros, timeout=timeout)
                time.sleep(_PAUSA_ENTRE_CONSULTAS)
        except requests.RequestException as error:
            ultimo_error = str(error)
            time.sleep(espera)
            continue
        if respuesta.status_code in (429, 500, 502, 503, 504):
            ultimo_error = f"HTTP {respuesta.status_code}"
            try:
                espera = max(espera, int(respuesta.headers.get("Retry-After", 0)))
            except (ValueError, AttributeError, TypeError):
                pass
            time.sleep(espera)
            continue
        return respuesta
    raise RuntimeError(f"NASA no respondió ({ultimo_error})")


def _valor_valido(valor):
    return isinstance(valor, (int, float)) and valor > -900


# 20 parámetros diarios de la comunidad AG (el máximo que permite POWER por consulta)
PARAMETROS_20 = [
    "T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "T2MWET", "TS", "RH2M", "QV2M", "PRECTOTCORR", "PS",
    "WS2M", "WS10M", "ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN", "CLOUD_AMT",
    "GWETROOT", "GWETTOP", "GWETPROF", "EVPTRNS", "EVLAND",
]
# Si NASA rechaza alguno (422), se descartan los rechazados; si no se puede, se usa este mínimo
PARAMETROS_BASE = ["T2M", "T2M_MAX", "T2M_MIN", "RH2M", "PRECTOTCORR", "WS2M", "ALLSKY_SFC_SW_DWN", "GWETROOT"]


def consultar_clima_historico(latitud, longitud, anios=10):
    """Serie diaria de hasta 20 parámetros de los últimos `anios` años completos."""
    fin_anio = date.today().year - 1
    inicio_anio = fin_anio - anios + 1
    parametros = list(PARAMETROS_20)
    respuesta = None
    for _ in range(4):
        consulta = {
            "parameters": ",".join(parametros),
            "community": "AG",
            "longitude": longitud,
            "latitude": latitud,
            "start": f"{inicio_anio}0101",
            "end": f"{fin_anio}1231",
            "format": "JSON",
        }
        respuesta = _pedir(URL, consulta, timeout=180)
        if respuesta.ok:
            break
        if respuesta.status_code != 422:
            raise RuntimeError(f"NASA {respuesta.status_code}: {respuesta.text[:200]}")
        print(f"[NASA] 422: {respuesta.text[:300]}")
        rechazados = [p for p in parametros if re.search(rf"\b{p}\b", respuesta.text)]
        if rechazados and len(parametros) - len(rechazados) >= 5:
            parametros = [p for p in parametros if p not in rechazados]
        else:
            parametros = list(PARAMETROS_BASE)
    if respuesta is None or not respuesta.ok:
        raise RuntimeError("NASA rechazó la consulta de clima")

    datos = respuesta.json()["properties"]["parameter"]
    return {"parametros": list(datos.keys()), "datos": datos, "periodo": f"{inicio_anio}-{fin_anio}"}


# ===== HUMEDAD RELATIVA (climatología) PARA EL MAPA MUNDIAL =====
def consultar_humedad_mundial(latitud, longitud):
    parametros = {
        "parameters": "RH2M",
        "community": "AG",
        "longitude": longitud,
        "latitude": latitud,
        "format": "JSON",
    }

    respuesta = _pedir(URL_CLIMATOLOGIA, parametros, timeout=60)
    if not respuesta.ok:
        raise RuntimeError(f"NASA {respuesta.status_code}: {respuesta.text[:200]}")

    humedades = respuesta.json()["properties"]["parameter"]["RH2M"]

    # La climatología trae JAN..DEC y ANN (promedio anual)
    anual = humedades.get("ANN")
    if _valor_valido(anual):
        return round(anual, 2)

    valores = [v for k, v in humedades.items() if k != "ANN" and _valor_valido(v)]
    if not valores:
        return None
    return round(sum(valores) / len(valores), 2)


# ===== LLUVIA MENSUAL GPM / IMERG =====
# IMPORTANTE: IMERG_PRECTOT NO existe en la comunidad "HY" (esa comunidad no
# existe en POWER, por eso daba 422). Las comunidades válidas son AG, RE y SB,
# y IMERG_PRECTOT se publica en "SB". Se prueban en orden por si NASA cambia.
COMUNIDADES_IMERG = ["SB", "AG", "RE"]
LATENCIA_IMERG_DIAS = 45           # Final Run tarda 3.5 meses, pero Late Run llega casi en tiempo real
INICIO_IMERG = date(2000, 6, 1)    # primer día con datos IMERG en POWER

# Se recuerda la combinación que funcionó para no volver a probar
_config_imerg = {"comunidad": None, "desfase": 0}


def ultimo_mes_imerg():
    """Último mes COMPLETO que probablemente ya tiene datos IMERG."""
    limite = date.today() - timedelta(days=LATENCIA_IMERG_DIAS)
    ultimo_dia = calendar.monthrange(limite.year, limite.month)[1]
    if limite.day == ultimo_dia:
        return limite.year, limite.month
    if limite.month == 1:
        return limite.year - 1, 12
    return limite.year, limite.month - 1


def _pedir_imerg(latitud, longitud, fecha_inicio, fecha_fin):
    comunidad_conocida = _config_imerg["comunidad"]
    comunidades = [comunidad_conocida] if comunidad_conocida else COMUNIDADES_IMERG
    base = _config_imerg["desfase"]
    desfases = [base, base + 30, base + 60]

    ultimo_error = ""
    for comunidad in comunidades:
        for desfase in desfases:
            fin = fecha_fin - timedelta(days=desfase)
            if fin < fecha_inicio:
                return {}

            parametros = {
                "parameters": "IMERG_PRECTOT",
                "community": comunidad,
                "longitude": longitud,
                "latitude": latitud,
                "start": fecha_inicio.strftime("%Y%m%d"),
                "end": fin.strftime("%Y%m%d"),
                "format": "JSON",
                # IMERG solo existe en UTC; sin esto NASA devuelve todo en -999
                "time-standard": "UTC",
            }
            respuesta = _pedir(URL, parametros, timeout=90)

            if respuesta.ok:
                _config_imerg["comunidad"] = comunidad
                _config_imerg["desfase"] = desfase
                return respuesta.json()["properties"]["parameter"]["IMERG_PRECTOT"]

            ultimo_error = f"NASA {respuesta.status_code}: {respuesta.text[:200]}"
            print(f"[IMERG] {ultimo_error} (community={comunidad}, end={parametros['end']})")
            if respuesta.status_code != 422:
                break

    raise RuntimeError(ultimo_error or "NASA rechazó la consulta de lluvia")


def consultar_lluvia_mensual_gpm(latitud, longitud, inicio=2020, fin=2026):
    fecha_inicio = max(date(inicio, 1, 1), INICIO_IMERG)
    fecha_fin = min(date(fin, 12, 31), date.today() - timedelta(days=LATENCIA_IMERG_DIAS))

    resultados_por_mes = defaultdict(list)

    if fecha_inicio <= fecha_fin:
        precipitaciones = _pedir_imerg(latitud, longitud, fecha_inicio, fecha_fin)
        for fecha, valor in precipitaciones.items():
            if not _valor_valido(valor) or valor < 0:
                continue
            resultados_por_mes[(int(fecha[:4]), int(fecha[4:6]))].append(valor)

    resultados = []
    for anio in range(inicio, fin + 1):
        for mes in range(1, 13):
            dias_mes = calendar.monthrange(anio, mes)[1]
            valores = resultados_por_mes.get((anio, mes), [])

            # Solo hay acumulado si NASA entregó todos los días del mes
            if len(valores) == dias_mes:
                acumulado = round(sum(valores), 2)
                promedio_diario = round(acumulado / dias_mes, 2)
            else:
                acumulado = None
                promedio_diario = None

            resultados.append({
                "anio": anio,
                "mes": mes,
                "fecha": f"{anio}-{mes:02d}",
                "promedio_diario_mm": promedio_diario,
                "lluvia_acumulada_mm": acumulado,
            })

    return {
        "ubicacion": {"latitud": latitud, "longitud": longitud},
        "fuente": "NASA POWER - GPM IMERG",
        "variable": "IMERG_PRECTOT",
        "unidad": "mm",
        "datos_mensuales": resultados,
    }


def diagnostico_imerg(latitud, longitud):
    """Resumen de lo que NASA devuelve realmente para IMERG (para depurar)."""
    hoy = date.today()
    inicio = hoy - timedelta(days=400)
    fin = hoy - timedelta(days=30)
    datos = _pedir_imerg(latitud, longitud, inicio, fin)
    validos = sorted(f for f, v in datos.items() if _valor_valido(v) and v >= 0)
    return {
        "comunidad_que_funciono": _config_imerg["comunidad"],
        "fechas_pedidas": f"{inicio} a {fin}",
        "dias_devueltos": len(datos),
        "dias_con_dato_valido": len(validos),
        "primer_dia_valido": validos[0] if validos else None,
        "ultimo_dia_valido": validos[-1] if validos else None,
        "ejemplo_ultimos_5": {f: datos[f] for f in sorted(datos)[-5:]},
    }
