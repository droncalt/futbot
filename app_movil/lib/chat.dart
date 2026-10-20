// Chat de FútBot en el celular: le pides fijas con tus palabras ("3 fijas para hoy a cuota 2 con 80%",
// "solo córners del Barcelona con 20 soles") y arma la combinada con las probabilidades del bot.
// Funciona sin internet y sin gastar tokens: entiende frases en español con reglas y busca la mejor combinación
// (máxima probabilidad que llegue a la cuota pedida) con programación dinámica.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import 'captura.dart';
import 'compartir.dart';
import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';
import 'noticias.dart';
import 'vivo.dart';

// ---------------------------------------------------------------- lo que pide el usuario
class Pedido {
  String? nivel, dia;
  double? cuota, pMin, monto;
  int? n;
  final familias = <String>{}; // goles, corners, tarjetas, jugadores, resultado
  final sinFamilias = <String>{};
  final equipos = <String>{}, ligas = <String>{};
  final tipos = <String>{}; // prefijos "mercado|opcion|linea": btts|si, doble|, goles|mas|2.5, jug_arco|
  bool get vacio => nivel == null && cuota == null && pMin == null && n == null && familias.isEmpty && equipos.isEmpty &&
      ligas.isEmpty && dia == null && tipos.isEmpty;
}

const _numeros = {'una': 1, 'un': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10};
const _ligas = {
  'premier': 'E0', 'championship': 'E1', 'laliga': 'SP1', 'la liga': 'SP1', 'liga espanola': 'SP1', 'serie a': 'I1', 'italia': 'I1',
  'bundesliga': 'D1', 'alemania': 'D1', 'ligue 1': 'F1', 'francia': 'F1', 'eredivisie': 'N1', 'holanda': 'N1', 'portugal': 'P1',
  'brasil': 'BRA', 'brasileirao': 'BRA', 'argentina': 'ARG', 'mexico': 'MEX', 'liga mx': 'MEX', 'mls': 'USA', 'turquia': 'T1',
  'belgica': 'B1', 'escocia': 'SC0', 'grecia': 'G1', 'inglaterra': 'E0', 'espana': 'SP1',
};

Pedido entender(String texto) {
  final t = ' ${normal(texto.replaceAll('%', ' por ciento ').replaceAll(',', '.'))} ';
  final crudo = texto.toLowerCase().replaceAll(',', '.');
  final p = Pedido();
  if (RegExp(r'ultra|super segura|muy segura|segurisim|casi fija|lo mas seguro').hasMatch(t)) {
    p.nivel = 'ultra';
  } else if (RegExp(r'equilibrad|arriesgad|valor|mas cuota|mas alta').hasMatch(t)) {
    p.nivel = 'equilibrada';
  } else if (t.contains('segura')) {
    p.nivel = 'segura';
  }
  final pm = RegExp(r'(\d{2}(?:\.\d)?)\s*(?:%|por ciento)').firstMatch(crudo);
  if (pm != null) p.pMin = (double.parse(pm.group(1)!) / 100).clamp(0.05, 0.99);
  final cm = RegExp(r'(?:cuota|pague|paga|@|multiplique|x)\s*(?:de|a|total|minima|mayor a|de al menos)?\s*(\d{1,3}(?:\.\d{1,2})?)').firstMatch(crudo) ??
      RegExp(r'a\s+(\d{1,2}\.\d{1,2})\b').firstMatch(crudo);
  if (cm != null) {
    final c = double.parse(cm.group(1)!);
    if (c > 1 && c <= 500) p.cuota = c;
  }
  final mm = RegExp(r'(\d{1,5}(?:\.\d{1,2})?)\s*(?:soles|sol|lucas)').firstMatch(crudo) ??
      RegExp(r's/\.?\s*(\d{1,5}(?:\.\d{1,2})?)').firstMatch(crudo);
  if (mm != null) p.monto = double.parse(mm.group(1)!);
  final nm = RegExp(r'(\d{1,2}|una|un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+(?:fijas?|selecciones|partidos|lineas|patas|picks|apuestas|eventos)').firstMatch(t);
  if (nm != null) p.n = int.tryParse(nm.group(1)!) ?? _numeros[nm.group(1)!];
  if (t.contains(' hoy ')) p.dia = 'hoy';
  if (t.contains(' manana ')) p.dia = 'manana';
  if (RegExp(r'fin de semana|finde|sabado|domingo').hasMatch(t)) p.dia = 'finde';
  void fam(String nombre, String patron) {
    final r = RegExp(patron);
    if (RegExp('(sin|no|nada de|excepto) (\\w+ )?($patron)').hasMatch(t)) {
      p.sinFamilias.add(nombre);
    } else if (r.hasMatch(t)) {
      p.familias.add(nombre);
    }
  }
  fam('corners', r'corner|esquina');
  fam('tarjetas', r'tarjeta|amarilla');
  fam('jugadores', r'jugador|tiros|remate|arco|puerta');
  fam('goles', r'goles|gol |over|under|mas de|menos de|ambos');
  fam('resultado', r'doble oportunidad|ganador|resultado|gana |empate');
  if (RegExp(r'ambos (equipos )?(anotan|marcan)|btts').hasMatch(t)) p.tipos.add(t.contains(' no ambos') ? 'btts|no' : 'btts|si');
  if (t.contains('doble oportunidad')) p.tipos.add('doble|');
  for (final m in RegExp(r'(m[aá]s|menos|over|under) (?:de )?(\d)[.,]5(?! ?(?:c[oó]rner|tarjeta))').allMatches(crudo)) {
    final mas = m.group(1)!.startsWith('m') && m.group(1) != 'menos' || m.group(1) == 'over';
    p.tipos.add('goles|${mas ? 'mas' : 'menos'}|${m.group(2)}.5');
  }
  if (RegExp(r'tiros? al arco|remates?|tiros? a puerta').hasMatch(t)) p.tipos.addAll(['jug_arco|', 'tiros_arco']);
  for (final e in _ligas.entries) {
    if (t.contains(' ${e.key} ')) p.ligas.add(e.value);
  }
  for (final eq in _equiposDelPaquete()) {
    final n = normal(eq);
    final palabras = n.split(' ').where((w) => w.length >= 4 && !{'real', 'united', 'city', 'club', 'sporting', 'athletic', 'atletico', 'inter'}.contains(w));
    if (t.contains(' $n ') || palabras.any((w) => t.contains(' $w '))) p.equipos.add(eq);
  }
  return p;
}

Set<String> _equiposDelPaquete() => {
      for (final m in repo.partidos) ...['${m['local']?['nombre'] ?? ''}', '${m['visitante']?['nombre'] ?? ''}'],
    }..removeWhere((x) => x.isEmpty);

