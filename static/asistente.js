/* ===== Asistente: explica los resultados de la página =====
   Se carga DESPUÉS de script.js y lee sus variables globales (resultadoRotaciones, temaRiesgoActivo,
   ZONAS_RESULTADO, etc.). En cada pregunta manda un "contexto" con lo que el usuario está viendo;
   la metodología (cómo se calcula todo) vive en el servidor, en asistente.py. */

const NOMBRES_CAPA = {'': 'sin capa', humedad: 'Humedad NASA', lluvia: 'Lluvia mensual GPM', zonas: 'Zonas agroclimáticas (K-means)',
  deficit: 'Déficit hídrico (predicción)', tendencia: 'Tendencia climática por zona'};

const redond = (n, d = 1) => (typeof n === 'number' && Number.isFinite(n)) ? +n.toFixed(d) : null;

function resumenDeCapa(valorDe, etiquetaUnidad) {
  // Cuenta países por nivel y da los 5 más altos / más bajos de la capa activa
  const filas = [];
  paisesDelMundo?.forEach(p => {
    const v = valorDe(idPais(p)); if (v) filas.push({pais: v.nombre || p.properties.name, valor: v.valor, nivel: v.nivel});
  });
  if (!filas.length) return null;
  const orden = [...filas].sort((a, b) => b.valor - a.valor);
  const cuenta = {bajo: 0, medio: 0, alto: 0};
  filas.forEach(f => { if (f.nivel in cuenta) cuenta[f.nivel]++; });
  return {paises_con_dato: filas.length, por_nivel: cuenta, unidad: etiquetaUnidad,
    mas_altos: orden.slice(0, 5).map(f => `${f.pais}: ${redond(f.valor)}`),
    mas_bajos: filas.length > 5 ? orden.slice(-5).reverse().map(f => `${f.pais}: ${redond(f.valor)}`) : []};
}

function contextoRotaciones() {
  if (!resultadoRotaciones) return null;
  const r = resultadoRotaciones, est = r.estaciones[estacionActiva];
  const compactas = {};
  ORDEN_ESTACIONES.filter(e => e !== estacionActiva).forEach(e => {
    compactas[e] = r.estaciones[e].rotaciones.map(x => ({puntaje: x.puntaje, ciclo: x.cultivos.map(c => `${c.estacion}: ${c.nombre} ${c.prob}%`)}));
  });
  return {
    hemisferio: r.hemisferio, estacion_actual: r.estacion_actual, periodo_datos: r.periodo, parametros_nasa: r.parametros_usados,
    explicacion_redactada_por: r.redactado_por, cultivo_actual_reconocido: r.cultivo_reconocido,
    clima_por_estacion: r.clima,
    pestana_abierta: `Empezar en ${estacionActiva}`,
    rotaciones_de_esa_pestana: est.rotaciones.map((rot, i) => ({
      numero: i + 1, puntaje: rot.puntaje,
      cultivos: rot.cultivos.map(c => ({estacion: c.estacion, cultivo: c.nombre, prob_exito: c.prob, motivo: c.motivo, aviso: c.aviso || null})),
      reglas_de_rotacion: rot.reglas, texto_mostrado: rot.texto})),
    no_conviene_sembrar: est.evitar.map(e => ({cultivo: e.nombre, prob_exito: e.prob, limitante: e.motivo})),
    otras_pestanas_resumen: compactas};
}

function contextoPais() {
  if (!paisTocadoActual) return null;
  const id = idPais(paisTocadoActual), nombre = paisTocadoActual.properties.name, out = {pais: nombre};
  const h = DATOS_HUMEDAD_POR_PAIS[id]; if (h && h.humedad != null) out.humedad = {porcentaje: h.humedad, nivel: h.nivel};
  const l = DATOS_LLUVIA_POR_PAIS[id];
  if (l && l.lluvia_acumulada_mm != null) out.lluvia_mensual = {mm: l.lluvia_acumulada_mm, mes: MESES[l.mes - 1], anio: l.anio};
  const cl = DATOS_CLIMA_POR_PAIS[id]?.valores;
  if (cl) out.clima_para_zonas = {temp_media_c: cl.temp, amplitud_termica_c: cl.amplitud, lluvia_anual_mm: Math.round(cl.lluvia), humedad_pct: cl.humedad, estacionalidad_lluvia: cl.estacionalidad};
  const z = ZONAS_RESULTADO?.asignacion[id];
  if (z !== undefined) out.zona_kmeans = {id: z, nombre: ZONAS_RESULTADO.zonas[z].nombre, regimen: ZONAS_RESULTADO.zonas[z].regimen};
  const v = DATOS_PRED_POR_PAIS[id]?.valores;
  if (v) {
    out.deficit_hidrico = {nivel: v.nivel, deficit_proyectado_12m_mm: Math.round(v.deficit_pron), deficit_historico_mm: Math.round(v.deficit_hist),
      cambio_vs_historico_pct: v.cambio_pct, indice_aridez: v.aridez, sequia_actual: v.sequia,
      meses: v.meses.filter(Boolean).map(m => ({mes: `${MESES[m.mes - 1]} ${m.anio}`, deficit_mm: Math.round(m.deficit), rango_80pct_mm: [Math.round(m.lo), Math.round(m.hi)], prob_deficit: m.p_deficit}))};
    out.tendencia_del_pais = v.tendencia;
    if (z !== undefined && TENDENCIA_ZONAS?.[z]) out.tendencia_promedio_de_su_zona = TENDENCIA_ZONAS[z];
  }
  return Object.keys(out).length > 1 ? out : {pais: nombre, nota: 'Aún no hay datos cargados de este país para la capa activa.'};
}

