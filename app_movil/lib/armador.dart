// Armador de Bet Builders: todas las selecciones que el bot calcula para un partido, su probabilidad CONJUNTA y los
// mejores Bet Builders de 1 a 10 patas (los más probables para cada cuota).
//
// Probabilidad conjunta de patas del MISMO partido:
//  - Goles (resultado, doble oportunidad, Más/Menos, goles de cada equipo, ambos anotan, 1.er tiempo): exacta sobre
//    la grilla de marcadores (Poisson con los goles esperados del partido; 45 % de los goles en el 1.er tiempo),
//    ajustada a las probabilidades calibradas del bot (factor por pata acotado a ±15 %, como el combinador).
//  - Conteos (córners, tarjetas, tiros al arco, atajadas): Más y Menos del mismo conteo = intervalo exacto.
//  - Entre familias distintas y jugadores se multiplica: aproximación (el bot lo avisa).
// Cuota estimada de un Bet Builder = 1 / (probabilidad conjunta × margen). Betano calcula la suya con mercados
// relacionados, por eso la real puede ser algo menor: siempre se marca con ≈.
import 'dart:math' as math;

import 'datos.dart';

class Seleccion {
  final String clave, titulo, mercado, grupo;
  final double p;
  final Map<String, dynamic> sel;
  Seleccion(this.clave, this.titulo, this.mercado, this.grupo, this.p, this.sel);
  Pata get pata => Pata(titulo, mercado, p, sel);
  String get familia => grupo.split('|').first;
}

const _lineasGoles = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5];

String _num(double x) => x == x.roundToDouble() ? x.toStringAsFixed(0) : x.toString();

/// Todas las selecciones del partido con su probabilidad (ya ajustada con [corregir]).
List<Seleccion> seleccionesPartido(Map<String, dynamic> m, double Function(String, double) corregir) {
  final mer = Map<String, dynamic>.from(m['mercados'] ?? {});
  final ln = '${m['local']?['nombre'] ?? ''}', vn = '${m['visitante']?['nombre'] ?? ''}';
  final out = <Seleccion>[];
  void add(String mercado, String opcion, double? linea, String titulo, String nombreMercado, String grupo) {
    final k = '$mercado|$opcion|${linea == null ? '' : linea.toString()}';
    final v = (mer[k] as num?)?.toDouble();
    if (v == null || v <= 0.01 || v >= 0.995) return;
    out.add(Seleccion(k, titulo, nombreMercado, grupo, corregir(mercado, v), {'mercado': mercado, 'opcion': opcion, 'linea': linea}));
  }

  add('1x2', 'local', null, ln, 'Resultado del partido', 'resultado');
  add('1x2', 'visitante', null, vn, 'Resultado del partido', 'resultado');
  add('doble', '1X', null, '$ln o Empate', 'Doble oportunidad', 'resultado');
  add('doble', 'X2', null, 'Empate o $vn', 'Doble oportunidad', 'resultado');
  add('doble', '12', null, '$ln o $vn', 'Doble oportunidad', 'resultado');
  for (final l in _lineasGoles) {
    add('goles', 'mas', l, 'Más de ${_num(l)}', 'Goles totales Más/Menos', 'goles|mas');
    add('goles', 'menos', l, 'Menos de ${_num(l)}', 'Goles totales Más/Menos', 'goles|menos');
  }
  for (final l in [0.5, 1.5, 2.5]) {
    add('goles_local', 'mas', l, 'Más de ${_num(l)}', '$ln Más/Menos Goles', 'goles_local|mas');
    add('goles_visitante', 'mas', l, 'Más de ${_num(l)}', '$vn Más/Menos Goles', 'goles_visitante|mas');
  }
  add('goles_local', 'menos', 1.5, 'Menos de 1.5', '$ln Más/Menos Goles', 'goles_local|menos');
  add('goles_visitante', 'menos', 1.5, 'Menos de 1.5', '$vn Más/Menos Goles', 'goles_visitante|menos');
  add('btts', 'si', null, 'Sí', 'Ambos equipos anotan', 'btts');
  add('btts', 'no', null, 'No', 'Ambos equipos anotan', 'btts');
  add('1t_goles', 'mas', 0.5, 'Más de 0.5', 'Más/Menos Goles en Primer Tiempo', '1t_goles|mas');
  add('1t_goles', 'menos', 2.5, 'Menos de 2.5', 'Más/Menos Goles en Primer Tiempo', '1t_goles|menos');
  // conteos: córners, tarjetas, tiros al arco y atajadas (del partido y de cada equipo)
  const conteos = {
    'corners': ('Más/Menos Córners', [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5], [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]),
    'tarjetas': ('Más/Menos Tarjetas', [1.5, 2.5, 3.5, 4.5, 5.5, 6.5], [0.5, 1.5, 2.5]),
    'tiros_arco': ('Tiros al Arco', [4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5], [1.5, 2.5, 3.5, 4.5, 5.5]),
    'atajadas': ('Atajadas del portero', [3.5, 4.5, 5.5, 6.5, 7.5], [0.5, 1.5, 2.5, 3.5, 4.5]),
  };
  conteos.forEach((base, v) {
    for (final l in v.$2) {
      add(base, 'mas', l, 'Más de ${_num(l)}', v.$1, '$base|mas');
      add(base, 'menos', l, 'Menos de ${_num(l)}', v.$1, '$base|menos');
    }
    for (final (sufijo, eq) in [('_local', ln), ('_visitante', vn)]) {
      for (final l in v.$3) {
        add('$base$sufijo', 'mas', l, 'Más de ${_num(l)}', '$eq ${v.$1}', '$base$sufijo|mas');
      }
    }
  });
  // jugadores (si es titular): tiros al arco 1+/2+/3+, gol, asistencia, gol o asistencia
  for (final j in (m['jugadores'] as List? ?? [])) {
    final nom = '${j['nombre']}';
    final min = (j['linea_min'] as num?)?.toInt() ?? 1;
    for (final k in [1, 2, 3]) {
      final p = (j['p$k'] as num?)?.toDouble();
      if (p == null || k < min) continue;
      out.add(Seleccion('jug_arco|$k+|$nom', '$k+', '$nom Tiros al Arco', 'jug_arco|$nom', corregir('jug_arco', p),
          {'mercado': 'jug_arco', 'opcion': '$k+', 'linea': k - 0.5, 'jugador_nombre': nom, 'lado': j['lado']}));
    }
    for (final (col, merc, titulo) in [('goles', 'jug_gol', 'Marca gol'), ('asistencias', 'jug_asist', 'Da asistencia'),
        ('ga', 'jug_ga', 'Marca o asiste')]) {
      final p = (j[col] as num?)?.toDouble();
      if (p == null) continue;
      out.add(Seleccion('$merc|si|$nom', 'Sí', '$nom - $titulo', '$merc|$nom', corregir(merc, p),
          {'mercado': merc, 'opcion': 'si', 'linea': 0.5, 'jugador_nombre': nom, 'lado': j['lado']}));
    }
  }
  return out;
}