// ---------------------------------------------------------------- armar la mejor combinada
class Opcion {
  final Linea linea;
  final int mask;
  final double p, cuota;
  final bool estimada;
  Opcion(this.linea, this.mask, this.p, this.cuota, this.estimada);
  List<Pata> get patas => [for (var i = 0; i < linea.patas.length; i++) if ((mask >> i) & 1 == 1) linea.patas[i]];
  String get partido => '${linea.local.nombre} vs ${linea.visitante.nombre}';
  String get clavePartido => '${linea.local.nombre}|${linea.visitante.nombre}';
}

String familiaDe(Pata p) {
  final m = '${p.sel['mercado']}';
  if (m.startsWith('corners')) return 'corners';
  if (m == 'tarjetas') return 'tarjetas';
  if (m == 'jug_arco' || m.startsWith('tiros_arco')) return 'jugadores';
  if (m == '1x2' || m == 'doble' || m == '1t_1x2') return 'resultado';
  return 'goles';
}

/// Lo aprendido de tus patas resueltas (mercado → [aciertos, total, suma prob. prometida]).
Map<String, List<double>> aprendido = {};

/// Corrige la probabilidad de una pata con tu historial, con encogimiento k = n/(n+300) (igual que la
/// calibración del backtest): con pocas patas casi no cambia; con cientos pesa de verdad.
double corregir(String mercado, double p) {
  final v = aprendido[mercado];
  if (v == null || v[1] < 5) return p;
  final k = v[1] / (v[1] + 300);
  return (p + k * (v[0] / v[1] - v[2] / v[1])).clamp(0.02, 0.99).toDouble();
}

List<Opcion> opciones(Pedido q) {
  final ahora = DateTime.now();
  final hoy = DateTime(ahora.year, ahora.month, ahora.day);
  final niveles = q.nivel == null ? ['ultra', 'segura', 'equilibrada'] : [q.nivel!];
  final out = <String, Opcion>{};
  for (final nivel in niveles) {
    for (final l in repo.lineas(nivel)) {
      if (!l.inicio.isAfter(ahora)) continue;
      if (q.dia == 'hoy' && !l.inicio.isBefore(hoy.add(const Duration(days: 1)))) continue;
      if (q.dia == 'manana' && (l.inicio.isBefore(hoy.add(const Duration(days: 1))) || !l.inicio.isBefore(hoy.add(const Duration(days: 2))))) continue;
      if (q.dia == 'finde' && l.inicio.weekday < DateTime.saturday) continue;
      if (q.ligas.isNotEmpty && !q.ligas.contains(l.liga)) continue;
      if (q.equipos.isNotEmpty && !q.equipos.any((e) => parecido(e, l.local.nombre) > 0.8 || parecido(e, l.visitante.nombre) > 0.8)) continue;
      for (final e in l.sub.entries) {
        var o = Opcion(l, e.key, e.value.p, e.value.cuota, e.value.estimada);
        var factor = 1.0;
        for (final pa in o.patas) {
          factor *= corregir('${pa.sel['mercado']}', pa.p) / pa.p;
        }
        if (factor != 1.0) o = Opcion(l, e.key, (o.p * factor).clamp(0.01, 0.99).toDouble(), o.cuota, o.estimada);
        final fams = o.patas.map(familiaDe).toSet();
        if (fams.any(q.sinFamilias.contains)) continue;
        if (q.familias.isNotEmpty && !fams.every(q.familias.contains)) continue;
        if (o.cuota < 1.04) continue;
        final k = '${o.clavePartido}|${o.patas.map((x) => x.titulo).join('+')}';
        if (!out.containsKey(k) || out[k]!.p < o.p) out[k] = o;
      }
    }
  }
  for (final o in _sueltas(q)) {
    final k = '${o.clavePartido}|${o.patas.map((x) => x.titulo).join('+')}';
    out.putIfAbsent(k, () => o);
  }
  final lista = out.values.toList();
  if (q.tipos.isEmpty) return lista;
  return lista.where((o) => o.patas.every((pa) => _pide(q, pa))).toList();
}

/// ¿La pata es de lo que se pidió? (un tipo concreto o una familia: "tiros al arco y córners" acepta ambas)
bool _pide(Pedido q, Pata pa) =>
    q.tipos.any((t) => _clavePata(pa).startsWith(t)) || q.familias.contains(familiaDe(pa));

String _clavePata(Pata pa) {
  final l = (pa.sel['linea'] as num?)?.toDouble();
  return '${pa.sel['mercado']}|${pa.sel['opcion']}|${l ?? ''}';
}

/// Mercados que el chat puede usar con las probabilidades del partido. {local}/{visit} se reemplazan por los equipos.
const _sueltasClaves = {
  'doble|1X|': ('1X ({local} o empate)', 'Doble oportunidad'), 'doble|X2|': ('X2 (empate o {visit})', 'Doble oportunidad'),
  'doble|12|': ('12 (no hay empate)', 'Doble oportunidad'),
  'goles|mas|0.5': ('Más de 0.5', 'Goles totales Más/Menos'), 'goles|mas|1.5': ('Más de 1.5', 'Goles totales Más/Menos'),
  'goles|mas|2.5': ('Más de 2.5', 'Goles totales Más/Menos'), 'goles|menos|3.5': ('Menos de 3.5', 'Goles totales Más/Menos'),
  'goles|menos|4.5': ('Menos de 4.5', 'Goles totales Más/Menos'), 'goles|menos|5.5': ('Menos de 5.5', 'Goles totales Más/Menos'),
  'goles_local|mas|0.5': ('Más de 0.5', '{local} - Goles totales Más/Menos'),
  'goles_visitante|mas|0.5': ('Más de 0.5', '{visit} - Goles totales Más/Menos'),
  '1t_goles|mas|0.5': ('Más de 0.5', 'Más/Menos Goles en Primer Tiempo'),
  'btts|si|': ('Sí', 'Ambos equipos anotan'), 'btts|no|': ('No', 'Ambos equipos anotan'),
  'corners|mas|5.5': ('Más de 5.5', 'Más/Menos Córners'), 'corners|mas|6.5': ('Más de 6.5', 'Más/Menos Córners'),
  'corners|mas|7.5': ('Más de 7.5', 'Más/Menos Córners'), 'corners|mas|8.5': ('Más de 8.5', 'Más/Menos Córners'),
  'corners_local|mas|1.5': ('Más de 1.5', '{local} Más/Menos Córners'), 'corners_local|mas|2.5': ('Más de 2.5', '{local} Más/Menos Córners'),
  'corners_local|mas|3.5': ('Más de 3.5', '{local} Más/Menos Córners'),
  'corners_visitante|mas|1.5': ('Más de 1.5', '{visit} Más/Menos Córners'),
  'corners_visitante|mas|2.5': ('Más de 2.5', '{visit} Más/Menos Córners'),
  'tarjetas|mas|1.5': ('Más de 1.5', 'Tarjetas Más/Menos'), 'tarjetas|mas|2.5': ('Más de 2.5', 'Tarjetas Más/Menos'),
  'tarjetas|mas|3.5': ('Más de 3.5', 'Tarjetas Más/Menos'),
  'tiros_arco|mas|4.5': ('Más de 4.5', 'Tiros al Arco'), 'tiros_arco|mas|5.5': ('Más de 5.5', 'Tiros al Arco'),
  'tiros_arco|mas|6.5': ('Más de 6.5', 'Tiros al Arco'), 'tiros_arco|mas|7.5': ('Más de 7.5', 'Tiros al Arco'),
  'tiros_arco_local|mas|1.5': ('Más de 1.5', '{local} Tiros al Arco'), 'tiros_arco_local|mas|2.5': ('Más de 2.5', '{local} Tiros al Arco'),
  'tiros_arco_visitante|mas|1.5': ('Más de 1.5', '{visit} Tiros al Arco'),
  'tiros_arco_visitante|mas|2.5': ('Más de 2.5', '{visit} Tiros al Arco'),
};

