// Opinión del bot sobre una apuesta escrita en el chat («¿cómo ves Barcelona gana y más de 2.5?», «¿qué tan segura es
// Haaland tira al arco y más de 8.5 córners en el City?») y conversación sobre ella («quítale los córners», «agrégale
// ambos anotan», «¿y si la cambio a más de 1.5?»). Usa todo lo que el paquete diario trae del partido: probabilidades
// calibradas, goles/córners/tarjetas/tiros/atajadas esperados, forma reciente, enfrentamientos directos y el estado de
// los jugadores. La probabilidad conjunta se calcula como en el armador (goles exactos en la grilla de marcadores).
import 'dart:math' as math;

import 'armador.dart';
import 'comunes.dart';
import 'vivo.dart' show normal, parecido;

class Apuesta {
  final Map<String, dynamic> partido;
  final List<Seleccion> sels;
  Apuesta(this.partido, this.sels);
  String get nombre => '${partido['local']?['nombre']} vs ${partido['visitante']?['nombre']}';
}

double _n(String s) => double.parse(s.replaceAll(',', '.'));

/// Busca en el catálogo del partido la selección que describe el texto (un trozo: «más de 2.5 goles», «Haaland 2+»).
Seleccion? _buscar(String trozo, Map<String, dynamic> m, List<Seleccion> cat) {
  final t = ' ${normal(trozo)} ';
  final crudo = trozo.toLowerCase().replaceAll(',', '.');
  final ln = '${m['local']?['nombre'] ?? ''}', vn = '${m['visitante']?['nombre'] ?? ''}';
  bool nombra(String eq) {
    final n = normal(eq);
    return n.isNotEmpty && (t.contains(' $n ') || n.split(' ').where((w) => w.length >= 4).any((w) => t.contains(' $w ')));
  }
  var esL = nombra(ln), esV = nombra(vn);
  // «córners en el Manchester City» = del partido; «córners del City» = del equipo
  final enElPartido = RegExp(r' en (el |la )?(partido |juego )?(del |de )?\w').hasMatch(t) && !RegExp(r' (del|de) ').hasMatch(t);
  final conteo = RegExp(r'corner|esquina|tarjeta|amarilla|atajada|parada|tiro|remate|arco').hasMatch(t) &&
      !RegExp(r'\d\s*\+').hasMatch(crudo);
  if (conteo && enElPartido) {
    esL = false;
    esV = false;
  }
  Seleccion? clave(String k) => cat.where((s) => s.clave == k).firstOrNull;
  // jugadores
  for (final j in (m['jugadores'] as List? ?? [])) {
    final nom = '${j['nombre']}';
    final ape = normal(nom).split(' ').where((w) => w.length >= 3).toList();
    if (ape.isEmpty || !(t.contains(' ${ape.last} ') || (ape.length > 1 && t.contains(' ${ape.first} ')))) continue;
    if (RegExp(r'gol o asist|marca o asist|anota o asist|g\+a').hasMatch(t)) return clave('jug_ga|si|$nom');
    if (t.contains('asist')) return clave('jug_asist|si|$nom');
    if (RegExp(r'\b(gol|marca|anota|goleador|convierte)\b').hasMatch(t) && !t.contains('tiro')) return clave('jug_gol|si|$nom');
    final k = RegExp(r'(\d)\s*\+').firstMatch(crudo)?.group(1) ?? RegExp(r'(\d)\s*(?:o mas )?tiros?').firstMatch(t)?.group(1) ?? '1';
    return clave('jug_arco|$k+|$nom') ?? clave('jug_arco|${int.parse(k) + 1}+|$nom');
  }
  if (RegExp(r'ambos (equipos )?(anotan|marcan)|btts').hasMatch(t)) {
    return clave(RegExp(r'\bno\b').hasMatch(t) ? 'btts|no|' : 'btts|si|');
  }
  if (t.contains('o empate') || t.contains('empate o') || t.contains('doble') || RegExp(r'\b(1x|x2)\b').hasMatch(t)) {
    if (RegExp(r'\bx2\b').hasMatch(t) || (esV && !esL)) return clave('doble|X2|');
    if (esL && esV) return clave('doble|12|');
    return clave('doble|1X|');
  }
  final mm = RegExp(r'(m[aá]s|menos|over|under)\s*(?:de\s*)?(\d{1,2}(?:[.,]5)?)').firstMatch(crudo);
  if (mm != null) {
    final mas = mm.group(1)!.startsWith('m') && mm.group(1) != 'menos' || mm.group(1) == 'over';
    var l = _n(mm.group(2)!);
    if (l == l.roundToDouble()) l += 0.5; // «más de 2 goles» = Más de 2.5 en Betano? no: «más de 2» = 2.5
    final o = mas ? 'mas' : 'menos';
    String base;
    if (RegExp(r'corner|esquina').hasMatch(t)) {
      base = 'corners';
    } else if (t.contains('tarjeta') || t.contains('amarilla')) {
      base = 'tarjetas';
    } else if (RegExp(r'atajada|parada').hasMatch(t)) {
      base = 'atajadas';
    } else if (RegExp(r'tiro|remate|arco|puerta').hasMatch(t)) {
      base = 'tiros_arco';
    } else if (RegExp(r'primer tiempo|1er tiempo|1 tiempo|primera mitad|1t').hasMatch(t)) {
      return clave('1t_goles|$o|$l');
    } else {
      if (esL != esV) return clave('${esL ? 'goles_local' : 'goles_visitante'}|$o|$l');
      return clave('goles|$o|$l');
    }
    // «córners en el Manchester City»: del equipo si existe esa línea; si no, del partido
    if (esL != esV) return clave('$base${esL ? '_local' : '_visitante'}|$o|$l') ?? clave('$base|$o|$l');
    return clave('$base|$o|$l');
  }
  if (RegExp(r'\b(gana|ganador|victoria|vence|gane)\b').hasMatch(t) || t.trim().split(' ').length <= 3) {
    if (esL && !esV) return clave('1x2|local|');
    if (esV && !esL) return clave('1x2|visitante|');
  }
  if (RegExp(r'gol en el primer tiempo|gol primer tiempo').hasMatch(t)) return clave('1t_goles|mas|0.5');
  return null;
}