function contextoMapa() {
  const tema = temaRiesgoActivo, m = {capa_activa: NOMBRES_CAPA[tema] || tema, cargando_datos: !!(cargandoHumedad || cargandoZonas || cargandoPred)};
  const texto = obtenerElemento('gcap')?.innerText?.trim(); if (texto) m.mensaje_en_pantalla = texto.slice(0, 600);
  if (tema === 'humedad') m.resumen_capa = resumenDeCapa(id => { const d = DATOS_HUMEDAD_POR_PAIS[id]; return d && d.humedad != null ? {nombre: d.nombre, valor: d.humedad, nivel: d.nivel} : null; }, '% humedad relativa');
  if (tema === 'lluvia') {
    m.mes_mostrado = obtenerElemento('selMes')?.selectedOptions[0]?.text + ' ' + obtenerElemento('selAnio')?.value;
    m.resumen_capa = resumenDeCapa(id => { const d = DATOS_LLUVIA_POR_PAIS[id]; if (!d || d.lluvia_acumulada_mm == null) return null;
      const v = d.lluvia_acumulada_mm; return {nombre: d.nombre, valor: v, nivel: v < 50 ? 'bajo' : v <= 150 ? 'medio' : 'alto'}; }, 'mm acumulados en el mes');
  }
  if (tema === 'deficit') m.resumen_capa = resumenDeCapa(id => { const v = DATOS_PRED_POR_PAIS[id]?.valores; return v ? {nombre: DATOS_PRED_POR_PAIS[id].nombre, valor: v.deficit_pron, nivel: v.nivel} : null; }, 'mm de déficit proyectado a 12 meses');
  if (ZONAS_RESULTADO && (tema === 'zonas' || tema === 'tendencia')) {
    const nombres = {};
    Object.entries(ZONAS_RESULTADO.asignacion).forEach(([id, z]) => { (nombres[z] ||= []).push(DATOS_CLIMA_POR_PAIS[id]?.nombre || id); });
    m.kmeans = {k: ZONAS_RESULTADO.k, silueta: ZONAS_RESULTADO.silueta, k_elegido_por_usuario: obtenerElemento('selK').value || 'automático',
      variables: ['temp', 'amplitud', 'lluvia (log)', 'humedad', 'estacionalidad'],
      zonas: ZONAS_RESULTADO.zonas.map(z => ({id: z.id, nombre: z.nombre, regimen: z.regimen, paises: z.paises, centroide: z.centroide,
        ejemplos: (nombres[z.id] || []).slice(0, 8)}))};
  }
  if (tema === 'tendencia' && TENDENCIA_ZONAS && ZONAS_RESULTADO) {
    m.tendencia_por_zona = ZONAS_RESULTADO.zonas.map(z => ({zona: z.nombre, ...TENDENCIA_ZONAS[z.id]}));
  }
  return m;
}

function construirContextoAsistente() {
  return {
    formulario: {cultivo_actual: camposFormulario.cultivo.value.trim() || null, tipo_suelo: camposFormulario.suelo.value || null,
      punto: puntoSeleccionado ? {lat: redond(puntoSeleccionado.lat, 4), lon: redond(puntoSeleccionado.lon, 4), nombre: puntoSeleccionado.nombre || null} : null,
      rotaciones_ya_calculadas: !!resultadoRotaciones},
    rotaciones: contextoRotaciones(),
    evaluador_de_cultivo: typeof contextoEvaluador === 'function' ? contextoEvaluador() : null,
    mapa: contextoMapa(),
    pais_tocado_en_el_mapa: contextoPais()
  };
}