/// Prob. mínima de CADA selección y de cada Bet Builder según el nivel (por defecto: muy seguras).
(double, double) _umbrales(Pedido q) => switch (q.nivel) {
      'equilibrada' => (0.72, 0.60),
      'segura' => (0.80, 0.70),
      _ => (0.85, 0.75),
    };

double _cuotaEstimada(double p) => double.parse((1 / (p * 1.06)).clamp(1.01, 50).toStringAsFixed(2));

/// Selecciones del partido (una pata) con la probabilidad del bot, ya corregida con tu historial.
List<Pata> _patasPartido(Map<String, dynamic> m, double minP) {
  final mer = Map<String, dynamic>.from(m['mercados'] ?? {});
  final ln = '${m['local']?['nombre'] ?? ''}', vn = '${m['visitante']?['nombre'] ?? ''}';
  final patas = <Pata>[];
  _sueltasClaves.forEach((k, v) {
    final p0 = (mer[k] as num?)?.toDouble();
    if (p0 == null || p0 > 0.985) return;
    final c = k.split('|');
    final p = corregir(c[0], p0);
    if (p < minP) return;
    patas.add(Pata(v.$1.replaceAll('{local}', ln).replaceAll('{visit}', vn), v.$2.replaceAll('{local}', ln).replaceAll('{visit}', vn), p,
        {'mercado': c[0], 'opcion': c[1], 'linea': c[2].isEmpty ? null : double.parse(c[2])}));
  });
  for (final j in (m['jugadores'] as List? ?? [])) {
    final k = (j['linea_min'] as num?)?.toInt() ?? 1;
    final p = (j['p$k'] as num?)?.toDouble();
    if (p == null || p < minP) continue;
    patas.add(Pata('$k+', '${j['nombre']} Tiros al Arco', p,
        {'mercado': 'jug_arco', 'opcion': '$k+', 'linea': k - 0.5, 'jugador_nombre': j['nombre'], 'lado': j['lado']}));
  }
  return patas;
}

/// Grupo de una pata: no se juntan dos del mismo grupo en un Bet Builder (salvo Más + Menos del mismo conteo).
String _grupo(Pata p) {
  final m = '${p.sel['mercado']}';
  if (m == 'jug_arco') return 'jug|${p.sel['jugador_nombre']}';
  if (m == 'doble' || m == '1x2') return 'resultado';
  return '$m|${p.sel['opcion']}';
}

/// Probabilidad conjunta de patas del MISMO partido: Más y Menos del mismo conteo como intervalo exacto
/// (Más 0.5 + Menos 4.5 = entre 1 y 4 goles); entre mercados distintos se multiplica (aproximación).
double _conjunta(List<Pata> patas, Map<String, dynamic> mer) {
  final porM = <String, List<Pata>>{};
  for (final p in patas) {
    porM.putIfAbsent('${p.sel['mercado']}', () => []).add(p);
  }
  var prob = 1.0;
  for (final e in porM.entries) {
    final mas = e.value.where((x) => x.sel['opcion'] == 'mas').toList();
    final menos = e.value.where((x) => x.sel['opcion'] == 'menos').toList();
    if (mas.length == 1 && menos.length == 1) {
      final pLo = (mer['${e.key}|mas|${(mas.first.sel['linea'] as num).toDouble()}'] as num?)?.toDouble();
      final pHi = (mer['${e.key}|mas|${(menos.first.sel['linea'] as num).toDouble()}'] as num?)?.toDouble();
      if (pLo != null && pHi != null) {
        prob *= (pLo - pHi).clamp(0.0, 1.0);
        continue;
      }
    }
    for (final p in e.value) {
      prob *= p.p;
    }
  }
  return prob;
}

Opcion _opcionSuelta(Map<String, dynamic> m, DateTime ini, List<Pata> patas, double p, double cuota) {
  final local = Equipo.de(Map<String, dynamic>.from(m['local'])), visit = Equipo.de(Map<String, dynamic>.from(m['visitante']));
  final mask = (1 << patas.length) - 1;
  final l = Linea('suelta|${local.nombre}|${patas.map((x) => '${x.titulo}${x.mercado}').join('+')}', '${m['liga']}',
      '${m['liga_nombre'] ?? m['liga']}', '${m['betano'] ?? 'https://www.betano.pe/sport/futbol/'}', ini, local, visit, patas,
      {mask: Sub(p, cuota, true)}, cuota, p, true, false, false,
      patas.length > 1 ? const ['Bet Builder armado por el chat: cuota estimada (Betano la calcula al armarlo).'] : const []);
  return Opcion(l, mask, p, cuota, true);
}

