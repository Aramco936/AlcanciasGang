/* ===== Evaluador de cultivo =====
   Se carga DESPUÉS de script.js (usa obtenerElemento, caracterEspecialATexto, campoLat, campoLon, camposFormulario)
   y ANTES de asistente.js (que lee resultadoEvaluador mediante contextoEvaluador()).
   Habla con el servidor en:
     GET  /api/evaluador/cultivos   catálogo para el buscador y las categorías
     POST /api/evaluador            evalúa un cultivo o devuelve un ranking                          */

let resultadoEvaluador = null;     // última respuesta del servidor (la lee el asistente)
let entradasEvaluador = null;      // lo que se envió en esa consulta

(function () {
  const el = obtenerElemento, esc = caracterEspecialATexto;
  const salida = el('evSalida'), estado = el('evEstado'), boton = el('evEnviar');
  let modo = 'cultivo', ocupado = false;

  /* ---------- Textos y formatos ---------- */
  const CLASE_CSS = {'Muy apto': 'c-ok', 'Apto': 'c-bien', 'Marginal': 'c-mid', 'No recomendable': 'c-mal'};
  const claseCss = clase => CLASE_CSS[clase] || 'c-mid';
  const colorComp = v => v >= 0.75 ? 'c-ok' : v >= 0.45 ? 'c-mid' : 'c-mal';
  const CICLOS = {annual: 'anual', perennial: 'perenne', biennial: 'bianual'};
  const CATEGORIAS = {cereals: 'cereales', vegetables: 'hortalizas', pulses: 'leguminosas', fruits: 'frutas',
    'medicinals & aromatic': 'medicinales y aromáticas', 'oil crops': 'oleaginosas', fibres: 'fibras',
    'roots/tubers': 'raíces y tubérculos', 'fodder/pasture': 'forraje', nuts: 'nueces', spices: 'especias'};
  const traducir = (txt, mapa) => String(txt || '').split(',').map(t => t.trim()).filter(Boolean).map(t => mapa[t.toLowerCase()] || t).join(', ');
  const fecha = iso => iso ? new Date(iso + 'T12:00:00').toLocaleDateString('es-MX', {day: 'numeric', month: 'short', year: 'numeric'}) : '—';
  const fechaCorta = iso => new Date(iso + 'T12:00:00').toLocaleDateString('es-MX', {day: 'numeric', month: 'short'});
  const num = (n, d = 1) => (typeof n === 'number' && Number.isFinite(n)) ? n.toFixed(d) : '—';
  const rangoAnios = a => a.length > 2 && a.every((y, i) => i === 0 || y === a[i - 1] + 1) ? `${a[0]}–${a[a.length - 1]}` : a.join(', ');
  const hoyISO = () => { const h = new Date(); return new Date(h.getTime() - h.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };

  // Nombres del formulario de rotaciones → nombre científico del catálogo
  const CIENTIFICOS = {'Maíz': 'Zea mays', 'Trigo': 'Triticum aestivum', 'Cebada': 'Hordeum vulgare', 'Avena': 'Avena sativa',
    'Sorgo': 'Sorghum bicolor', 'Amaranto': 'Amaranthus cruentus', 'Frijol': 'Phaseolus vulgaris', 'Garbanzo': 'Cicer arietinum',
    'Haba': 'Vicia faba', 'Chícharo': 'Pisum sativum', 'Lenteja': 'Lens culinaris', 'Soya': 'Glycine max', 'Cacahuate': 'Arachis hypogaea',
    'Jitomate': 'Solanum lycopersicum', 'Chile': 'Capsicum annuum', 'Papa': 'Solanum tuberosum', 'Calabaza': 'Cucurbita pepo',
    'Pepino': 'Cucumis sativus', 'Sandía': 'Citrullus lanatus', 'Melón': 'Cucumis melo', 'Brócoli': 'Brassica oleracea',
    'Col': 'Brassica oleracea', 'Coliflor': 'Brassica oleracea', 'Cebolla': 'Allium cepa', 'Ajo': 'Allium sativum',
    'Zanahoria': 'Daucus carota', 'Lechuga': 'Lactuca sativa', 'Girasol': 'Helianthus annuus'};

  /* ---------- Catálogo para el buscador ---------- */
  fetch('/api/evaluador/cultivos').then(async r => {
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo leer el catálogo.');
    el('evLista').innerHTML = d.cultivos.map(c => `<option value="${esc(c.cientifico)}">${esc(c.comun)}</option>`).join('');
    el('evCategoria').insertAdjacentHTML('beforeend', d.categorias.map(c => `<option value="${esc(c)}">${esc(traducir(c, CATEGORIAS))}</option>`).join(''));
  }).catch(e => { estado.textContent = 'No pude cargar el catálogo de cultivos: ' + e.message; });

  el('evSiembra').value = hoyISO();

  /* ---------- Controles ---------- */
  document.querySelector('#evForm .seg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    cambiarModo(b.dataset.m);
  });
  function cambiarModo(nuevo) {
    modo = nuevo;
    document.querySelectorAll('#evForm .seg button').forEach(b => {
      const on = b.dataset.m === modo; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
    el('evBloqueCultivo').hidden = modo !== 'cultivo';
    el('evBloqueRanking').hidden = modo !== 'ranking';
    boton.textContent = modo === 'cultivo' ? 'Evaluar cultivo' : 'Buscar los mejores cultivos';
  }

  // "Probar hasta" y "cosecha" no se combinan (lo exige el evaluador)
  function sincronizarFechas() {
    const fin = el('evSiembraFin').value, cos = el('evCosecha').value;
    el('evCosecha').disabled = !!fin; el('evSiembraFin').disabled = !!cos;
    if (fin) el('evCosecha').value = ''; if (cos) el('evSiembraFin').value = '';
  }
  el('evSiembraFin').addEventListener('input', sincronizarFechas);
  el('evCosecha').addEventListener('input', sincronizarFechas);

  // Punto elegido en el mapa
  function actualizarPunto() {
    const lat = parseFloat(campoLat.value), lon = parseFloat(campoLon.value), ok = Number.isFinite(lat) && Number.isFinite(lon);
    const caja = el('evPunto'); caja.classList.toggle('ok', ok);
    const lugar = (typeof puntoSeleccionado !== 'undefined' && puntoSeleccionado && puntoSeleccionado.nombre) ? ` · ${puntoSeleccionado.nombre}` : '';
    caja.querySelector('span').textContent = ok ? `${lat.toFixed(4)}, ${lon.toFixed(4)}${lugar}` : 'Aún no eliges un punto en el mapa';
  }
  new MutationObserver(actualizarPunto).observe(el('rPunto'), {childList: true, characterData: true, subtree: true});
  campoLat.addEventListener('input', actualizarPunto); campoLon.addEventListener('input', actualizarPunto);

  // Atajo: usar el cultivo del formulario de rotaciones
  function actualizarAtajo() {
    const n = camposFormulario.cultivo.value, c = CIENTIFICOS[n], b = el('evUsarForm');
    b.hidden = !c; if (c) { b.textContent = `Usar ${n} del formulario (${c})`; b.dataset.c = c; }
  }
  camposFormulario.cultivo.addEventListener('change', actualizarAtajo); actualizarAtajo();
  el('evUsarForm').onclick = () => { cambiarModo('cultivo'); el('evCultivo').value = el('evUsarForm').dataset.c; el('evCultivo').focus(); };

  /* ---------- Envío ---------- */
  function mostrarEstado(txt) { estado.textContent = txt || ''; }

  async function enviar() {
    if (ocupado) return;
    const lat = parseFloat(campoLat.value), lon = parseFloat(campoLon.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      mostrarEstado('Elige un punto en el mapa o escribe una latitud y una longitud válidas.'); el('mapa').scrollIntoView({behavior: 'smooth'}); return;
    }
    if (!el('evSiembra').value) { mostrarEstado('Elige la fecha de siembra.'); el('evSiembra').focus(); return; }
    const cultivo = el('evCultivo').value.trim();
    if (modo === 'cultivo' && !cultivo) { mostrarEstado('Escribe el nombre científico del cultivo, por ejemplo Zea mays.'); el('evCultivo').focus(); return; }

    const cuerpo = {lat, lon, siembra: el('evSiembra').value, riego: el('evRiego').checked, modo: el('evModo').value,
      anios_clima: +el('evAnios').value || 5, tolerancia: +el('evTol').value || 0.001};
    if (el('evSiembraFin').value) cuerpo.siembra_fin = el('evSiembraFin').value;
    if (el('evCosecha').value) cuerpo.cosecha = el('evCosecha').value;
    if (modo === 'cultivo') cuerpo.cultivo = cultivo;
    else { cuerpo.top = +el('evTop').value || 10; if (el('evTipo').value) cuerpo.tipo = el('evTipo').value; if (el('evCategoria').value) cuerpo.categoria = el('evCategoria').value; }

    ocupado = true; boton.disabled = true; mostrarEstado('');
    salida.setAttribute('aria-busy', 'true');
    salida.innerHTML = cuerpo.modo === 'api'
      ? `<div class="ev-carga"><div class="spinner" aria-hidden="true"></div><b>Reuniendo clima y suelo…</b><p>Descargamos el clima de NASA POWER y el suelo de SoilGrids para tu punto. La primera consulta de un lugar puede tardar uno o dos minutos; después queda guardada.</p></div>`
      : `<div class="ev-carga"><div class="spinner" aria-hidden="true"></div><b>Leyendo tus archivos locales…</b></div>`;
    try {
      const r = await fetch('/api/evaluador', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(cuerpo)});
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'La solicitud no es válida: revisa los datos del formulario.');
      resultadoEvaluador = d; entradasEvaluador = cuerpo;
      salida.innerHTML = d.tipo === 'ranking' ? htmlRanking(d) : htmlCultivo(d);
      animarMedidor();
      salida.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } catch (e) {
      salida.innerHTML = htmlError(e.message);
    } finally {
      ocupado = false; boton.disabled = false; salida.removeAttribute('aria-busy');
    }
  }
  boton.addEventListener('click', enviar);
  el('evCultivo').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); enviar(); } });

  /* ---------- Piezas de la respuesta ---------- */
  function htmlError(mensaje) {
    const lineas = String(mensaje).split('\n').map(l => l.trim()).filter(Boolean);
    const sugerencias = lineas.filter(l => l.startsWith('- ')).map(l => l.slice(2));
    const texto = lineas.filter(l => !l.startsWith('- '));
    return `<div class="ev-error" role="alert"><b>No pude completar la evaluación</b>
      ${texto.map(t => `<p>${esc(t)}</p>`).join('')}
      ${sugerencias.length ? `<div class="sugeridos">${sugerencias.map(s => `<button type="button" data-cultivo="${esc(s)}">${esc(s)}</button>`).join('')}</div>` : ''}</div>`;
  }
  salida.addEventListener('click', e => {
    const sug = e.target.closest('[data-cultivo]');
    if (sug) { cambiarModo('cultivo'); el('evCultivo').value = sug.dataset.cultivo; enviar(); }
  });

  function htmlContexto(enc) {
    const s = enc.suelo, c = enc.clima;
    let ventana = fecha(enc.siembra) + (enc.siembra_fin ? ` → ${fecha(enc.siembra_fin)}` : '') + (enc.cosecha ? ` · cosecha ${fecha(enc.cosecha)}` : '');
    const suelo = s
      ? `<b>${esc((s.textura || 'Suelo').replace(/^./, m => m.toUpperCase()))}${s.textura_usda ? ` · ${esc(s.textura_usda)}` : ''}</b>
         <span>pH ${num(s.ph)} · carbono ${num(s.soc)} g/kg · N ${num(s.nitrogeno, 2)} g/kg · CIC ${num(s.cec)} cmol/kg</span>`
      : `<b>Sin datos de suelo</b><span>El punto cae sobre agua o zona urbana: solo se evaluó el clima.</span>`;
    const avisos = s && s.avisos && s.avisos.length ? `<ul class="avisos">${s.avisos.map(a => `<li>${esc(a)}</li>`).join('')}</ul>` : '';
    return `<div class="ev-ctx">
      <div><small>Siembra${enc.riego ? ' · con riego' : ''}</small><b>${esc(ventana)}</b><span>${num(enc.lat, 4)}, ${num(enc.lon, 4)}</span></div>
      <div><small>Clima</small><b>${esc(c.fuente)}</b><span>${fecha(c.ini)} → ${fecha(c.fin)}</span></div>
      <div><small>Suelo</small>${suelo}</div></div>${avisos}`;
  }

  // Medidor semicircular: pista por zonas (0-35 / 35-55 / 55-75 / 75-100) y arco del puntaje encima
  function htmlMedidor(puntaje, clase) {
    const zonas = [[0, 35, 'c-mal'], [35, 55, 'c-mid'], [55, 75, 'c-bien'], [75, 100, 'c-ok']];
    const pista = zonas.map(([a, b, c]) => `<path d="M20 110A90 90 0 0 1 200 110" pathLength="100" class="g-zona ${c}" stroke-dasharray="0 ${a + 0.6} ${b - a - 1.2} 200"/>`).join('');
    const p = Math.max(0, Math.min(100, puntaje));
    return `<svg class="medidor ${claseCss(clase)}" viewBox="0 0 220 128" role="img" aria-label="Puntaje ${Math.round(p)} de 100, ${esc(clase)}">
      ${pista}
      <path d="M20 110A90 90 0 0 1 200 110" pathLength="100" class="g-arco" data-p="${p}" stroke-dasharray="0 200"/>
      <text x="110" y="100" text-anchor="middle" class="g-num">${Math.round(p)}</text>
      <text x="110" y="121" text-anchor="middle" class="g-de">de 100</text></svg>`;
  }
  function animarMedidor() {
    salida.querySelectorAll('.g-arco').forEach(a => {
      const p = +a.dataset.p, fin = `${p} 200`;
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) { a.setAttribute('stroke-dasharray', fin); return; }
      a.getBoundingClientRect();           // fuerza el estado inicial antes de animar
      a.style.transition = 'stroke-dasharray 1.1s cubic-bezier(.2,.7,.2,1)';
      requestAnimationFrame(() => a.setAttribute('stroke-dasharray', fin));
    });
  }

  function htmlPorFecha(lista, mejor) {
    if (!lista || lista.length < 2) return '';
    const paso = lista.length > 14 ? 3 : lista.length > 8 ? 2 : 1;
    return `<section class="ev-bloque-res"><h5>Puntaje por fecha de siembra</h5>
      <div class="fechas" style="--n:${lista.length}">${lista.map((f, i) => `<div class="fb${f.fecha === mejor ? ' mejor' : ''}" title="${esc(fecha(f.fecha))}: ${Math.round(f.puntaje)}">
        <span class="fv">${Math.round(f.puntaje)}</span><i style="height:${Math.max(3, f.puntaje)}%"></i>
        <span class="fl">${i % paso === 0 || f.fecha === mejor ? esc(fechaCorta(f.fecha)) : ''}</span></div>`).join('')}</div>
      <p class="sub">La barra marcada es la mejor fecha de la ventana.</p></section>`;
  }

  function htmlCultivo(d) {
    const r = d.resultado, enc = d.encabezado;
    const clima = r.modo_clima === 'observado'
      ? `Datos reales de ${fecha(r.siembra)} a ${fecha(r.cosecha_est)}`
      : `Promedio histórico de ${rangoAnios(r.anios_clima)}. Es un clima típico, no un pronóstico.`;
    const etiquetas = [r.familia && `Familia ${r.familia}`, r.categoria && traducir(r.categoria, CATEGORIAS), r.ciclo_vida && `Ciclo ${traducir(r.ciclo_vida, CICLOS)}`].filter(Boolean);
    return `${htmlContexto(enc)}
      <div class="ev-res">
        <header class="ev-cult"><h4>${esc(r.cientifico)}</h4>
          <p>${esc(r.comun || 'Sin nombre común en el catálogo')}</p>
          ${etiquetas.length ? `<div class="etiquetas">${etiquetas.map(t => `<span>${esc(t)}</span>`).join('')}</div>` : ''}</header>
        ${r.datos_dudosos ? `<p class="ev-nota">Este cultivo tiene datos dudosos en el catálogo; toma el puntaje con cuidado.</p>` : ''}
        <div class="ev-veredicto">
          <figure>${htmlMedidor(r.puntaje, r.clase)}<figcaption><span class="clase ${claseCss(r.clase)}">${esc(r.clase)}</span></figcaption></figure>
          <dl class="hechos">
            <div><dt>Mejor siembra</dt><dd>${esc(fecha(r.siembra))}</dd></div>
            <div><dt>Ciclo</dt><dd>${r.dias_ciclo} días${r.ciclo_supuesto ? ' <small>(estimado)</small>' : ''}</dd></div>
            <div><dt>Cosecha estimada</dt><dd>${esc(fecha(r.cosecha_est))}</dd></div>
            <div><dt>Lo que más limita</dt><dd class="${colorComp(r.limitante.valor)}-txt">${esc(r.limitante.etiqueta)} <small>${num(r.limitante.valor, 2)}</small></dd></div>
            <div class="ancho"><dt>Clima usado</dt><dd>${esc(clima)}</dd></div>
          </dl>
        </div>
        ${htmlPorFecha(r.por_fecha, r.siembra)}
        <section class="ev-bloque-res"><h5>Cómo se compone el puntaje</h5>
          <ul class="comps">${r.componentes.map(c => `<li class="${c.limitante ? 'lim' : ''}">
            <div class="cab"><b>${esc(c.etiqueta)}</b><small>pesa ${c.peso} %</small>${c.limitante ? '<em>limita el puntaje</em>' : ''}<span class="val ${colorComp(c.valor)}-txt">${num(c.valor, 2)}</span></div>
            <div class="barra" role="img" aria-label="${esc(c.etiqueta)}: ${num(c.valor, 2)} de 1"><i class="${colorComp(c.valor)}" style="width:${Math.round(c.valor * 100)}%"></i></div>
            <p>${esc(c.detalle)}</p></li>`).join('')}</ul>
          ${r.tope_aplicado ? `<p class="ev-nota">${esc(r.limitante.etiqueta)} quedó por debajo de 0.20, así que el puntaje se topa en 40 sin importar lo bien que estén los demás componentes.</p>` : ''}
        </section>
        ${r.consejos.length ? `<section class="ev-bloque-res"><h5>Qué puedes hacer</h5><ul class="consejos">${r.consejos.map(t => `<li>${esc(t)}</li>`).join('')}</ul></section>` : ''}
      </div>`;
  }

  function htmlRanking(d) {
    const enc = d.encabezado;
    return `${htmlContexto(enc)}
      <div class="ev-res"><h4 class="ev-rank-t">${d.ranking.length < d.evaluados ? `Los ${d.ranking.length} mejores de ${d.evaluados} cultivos evaluados` : `${d.evaluados} cultivos evaluados`}</h4>
      <ol class="rank">${d.ranking.map((r, i) => `<li>
        <span class="pos">${i + 1}</span>
        <div class="nom"><b>${esc(r.cientifico)}</b><small>${esc(r.comun || 'Sin nombre común')}</small></div>
        <div class="pun"><span class="pn">${Math.round(r.puntaje)}</span><div class="barra"><i class="${claseCss(r.clase)}" style="width:${r.puntaje}%"></i></div></div>
        <span class="clase ${claseCss(r.clase)}">${esc(r.clase)}</span>
        <div class="det"><span>Siembra ${esc(fechaCorta(r.siembra))} → cosecha ${esc(fechaCorta(r.cosecha_est))}</span><span>Limita: ${esc(r.limitante.etiqueta)} (${num(r.limitante.valor, 2)})</span></div>
        <button type="button" class="enlace" data-cultivo="${esc(r.cientifico)}">Ver detalle</button></li>`).join('')}</ol>
      <p class="sub">Cada puntaje usa la fecha de siembra elegida. Toca “Ver detalle” para ver los componentes y las recomendaciones.</p></div>`;
  }
})();