/* ---------- Interfaz del chat ---------- */
(function () {
  const historial = [];
  let ocupado = false;
  const el = id => document.getElementById(id);

  document.body.insertAdjacentHTML('beforeend', `
    <button type="button" id="asBtn" aria-label="Abrir asistente">💬 <span>Asistente</span></button>
    <section id="asPanel" aria-live="polite" hidden>
      <header><div><b>Asistente</b><small>Te explica lo que ves en pantalla</small></div><button type="button" id="asCerrar" aria-label="Cerrar">✕</button></header>
      <div id="asMsgs"></div>
      <div id="asSug"></div>
      <form id="asForm" autocomplete="off">
        <input id="asTexto" type="text" maxlength="1000" placeholder="Pregunta sobre tus resultados…">
        <button type="submit" id="asEnviar">Enviar</button>
      </form>
    </section>`);

  const html = t => caracterEspecialATexto(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/^\s*[-•]\s+(.*)$/gm, '<li>$1</li>').replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`).replace(/\n/g, '<br>');

  function agregar(rol, texto) {
    const d = document.createElement('div'); d.className = 'as-m ' + rol; d.innerHTML = html(texto);
    el('asMsgs').appendChild(d); el('asMsgs').scrollTop = el('asMsgs').scrollHeight; return d;
  }

  function sugerencias() {
    const s = [];
    if (resultadoRotaciones) s.push('¿Por qué me recomiendan la rotación 1?', '¿Qué significa el puntaje?', '¿Qué cultivos debo evitar y por qué?');
    else s.push('¿Cómo se calculan las rotaciones?');
    if (typeof resultadoEvaluador !== 'undefined' && resultadoEvaluador) {
      if (resultadoEvaluador.tipo === 'ranking') s.push('¿Cómo se calcula este ranking de cultivos?', '¿Por qué el primer cultivo es el mejor?');
      else s.push('¿Por qué mi cultivo tiene ese puntaje?', '¿Qué hago con el factor limitante?');
    } else s.push('¿Cómo funciona el evaluador de cultivo?');
    if (paisTocadoActual) s.push(`Explícame los datos de ${paisTocadoActual.properties.name}`);
    if (temaRiesgoActivo === 'zonas') s.push('¿Cómo funciona K-means?', '¿Qué significa la silueta?');
    else if (temaRiesgoActivo === 'deficit') s.push('¿Qué es el déficit hídrico?', '¿Qué tan confiable es esta predicción?');
    else if (temaRiesgoActivo === 'tendencia') s.push('¿Qué es una tendencia significativa?', '¿Qué significan los colores?');
    else if (temaRiesgoActivo) s.push('Explícame esta capa del mapa');
    else s.push('¿Qué puedo ver en el mapa mundial?');
    el('asSug').innerHTML = s.slice(0, 5).map(t => `<button type="button">${caracterEspecialATexto(t)}</button>`).join('');
  }

  async function preguntar(texto) {
    texto = texto.trim(); if (!texto || ocupado) return;
    ocupado = true; el('asEnviar').disabled = true; el('asTexto').value = '';
    agregar('user', texto); historial.push({rol: 'user', texto});
    const espera = agregar('bot', 'Pensando…'); espera.classList.add('espera');
    try {
      const r = await fetch('/api/asistente', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mensajes: historial.slice(-12), contexto: construirContextoAsistente()})});
      const datos = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : `Error del servidor (${r.status}): la solicitud no es válida.`);
      espera.classList.remove('espera'); espera.innerHTML = html(datos.respuesta);
      historial.push({rol: 'assistant', texto: datos.respuesta});
    } catch (e) {
      espera.classList.remove('espera'); espera.classList.add('error'); espera.textContent = e.message || 'No pude responder.';
      historial.pop();   // para poder reintentar la misma pregunta
    } finally { ocupado = false; el('asEnviar').disabled = false; el('asMsgs').scrollTop = el('asMsgs').scrollHeight; sugerencias(); }
  }

  function abrir(mostrar) {
    el('asPanel').hidden = !mostrar; el('asBtn').style.display = mostrar ? 'none' : '';
    if (mostrar) {
      if (!el('asMsgs').children.length) agregar('bot', '¡Hola! Puedo explicarte lo que ves en la página: tus rotaciones recomendadas, el puntaje del evaluador de cultivo y cómo leer el mapa (K-means, déficit hídrico, tendencias). ¿Qué quieres entender?');
      sugerencias(); el('asTexto').focus();
    }
  }

  el('asBtn').onclick = () => abrir(true);
  el('asCerrar').onclick = () => abrir(false);
  el('asForm').onsubmit = e => { e.preventDefault(); preguntar(el('asTexto').value); };
  el('asSug').onclick = e => { const b = e.target.closest('button'); if (b) preguntar(b.textContent); };
})();