/// Por partido: cada selección segura sola y Bet Builders de 2 a 4 selecciones seguras de mercados distintos
/// (goles, córners, tarjetas, tiros al arco, jugador, doble oportunidad). Cuota estimada (≈).
List<Opcion> _sueltas(Pedido q) {
  final ahora = DateTime.now();
  final hoy = DateTime(ahora.year, ahora.month, ahora.day);
  final (minPata, minBB) = _umbrales(q);
  final out = <Opcion>[];
  for (final m in repo.partidos) {
    final ini = DateTime.tryParse('${m['inicio']}'.replaceAll(' ', 'T'));
    if (ini == null || !ini.isAfter(ahora)) continue;
    if (q.dia == 'hoy' && !ini.isBefore(hoy.add(const Duration(days: 1)))) continue;
    if (q.dia == 'manana' && (ini.isBefore(hoy.add(const Duration(days: 1))) || !ini.isBefore(hoy.add(const Duration(days: 2))))) continue;
    if (q.dia == 'finde' && ini.weekday < DateTime.saturday) continue;
    if (q.ligas.isNotEmpty && !q.ligas.contains('${m['liga']}')) continue;
    final ln = '${m['local']?['nombre'] ?? ''}', vn = '${m['visitante']?['nombre'] ?? ''}';
    if (q.equipos.isNotEmpty && !q.equipos.any((e) => parecido(e, ln) > 0.8 || parecido(e, vn) > 0.8)) continue;
    final mer = Map<String, dynamic>.from(m['mercados'] ?? {});
    final patas = _patasPartido(Map<String, dynamic>.from(m), minPata);
    if (q.tipos.isNotEmpty) patas.retainWhere((pa) => _pide(q, pa));
    for (final pa in patas) {
      final c = _cuotaEstimada(pa.p);
      if (c >= 1.04) out.add(_opcionSuelta(m, ini, [pa], pa.p, c));
    }
    // Bet Builders: de las más seguras, combinaciones de grupos distintos
    final mejores = ([...patas]..sort((a, b) => b.p.compareTo(a.p))).take(8).toList();
    final combos = <Opcion>[];
    void armar(int desde, List<Pata> act) {
      if (act.length >= 2) {
        final p = _conjunta(act, mer);
        if (p >= minBB) {
          final c = double.parse((act.fold<double>(1, (a, x) => a * _cuotaEstimada(x.p)) * 0.93).clamp(1.01, 50).toStringAsFixed(2));
          if (c >= 1.10) combos.add(_opcionSuelta(m, ini, [...act], p, c));
        }
      }
      if (act.length == 4) return;
      for (var i = desde; i < mejores.length; i++) {
        final g = _grupo(mejores[i]);
        final mercado = '${mejores[i].sel['mercado']}';
        // mismo grupo no; del mismo conteo solo Más + Menos (intervalo)
        if (act.any((x) => _grupo(x) == g)) continue;
        if (act.where((x) => '${x.sel['mercado']}' == mercado).length >= 2) continue;
        armar(i + 1, [...act, mejores[i]]);
      }
    }
    armar(0, []);
    combos.sort((a, b) => (b.p * math.log(b.cuota)).compareTo(a.p * math.log(a.cuota)));
    out.addAll(combos.take(8));
  }
  return out;
}

class _Nodo {
  final Opcion o;
  final _Nodo? prev;
  final int n;
  _Nodo(this.o, this.prev, this.n);
}

/// Máxima probabilidad conjunta que llega a la cuota [objetivo] usando a lo sumo [maxN] partidos (uno por
/// partido, que puede ser un Bet Builder). Programación dinámica sobre log-cuota en pasos finos (0.005).
List<Opcion>? mejorParaCuota(List<Opcion> ops, double objetivo, int maxN, {int? exacto}) {
  if (exacto != null) return _mejorExacto(ops, objetivo, exacto);
  const paso = 0.005;
  final cap = (math.log(objetivo) / paso).ceil();
  final porPartido = <String, List<Opcion>>{};
  for (final o in ops) {
    porPartido.putIfAbsent(o.clavePartido, () => []).add(o);
  }
  var dp = <int, (double, _Nodo?)>{0: (0.0, null)};
  for (final grupo in porPartido.values) {
    final nuevo = Map<int, (double, _Nodo?)>.from(dp);
    dp.forEach((b, v) {
      if ((v.$2?.n ?? 0) >= maxN) return;
      for (final o in grupo) {
        final nb = math.min(cap, b + (math.log(o.cuota) / paso).floor());
        final lp = v.$1 + math.log(o.p);
        final previo = nuevo[nb];
        if (previo == null || previo.$1 < lp) nuevo[nb] = (lp, _Nodo(o, v.$2, (v.$2?.n ?? 0) + 1));
      }
    });
    dp = nuevo;
  }
  var nodo = dp[cap]?.$2;
  if (nodo == null) return null;
  final res = <Opcion>[];
  while (nodo != null) {
    res.add(nodo.o);
    nodo = nodo.prev;
  }
  return res.reversed.toList();
}

/// Igual, con un número EXACTO de partidos.
List<Opcion>? _mejorExacto(List<Opcion> ops, double objetivo, int maxN) {
  const paso = 0.02;
  final cap = (math.log(objetivo) / paso).ceil();
  final porPartido = <String, List<Opcion>>{};
  for (final o in ops) {
    porPartido.putIfAbsent(o.clavePartido, () => []).add(o);
  }
  // dp[k][b] = (log p, elegidas) con k partidos y log-cuota acumulada en el casillero b (tope en cap)
  var dp = List.generate(maxN + 1, (_) => <int, (double, List<Opcion>)>{});
  dp[0][0] = (0.0, <Opcion>[]);
  for (final grupo in porPartido.values) {
    final nuevo = List.generate(maxN + 1, (k) => Map<int, (double, List<Opcion>)>.from(dp[k]));
    for (var k = 0; k < maxN; k++) {
      dp[k].forEach((b, v) {
        for (final o in grupo) {
          final nb = math.min(cap, b + (math.log(o.cuota) / paso).floor());
          final lp = v.$1 + math.log(o.p);
          final previo = nuevo[k + 1][nb];
          if (previo == null || previo.$1 < lp) nuevo[k + 1][nb] = (lp, [...v.$2, o]);
        }
      });
    }
    dp = nuevo;
  }
  (double, List<Opcion>)? mejor;
  for (var k = 1; k <= maxN; k++) {
    if (k != maxN) continue;
    final v = dp[k][cap];
    if (v != null && (mejor == null || v.$1 > mejor.$1)) mejor = v;
  }
  return mejor?.$2;
}

/// Las [n] selecciones más probables (una por partido) con cuota mínima [cuotaMin] cada una.
List<Opcion> mejoresN(List<Opcion> ops, int n, double cuotaMin) {
  final orden = [...ops.where((o) => o.cuota >= cuotaMin)]..sort((a, b) => b.p.compareTo(a.p));
  final usados = <String>{}, out = <Opcion>[];
  for (final o in orden) {
    if (usados.add(o.clavePartido)) out.add(o);
    if (out.length >= n) break;
  }
  return out;
}

/// La cuota más alta que se puede armar sin bajar de [pMin] de probabilidad conjunta.
List<Opcion> maxCuotaConProb(List<Opcion> ops, double pMin) {
  final orden = [...ops]..sort((a, b) => (b.p * math.log(b.cuota)).compareTo(a.p * math.log(a.cuota)));
  final usados = <String>{}, out = <Opcion>[];
  var p = 1.0;
  for (final o in orden) {
    if (usados.contains(o.clavePartido) || p * o.p < pMin) continue;
    usados.add(o.clavePartido);
    out.add(o);
    p *= o.p;
  }
  return out;
}

double _prod(Iterable<double> xs) => xs.fold(1.0, (a, b) => a * b);

// ---------------------------------------------------------------- respuestas
class Mensaje {
  final bool mio;
  final String texto;
  final List<Opcion>? boleta;
  final LecturaCaptura? lectura;
  final double monto;
  final List<(String, String)> investigar; // partidos (local, visitante) a buscar en internet después de responder
  Mensaje(this.mio, this.texto, {this.boleta, this.lectura, this.monto = 10, this.investigar = const []});
}