/* Resumen para el asistente: lo que el usuario está viendo en el evaluador */
function contextoEvaluador() {
  const d = resultadoEvaluador; if (!d) return null;
  const e = d.encabezado, s = e.suelo;
  const base = {
    consulta: entradasEvaluador && {lat: e.lat, lon: e.lon, siembra: e.siembra, ventana_hasta: e.siembra_fin, cosecha_deseada: e.cosecha, con_riego: e.riego,
      fuente_datos: e.modo, filtro_tipo: entradasEvaluador.tipo || null, filtro_categoria: entradasEvaluador.categoria || null},
    clima_cargado: `${e.clima.ini} → ${e.clima.fin}`,
    suelo: s ? {textura: s.textura, textura_usda: s.textura_usda, ph: redond(s.ph), carbono_organico_g_kg: redond(s.soc), nitrogeno_g_kg: redond(s.nitrogeno, 2),
      cic_cmol_kg: redond(s.cec), avisos: s.avisos} : 'sin datos (agua o zona urbana)'
  };
  if (d.tipo === 'ranking') {
    return {...base, modo: 'recomendación (ranking)', cultivos_evaluados: d.evaluados,
      ranking: d.ranking.map((r, i) => ({lugar: i + 1, cultivo: r.cientifico, nombre_comun: r.comun, puntaje: Math.round(r.puntaje), clase: r.clase,
        siembra: r.siembra, cosecha_est: r.cosecha_est, limitante: `${r.limitante.etiqueta} (${redond(r.limitante.valor, 2)})`}))};
  }
  const r = d.resultado;
  return {...base, modo: 'evaluación de un cultivo', cultivo: r.cientifico, nombre_comun: r.comun, familia: r.familia, categoria: r.categoria,
    puntaje: Math.round(r.puntaje), clase: r.clase, mejor_siembra: r.siembra, ciclo_dias: r.dias_ciclo, ciclo_estimado_por_el_programa: r.ciclo_supuesto,
    cosecha_estimada: r.cosecha_est, clima_usado: r.modo_clima === 'observado' ? 'datos reales' : `promedio histórico de ${r.anios_clima.join(', ')} (no es pronóstico)`,
    factor_limitante: `${r.limitante.etiqueta} (${redond(r.limitante.valor, 2)})`, puntaje_topado_en_40_por_limitante: r.tope_aplicado,
    componentes: r.componentes.map(c => ({componente: c.etiqueta, valor_0_a_1: c.valor, peso_pct: c.peso, detalle: c.detalle})),
    recomendaciones_mostradas: r.consejos,
    puntaje_por_fecha: r.por_fecha.length > 1 ? r.por_fecha.slice(0, 30).map(f => `${f.fecha}: ${Math.round(f.puntaje)}`) : undefined};
}