// ---------------------------------------------------------------- probabilidad conjunta
const _goles = {'1x2', 'doble', 'goles', 'goles_local', 'goles_visitante', 'btts', '1t_goles', '1t_1x2', '2t_goles'};

bool _cumpleGoles(Map<String, dynamic> s, int h1, int a1, int h, int a) {
  final m = '${s['mercado']}', o = '${s['opcion']}';
  final l = (s['linea'] as num?)?.toDouble() ?? 0;
  bool cmp(num v) => o == 'mas' ? v > l : v < l;
  switch (m) {
    case '1x2':
      return o == 'local' ? h > a : o == 'visitante' ? h < a : h == a;
    case '1t_1x2':
      return o == 'local' ? h1 > a1 : o == 'visitante' ? h1 < a1 : h1 == a1;
    case 'doble':
      return o == '1X' ? h >= a : o == 'X2' ? h <= a : h != a;
    case 'goles':
      return cmp(h + a);
    case 'goles_local':
      return cmp(h);
    case 'goles_visitante':
      return cmp(a);
    case 'btts':
      return o == 'si' ? (h > 0 && a > 0) : !(h > 0 && a > 0);
    case '1t_goles':
      return cmp(h1 + a1);
    case '2t_goles':
      return cmp(h + a - h1 - a1);
  }
  return true;
}

double _pois(double l, int k) {
  var p = math.exp(-l);
  for (var i = 1; i <= k; i++) {
    p *= l / i;
  }
  return p;
}