List<(String, String)> _partidosDe(Set<String> equipos) => [
      for (final m in repo.partidos)
        if (equipos.any((e) => parecido(e, '${m['local']?['nombre']}') > 0.8 || parecido(e, '${m['visitante']?['nombre']}') > 0.8))
          ('${m['local']?['nombre']}', '${m['visitante']?['nombre']}'),
    ].take(3).toList();

Future<Mensaje> responder(String texto) async {
  final t = ' ${normal(texto)} ';
  // reglas de Betano
  for (final r in repo.reglas) {
    final claves = (r['claves'] as List? ?? []).map((e) => normal('$e'));
    if (claves.any((c) => c.isNotEmpty && t.contains(c)) && !RegExp(r'fija|combinada|boleta|cuota \d').hasMatch(t)) {
      return Mensaje(false, '📘 ${r['titulo']}\n\n${r['texto']}');
    }
  }
  if (RegExp(r'ayuda|que puedes|como funciona|como te uso|comandos').hasMatch(t)) {
    return Mensaje(false, 'Pídeme las fijas como quieras, por ejemplo:\n'
        '• «3 fijas para hoy ultra seguras»\n• «armame cuota 3 con la mayor probabilidad»\n'
        '• «cuota 2 con 80%»\n• «solo córners de la Premier»\n• «fijas del Barcelona con 20 soles»\n'
        '• «sin jugadores, 4 partidos de mañana»\n• «analiza Real Madrid» · «¿qué es Multi Bono?» · «cómo voy»\n\n'
        'También puedes subir una captura con 📷 y la sigo en vivo.');
  }
  if (RegExp(r'como voy|mi historial|cuanto gane|cuanto perdi|mis apuestas|mi rendimiento').hasMatch(t)) {
    return Mensaje(false, await _resumenHistorial());
  }
  if (RegExp(r'acierta|confiable|funciona de verdad|que tan bueno|precision|calibra').hasMatch(t)) {
    final c = Map<String, dynamic>.from(repo.paquete['calidad'] ?? {});
    final f = Map<String, dynamic>.from(c['fijas_global'] ?? {});
    if (f.isNotEmpty) {
      return Mensaje(false, 'Prueba honesta (backtest ${c['periodo']}, ${c['partidos']} partidos, sin mirar el futuro): '
          'de ${f['n']} fijas, el bot decía ${pct((f['prob_media'] as num).toDouble())} y acertaron '
          '${pct((f['acierto_real'] as num).toDouble())}. O sea: sus porcentajes se cumplen, pero ninguna fija es segura al 100%. '
          'En una combinada las probabilidades se multiplican: 4 patas de 85% ≈ 52%.');
    }
  }
  final q = entender(texto);
  if (RegExp(r'analiza|analisis|como ves|que opinas|pronostico').hasMatch(t) && q.equipos.isNotEmpty) {
    return Mensaje(false, _analizar(q.equipos), investigar: _partidosDe(q.equipos));
  }
  if (q.vacio && !RegExp(r'fija|combinada|boleta|apuesta|parley|pick').hasMatch(t)) {
    return Mensaje(false, 'No te entendí del todo 🤔. Prueba «3 fijas para hoy», «cuota 2 con 80%» o escribe «ayuda».');
  }
  return _armar(q);
}

Mensaje _armar(Pedido q) {
  if ((q.n ?? 0) > LimitesBetano.maxSelecciones) {
    return Mensaje(false, 'Betano permite máximo ${LimitesBetano.maxSelecciones} selecciones por cupón. '
        'Pídeme ${LimitesBetano.maxSelecciones} o menos.');
  }
  final ops = opciones(q);
  final monto = math.max(q.monto ?? 10, LimitesBetano.minima);
  final filtro = [
    if (q.nivel != null) 'nivel ${q.nivel}',
    if (q.dia != null) q.dia == 'finde' ? 'fin de semana' : q.dia == 'manana' ? 'mañana' : 'hoy',
    if (q.equipos.isNotEmpty) q.equipos.join(', '),
    if (q.ligas.isNotEmpty) q.ligas.join(', '),
    if (q.familias.isNotEmpty) 'solo ${q.familias.join('/')}',
    if (q.sinFamilias.isNotEmpty) 'sin ${q.sinFamilias.join('/')}',
  ].join(' · ');
  if (ops.isEmpty) {
    return Mensaje(false, 'No encontré selecciones con eso${filtro.isEmpty ? '' : ' ($filtro)'}. '
        'Puede que el equipo no juegue en los próximos días o que ese mercado no pase el filtro de seguridad. '
        'Prueba quitando un filtro o con «equilibrada».');
  }
  List<Opcion>? sel;
  final notas = <String>[];
  if (q.cuota != null) {
    // hasta 20 partidos (Betano admite 30 por cupón; cada Bet Builder cuenta como una selección)
    sel = mejorParaCuota(ops, q.cuota!, math.min(20, LimitesBetano.maxSelecciones),
        exacto: q.n == null ? null : math.min(q.n!, LimitesBetano.maxSelecciones));
    if (sel == null) {
      final todo = mejoresN(ops, 20, 1.0);
      return Mensaje(false, 'Con ${filtro.isEmpty ? 'lo disponible' : filtro} no llego a cuota ${f2(q.cuota!)}'
          '${q.n != null ? ' con ${q.n} partidos' : ''}. Lo máximo sería ≈${f2(_prod(todo.map((o) => o.cuota)))}. '
          'Quita filtros, sube el número de partidos o usa «equilibrada».');
    }
    if (q.pMin != null && _prod(sel.map((o) => o.p)) < q.pMin!) {
      final alt = maxCuotaConProb(ops, q.pMin!);
      notas.add('⚠️ Cuota ${f2(q.cuota!)} con ${pct(q.pMin!)} no se puede: esta es la más probable que llega a esa cuota. '
          '${alt.isNotEmpty ? 'Con ${pct(q.pMin!)} o más, lo máximo es cuota ≈${f2(_prod(alt.map((o) => o.cuota)))} (escribe «cuota ${f2(_prod(alt.map((o) => o.cuota)))}»).' : ''}');
    }
  } else if (q.pMin != null && q.n == null) {
    sel = maxCuotaConProb(ops, q.pMin!);
    if (sel.isEmpty) {
      return Mensaje(false, 'Ninguna selección llega a ${pct(q.pMin!)} con esos filtros. Prueba con un porcentaje menor.');
    }
    notas.add('La cuota más alta que encontré sin bajar de ${pct(q.pMin!)}.');
  } else {
    final minC = {'ultra': 1.15, 'segura': 1.25, 'equilibrada': 1.40}[q.nivel ?? 'segura']!;
    sel = mejoresN(ops, q.n ?? 3, minC);
    if (sel.length < (q.n ?? 3)) notas.add('Solo encontré ${sel.length} partido(s) que cumplen.');
  }
  final p = _prod(sel.map((o) => o.p)), c = _prod(sel.map((o) => o.cuota));
  final b = StringBuffer('Te armé esta ${sel.length == 1 ? 'simple' : 'combinada de ${sel.length}'}'
      '${filtro.isEmpty ? '' : ' ($filtro)'}:\n');
  b.write('Cuota ≈${f2(c)} · prob. de acertar todo ${pct(p)} · ${deCada10(p)}.');
  if (sel.length >= 4) {
    final ps = sel.map((o) => o.p).toList()..sort();
    b.write('\nCada partido tiene entre ${pct(ps.first)} y ${pct(ps.last)}, pero son ${sel.length} y hay que acertar TODOS: '
        'por eso el total baja. Es la combinada más probable que encontré para esa cuota.');
  }
  for (final x in notas) {
    b.write('\n$x');
  }
  final nAprendidas = aprendido.values.fold<double>(0, (a, v) => a + v[1]).toInt();
  if (nAprendidas >= 5) b.write('\nProbabilidades ajustadas con $nAprendidas patas resueltas de tu historial.');
  if (sel.any((o) => o.estimada)) b.write('\nCuotas con ≈ son estimadas: confírmalas en Betano antes de apostar.');
  return Mensaje(false, b.toString(), boleta: sel, monto: monto);
}

