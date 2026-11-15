const obtenerElemento = idElemento => document.getElementById(idElemento);
const caracterEspecialATexto = texto => String(texto).replace(/[&<>"]/g, caracter => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[caracter]));

/* globo de la intro*/
let CoordenadasContinentes = null, rotacionGlobo = 0, introduccionActiva = true;
const globoIntroduccion = obtenerElemento('big'), globoMiniatura = obtenerElemento('mini'), densidadPixeles = window.devicePixelRatio || 1;
(function(){ 
    const tamano = Math.min(innerWidth, innerHeight) * 0.88; globoIntroduccion.style.width = globoIntroduccion.style.height = tamano + 'px'; 
    globoIntroduccion.width = globoIntroduccion.height = tamano * densidadPixeles; 
})();

function dibujarGlobo(lienzo, rotacionHorizontal=rotacionGlobo, inclinacionVertical=-20, dibujoAdicional){
  const contexto = lienzo.getContext('2d'), tamano = lienzo.width, radio = tamano/2 - 4;
  const proyeccion = d3.geoOrthographic().scale(radio).translate([tamano/2, tamano/2]).rotate([rotacionHorizontal, inclinacionVertical]).clipAngle(90);
  const trazado = d3.geoPath(proyeccion, contexto);
  contexto.clearRect(0,0,tamano,tamano);
  const degradadoOceano = contexto.createRadialGradient(tamano*.4, tamano*.35, radio*.1, tamano/2, tamano/2, radio);
  degradadoOceano.addColorStop(0,'#2b7bd1'); degradadoOceano.addColorStop(1,'#0a2a55');
  contexto.beginPath(); trazado({type:'Sphere'}); contexto.fillStyle = degradadoOceano; contexto.fill();
  contexto.beginPath(); trazado(d3.geoGraticule10()); contexto.strokeStyle='rgba(255,255,255,.12)'; contexto.stroke();
    if(CoordenadasContinentes){ 
        contexto.beginPath(); trazado(CoordenadasContinentes); 
        contexto.fillStyle='#8fd0ff'; contexto.fill(); 
        contexto.strokeStyle='#3a8fd6'; contexto.stroke(); 
    }
  dibujoAdicional && dibujoAdicional(contexto, proyeccion);
  contexto.beginPath(); trazado({type:'Sphere'}); contexto.strokeStyle='rgba(140,190,255,.6)'; contexto.lineWidth=2*densidadPixeles; contexto.stroke();
}

(function animarGlobosDeIntroduccion(){
    rotacionGlobo += 0.45; 
    if(introduccionActiva) dibujarGlobo(globoIntroduccion); 
    dibujarGlobo(globoMiniatura); 
    requestAnimationFrame(animarGlobosDeIntroduccion); 
})();

fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/land-50m.json')
    .then(respuesta=>respuesta.json())
    .then(topologiaTierra=>{ CoordenadasContinentes = topojson.feature(topologiaTierra, topologiaTierra.objects.land);});

setTimeout(() => {
  const pantallaIntroduccion = obtenerElemento('intro'), cajaGloboIntroduccion = globoIntroduccion.getBoundingClientRect(), cajaGloboMiniatura = globoMiniatura.getBoundingClientRect();
  const factorEscala = cajaGloboMiniatura.width / cajaGloboIntroduccion.width, desplazamientoHorizontal = (cajaGloboMiniatura.left+cajaGloboMiniatura.width/2)-(cajaGloboIntroduccion.left+cajaGloboIntroduccion.width/2), desplazamientoVertical = (cajaGloboMiniatura.top+cajaGloboMiniatura.height/2)-(cajaGloboIntroduccion.top+cajaGloboIntroduccion.height/2);
  globoIntroduccion.style.transform = `translate(${desplazamientoHorizontal}px,${desplazamientoVertical}px) scale(${factorEscala})`;
  pantallaIntroduccion.classList.add('done'); obtenerElemento('app').classList.add('show'); mapaSeleccionPunto.invalidateSize();
  setTimeout(() => { introduccionActiva = false; pantallaIntroduccion.remove(); document.body.classList.remove('lock'); obtenerElemento('modal').style.display = 'flex'; }, 1600);
}, 3500);


/* ===== Tutorial ===== */
const pasosTutorial = [
  ['registro','Elige de la lista qué cultivo tienes sembrado (o "Ninguno") y el tipo de suelo de tu terreno.'],
  ['mapa','Escribe la latitud y la longitud con el teclado, o toca el mapa para marcar el punto. Las dos opciones se sincronizan.'],
  ['evaluador','Evalúa un cultivo concreto (escribe su nombre científico) o pide una recomendación de los mejores para tu punto. Elige la fecha de siembra y recibirás un puntaje de 0 a 100, el factor que más lo limita y consejos para mejorarlo.'],
  ['resultados','Al presionar "Calcular rotaciones" se consultan 20 parámetros de NASA POWER y se calculan 3 rotaciones por estación, con la explicación de cada una.'],
  ['riesgos','Elige Humedad NASA o Lluvia mensual GPM y el mapa se pinta de verde, amarillo o rojo. Con Zonas agroclimáticas, K-means agrupa los países con clima parecido. Déficit hídrico predice sequía a 12 meses y Tendencia climática por zona muestra cómo cambian temperatura y lluvia. Toca un país para ver su dato.']
];
let elementoResaltado = null;
function mostrarPasoTutorial(indicePaso){
  elementoResaltado && elementoResaltado.classList.remove('hl');
  if(indicePaso >= pasosTutorial.length) return terminarTutorial();
  elementoResaltado = obtenerElemento(pasosTutorial[indicePaso][0]); elementoResaltado.classList.add('hl'); elementoResaltado.scrollIntoView({behavior:'smooth', block:'start'});
  obtenerElemento('tipn').textContent = `Paso ${indicePaso+1} de ${pasosTutorial.length}`; obtenerElemento('tipt').textContent = pasosTutorial[indicePaso][1];
  obtenerElemento('prev').disabled = indicePaso === 0; obtenerElemento('next').textContent = indicePaso === pasosTutorial.length-1 ? 'Terminar' : 'Siguiente';
  obtenerElemento('prev').onclick = () => mostrarPasoTutorial(indicePaso-1); obtenerElemento('next').onclick = () => mostrarPasoTutorial(indicePaso+1);
  obtenerElemento('tip').style.display = 'block';
}
function terminarTutorial(){ elementoResaltado && elementoResaltado.classList.remove('hl'); elementoResaltado = null; obtenerElemento('tip').style.display = 'none'; }
obtenerElemento('si').onclick = () => obtenerElemento('modal').style.display = 'none';
obtenerElemento('no').onclick = () => { obtenerElemento('modal').style.display = 'none'; mostrarPasoTutorial(0); };
obtenerElemento('exit').onclick = terminarTutorial;
obtenerElemento('btnTut').onclick = () => mostrarPasoTutorial(0);


/* ===== Formulario ===== */
const camposFormulario = obtenerElemento('registro').elements;


/* ===== Mapa para elegir el punto ===== */
const construirUrlCapaEsri = nombreCapaEsri => `https://server.arcgisonline.com/ArcGIS/rest/services/${nombreCapaEsri}/MapServer/tile/{z}/{y}/{x}`;
const capaTerreno = L.tileLayer(construirUrlCapaEsri('World_Topo_Map'), {maxZoom:19, maxNativeZoom:17, attribution:'Tiles © Esri'});
const capaSatelite = L.layerGroup([
  L.tileLayer(construirUrlCapaEsri('World_Imagery'), {maxZoom:19, maxNativeZoom:18, attribution:'Tiles © Esri, Maxar, Earthstar Geographics'}),
  L.tileLayer(construirUrlCapaEsri('Reference/World_Boundaries_and_Places'), {maxZoom:19})]);
const mapaSeleccionPunto = L.map('map', {layers:[capaTerreno]}).setView([23, -102], 4);
L.control.layers({'Terreno':capaTerreno, 'Satélite':capaSatelite}, null, {collapsed:false}).addTo(mapaSeleccionPunto);
let marcadorPuntoCultivo = null, numeroSolicitudActual = 0, puntoSeleccionado = null;
const campoLat = obtenerElemento('lat'), campoLon = obtenerElemento('lon');

async function fijarPunto(latitud, longitud, centrarMapa){
  puntoSeleccionado = {lat:latitud, lon:longitud, nombre:''};
  if(marcadorPuntoCultivo) mapaSeleccionPunto.removeLayer(marcadorPuntoCultivo);
  marcadorPuntoCultivo = L.circleMarker([latitud, longitud], {radius:9, color:'#fff', weight:2, fillColor:'#1565c0', fillOpacity:1}).addTo(mapaSeleccionPunto);
  if(centrarMapa) mapaSeleccionPunto.setView([latitud, longitud], Math.max(mapaSeleccionPunto.getZoom(), 8));
  campoLat.value = latitud.toFixed(5); campoLon.value = longitud.toFixed(5);
  const numeroDeEstaSolicitud = ++numeroSolicitudActual;
  const panelDatos = obtenerElemento('datos');
  const coordenadasTexto = `${latitud.toFixed(3)}, ${longitud.toFixed(3)}`;
  // Lugar con nombre: se muestran sus datos.
  const mostrarDatosDelPunto = nombreLugar => {
    panelDatos.innerHTML = `<h4>${caracterEspecialATexto(nombreLugar)}</h4><div class="dl"><div>Latitud<b>${latitud.toFixed(5)}</b></div><div>Longitud<b>${longitud.toFixed(5)}</b></div></div>`;
    obtenerElemento('rPunto').textContent = nombreLugar;
  };
   // Lugar sin nombre (por ejemplo, mar abierto): no se muestran datos.
  const ocultarDatosDelPunto = () => {
    panelDatos.innerHTML = '<div class="vacio">Este punto es desconocido. Toca un lugar en tierra.</div>';
    obtenerElemento('rPunto').textContent = coordenadasTexto;
  };
  
  panelDatos.innerHTML = '<div class="vacio">Buscando el lugar…</div>';
  obtenerElemento('rPunto').textContent = coordenadasTexto;
  try{
    const respuestaGeocodificacion = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=10&accept-language=es&lat=${latitud}&lon=${longitud}`).then(r => r.json());
    if(numeroDeEstaSolicitud !== numeroSolicitudActual) return;
    const direccion = respuestaGeocodificacion.address || {};
    const nombreLugar = [direccion.city || direccion.town || direccion.village || direccion.municipality || direccion.county, direccion.state, direccion.country].filter(Boolean).join(', ');
    if(nombreLugar){ puntoSeleccionado.nombre = nombreLugar; mostrarDatosDelPunto(nombreLugar); }
    else ocultarDatosDelPunto();
  }catch{
    // Si falla la consulta (sin internet, límite de Nominatim) no sabemos si el lugar tiene nombre:
    // se muestran las coordenadas como antes para no ocultar datos de un lugar real.
    if(numeroDeEstaSolicitud === numeroSolicitudActual){ mostrarDatosDelPunto('Punto seleccionado'); obtenerElemento('rPunto').textContent = coordenadasTexto; }
  }
}

// Opción 1: tocar el mapa
mapaSeleccionPunto.on('click', evento => { const p = evento.latlng.wrap(); fijarPunto(p.lat, p.lng, false); });

// Opción 2: escribir latitud y longitud con el teclado
function leerCoordenadasDeTeclado(){
  const latitud = parseFloat(campoLat.value), longitud = parseFloat(campoLon.value);
  if(Number.isFinite(latitud) && Number.isFinite(longitud) && Math.abs(latitud) <= 90 && Math.abs(longitud) <= 180) fijarPunto(latitud, longitud, true);
}
campoLat.addEventListener('change', leerCoordenadasDeTeclado);
campoLon.addEventListener('change', leerCoordenadasDeTeclado);


/* ===== Resultados: rotaciones por estación ===== */
const MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
const ORDEN_ESTACIONES = ['invierno','primavera','verano','otoño'];
let resultadoRotaciones = null, estacionActiva = null;

(function llenarSelectoresDeLluvia(){
  const hoy = new Date();
  obtenerElemento('selMes').innerHTML = MESES.map((mes, i) => `<option value="${i+1}"${i === hoy.getMonth() ? ' selected' : ''}>${mes}</option>`).join('');
  let anios = ''; for(let anio = hoy.getFullYear(); anio >= 2001; anio--) anios += `<option>${anio}</option>`;
  obtenerElemento('selAnio').innerHTML = anios;
})();
obtenerElemento('selMes').onchange = obtenerElemento('selAnio').onchange = () => recargarLluviaSiCorresponde();

// La imagen se busca en static/img/<archivo de la columna 'imagen' de cultivos.csv> (ej. img/maiz.jpg); si no existe se muestra un recuadro 'Sin imagen'
const crearCarta = cultivo => `<div class="carta" title="${caracterEspecialATexto(cultivo.aviso ? 'Ojo: ' + cultivo.aviso : cultivo.motivo)}">
  <small>${cultivo.estacion}</small>
  <div class="img"><span>Sin imagen</span><img src="img/${cultivo.imagen}" alt="" onerror="this.remove()"></div>
  <b>${caracterEspecialATexto(cultivo.nombre)}</b><small>${cultivo.prob}% de éxito</small></div>`;

function dibujarRotaciones(){
  const datosEstacion = resultadoRotaciones.estaciones[estacionActiva];
  obtenerElemento('tabsEst').innerHTML = ORDEN_ESTACIONES.map(est => `<button type="button" data-e="${est}" class="${est === estacionActiva ? 'on' : ''}">Empezar en ${est}${est === resultadoRotaciones.estacion_actual ? ' (ahora)' : ''}</button>`).join('');
  obtenerElemento('rotaciones').innerHTML = datosEstacion.rotaciones.map((rot, i) => `<article class="rot${i ? '' : ' best'}">
    <div class="rot-h"><b>Rotación ${i+1}</b><span class="pt">${rot.puntaje}</span><span class="sub">puntaje · el ciclo se repite</span></div>
    <div class="cartas">${rot.cultivos.map(crearCarta).join('<div class="flecha">➜</div>')}</div>
    <p class="why">${caracterEspecialATexto(rot.texto)}</p></article>`).join('');
  obtenerElemento('rEvitar').innerHTML = datosEstacion.evitar.length
    ? `<div class="evitar"><b>No conviene sembrar en ${estacionActiva}:</b><br>${datosEstacion.evitar.map(e => `${caracterEspecialATexto(e.nombre)} (${e.prob}% de éxito): ${caracterEspecialATexto(e.motivo)}.`).join('<br>')}</div>` : '';
  obtenerElemento('rBest').textContent = datosEstacion.rotaciones[0].cultivos.map(c => c.nombre).join(' → ');
}

function mostrarResultados(datos, r){
  resultadoRotaciones = r; estacionActiva = r.estacion_actual;
  obtenerElemento('rCult').textContent = datos.cultivo || '—';
  obtenerElemento('rNota').textContent = `Basado en ${r.parametros_usados} parámetros de NASA POWER (${r.periodo}), hemisferio ${r.hemisferio}. Probabilidades calculadas con la frecuencia real de heladas, calor, lluvia, humedad y radiación. Explicación redactada por: ${r.redactado_por}.` + (r.cultivo_reconocido ? '' : ' No reconocí tu cultivo actual, así que no pude evitar su familia.');
  obtenerElemento('rClima').innerHTML = `<table><thead><tr><th>Estación</th><th>Temp. media</th><th>Mín / Máx</th><th>Lluvia (mm)</th><th>Noches ≤ 2 °C</th><th>Humedad aire</th><th>Radiación</th><th>Humedad suelo</th></tr></thead><tbody>${r.clima.map(c => `<tr><td class="crops" style="text-transform:capitalize">${c.estacion}</td><td>${c.t_media} °C</td><td>${c.t_min} / ${c.t_max} °C</td><td>${c.lluvia_mm}</td><td>${c.p_helada}%</td><td>${c.rh}%</td><td>${c.solar} kWh/m²</td><td>${c.suelo}%</td></tr>`).join('')}</tbody></table>`;
  dibujarRotaciones();
}
obtenerElemento('tabsEst').onclick = evento => { const boton = evento.target.closest('button'); if(boton && resultadoRotaciones){ estacionActiva = boton.dataset.e; dibujarRotaciones(); } };


/* ===== Riesgos: mapa del mundo plano pintado por pais ===== */
const COLORES_NIVEL_RIESGO = {alto:'#e53935', medio:'#f9a825', bajo:'#43a047'};
const EXPLICACION_POR_TEMA = {
  '': 'Elige Humedad o Lluvia mensual para pintar el mundo.',
  humedad: '<b>Humedad:</b> humedad relativa del aire a 2 metros de altura (promedio anual), obtenida de NASA POWER. Verde: baja (&lt;40%), amarillo: media y rojo: alta (&gt;70%).',
  zonas: '<b>Zonas agroclimáticas:</b> K-means agrupa los países con clima parecido usando 5 datos de NASA POWER: temperatura media, amplitud térmica, lluvia anual, humedad del aire y qué tan estacional es la lluvia. Cada color es una zona; toca una zona de la lista o un país para ver sus valores.',
  lluvia: '<b>Lluvia mensual:</b> precipitación mensual estimada con NASA POWER - GPM IMERG, en milímetros acumulados. Verde: &lt;50 mm, amarillo: 50-150 mm y rojo: &gt;150 mm.'
};
EXPLICACION_POR_TEMA.deficit = '<b>Déficit hídrico y sequía (predicción):</b> con series mensuales de NASA POWER (1991 al presente) se calcula el balance de agua: evapotranspiración (Hargreaves, con T2M, T2M_MAX y T2M_MIN) menos lluvia (PRECTOTCORR). Se proyectan los próximos 12 meses sumando la tendencia lineal al promedio de cada mes, y la sequía actual se mide con un índice estandarizado de los últimos 3 meses. Color: déficit proyectado como parte del agua que pide el clima. Verde: &lt;15%, amarillo: 15-45% y rojo: &gt;45%. Es una extrapolación estadística, no un modelo climático. Toca un país para ver el detalle mes a mes.';
EXPLICACION_POR_TEMA.tendencia = '<b>Tendencia climática por zona:</b> cada zona de K-means promedia, entre sus países, la pendiente de la temperatura (°C por década), de la lluvia anual (% por década) y del déficit hídrico (mm por década) con datos mensuales de NASA POWER desde 1991. El color depende del calentamiento: verde &lt;0.2 °C/década, amarillo 0.2-0.4 y rojo &gt;0.4. La tendencia es lineal y la lluvia varía mucho de un año a otro, así que su cambio es menos confiable que el de la temperatura.';
const DATOS_PRED_POR_PAIS = {};     // predicción de cada país (déficit + tendencia)
let TENDENCIA_ZONAS = null, cargandoPred = false;
const signo = n => (n > 0 ? '+' : '') + n;
const DATOS_HUMEDAD_POR_PAIS = {};
const DATOS_LLUVIA_POR_PAIS = {};
const DATOS_CLIMA_POR_PAIS = {};      // valores de clima por país para K-means
let ZONAS_RESULTADO = null;           // {zonas:[...], asignacion:{id:n}, k, silueta}
let cargandoZonas = false, zonaResaltada = null;
let cargandoHumedad = false, numeroSolicitudLluvia = 0;
let temaRiesgoActivo = '', paisesDelMundo = null;
let paisTocadoActual = null;            // último país tocado en el mapa (lo lee el asistente)
const lienzoMapaPlano = obtenerElemento('gr'), contextoMapaPlano = lienzoMapaPlano.getContext('2d');
const proyeccionMapaPlano = d3.geoNaturalEarth1().fitSize([lienzoMapaPlano.width, lienzoMapaPlano.height], {type:'Sphere'});
const trazadoMapaPlano = d3.geoPath(proyeccionMapaPlano, contextoMapaPlano);

function obtenerNivelRiesgoDelPais(pais, tema){
  if (tema === 'deficit') return DATOS_PRED_POR_PAIS[idPais(pais)]?.valores?.nivel || null;
  if (tema === 'tendencia') { const z = ZONAS_RESULTADO?.asignacion[idPais(pais)]; return (z !== undefined && TENDENCIA_ZONAS?.[z]?.nivel) || null; }
  if (tema === 'humedad') return DATOS_HUMEDAD_POR_PAIS[idPais(pais)]?.nivel || null;
  if (tema === 'lluvia') {
    const lluvia = Number(DATOS_LLUVIA_POR_PAIS[idPais(pais)]?.lluvia_acumulada_mm ?? NaN);
    if (!Number.isFinite(lluvia) || lluvia < 0) return null;
    return lluvia < 50 ? 'bajo' : lluvia <= 150 ? 'medio' : 'alto';
  }
  return null;
}

// ===== CONSULTA DE HUMEDAD Y LLUVIA PARA EL MAPA MUNDI (por lotes) =====
// Se envían pocos países a la vez para que el mapa se vaya pintando
// poco a poco y una petición lenta no bloquee todo.
const TAMANO_LOTE = 12;
const idPais = pais => String(pais.id ?? pais.properties.name);

function listaDePaisesParaNasa() {
    return paisesDelMundo.map(pais => {
        const centro = d3.geoCentroid(pais);
        return {id: idPais(pais), nombre: pais.properties.name, lat: centro[1], lon: centro[0]};
    });
}

async function pedirPorLotes(url, paises, extra, alRecibirLote) {
    for (let i = 0; i < paises.length; i += TAMANO_LOTE) {
        const lote = paises.slice(i, i + TAMANO_LOTE);
        const hechos = Math.min(i + TAMANO_LOTE, paises.length);
        let resultado = null;
        try {
            const respuesta = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({paises: lote, ...extra})
            });
            if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
            resultado = await respuesta.json();
        } catch (error) {
            console.error('Error al consultar', url, error);
        }
        if (alRecibirLote(resultado, hechos) === false) return;
    }
}

const esErrorTemporal = dato => !dato || (dato.motivo && /429|no respondi/i.test(dato.motivo));
const esperar = ms => new Promise(resolver => setTimeout(resolver, ms));

function recargarLluviaSiCorresponde() {
    if (temaRiesgoActivo === 'lluvia') cargarLluviaMensualMundial();
}

async function cargarHumedadMundial() {
    if (!paisesDelMundo || cargandoHumedad) return;
    cargandoHumedad = true;
    const decir = texto => { if (temaRiesgoActivo === 'humedad') mostrarTextoYLeyendaDelMapa(texto); };

    const pendientes = listaDePaisesParaNasa().filter(pais => {
        const dato = DATOS_HUMEDAD_POR_PAIS[pais.id];
        return !dato || dato.humedad === null || dato.humedad === undefined;
    });
    decir(`Consultando humedad en NASA POWER... 0/${pendientes.length} países`);

    await pedirPorLotes('/api/humedad-mundial', pendientes, {}, (resultado, hechos) => {
        if (resultado) resultado.resultados.forEach(dato => { DATOS_HUMEDAD_POR_PAIS[dato.id] = dato; });
        dibujarMapaPlano();
        decir(`Consultando humedad en NASA POWER... ${hechos}/${pendientes.length} países`);
    });

    for (let ronda = 1; ronda <= 3; ronda++) {
        const fallidos = pendientes.filter(pais => {
            const dato = DATOS_HUMEDAD_POR_PAIS[pais.id];
            return (!dato || dato.humedad == null) && esErrorTemporal(dato);
        });
        if (!fallidos.length) break;
        decir(`NASA pidió esperar. Reintentando ${fallidos.length} países (ronda ${ronda}/3)...`);
        await esperar(8000);
        await pedirPorLotes('/api/humedad-mundial', fallidos, {}, resultado => {
            if (resultado) resultado.resultados.forEach(dato => { DATOS_HUMEDAD_POR_PAIS[dato.id] = dato; });
            dibujarMapaPlano();
        });
    }

    cargandoHumedad = false;
    const conDato = Object.values(DATOS_HUMEDAD_POR_PAIS).filter(d => d.humedad !== null && d.humedad !== undefined).length;
    decir(conDato
        ? `Humedad mundial cargada (${conDato} países con dato). Toca un país para consultar su porcentaje.`
        : 'No se pudieron obtener datos de humedad. Revisa la terminal de Python o abre /api/prueba-nasa.');
}

async function cargarLluviaMensualMundial() {
    if (!paisesDelMundo) return;
    const anio = +obtenerElemento('selAnio').value, mes = +obtenerElemento('selMes').value;
    const solicitudActual = ++numeroSolicitudLluvia;
    Object.keys(DATOS_LLUVIA_POR_PAIS).forEach(id => delete DATOS_LLUVIA_POR_PAIS[id]);
    dibujarMapaPlano();
    const decir = texto => { if (temaRiesgoActivo === 'lluvia') mostrarTextoYLeyendaDelMapa(texto); };

    const paises = listaDePaisesParaNasa();
    let aviso = '';
    decir(`Consultando lluvia de ${MESES[mes - 1]} de ${anio}... 0/${paises.length} países`);

    await pedirPorLotes('/api/lluvia-mensual', paises, {anio, mes}, (resultado, hechos) => {
        if (solicitudActual !== numeroSolicitudLluvia) return false;
        if (resultado) {
            resultado.resultados.forEach(dato => { DATOS_LLUVIA_POR_PAIS[String(dato.id)] = dato; });
            if (resultado.ajustado) {
                aviso = `Aún no hay datos IMERG de ${MESES[mes - 1]} de ${anio}; se muestra ${MESES[resultado.mes_mostrado - 1]} de ${resultado.anio_mostrado}, el último mes disponible. `;
            }
        }
        dibujarMapaPlano();
        if (hechos < paises.length) decir(`${aviso}Consultando lluvia... ${hechos}/${paises.length} países`);
    });

    for (let ronda = 1; ronda <= 3; ronda++) {
        if (solicitudActual !== numeroSolicitudLluvia) return;
        const fallidos = paises.filter(pais => {
            const dato = DATOS_LLUVIA_POR_PAIS[pais.id];
            return (!dato || dato.lluvia_acumulada_mm == null) && esErrorTemporal(dato);
        });
        if (!fallidos.length) break;
        decir(`${aviso}NASA pidió esperar. Reintentando ${fallidos.length} países (ronda ${ronda}/3)...`);
        await esperar(8000);
        await pedirPorLotes('/api/lluvia-mensual', fallidos, {anio, mes}, resultado => {
            if (solicitudActual !== numeroSolicitudLluvia) return false;
            if (resultado) resultado.resultados.forEach(dato => { DATOS_LLUVIA_POR_PAIS[String(dato.id)] = dato; });
            dibujarMapaPlano();
        });
    }

    if (solicitudActual !== numeroSolicitudLluvia) return;
    const conDato = Object.values(DATOS_LLUVIA_POR_PAIS).filter(d => d.lluvia_acumulada_mm !== null && d.lluvia_acumulada_mm !== undefined).length;
    decir(conDato
        ? `${aviso}Lluvia mensual NASA GPM IMERG (${conDato} países con dato). Toca un país para ver sus milímetros.`
        : `${aviso}NASA no devolvió datos de lluvia. Revisa la terminal de Python o abre /api/prueba-nasa.`);
}

async function agruparZonas(){
  const puntos = {};
  Object.values(DATOS_CLIMA_POR_PAIS).forEach(d => { if(d.valores) puntos[d.id] = d.valores; });
  const k = obtenerElemento('selK').value;
  const respuesta = await fetch('/api/zonas-agrupar', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({puntos, k: k ? +k : null})});
  const datos = await respuesta.json();
  if(!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'No se pudieron formar zonas');
  ZONAS_RESULTADO = datos; zonaResaltada = null;
}

async function cargarZonasMundiales() {
    if (!paisesDelMundo || cargandoZonas) return;
    cargandoZonas = true;
    const decir = texto => { if (temaRiesgoActivo === 'zonas') mostrarTextoYLeyendaDelMapa(texto); };
    const sinDato = pais => { const d = DATOS_CLIMA_POR_PAIS[pais.id]; return !d || !d.valores; };

    try {
        const pendientes = listaDePaisesParaNasa().filter(sinDato);
        if (pendientes.length) decir(`Consultando clima en NASA POWER... 0/${pendientes.length} países`);

        await pedirPorLotes('/api/zonas-clima', pendientes, {}, (resultado, hechos) => {
            if (resultado) resultado.resultados.forEach(dato => { DATOS_CLIMA_POR_PAIS[dato.id] = dato; });
            decir(`Consultando clima en NASA POWER... ${hechos}/${pendientes.length} países`);
        });

        for (let ronda = 1; ronda <= 3; ronda++) {
            const fallidos = pendientes.filter(pais => sinDato(pais) && esErrorTemporal(DATOS_CLIMA_POR_PAIS[pais.id]));
            if (!fallidos.length) break;
            decir(`NASA pidió esperar. Reintentando ${fallidos.length} países (ronda ${ronda}/3)...`);
            await esperar(8000);
            await pedirPorLotes('/api/zonas-clima', fallidos, {}, resultado => {
                if (resultado) resultado.resultados.forEach(dato => { DATOS_CLIMA_POR_PAIS[dato.id] = dato; });
            });
        }

        const conDato = Object.values(DATOS_CLIMA_POR_PAIS).filter(d => d.valores).length;
        if (conDato < 4) { decir('No se obtuvieron suficientes datos de NASA para formar zonas. Revisa la terminal de Python.'); return; }
        decir('Agrupando países con K-means...');
        await agruparZonas();
        dibujarMapaPlano();
        decir(`Zonas agroclimáticas formadas con ${conDato} países. Toca una zona de la lista o un país del mapa.`);
    } catch (error) {
        console.error(error);
        decir('Error al formar las zonas: ' + error.message);
    } finally {
        cargandoZonas = false;
    }
}

function dibujarMapaPlano(){
  contextoMapaPlano.clearRect(0, 0, lienzoMapaPlano.width, lienzoMapaPlano.height);
  contextoMapaPlano.beginPath(); trazadoMapaPlano({type:'Sphere'}); contextoMapaPlano.fillStyle = '#0a2a55'; contextoMapaPlano.fill();
  if(!paisesDelMundo) return;
  paisesDelMundo.forEach(pais => {
    const nivelRiesgo = temaRiesgoActivo && temaRiesgoActivo !== 'zonas' && obtenerNivelRiesgoDelPais(pais, temaRiesgoActivo);
    let colorPais = nivelRiesgo ? COLORES_NIVEL_RIESGO[nivelRiesgo] : '#8fd0ff';
    if(temaRiesgoActivo === 'zonas' && ZONAS_RESULTADO){
      const zona = ZONAS_RESULTADO.zonas[ZONAS_RESULTADO.asignacion[idPais(pais)]];
      if(zona) colorPais = (zonaResaltada === null || zonaResaltada === zona.id) ? zona.color : '#3a5f8a';
    }
    contextoMapaPlano.beginPath(); trazadoMapaPlano(pais); contextoMapaPlano.fillStyle = colorPais; contextoMapaPlano.fill();
    contextoMapaPlano.strokeStyle = 'rgba(255,255,255,.55)'; contextoMapaPlano.lineWidth = 1; contextoMapaPlano.stroke();
  });
}

const TEXTO_TOCAR_PAIS = 'Toca un país para consultar sus datos.';
function dibujarLeyendaZonas(textoMensaje){
  const cajaZonas = ZONAS_RESULTADO ? `<div class="zonas">${ZONAS_RESULTADO.zonas.map(z => `<div class="zona${zonaResaltada === z.id ? ' on' : ''}" data-z="${z.id}" style="border-left-color:${z.color}">
      <div><b>${caracterEspecialATexto(z.nombre)}</b>${z.paises} países · ${caracterEspecialATexto(z.regimen)}
      <small>${z.centroide.temp} °C · ${Math.round(z.centroide.lluvia)} mm/año · humedad ${z.centroide.humedad}% · amplitud ${z.centroide.amplitud} °C</small></div></div>`).join('')}</div>
      <div class="zona-info">${ZONAS_RESULTADO.k} zonas · silhouette ${ZONAS_RESULTADO.silueta} (más cerca de 1 = grupos mejor separados)</div>` : '';
  obtenerElemento('gcap').innerHTML = caracterEspecialATexto(textoMensaje) + cajaZonas;
}

// ===== PREDICCIÓN: déficit hídrico y tendencia por zona =====
function calcularTendenciaZonas(){
  TENDENCIA_ZONAS = {};
  ZONAS_RESULTADO.zonas.forEach(z => {
    const m = Object.keys(ZONAS_RESULTADO.asignacion).filter(id => ZONAS_RESULTADO.asignacion[id] === z.id)
      .map(id => DATOS_PRED_POR_PAIS[id]?.valores?.tendencia).filter(Boolean);
    const media = campo => m.length ? +(m.reduce((s, x) => s + x[campo], 0) / m.length).toFixed(2) : null;
    const t = media('t_dec');
    TENDENCIA_ZONAS[z.id] = {n: m.length, t, p: media('p_pct_dec'), cwd: media('cwd_dec'), nivel: t === null ? null : t < 0.2 ? 'bajo' : t <= 0.4 ? 'medio' : 'alto'};
  });
}

function dibujarLeyendaTendencia(textoMensaje){
  const tarjetas = TENDENCIA_ZONAS ? `<div class="zonas">${ZONAS_RESULTADO.zonas.map(z => { const t = TENDENCIA_ZONAS[z.id];
    return t.t === null ? '' : `<div class="zona" style="border-left-color:${COLORES_NIVEL_RIESGO[t.nivel]}"><div><b>${caracterEspecialATexto(z.nombre)}</b>${t.n} países
      <small>Temperatura ${signo(t.t)} °C/década · lluvia ${signo(t.p)} %/década · déficit ${signo(Math.round(t.cwd))} mm/década</small></div></div>`; }).join('')}</div>
    <div class="zona-info">Tendencia lineal de 1991 a hoy. Color por calentamiento: verde &lt;0.2 °C/década, amarillo 0.2-0.4, rojo &gt;0.4.</div>` : '';
  obtenerElemento('gcap').innerHTML = caracterEspecialATexto(textoMensaje) + tarjetas;
}

function detalleDeficit(nombre, v){
  const meses = v.meses.filter(Boolean), maximo = Math.max(...meses.map(m => Math.abs(m.deficit)), 1);
  const filas = meses.map(m => `<div class="pbar"><span>${MESES[m.mes - 1].slice(0, 3)} ${String(m.anio).slice(2)}</span>
    <div class="pb"><i class="${m.deficit > 0 ? 'def' : 'sob'}" style="width:${Math.round(Math.abs(m.deficit) / maximo * 100)}%"></i></div>
    <b>${signo(Math.round(m.deficit))} mm</b><small>${Math.round(m.p_deficit * 100)}%</small></div>`).join('');
  return `<h4>${caracterEspecialATexto(nombre)}</h4>
    Sequía actual (${caracterEspecialATexto(v.sequia.periodo || 'sin dato')}): <b>${caracterEspecialATexto(v.sequia.categoria)}</b>${v.sequia.z !== null ? ` (índice ${v.sequia.z})` : ''}.<br>
    Índice de aridez (lluvia / evapotranspiración): <b>${v.aridez ?? '—'}</b>. Déficit proyectado a 12 meses: <b>${Math.round(v.deficit_pron)} mm</b> (promedio histórico ${Math.round(v.deficit_hist)} mm).
    <div style="margin-top:8px"><span class="sub">Déficit esperado por mes · rojo: falta de agua, azul: sobra · % = probabilidad de déficit</span>${filas}</div>`;
}

async function cargarPrediccion(){
  if (!paisesDelMundo || cargandoPred) return;
  cargandoPred = true;
  const decir = texto => { if (temaRiesgoActivo === 'deficit' || temaRiesgoActivo === 'tendencia') mostrarTextoYLeyendaDelMapa(texto); };
  const guardar = resultado => { if (resultado) resultado.resultados.forEach(d => { DATOS_PRED_POR_PAIS[d.id] = d; }); dibujarMapaPlano(); };
  const sinDato = pais => !DATOS_PRED_POR_PAIS[pais.id]?.valores;
  try {
    const pendientes = listaDePaisesParaNasa().filter(sinDato);
    if (pendientes.length) decir(`Consultando series mensuales en NASA POWER... 0/${pendientes.length} países`);
    await pedirPorLotes('/api/prediccion-clima', pendientes, {}, (resultado, hechos) => { guardar(resultado); decir(`Consultando series mensuales en NASA POWER... ${hechos}/${pendientes.length} países`); });
    for (let ronda = 1; ronda <= 3; ronda++) {
      const fallidos = pendientes.filter(pais => sinDato(pais) && esErrorTemporal(DATOS_PRED_POR_PAIS[pais.id]));
      if (!fallidos.length) break;
      decir(`NASA pidió esperar. Reintentando ${fallidos.length} países (ronda ${ronda}/3)...`);
      await esperar(8000);
      await pedirPorLotes('/api/prediccion-clima', fallidos, {}, guardar);
    }
    if (temaRiesgoActivo === 'tendencia' && !ZONAS_RESULTADO) { decir('Formando zonas con K-means...'); await cargarZonasMundiales(); }
    if (ZONAS_RESULTADO) calcularTendenciaZonas();
    dibujarMapaPlano();
    const conDato = Object.values(DATOS_PRED_POR_PAIS).filter(d => d.valores).length;
    decir(!conDato ? 'NASA no devolvió series mensuales. Revisa la terminal de Python.'
      : temaRiesgoActivo === 'tendencia' && !ZONAS_RESULTADO ? 'No se pudieron formar zonas para calcular la tendencia.'
      : `Predicción lista (${conDato} países con dato). Toca un país para ver el detalle.`);
  } catch (error) {
    console.error(error); decir('Error en la predicción: ' + error.message);
  } finally { cargandoPred = false; }
}

function mostrarTextoYLeyendaDelMapa(textoMensaje){
  if(temaRiesgoActivo === 'tendencia') return dibujarLeyendaTendencia(textoMensaje);
  if(temaRiesgoActivo === 'zonas') return dibujarLeyendaZonas(textoMensaje);
  const esHumedad = temaRiesgoActivo === 'humedad';
  const esLluvia = temaRiesgoActivo === 'lluvia';
  const nombreDato = esHumedad ? 'Humedad' : esLluvia ? 'Lluvia' : 'Riesgo';
  const leyendaColores = temaRiesgoActivo
    ? '<div class="lg">' + [
        ['bajo', esHumedad ? 'Humedad baja' : esLluvia ? 'Lluvia baja' : 'Riesgo bajo'],
        ['medio', esHumedad ? 'Humedad media' : esLluvia ? 'Lluvia media' : 'Riesgo medio'],
        ['alto', esHumedad ? 'Humedad alta' : esLluvia ? 'Lluvia alta' : 'Riesgo alto']
    ].map(([nivelRiesgo, etiquetaNivel]) =>
        `<span><i style="background:${COLORES_NIVEL_RIESGO[nivelRiesgo]}"></i>${etiquetaNivel}</span>`
    ).join('') + '</div>'
    : '';
  obtenerElemento('gcap').innerHTML = caracterEspecialATexto(textoMensaje) + leyendaColores;
}

function activarTemaDeRiesgo(temaRiesgo){
  temaRiesgoActivo = temaRiesgo;
  dibujarMapaPlano();
  document.querySelectorAll('#capas button').forEach(botonTema => botonTema.classList.toggle('on', botonTema.dataset.c === temaRiesgo));
  obtenerElemento('explica').innerHTML = EXPLICACION_POR_TEMA[temaRiesgo] || '';
  obtenerElemento('filtroLluvia').style.display = temaRiesgo === 'lluvia' ? 'flex' : 'none';
  obtenerElemento('filtroZonas').style.display = (temaRiesgo === 'zonas' || temaRiesgo === 'tendencia') ? 'flex' : 'none';
  obtenerElemento('predDet').innerHTML = '';
  if (temaRiesgo === 'humedad') {
    mostrarTextoYLeyendaDelMapa('Consultando humedad mundial...');
    cargarHumedadMundial();
  } else if (temaRiesgo === 'lluvia') {
    mostrarTextoYLeyendaDelMapa('Consultando lluvia mensual...');
    cargarLluviaMensualMundial();
  } else if (temaRiesgo === 'zonas') {
    mostrarTextoYLeyendaDelMapa(ZONAS_RESULTADO ? 'Zonas agroclimáticas. Toca una zona de la lista o un país del mapa.' : 'Consultando clima para formar zonas...');
    if (!ZONAS_RESULTADO) cargarZonasMundiales();
  } else if (temaRiesgo === 'deficit' || temaRiesgo === 'tendencia') {
    mostrarTextoYLeyendaDelMapa('Consultando series mensuales en NASA POWER...');
    cargarPrediccion();
  } else {
    mostrarTextoYLeyendaDelMapa(temaRiesgo ? TEXTO_TOCAR_PAIS : 'Elige Humedad o Lluvia arriba para pintar el mundo.');
  }
}

// Agregar el botón de lluvia al menú de capas si todavía no existe
if (!document.querySelector('#capas button[data-c="lluvia"]')) {
  const botonLluvia = document.createElement('button');
  botonLluvia.type = 'button';
  botonLluvia.dataset.c = 'lluvia';
  botonLluvia.textContent = 'Lluvia mensual GPM';
  obtenerElemento('capas').appendChild(botonLluvia);
}

obtenerElemento('capas').onclick = evento => {
  const botonTema = evento.target.closest('button');
  if(botonTema) activarTemaDeRiesgo(botonTema.dataset.c);
};

obtenerElemento('selK').onchange = async () => {
  if (temaRiesgoActivo !== 'zonas' && temaRiesgoActivo !== 'tendencia') return;
  if (Object.values(DATOS_CLIMA_POR_PAIS).filter(d => d.valores).length < 4) { ZONAS_RESULTADO = null; return cargarZonasMundiales(); }
  try { mostrarTextoYLeyendaDelMapa('Agrupando países con K-means...'); await agruparZonas(); if (temaRiesgoActivo === 'tendencia') calcularTendenciaZonas(); dibujarMapaPlano(); mostrarTextoYLeyendaDelMapa('Zonas recalculadas.'); }
  catch (error) { mostrarTextoYLeyendaDelMapa('Error al formar las zonas: ' + error.message); }
};
obtenerElemento('gcap').addEventListener('click', evento => {
  const tarjeta = evento.target.closest('.zona');
  if (!tarjeta || temaRiesgoActivo !== 'zonas') return;
  const id = +tarjeta.dataset.z;
  zonaResaltada = zonaResaltada === id ? null : id;
  dibujarMapaPlano();
  mostrarTextoYLeyendaDelMapa(zonaResaltada === null ? 'Mostrando todas las zonas.' : `Resaltando: ${ZONAS_RESULTADO.zonas[id].nombre}.`);
});

fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json').then(respuesta => respuesta.json())
  .then(topologiaPaises => {
    paisesDelMundo = topojson.feature(topologiaPaises, topologiaPaises.objects.countries).features;
    dibujarMapaPlano();
    cargarHumedadMundial();
  })
  .catch(() => { obtenerElemento('gcap').textContent = 'No se pudo cargar el mapa del mundo. Revisa tu internet.'; });

lienzoMapaPlano.addEventListener('click', evento => {
  if(!paisesDelMundo) return;
  const cajaLienzo = lienzoMapaPlano.getBoundingClientRect(), factorEscala = lienzoMapaPlano.width / cajaLienzo.width;
  const coordenadasGeograficas = proyeccionMapaPlano.invert([(evento.clientX - cajaLienzo.left) * factorEscala, (evento.clientY - cajaLienzo.top) * factorEscala]);
  const paisTocado = coordenadasGeograficas && paisesDelMundo.find(pais => d3.geoContains(pais, coordenadasGeograficas));
  if(!paisTocado) return mostrarTextoYLeyendaDelMapa(temaRiesgoActivo ? TEXTO_TOCAR_PAIS : 'Elige un tema para ver sus datos.');
  paisTocadoActual = paisTocado;
  const nivelRiesgo = temaRiesgoActivo && obtenerNivelRiesgoDelPais(paisTocado, temaRiesgoActivo);
  if (temaRiesgoActivo === 'humedad') {
    const dato = DATOS_HUMEDAD_POR_PAIS[idPais(paisTocado)];
    mostrarTextoYLeyendaDelMapa(dato && dato.humedad !== null ? `${dato.nombre}: humedad ${dato.humedad}% (${dato.nivel}).` : `${paisTocado.properties.name}: sin datos de humedad${dato && dato.motivo ? ' (' + dato.motivo + ')' : ''}.`);
    return;
  }
  if (temaRiesgoActivo === 'lluvia') {
    const dato = DATOS_LLUVIA_POR_PAIS[idPais(paisTocado)];
    mostrarTextoYLeyendaDelMapa(dato && dato.lluvia_acumulada_mm !== null && dato.lluvia_acumulada_mm !== undefined
      ? `${dato.nombre}: ${dato.lluvia_acumulada_mm} mm de lluvia acumulada en ${MESES[dato.mes - 1]} de ${dato.anio} (${nivelRiesgo || 'sin clasificación'}).`
      : `${paisTocado.properties.name}: sin datos de lluvia para este mes${dato && dato.motivo ? ' (' + dato.motivo + ')' : ''}.`);
    return;
  }
  if (temaRiesgoActivo === 'deficit') {
    const v = DATOS_PRED_POR_PAIS[idPais(paisTocado)]?.valores, nombre = paisTocado.properties.name;
    mostrarTextoYLeyendaDelMapa(v ? `${nombre}: déficit proyectado de ${Math.round(v.deficit_pron)} mm en 12 meses (${v.cambio_pct === null ? 'sin cambio calculable' : signo(v.cambio_pct) + '% frente a su promedio'}), nivel ${v.nivel}; ${v.sequia.categoria}.` : `${nombre}: sin datos de predicción.`);
    obtenerElemento('predDet').innerHTML = v ? detalleDeficit(nombre, v) : '';
    return;
  }
  if (temaRiesgoActivo === 'tendencia') {
    const nombre = paisTocado.properties.name, z = ZONAS_RESULTADO?.asignacion[idPais(paisTocado)];
    const v = DATOS_PRED_POR_PAIS[idPais(paisTocado)]?.valores?.tendencia, t = z !== undefined && TENDENCIA_ZONAS?.[z];
    mostrarTextoYLeyendaDelMapa(v && t ? `${nombre} (zona "${ZONAS_RESULTADO.zonas[z].nombre}"): ${signo(v.t_dec)} °C/década${v.t_sig ? '' : ' (no significativa)'}, lluvia ${signo(v.p_pct_dec)} %/década${v.p_sig ? '' : ' (no significativa)'}. Promedio de su zona: ${signo(t.t)} °C/década.` : `${nombre}: sin tendencia disponible.`);
    return;
  }
  if (temaRiesgoActivo === 'zonas') {
    const zona = ZONAS_RESULTADO && ZONAS_RESULTADO.zonas[ZONAS_RESULTADO.asignacion[idPais(paisTocado)]];
    const valores = DATOS_CLIMA_POR_PAIS[idPais(paisTocado)]?.valores;
    mostrarTextoYLeyendaDelMapa(zona && valores
      ? `${paisTocado.properties.name}: zona "${zona.nombre}" (${zona.regimen}). ${valores.temp} °C de media, ${Math.round(valores.lluvia)} mm/año, humedad ${valores.humedad}%, amplitud térmica ${valores.amplitud} °C.`
      : `${paisTocado.properties.name}: sin zona asignada (NASA no devolvió datos para este punto).`);
    return;
  }
  mostrarTextoYLeyendaDelMapa(`${paisTocado.properties.name}. Elige Humedad, Lluvia o Zonas para ver sus datos.`);
});
activarTemaDeRiesgo('');


/* ===== Enviar el formulario: Python consulta NASA, calcula probabilidades y arma las rotaciones ===== */
obtenerElemento('btnEnviar').addEventListener('click', async () => {
  const salida = obtenerElemento('respuesta'), boton = obtenerElemento('btnEnviar');
  const latitud = parseFloat(campoLat.value), longitud = parseFloat(campoLon.value);
  if(!Number.isFinite(latitud) || !Number.isFinite(longitud) || Math.abs(latitud) > 90 || Math.abs(longitud) > 180){
    salida.textContent = 'Escribe una latitud (-90 a 90) y una longitud (-180 a 180) válidas, o toca el mapa.'; return;
  }
  const datos = {
    cultivo: camposFormulario.cultivo.value.trim(),
    tipo_suelo: camposFormulario.suelo.value,
    lat: latitud, lon: longitud,
    nombre_lugar: puntoSeleccionado?.nombre || ''
  };
  boton.disabled = true;
  salida.textContent = 'Consultando NASA POWER (20 parámetros, 10 años) y calculando rotaciones… puede tardar hasta un minuto.';
  try{
    const respuesta = await fetch('/api/rotaciones', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(datos)});
    const resultado = await respuesta.json();
    if(!respuesta.ok) throw new Error(typeof resultado.detail === 'string' ? resultado.detail : JSON.stringify(resultado.detail));
    salida.textContent = '¡Listo! Rotaciones calculadas para tu punto.';
    mostrarResultados(datos, resultado);
    obtenerElemento('resultados').scrollIntoView({behavior:'smooth'});
  }catch(error){
    console.error(error);
    salida.textContent = 'Error: ' + error.message;
  }finally{
    boton.disabled = false;
  }
});