class _Grilla {
  final List<(int, int, int, int)> celdas = [];
  final List<double> pr = [];
  final _mascaras = <String, List<bool>>{};
  final _simples = <String, double>{};
  _Grilla(double lam, double mu) {
    const f = 0.45, n = 5;
    final p1l = [for (var i = 0; i <= n; i++) _pois(lam * f, i)], p1v = [for (var i = 0; i <= n; i++) _pois(mu * f, i)];
    final p2l = [for (var i = 0; i <= n; i++) _pois(lam * (1 - f), i)], p2v = [for (var i = 0; i <= n; i++) _pois(mu * (1 - f), i)];
    var tot = 0.0;
    for (var a = 0; a <= n; a++) {
      for (var b = 0; b <= n; b++) {
        for (var c = 0; c <= n; c++) {
          for (var d = 0; d <= n; d++) {
            final p = p1l[a] * p1v[b] * p2l[c] * p2v[d];
            if (p < 1e-6) continue;
            celdas.add((a, b, a + c, b + d));
            pr.add(p);
            tot += p;
          }
        }
      }
    }
    for (var i = 0; i < pr.length; i++) {
      pr[i] /= tot;
    }
  }

  List<bool> _mascara(Map<String, dynamic> s) => _mascaras.putIfAbsent('${s['mercado']}|${s['opcion']}|${s['linea']}',
      () => [for (final (h1, a1, h, a) in celdas) _cumpleGoles(s, h1, a1, h, a)]);

  double simple(Map<String, dynamic> s) => _simples.putIfAbsent('${s['mercado']}|${s['opcion']}|${s['linea']}', () => prob([s]));

  double prob(List<Map<String, dynamic>> sels) {
    final ms = [for (final s in sels) _mascara(s)];
    var t = 0.0;
    for (var i = 0; i < pr.length; i++) {
      var ok = true;
      for (final m in ms) {
        if (!m[i]) {
          ok = false;
          break;
        }
      }
      if (ok) t += pr[i];
    }
    return t;
  }
}

final _grillas = <String, _Grilla>{};

/// Probabilidad de que se cumplan TODAS las selecciones (del mismo partido).
double conjunta(Map<String, dynamic> m, List<Seleccion> sels) {
  if (sels.isEmpty) return 1;
  if (sels.length == 1) return sels.first.p;
  final mer = Map<String, dynamic>.from(m['mercados'] ?? {});
  var prob = 1.0;
  // goles: grilla de marcadores
  final goles = sels.where((s) => _goles.contains(s.sel['mercado'])).toList();
  if (goles.length == 1) prob *= goles.first.p;
  if (goles.length > 1) {
    final esp = Map<String, dynamic>.from(m['esperados'] ?? {});
    final lam = (esp['goles_local'] as num?)?.toDouble(), mu = (esp['goles_visitante'] as num?)?.toDouble();
    if (lam != null && mu != null) {
      final clave = '${m['local']?['nombre']}|${m['visitante']?['nombre']}';
      final g = _grillas.putIfAbsent(clave, () => _Grilla(lam, mu));
      final pj = g.prob([for (final s in goles) s.sel]);
      var factor = 1.0;
      for (final s in goles) {
        final pg = g.simple(s.sel);
        if (pg > 0) factor *= (s.p / pg).clamp(0.85, 1.15);
      }
      prob *= math.min(pj * factor, goles.map((s) => s.p).reduce(math.min));
    } else {
      for (final s in goles) {
        prob *= s.p;
      }
    }
  }
  // conteos: Más y Menos del mismo conteo como intervalo
  final porConteo = <String, List<Seleccion>>{};
  for (final s in sels.where((s) => !_goles.contains(s.sel['mercado']) && !'${s.sel['mercado']}'.startsWith('jug_'))) {
    porConteo.putIfAbsent('${s.sel['mercado']}', () => []).add(s);
  }
  porConteo.forEach((mercado, xs) {
    final mas = xs.where((x) => x.sel['opcion'] == 'mas').toList(), menos = xs.where((x) => x.sel['opcion'] == 'menos').toList();
    if (mas.length == 1 && menos.length == 1) {
      final pLo = (mer['$mercado|mas|${mas.first.sel['linea']}'] as num?)?.toDouble();
      final pHi = (mer['$mercado|mas|${menos.first.sel['linea']}'] as num?)?.toDouble();
      if (pLo != null && pHi != null) {
        prob *= (pLo - pHi).clamp(0.0, 1.0);
        return;
      }
    }
    for (final x in xs) {
      prob *= x.p;
    }
  });
  // jugadores: independientes
  for (final s in sels.where((s) => '${s.sel['mercado']}'.startsWith('jug_'))) {
    prob *= s.p;
  }
  return prob.clamp(0.0, 1.0).toDouble();
}