String _analizar(Set<String> equipos) {
  final b = StringBuffer();
  for (final m in repo.partidos) {
    final l = '${m['local']?['nombre']}', v = '${m['visitante']?['nombre']}';
    if (!equipos.any((e) => parecido(e, l) > 0.8 || parecido(e, v) > 0.8)) continue;
    final pr = Map<String, dynamic>.from(m['prob'] ?? {});
    String x(String k) => pr[k] == null ? '—' : pct((pr[k] as num).toDouble());
    b.write('⚽ $l vs $v (${m['liga_nombre']}, ${m['inicio']})\n'
        'Local ${x('1')} · Empate ${x('X')} · Visita ${x('2')}\n'
        '1X ${x('1X')} · X2 ${x('X2')} · Más 1.5 ${x('Más 1.5')} · Más 2.5 ${x('Más 2.5')} · Menos 3.5 ${x('Menos 3.5')} · '
        'Ambos anotan ${x('Ambos anotan')}\n'
        '${m['goles_esperados'] != null ? 'Goles esperados: ${m['goles_esperados']}\n' : ''}'
        '${_extras(m)}\n');
  }
  if (b.isEmpty) return 'Ese equipo no juega en los próximos días en las ligas que analiza el bot.';
  b.write('Pídeme «fijas del ${equipos.first}» para armar una combinada con él.');
  return b.toString();
}

String _extras(Map<String, dynamic> m) {
  final e = Map<String, dynamic>.from(m['esperados'] ?? {});
  final mer = Map<String, dynamic>.from(m['mercados'] ?? {});
  String p(String k) => mer[k] == null ? '—' : pct((mer[k] as num).toDouble());
  final b = StringBuffer();
  if (mer.isNotEmpty) {
    b.writeln('Goles: Más 0.5 ${p('goles|mas|0.5')} · Más 1.5 ${p('goles|mas|1.5')} · Menos 4.5 ${p('goles|menos|4.5')}');
  }
  if (e['corners'] != null) {
    b.writeln('Córners esperados ${e['corners']} (${e['corners_local']}-${e['corners_visitante']}) · Más 7.5 ${p('corners|mas|7.5')} · '
        'Más 8.5 ${p('corners|mas|8.5')}');
  }
  for (final j in (m['jugadores'] as List? ?? []).take(3)) {
    b.writeln('👟 ${j['nombre']}: tiro al arco 1+ ${j['p1'] == null ? '—' : pct((j['p1'] as num).toDouble())}'
        '${j['p2'] != null ? ' · 2+ ${pct((j['p2'] as num).toDouble())}' : ''} (si es titular)');
  }
  if (e['tarjetas'] != null) b.writeln('Tarjetas esperadas ${e['tarjetas']} · Más 2.5 ${p('tarjetas|mas|2.5')} · Más 3.5 ${p('tarjetas|mas|3.5')}');
  if (e['tiros_arco'] != null) {
    b.writeln('Tiros al arco esperados ${e['tiros_arco']} (${e['tiros_arco_local']}-${e['tiros_arco_visitante']}) · '
        'Más 7.5 ${p('tiros_arco|mas|7.5')} (estimación por promedios)');
  }
  return b.toString();
}

Future<String> _resumenHistorial() async {
  final b = await Historial.cargar();
  final cerradas = b.where((x) => x['tipo'] == 'apostada' && x['estado'] != 'pendiente').toList();
  if (b.isEmpty) return 'Aún no tienes boletas guardadas. Cuando apuestes una, pulsa «La aposté» y yo la sigo.';
  final ap = cerradas.fold<double>(0, (s, x) => s + (x['monto'] as num).toDouble());
  final ret = cerradas.fold<double>(0, (s, x) => s + ((x['retorno'] ?? 0) as num).toDouble());
  final gan = cerradas.where((x) => x['estado'] == 'ganada').length;
  final pend = b.where((x) => x['estado'] == 'pendiente').length;
  final porM = Historial.porMercado(b);
  final peor = porM.entries.where((e) => e.value[1] >= 5).toList()
    ..sort((x, y) => (x.value[0] / x.value[1] - x.value[2] / x.value[1]).compareTo(y.value[0] / y.value[1] - y.value[2] / y.value[1]));
  return 'Apostadas cerradas: ${cerradas.length} (ganadas $gan) · apostado S/${f2(ap)} · neto '
      '${ret - ap >= 0 ? '+' : ''}S/${f2(ret - ap)} · pendientes: $pend.'
      '${peor.isNotEmpty ? '\nMercado que más falla vs lo prometido: ${peor.first.key} '
          '(${peor.first.value[0].toInt()}/${peor.first.value[1].toInt()}).' : ''}';
}

// ---------------------------------------------------------------- pantalla
class PantallaChat extends StatefulWidget {
  const PantallaChat({super.key});
  @override
  State<PantallaChat> createState() => _PantallaChatState();
}

class _PantallaChatState extends State<PantallaChat> {
  final mensajes = <Mensaje>[
    Mensaje(false, '¡Hola! Soy FútBot ⚽. Dime qué fijas quieres: «3 fijas para hoy», «cuota 2 con 80%», '
        '«solo córners de la Premier», «fijas del Barcelona con 20 soles»… También puedes mandarme la captura de tu '
        'combinada con 🖼️ y te digo qué tan probable es. Escribe «ayuda» para más ideas.'),
  ];
  final ctrl = TextEditingController();
  final scroll = ScrollController();

  static const sugerencias = ['3 fijas para hoy', 'cuota 2 con 80%', 'ultra segura de mañana', 'cuota 5 equilibrada',
    'solo goles, 4 partidos', '¿el bot acierta?', 'cómo voy'];