/// Lee una apuesta escrita. [partido] = el partido del que se viene hablando (si el texto no nombra equipos).
(Apuesta?, List<String>) leerApuestaTexto(String texto, Map<String, dynamic>? partido, List<Map<String, dynamic>> partidos,
    double Function(String, double) corregir) {
  final t = ' ${normal(texto)} ';
  Map<String, dynamic>? m;
  var mejor = 0.0;
  for (final p in partidos) {
    var s = 0.0;
    for (final eq in ['${p['local']?['nombre']}', '${p['visitante']?['nombre']}']) {
      final n = normal(eq);
      if (t.contains(' $n ')) {
        s += 1;
      } else if (n.split(' ').where((w) => w.length >= 4 && !{'real', 'united', 'city', 'club', 'sporting', 'saint'}.contains(w))
          .any((w) => t.contains(' $w '))) {
        s += 0.6;
      }
    }
    if (s > mejor) {
      mejor = s;
      m = p;
    }
  }
  m ??= partido;
  if (m == null) return (null, []);
  final cat = seleccionesPartido(m, corregir);
  final trozos = _trozos(texto)
      .where((x) => x.trim().length > 1);
  final sels = <Seleccion>[];
  final noEntendidas = <String>[];
  for (final tr in trozos) {
    final s = _buscar(tr, m, cat);
    if (s != null) {
      if (!sels.any((x) => x.clave == s.clave)) sels.add(s);
    } else if (RegExp(r'm[aá]s|menos|gana|ambos|empate|corner|tarjeta|tiro|gol|asist|ataj', caseSensitive: false).hasMatch(tr)) {
      noEntendidas.add(tr.trim());
    }
  }
  return (Apuesta(m, sels), noEntendidas);
}

String _veredicto(double p) => p >= 0.85 ? '🟢 Muy segura' : p >= 0.70 ? '🟢 Segura' : p >= 0.55 ? '🟡 Riesgo medio'
    : p >= 0.35 ? '🟠 Arriesgada' : '🔴 Muy arriesgada';