double cuotaEstimada(double p, int patas) => double.parse((1 / (p * math.min(1.06 + 0.015 * (patas - 1), 1.15))).clamp(1.01, 500).toStringAsFixed(2));

// ---------------------------------------------------------------- Bet Builders
/// ¿Se pueden juntar? Una por grupo, salvo Más + Menos del mismo conteo (intervalo). Sin contradicciones obvias.
bool compatibles(List<Seleccion> act, Seleccion s) {
  for (final x in act) {
    if (x.grupo == s.grupo) return false;
    if (x.sel['mercado'] == s.sel['mercado'] && x.sel['opcion'] == s.sel['opcion']) return false;
    final jx = x.sel['jugador_nombre'], js = s.sel['jugador_nombre'];
    if (jx != null && jx == js && x.sel['mercado'] == s.sel['mercado']) return false;
  }
  return true;
}

class BetBuilder {
  final List<Seleccion> patas;
  final double p, cuota;
  BetBuilder(this.patas, this.p, this.cuota);
}

/// Los mejores Bet Builders del partido: para cada cuota, el más probable (frente de Pareto), de 1 a [maxPatas]
/// patas, con selecciones de probabilidad ≥ [minPata] y conjunta ≥ [minBB].
List<BetBuilder> betBuilders(Map<String, dynamic> m, List<Seleccion> cands, {required double minPata,
    required double minBB, int maxPatas = 10, int ancho = 40}) {
  // por mercado: la línea más segura, una intermedia y la que más paga sin bajar de minPata
  final porGrupo = <String, List<Seleccion>>{};
  for (final s in cands.where((s) => s.p >= minPata)) {
    porGrupo.putIfAbsent(s.grupo, () => []).add(s);
  }
  final cs = <Seleccion>[];
  for (final g in porGrupo.values) {
    g.sort((a, b) => b.p.compareTo(a.p));
    final elegidas = {g.first, g[g.length ~/ 2], g.last};
    cs.addAll(elegidas);
  }
  cs.sort((a, b) => b.p.compareTo(a.p));
  if (cs.length > 45) cs.removeRange(45, cs.length);
  final idx = {for (var i = 0; i < cs.length; i++) cs[i].clave: i};
  final todos = <BetBuilder>[for (final s in cs) BetBuilder([s], s.p, cuotaEstimada(s.p, 1))];
  var capa = [for (final s in cs) [s]];
  for (var k = 2; k <= maxPatas && capa.isNotEmpty; k++) {
    final nuevos = <String, (List<Seleccion>, double)>{};
    for (final act in capa) {
      final desde = idx[act.last.clave]! + 1;
      for (var i = desde; i < cs.length; i++) {
        final s = cs[i];
        if (!compatibles(act, s)) continue;
        final combo = [...act, s];
        final p = conjunta(m, combo);
        if (p < minBB) continue;
        nuevos[combo.map((x) => x.clave).join('+')] = (combo, p);
      }
    }
    // se guardan las más probables de cada nivel de cuota (cubos de log-cuota), para que haya de todo
    final cubos = <int, List<(List<Seleccion>, double)>>{};
    for (final x in nuevos.values) {
      final c = cuotaEstimada(x.$2, k);
      cubos.putIfAbsent((math.log(c) / 0.06).floor(), () => []).add(x);
    }
    final elegidos = <(List<Seleccion>, double)>[];
    final porCubo = math.max(1, ancho ~/ math.max(1, cubos.length));
    for (final lista in cubos.values) {
      lista.sort((a, b) => b.$2.compareTo(a.$2));
      elegidos.addAll(lista.take(math.max(porCubo, 2)));
    }
    elegidos.sort((a, b) => b.$2.compareTo(a.$2));
    capa = [for (final x in elegidos.take(ancho * 2)) x.$1];
    for (final x in elegidos) {
      todos.add(BetBuilder(x.$1, x.$2, cuotaEstimada(x.$2, k)));
    }
  }
  // frente de Pareto: nadie con más cuota Y más probabilidad
  todos.sort((a, b) => b.cuota.compareTo(a.cuota));
  final frente = <BetBuilder>[];
  var mejorP = -1.0;
  for (final b in todos) {
    if (b.p > mejorP + 1e-9) {
      frente.add(b);
      mejorP = b.p;
    }
  }
  return frente;
}