  @override
  void initState() {
    super.initState();
    Historial.cargar().then((b) => aprendido = Historial.porMercado(b));
  }

  Future<void> _enviar(String texto) async {
    if (texto.trim().isEmpty) return;
    ctrl.clear();
    setState(() => mensajes.add(Mensaje(true, texto)));
    final r = await responder(texto);
    setState(() => mensajes.add(r));
    await _investigar(r.investigar);
    await Future.delayed(const Duration(milliseconds: 50));
    if (scroll.hasClients) scroll.animateTo(scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
  }

  Future<void> _imagen() async {
    final origen = await showModalBottomSheet<ImageSource>(context: context, backgroundColor: Col.panel, builder: (c) => SafeArea(
          child: Wrap(children: [
            ListTile(leading: const Icon(Icons.photo_library), title: const Text('Captura de la galería'),
                onTap: () => Navigator.pop(c, ImageSource.gallery)),
            ListTile(leading: const Icon(Icons.photo_camera), title: const Text('Tomar foto'),
                onTap: () => Navigator.pop(c, ImageSource.camera)),
          ]),
        ));
    if (origen == null) return;
    setState(() => mensajes.add(Mensaje(true, '📷 Te envío mi combinada')));
    _bajar();
    try {
      final r = await elegirYLeer(origen);
      if (r == null) {
        setState(() => mensajes.removeLast());
        return;
      }
      final a = analizar(r);
      setState(() => mensajes.add(Mensaje(false, a.texto, lectura: r.patas.isEmpty ? null : r, monto: r.monto ?? 0)));
      _bajar();
      await _investigar([for (final pc in r.partidos) if (pc.local.isNotEmpty && pc.visitante.isNotEmpty) (pc.local, pc.visitante)]);
    } catch (e) {
      setState(() => mensajes.add(Mensaje(false, 'No pude leer la imagen ($e). Prueba con otra captura.')));
    }
    _bajar();
  }

  /// Busca noticias y pronósticos del partido en internet y avisa mientras lo hace.
  Future<void> _investigar(List<(String, String)> partidos) async {
    if (partidos.isEmpty) return;
    final lista = partidos.take(4).toList();
    setState(() => mensajes.add(Mensaje(false, '🔎 Investigando en internet (noticias, pronósticos y bajas) de '
        '${lista.length == 1 ? '${lista.first.$1} vs ${lista.first.$2}' : '${lista.length} partidos'}…')));
    _bajar();
    final partes = <String>[];
    for (final (l, v) in lista) {
      partes.add(resumenNoticias('$l vs $v', await buscarNoticias(l, v)));
    }
    if (!mounted) return;
    setState(() => mensajes.add(Mensaje(false, partes.join('\n\n'))));
    _bajar();
  }

  Future<void> _bajar() async {
    await Future.delayed(const Duration(milliseconds: 80));
    if (scroll.hasClients) scroll.animateTo(scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Expanded(
        child: ListView.builder(
          controller: scroll,
          padding: const EdgeInsets.all(12),
          itemCount: mensajes.length,
          itemBuilder: (_, i) => _burbuja(mensajes[i]),
        ),
      ),
      SizedBox(
        height: 40,
        child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 8), children: [
          for (final s in sugerencias)
            Padding(padding: const EdgeInsets.only(right: 6), child: ActionChip(label: Text(s), onPressed: () => _enviar(s))),
        ]),
      ),
      Container(
        color: Col.panel,
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
        child: Row(children: [
          IconButton(tooltip: 'Enviar captura o foto', icon: const Icon(Icons.add_photo_alternate_outlined, color: Col.naranja),
              onPressed: _imagen),
          Expanded(child: TextField(
            controller: ctrl,
            textInputAction: TextInputAction.send,
            onSubmitted: _enviar,
            decoration: InputDecoration(hintText: 'Pide tus fijas…', isDense: true, filled: true, fillColor: Col.tarjeta,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(20), borderSide: BorderSide.none)),
          )),
          IconButton(icon: const Icon(Icons.send, color: Col.naranja), onPressed: () => _enviar(ctrl.text)),
        ]),
      ),
    ]);
  }

  Widget _burbuja(Mensaje m) => Align(
        alignment: m.mio ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * (m.boleta != null || m.lectura != null ? 0.95 : 0.85)),
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: m.mio ? Col.naranjaOsc.withValues(alpha: 0.85) : Col.tarjeta,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SelectableText(m.texto),
            if (m.boleta != null) BoletaChat(opciones: m.boleta!, montoInicial: m.monto),
            if (m.lectura != null) AccionesCaptura(lectura: m.lectura!, montoInicial: m.monto),
          ]),
        ),
      );
}

class BoletaChat extends StatefulWidget {
  final List<Opcion> opciones;
  final double montoInicial;
  const BoletaChat({super.key, required this.opciones, required this.montoInicial});
  @override
  State<BoletaChat> createState() => _BoletaChatState();
}

class _BoletaChatState extends State<BoletaChat> {
  late final quitadas = <int>{};
  late final montoCtrl = TextEditingController(text: f2(widget.montoInicial));
  bool guardada = false;

  List<Opcion> get activas => [for (var i = 0; i < widget.opciones.length; i++) if (!quitadas.contains(i)) widget.opciones[i]];
  double get monto => double.tryParse(montoCtrl.text.replaceAll(',', '.')) ?? 0;

  String _texto() {
    final t = <String>['Combinada de ${activas.length} · FútBot (verifica cuotas en Betano)', ''];
    for (final o in activas) {
      t.add('${o.partido}  (${diaHora(o.linea.inicio)})');
      for (final p in o.patas) {
        t.add('  • ${p.titulo} — ${p.mercado}');
      }
      t.add('  Cuota ≈${f2(o.cuota)}');
    }
    final c = _prod(activas.map((o) => o.cuota));
    t.addAll(['', 'Cuota total ≈${f2(c)} · Apuesta S/${f2(monto)} · Ganancias S/${f2(monto * c)}',
      'Probabilidad de acertar todo: ${pct(_prod(activas.map((o) => o.p)))}']);
    return t.join('\n');
  }

  Map<String, dynamic> _mapa(String tipo) => {
      'id': DateTime.now().millisecondsSinceEpoch, 'fecha': DateTime.now().toIso8601String(), 'tipo': tipo, 'origen': 'chat',
      'monto': tipo == 'apostada' ? monto : 0, 'cuota': _prod(activas.map((o) => o.cuota)), 'p': _prod(activas.map((o) => o.p)),
      'estado': 'pendiente',
      'lineas': [
        for (final o in activas)
          {'liga': o.linea.liga, 'inicio': o.linea.inicio.toIso8601String(), 'local': o.linea.local.nombre,
            'visitante': o.linea.visitante.nombre, 'cuota': o.cuota, 'p': o.p,
            'patas': [for (final p in o.patas) {'titulo': p.titulo, 'mercado': p.mercado, 'sel': p.sel, 'p': p.p}]},
      ],
    };