/// Por qué el bot da esa probabilidad a la selección (datos del partido).
String _porque(Seleccion s, Map<String, dynamic> m) {
  final e = Map<String, dynamic>.from(m['esperados'] ?? {});
  final mer = '${s.sel['mercado']}';
  String x(String k) => e[k] == null ? '?' : (e[k] as num).toStringAsFixed(1);
  if (mer.startsWith('jug_')) {
    final j = (m['jugadores'] as List? ?? []).cast<Map>().where((j) => j['nombre'] == s.sel['jugador_nombre']).firstOrNull;
    if (j == null) return '';
    final av = ((j['avisos'] as List?) ?? []).where((a) => !'$a'.startsWith('Rival sin datos')).toList();
    return 'titular ${pct(((j['titular'] ?? 0) as num).toDouble())} de sus últimos 10'
        '${j['arco90'] != null ? ', ${(j['arco90'] as num).toStringAsFixed(1)} tiros al arco por 90’' : ''}'
        '${j['ultima'] != null ? ', jugó por última vez el ${'${j['ultima']}'.substring(5).split('-').reversed.join('/')}' : ''}'
        '${av.isNotEmpty ? '. ⚠️ ${av.first}' : ''}';
  }
  if (mer.startsWith('corners')) return 'córners esperados ${x('corners')} (${x('corners_local')}–${x('corners_visitante')})';
  if (mer.startsWith('tarjetas')) return 'tarjetas esperadas ${x('tarjetas')} (amarilla 1, roja 2)';
  if (mer.startsWith('tiros_arco')) return 'tiros al arco esperados ${x('tiros_arco')} (${x('tiros_arco_local')}–${x('tiros_arco_visitante')})';
  if (mer.startsWith('atajadas')) return 'atajadas esperadas ${x('atajadas_local')} del local y ${x('atajadas_visitante')} del visitante';
  return 'goles esperados ${x('goles')} (${x('goles_local')}–${x('goles_visitante')})';
}

String _forma(Map<String, dynamic> m) {
  final f = Map<String, dynamic>.from(m['forma'] ?? {});
  if (f.isEmpty) return '';
  String linea(String lado, String nombre) {
    final us = (f[lado] as List? ?? []).cast<Map>();
    if (us.isEmpty) return '';
    final gf = us.fold<int>(0, (a, x) => a + (x['gf'] as num).toInt()), gc = us.fold<int>(0, (a, x) => a + (x['gc'] as num).toInt());
    return '$nombre: ${us.map((x) => x['res']).join()} (últimos ${us.length}: $gf a favor, $gc en contra; último '
        '${us.first['gf']}-${us.first['gc']} ${us.first['casa'] == true ? 'vs' : 'en casa de'} ${us.first['rival']})';
  }
  final b = StringBuffer();
  final a = linea('local', '${m['local']?['nombre']}'), c = linea('visitante', '${m['visitante']?['nombre']}');
  if (a.isNotEmpty) b.writeln('📈 $a');
  if (c.isNotEmpty) b.writeln('📈 $c');
  final h = (f['h2h'] as List? ?? []).cast<Map>();
  if (h.isNotEmpty) b.writeln('🤝 Últimos cruces: ${h.take(3).map((x) => '${x['local']} ${x['gl']}-${x['gv']} ${x['visitante']} (${x['fecha']})').join(' · ')}');
  return b.toString();
}

/// Opinión completa de la apuesta. [cuota] = la que te paga Betano (si la dijiste).
String opinar(Apuesta a, {double? cuota, List<String> noEntendidas = const []}) {
  final m = a.partido;
  final b = StringBuffer('🔍 ${a.nombre} (${m['liga_nombre'] ?? ''}, ${m['inicio'] ?? ''})\n');
  if (a.sels.isEmpty) {
    b.write('No reconocí selecciones que el bot calcule. Escríbelas como en Betano: «gana el Barcelona», «más de 2.5 goles», '
        '«ambos anotan», «más de 8.5 córners», «Haaland 2+ tiros al arco», «Raphinha marca».');
    return b.toString();
  }
  for (final s in a.sels) {
    final pq = _porque(s, m);
    b.writeln('• ${s.titulo} · ${s.mercado} → ${pct(s.p)}${pq.isEmpty ? '' : ' — $pq'}');
  }
  final p = conjunta(m, a.sels);
  final justa = 1 / p;
  b.writeln();
  b.writeln('${_veredicto(p)}: ${a.sels.length == 1 ? 'se cumple' : 'se cumplen todas'} el ${pct(p)} de las veces '
      '(${deCada10(p)}). Cuota justa ≈${f2(justa)}${a.sels.length > 1 ? ' · en Betano el Bet Builder pagaría ≈${f2(cuotaEstimada(p, a.sels.length))}' : ''}.');
  if (cuota != null) {
    final ev = p * cuota - 1;
    b.writeln(ev >= 0.03 ? '💰 A cuota ${f2(cuota)} tiene valor (paga más de lo que vale).'
        : ev <= -0.08 ? '⚠️ A cuota ${f2(cuota)} paga menos de lo que vale: a la larga pierde.'
        : '≈ A cuota ${f2(cuota)} está cerca de lo justo.');
  }
  if (a.sels.length > 1) {
    final debil = [...a.sels]..sort((x, y) => x.p.compareTo(y.p));
    final d = debil.first;
    final sin = conjunta(m, [...a.sels]..remove(d));
    b.writeln('🔎 Lo más flojo: ${d.titulo} (${d.mercado}, ${pct(d.p)}). Sin ella subes a ${pct(sin)}.');
    // alternativa más segura del mismo mercado
    final cat = seleccionesPartido(m, (k, v) => v);
    final alt = cat.where((s) => s.grupo == d.grupo && s.p > d.p + 0.04).toList()..sort((x, y) => x.p.compareTo(y.p));
    if (alt.isNotEmpty) {
      final nueva = [...a.sels]..[a.sels.indexOf(d)] = alt.first;
      b.writeln('💡 Si la cambias por ${alt.first.titulo} (${pct(alt.first.p)}), la apuesta sube a ${pct(conjunta(m, nueva))}.');
    }
  }
  if (noEntendidas.isNotEmpty) b.writeln('❔ No pude calcular: ${noEntendidas.join(' · ')} (línea o mercado que el bot no tiene).');
  final fo = _forma(m);
  if (fo.isNotEmpty) b.write('\n$fo');
  final est = (m['estimados'] as List? ?? []);
  if (a.sels.any((s) => est.contains('${s.sel['mercado']}'))) {
    b.writeln('ℹ️ Córners/tarjetas/tiros/atajadas de este partido: estimación por promedios de cada equipo (comprobada con partidos pasados).');
  }
  return b.toString().trim();
}