  Future<void> _guardar(String tipo) async {
    final nueva = await Historial.guardar(_mapa(tipo));
    setState(() => guardada = true);
    if (!nueva && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Ya la tenías guardada: no la dupliqué.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _prod(activas.map((o) => o.cuota)), p = _prod(activas.map((o) => o.p));
    final problemas = LimitesBetano.revisar(selecciones: activas.length, monto: monto,
        patasPorPartido: [for (final o in activas) o.patas.length]);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 8),
      for (var i = 0; i < widget.opciones.length; i++) _fila(i),
      const SizedBox(height: 6),
      Row(children: [
        const Text('S/ '),
        SizedBox(width: 80, child: TextField(controller: montoCtrl, keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(isDense: true), onChanged: (_) => setState(() {}))),
        const SizedBox(width: 10),
        Expanded(child: Text('Cuota ${f2(c)} · ${pct(p)}\nGanas S/${f2(monto * c)}',
            style: TextStyle(fontWeight: FontWeight.w900, color: colorProb(p)))),
      ]),
      const SizedBox(height: 6),
      Wrap(spacing: 6, runSpacing: 6, children: [
        FilledButton.icon(onPressed: guardada || activas.isEmpty || problemas.isNotEmpty ? null : () => _guardar('apostada'),
            icon: const Icon(Icons.check), label: Text(guardada ? 'Guardada' : 'La aposté')),
        OutlinedButton.icon(onPressed: guardada || activas.isEmpty ? null : () => _guardar('seguimiento'),
            icon: const Icon(Icons.visibility), label: const Text('Seguir')),
        IconButton.filledTonal(tooltip: 'Compartir imagen', icon: const Icon(Icons.share),
            onPressed: activas.isEmpty ? null : () => compartirBoleta(context, _mapa(monto > 0 ? 'apostada' : 'seguimiento'))),
        IconButton.filledTonal(tooltip: 'Abrir Betano', icon: const Icon(Icons.open_in_new),
            onPressed: () => abrir(activas.isEmpty ? 'https://www.betano.pe/sport/futbol/' : activas.first.linea.betano)),
      ]),
      if (guardada) const Text('✅ En tu historial y en «En vivo»: la sigo minuto a minuto.', style: TextStyle(color: Color(0xFF34D399))),
      for (final x in problemas) Text('⛔ $x', style: const TextStyle(color: Col.rosa, fontWeight: FontWeight.w700)),
    ]);
  }

  Widget _fila(int i) {
    final o = widget.opciones[i];
    final off = quitadas.contains(i);
    return Opacity(
      opacity: off ? 0.4 : 1,
      child: Container(
        margin: const EdgeInsets.only(top: 6),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(color: Col.panel, borderRadius: BorderRadius.circular(10)),
        child: Row(children: [
          Checkbox(value: !off, activeColor: Col.naranja, onChanged: guardada ? null : (_) => setState(() => off ? quitadas.remove(i) : quitadas.add(i))),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Escudo(o.linea.local, tam: 16), const SizedBox(width: 4),
              Expanded(child: Text(o.partido, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13), overflow: TextOverflow.ellipsis)),
            ]),
            for (final p in o.patas) Text('• ${p.titulo} — ${p.mercado}', style: const TextStyle(fontSize: 12.5)),
            Text('${diaHora(o.linea.inicio)} · ${o.linea.ligaNombre}', style: const TextStyle(color: Col.suave, fontSize: 11.5)),
          ])),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${o.estimada ? '≈' : ''}${f2(o.cuota)}', style: const TextStyle(fontWeight: FontWeight.w900)),
            Text(pct(o.p), style: TextStyle(color: colorProb(o.p), fontWeight: FontWeight.w800, fontSize: 12)),
          ]),
        ]),
      ),
    );
  }
}

/// Botones bajo el análisis de una captura: guardar como apostada o solo seguir, de quién es, corregir.
class AccionesCaptura extends StatefulWidget {
  final LecturaCaptura lectura;
  final double montoInicial;
  const AccionesCaptura({super.key, required this.lectura, required this.montoInicial});
  @override
  State<AccionesCaptura> createState() => _AccionesCapturaState();
}

class _AccionesCapturaState extends State<AccionesCaptura> {
  late final montoCtrl = TextEditingController(text: widget.montoInicial > 0 ? f2(widget.montoInicial) : '');
  final autorCtrl = TextEditingController();
  bool mia = true, guardada = false;

  Future<void> _guardar(bool apostada) async {
    await guardarLectura(widget.lectura,
        monto: apostada ? (double.tryParse(montoCtrl.text.replaceAll(',', '.')) ?? 0) : 0,
        autor: mia ? 'yo' : 'tipster:${autorCtrl.text.trim().isEmpty ? 'sin nombre' : autorCtrl.text.trim()}');
    setState(() => guardada = true);
  }

  @override
  Widget build(BuildContext context) {
    final monto = double.tryParse(montoCtrl.text.replaceAll(',', '.')) ?? 0;
    final problemas = LimitesBetano.revisar(selecciones: widget.lectura.partidos.length, monto: monto);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SizedBox(height: 8),
        Wrap(spacing: 6, children: [
          ChoiceChip(label: const Text('Es mía'), selected: mia, onSelected: guardada ? null : (_) => setState(() => mia = true)),
          ChoiceChip(label: const Text('Me la mandaron'), selected: !mia, onSelected: guardada ? null : (_) => setState(() => mia = false)),
        ]),
        if (!mia && !guardada)
          TextField(controller: autorCtrl, decoration: const InputDecoration(isDense: true, labelText: '¿Quién? (ej. lasfijas)')),
        Row(children: [
          const Text('S/ '),
          SizedBox(width: 80, child: TextField(controller: montoCtrl, enabled: !guardada,
              keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(isDense: true),
              onChanged: (_) => setState(() {}))),
        ]),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 6, children: [
          FilledButton.icon(onPressed: guardada || problemas.isNotEmpty ? null : () => _guardar(true), icon: const Icon(Icons.check),
              label: Text(guardada ? 'Guardada' : 'La aposté')),
          OutlinedButton.icon(onPressed: guardada ? null : () => _guardar(false), icon: const Icon(Icons.visibility),
              label: const Text('Solo seguir')),
          TextButton.icon(onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => Scaffold(
                  appBar: AppBar(backgroundColor: Col.panel, title: const Text('Corregir lectura')),
                  body: PantallaCapturas(inicial: widget.lectura)))),
              icon: const Icon(Icons.edit), label: const Text('Corregir')),
        ]),
        if (guardada) const Text('✅ La sigo en «En vivo» y te digo si se cumplió o se perdió.', style: TextStyle(color: Color(0xFF34D399))),
        if (!guardada) for (final x in problemas) Text('⛔ $x', style: const TextStyle(color: Col.rosa, fontSize: 12)),
      ]);
  }
}