/// Separa una apuesta escrita en selecciones («Barcelona gana y más de 2.5, Raphinha 1+»). El «+» de «1+» no separa.
Iterable<String> _trozos(String texto) =>
    texto.split(RegExp(r'\s*(?:(?<!\d)\+|,|;|\n|\by\b|\bcon\b|\badem[aá]s\b)\s*', caseSensitive: false)).where((x) => x.trim().length > 1);

const _verbos = r'\b(quita\w*|saca\w*|sin|elimina\w*|borra\w*|agrega\w*|añade\w*|anade\w*|cambia\w*|en vez de|mejor|'
    r'reemplaza\w*|baja\w*|sube\w*|ponle|y si|el|la|los|las)\b';

/// Cambios sobre la apuesta de la que se viene hablando: «quítale X», «agrégale Y y Z», «cámbiala a W».
Apuesta? modificar(Apuesta a, String texto, double Function(String, double) corregir) {
  final t = ' ${normal(texto)} ';
  final cat = seleccionesPartido(a.partido, corregir);
  final sels = [...a.sels];
  final quitar = RegExp(r'\b(quita|quitale|saca|sacale|sin|elimina|borra)\b').hasMatch(t);
  final cambiar = RegExp(r'\b(cambia|cambiala|cambialo|en vez|mejor|reemplaza|baja|bajale|sube|subele)\b').hasMatch(t);
  var hubo = false;
  for (final tr in _trozos(texto)) {
    final limpio = tr.replaceAll(RegExp(_verbos, caseSensitive: false), ' ');
    final s = _buscar(limpio, a.partido, cat);
    if (quitar) {
      final antes = sels.length;
      sels.removeWhere((x) => (s != null && (x.grupo == s.grupo || x.clave == s.clave)) ||
          (s == null && normal(limpio).split(' ').where((w) => w.length >= 4).any((w) => normal('${x.titulo} ${x.mercado}').contains(w))));
      hubo |= sels.length != antes;
      continue;
    }
    if (s == null) continue;
    final i = sels.indexWhere((x) => x.grupo == s.grupo || (cambiar && x.sel['mercado'] == s.sel['mercado']));
    if (i >= 0) {
      sels[i] = s;
    } else if (!sels.any((x) => x.clave == s.clave)) {
      sels.add(s);
    }
    hubo = true;
  }
  return hubo ? Apuesta(a.partido, sels) : null;
}

/// Cuota que el usuario dice que le pagan («me pagan 1.87», «a 2.10», «cuota 1.9»).
double? cuotaMencionada(String texto) {
  final m = RegExp(r'(?:pagan?|cuota|a)\s+(\d{1,2}[.,]\d{1,2})').firstMatch(texto.toLowerCase());
  return m == null ? null : math.max(1.01, _n(m.group(1)!));
}
