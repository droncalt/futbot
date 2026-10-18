// En vivo: sigue tus boletas con datos públicos de ESPN (marcador, minuto, córners, tarjetas, tiros por jugador),
// marca el avance de cada pata, calcula la probabilidad en vivo (aprox.) y liquida al terminar.
import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';

const _espn = 'https://site.api.espn.com/apis/site/v2/sports/soccer/';

/// Código de liga del bot → liga de ESPN (verificadas el 18/10/2026; Polonia no está en ESPN).
const slugsEspn = {
  'E0': 'eng.1', 'E1': 'eng.2', 'E2': 'eng.3', 'E3': 'eng.4', 'SP1': 'esp.1', 'SP2': 'esp.2', 'D1': 'ger.1',
  'D2': 'ger.2', 'I1': 'ita.1', 'I2': 'ita.2', 'F1': 'fra.1', 'F2': 'fra.2', 'N1': 'ned.1', 'B1': 'bel.1',
  'P1': 'por.1', 'T1': 'tur.1', 'G1': 'gre.1', 'SC0': 'sco.1', 'SC1': 'sco.2', 'SC2': 'sco.3', 'SC3': 'sco.4',
  'BRA': 'bra.1', 'ARG': 'arg.1', 'MEX': 'mex.1', 'USA': 'usa.1', 'AUT': 'aut.1', 'SWZ': 'sui.1', 'DNK': 'den.1',
  'NOR': 'nor.1', 'SWE': 'swe.1',
};

// ---------------------------------------------------------------- nombres
const _sinTilde = {'á': 'a', 'à': 'a', 'ä': 'a', 'â': 'a', 'ã': 'a', 'é': 'e', 'è': 'e', 'ë': 'e', 'ê': 'e', 'í': 'i',
  'ï': 'i', 'î': 'i', 'ó': 'o', 'ö': 'o', 'ô': 'o', 'õ': 'o', 'ø': 'o', 'ú': 'u', 'ü': 'u', 'û': 'u', 'ñ': 'n', 'ç': 'c',
  'ş': 's', 'ğ': 'g', 'ı': 'i', 'å': 'a', 'æ': 'ae', 'ß': 'ss', 'ł': 'l', 'č': 'c', 'ć': 'c', 'š': 's', 'ž': 'z'};
const _relleno = {'fc', 'cf', 'ac', 'sc', 'afc', 'cd', 'ud', 'club', 'de', 'del', 'la', 'le', 'fk', 'sk', 'if', 'bk',
  'ss', 'us', 'as', 'rc', 'rcd', 'sd', 'ca', 'cr', 'se', 'ec', 'calcio', 'football', 'futbol', 'the', 'and', 'of'};

String normal(String s) {
  final b = StringBuffer();
  for (final ch in s.toLowerCase().split('')) {
    b.write(_sinTilde[ch] ?? ch);
  }
  return b.toString().replaceAll(RegExp(r'[^a-z0-9 ]'), ' ').split(' ')
      .where((w) => w.isNotEmpty && !_relleno.contains(w)).join(' ');
}

/// 0..1: qué tanto se parecen dos nombres de equipo/jugador (tolera "Man United" vs "Manchester United").
double parecido(String a, String b) {
  final x = normal(a), y = normal(b);
  if (x.isEmpty || y.isEmpty) return 0;
  if (x == y) return 1;
  if (x.contains(y) || y.contains(x)) return 0.9;
  final tx = x.split(' '), ty = y.split(' ');
  var comunes = 0.0;
  for (final t in tx) {
    if (ty.contains(t)) {
      comunes += 1;
    } else if (t.length >= 3 && ty.any((u) => u.length >= 3 && (u.startsWith(t) || t.startsWith(u)))) {
      comunes += 0.8; // "man" ~ "manchester", "utd" no
    } else if (t.length >= 4 && ty.any((u) => u.length >= 4 && (u.startsWith(t.substring(0, 4))))) {
      comunes += 0.7;
    }
  }
  return comunes / math.max(tx.length, ty.length);
}

// ---------------------------------------------------------------- datos de ESPN
class Jugador {
  final String nombre;
  final bool titular;
  final int tirosArco, tiros, goles, amarillas, rojas;
  Jugador(this.nombre, this.titular, this.tirosArco, this.tiros, this.goles, this.amarillas, this.rojas);
}

class Estado {
  String id = '', estado = 'pre', reloj = '', detalle = '', nl = '', nv = '';
  int minuto = 0, periodo = 0, gl = 0, gv = 0;
  int? htl, htv;
  DateTime? inicio;
  Map<String, String> sl = {}, sv = {};
  List<Jugador> jugadores = [];
  List<String> eventos = [];
  DateTime leido = DateTime.now();

  int stat(bool local, String k) => (double.tryParse((local ? sl : sv)[k] ?? '') ?? 0).round();
  int get cornersL => stat(true, 'wonCorners');
  int get cornersV => stat(false, 'wonCorners');
  int get tarjetasPts => stat(true, 'yellowCards') + stat(false, 'yellowCards') + 2 * (stat(true, 'redCards') + stat(false, 'redCards'));
  bool get terminado => estado == 'post';
  bool get enJuego => estado == 'in';
}

class Espn {
  static final _ids = <String, String>{};
  static final _cache = <String, Estado>{};

  static Future<Map<String, dynamic>> _get(String url) async {
    final r = await http.get(Uri.parse(url)).timeout(const Duration(seconds: 20));
    if (r.statusCode != 200) throw 'ESPN HTTP ${r.statusCode}';
    return Map<String, dynamic>.from(jsonDecode(utf8.decode(r.bodyBytes)));
  }

  static String _fecha(DateTime d) =>
      '${d.year}${d.month.toString().padLeft(2, '0')}${d.day.toString().padLeft(2, '0')}';

  /// Busca el id del partido en ESPN (por liga y nombres; si no, en "todas las ligas").
  static Future<String?> buscar(String liga, String local, String visitante, DateTime inicio) async {
    final clave = '$local|$visitante|${_fecha(inicio)}';
    if (_ids.containsKey(clave)) return _ids[clave];
    final slugs = [if (slugsEspn[liga] != null) slugsEspn[liga]!, 'all'];
    final dias = {_fecha(inicio), _fecha(inicio.add(const Duration(hours: 6))), _fecha(inicio.subtract(const Duration(hours: 6)))};
    String? mejor;
    var mejorPuntos = 1.0;
    for (final s in slugs) {
      for (final d in dias) {
        try {
          final j = await _get('${_espn}$s/scoreboard?dates=$d');
          for (final e in (j['events'] as List? ?? [])) {
            final cs = (e['competitions'][0]['competitors'] as List);
            String nom(String lado) {
              final c = cs.firstWhere((x) => x['homeAway'] == lado, orElse: () => cs.first);
              return '${c['team']['displayName']}';
            }
            final h = nom('home'), a = nom('away');
            final pl = parecido(h, local), pv = parecido(a, visitante);
            final pts = (pl >= 0.4 && pv >= 0.4) ? pl + pv : 0.0;
            if (pts > mejorPuntos) {
              mejorPuntos = pts;
              mejor = '${e['id']}';
            }
          }
        } catch (_) {}
        if (mejor != null && mejorPuntos >= 1.6) break;
      }
      if (mejor != null) break;
    }
    if (mejor != null) _ids[clave] = mejor;
    return mejor;
  }

  /// Estado completo del partido (se reusa si se leyó hace menos de [maxEdad]).
  static Future<Estado?> estado(String id, {Duration maxEdad = const Duration(seconds: 50)}) async {
    final c = _cache[id];
    if (c != null && (c.terminado || DateTime.now().difference(c.leido) < maxEdad)) return c;
    try {
      final j = await _get('${_espn}all/summary?event=$id');
      final e = Estado()..id = id;
      final comp = j['header']['competitions'][0];
      final st = comp['status'] ?? j['header']['competitions'][0]['status'];
      e.estado = '${st['type']['state']}';
      e.detalle = '${st['type']['shortDetail'] ?? st['type']['detail'] ?? ''}';
      e.reloj = '${st['displayClock'] ?? ''}';
      e.periodo = (st['period'] as num?)?.toInt() ?? 0;
      e.minuto = int.tryParse(RegExp(r'\d+').firstMatch(e.reloj)?.group(0) ?? '') ?? 0;
      e.inicio = DateTime.tryParse('${comp['date']}')?.toLocal();
      String? idL;
      for (final c in (comp['competitors'] as List)) {
        final local = c['homeAway'] == 'home';
        final g = int.tryParse('${c['score'] ?? 0}') ?? 0;
        final ls = (c['linescores'] as List?) ?? [];
        final ht = ls.isNotEmpty ? int.tryParse('${ls[0]['displayValue']}') : null;
        if (local) {
          e.nl = '${c['team']['displayName']}';
          e.gl = g;
          e.htl = ht;
          idL = '${c['team']['id']}';
        } else {
          e.nv = '${c['team']['displayName']}';
          e.gv = g;
          e.htv = ht;
        }
      }
      for (final t in ((j['boxscore']?['teams']) as List? ?? [])) {
        final m = {for (final s in (t['statistics'] as List? ?? [])) '${s['name']}': '${s['displayValue']}'};
        if ('${t['team']['id']}' == idL) {
          e.sl = m;
        } else {
          e.sv = m;
        }
      }
      for (final r in (j['rosters'] as List? ?? [])) {
        for (final p in (r['roster'] as List? ?? [])) {
          final s = {for (final x in (p['stats'] as List? ?? [])) '${x['name']}': (x['value'] as num?)?.toInt() ?? 0};
          if ((s['appearances'] ?? 0) == 0 && p['starter'] != true && (s['subIns'] ?? 0) == 0) continue;
          e.jugadores.add(Jugador('${p['athlete']?['displayName'] ?? ''}', p['starter'] == true, s['shotsOnTarget'] ?? 0,
              s['totalShots'] ?? 0, s['totalGoals'] ?? 0, s['yellowCards'] ?? 0, s['redCards'] ?? 0));
        }
      }
      for (final k in (j['keyEvents'] as List? ?? [])) {
        final tipo = '${k['type']?['text'] ?? ''}';
        if (!RegExp('Goal|Card|Penalty|Substitution|Halftime|End', caseSensitive: false).hasMatch(tipo)) continue;
        final quien = (k['participants'] as List? ?? []).map((x) => x['athlete']?['displayName'] ?? '').join(', ');
        e.eventos.add('${k['clock']?['displayValue'] ?? ''} ${_tipoEs(tipo)}'
            '${k['team'] != null ? ' · ${k['team']['displayName']}' : ''}${quien.isNotEmpty ? ' · $quien' : ''}');
      }
      _cache[id] = e;
      return e;
    } catch (_) {
      return c;
    }
  }

  static String _tipoEs(String t) => t
      .replaceAll('Own Goal', '⚽ Autogol').replaceAll('Penalty - Scored', '⚽ Penal').replaceAll(RegExp('^Goal.*'), '⚽ Gol')
      .replaceAll('Yellow Card', '🟨 Amarilla').replaceAll('Red Card', '🟥 Roja').replaceAll('Substitution', '🔁 Cambio')
      .replaceAll('Halftime', 'Medio tiempo').replaceAll('End Regular Time', 'Final');
}

// ---------------------------------------------------------------- avance de cada pata
class Avance {
  final String texto, estado; // estado: ganada | perdida | en juego | por empezar | sin datos
  final double? pVivo;
  Avance(this.texto, this.estado, [this.pVivo]);
}

double _poisMayorIgual(double l, int k) {
  if (k <= 0) return 1;
  var t = math.exp(-l), s = t;
  for (var i = 1; i < k; i++) {
    t *= l / i;
    s += t;
  }
  return (1 - s).clamp(0, 1).toDouble();
}

double _poisMenorIgual(double l, int k) => k < 0 ? 0 : 1 - _poisMayorIgual(l, k + 1);

/// λ (por partido) que hace que la probabilidad previa de la pata sea [p]: la "fuerza" que el bot esperaba.
double _lambdaDe(double p, int k, bool mas) {
  var lo = 0.01, hi = 40.0;
  for (var i = 0; i < 50; i++) {
    final m = (lo + hi) / 2;
    final q = mas ? _poisMayorIgual(m, k) : _poisMenorIgual(m, k);
    if ((mas && q < p) || (!mas && q > p)) {
      lo = m;
    } else {
      hi = m;
    }
  }
  return (lo + hi) / 2;
}

/// Parte del partido que falta (0..1) para un mercado del partido completo, 1.er o 2.º tiempo.
double _falta(Estado e, String m) {
  if (e.estado == 'pre') return 1;
  if (e.terminado) return 0;
  final min = e.minuto.clamp(0, 90);
  if (m.startsWith('1t_')) return e.periodo >= 2 ? 0 : math.max(0.01, (45 - min) / 45);
  if (m.startsWith('2t_')) return e.periodo < 2 ? 1 : math.max(0.01, (90 - min) / 45);
  return math.max(0.01, (90 - min) / 90);
}

Avance evaluar(Map<String, dynamic> sel, double pPre, Estado? e, {String? nombreJugador}) {
  if (e == null) return Avance('Sin datos en vivo todavía', 'sin datos');
  final m = '${sel['mercado'] ?? ''}', o = '${sel['opcion'] ?? ''}';
  final linea = (sel['linea'] as num?)?.toDouble() ?? 0.5;
  final pp = pPre.clamp(0.02, 0.98);
  // --- mercados de conteo
  int? valor;
  String que = '';
  switch (m) {
    case 'goles':
      valor = e.gl + e.gv;
      que = 'Goles';
    case 'goles_local':
      valor = e.gl;
      que = 'Goles ${e.nl}';
    case 'goles_visitante':
      valor = e.gv;
      que = 'Goles ${e.nv}';
    case '1t_goles':
      valor = e.periodo >= 2 || e.terminado ? (e.htl ?? e.gl) + (e.htv ?? e.gv) : e.gl + e.gv;
      que = 'Goles 1.er tiempo';
    case '2t_goles':
      valor = e.periodo >= 2 || e.terminado ? e.gl + e.gv - (e.htl ?? 0) - (e.htv ?? 0) : 0;
      que = 'Goles 2.º tiempo';
    case 'corners':
      valor = e.cornersL + e.cornersV;
      que = 'Córners';
    case 'corners_local':
      valor = e.cornersL;
      que = 'Córners ${e.nl}';
    case 'corners_visitante':
      valor = e.cornersV;
      que = 'Córners ${e.nv}';
    case 'tarjetas':
      valor = e.tarjetasPts;
      que = 'Tarjetas (amarilla 1, roja 2)';
    case 'jug_arco':
      final nom = nombreJugador ?? '${sel['jugador_nombre'] ?? ''}';
      Jugador? j;
      var best = 0.55;
      for (final x in e.jugadores) {
        final s = parecido(x.nombre, nom);
        if (s > best) {
          best = s;
          j = x;
        }
      }
      if (j == null) {
        return Avance(e.estado == 'pre' ? '$nom: alineación aún no publicada' : '$nom: no aparece en la alineación',
            e.estado == 'pre' ? 'por empezar' : 'sin datos');
      }
      valor = j.tirosArco;
      que = '${j.nombre}${j.titular ? '' : ' (suplente)'} · tiros al arco';
  }
  if (valor != null) {
    final mas = m == 'jug_arco' || o == 'mas';
    final k = mas ? linea.floor() + 1 : linea.floor();
    final objetivo = mas ? 'necesita ${linea.floor() + 1}+' : 'máximo ${linea.floor()}';
    final txt = '$que: $valor ($objetivo)';
    final cierre = e.terminado || (m.startsWith('1t_') && e.periodo >= 2);
    if (mas && valor >= k) return Avance(txt, 'ganada', 1);
    if (!mas && valor > k) return Avance(txt, 'perdida', 0);
    if (cierre) return Avance(txt, mas ? 'perdida' : 'ganada', mas ? 0 : 1);
    final l = _lambdaDe(pp, k, mas) * _falta(e, m);
    final pv = mas ? _poisMayorIgual(l, k - valor) : _poisMenorIgual(l, k - valor);
    return Avance(txt, e.estado == 'pre' ? 'por empezar' : 'en juego', pv);
  }
  // --- mercados de resultado: goles que faltan con Poisson para cada equipo
  final p1x2 = _probPartido(e);
  final g = (p1x2['g'] ?? 2.6), share = 0.5 + 0.35 * ((p1x2['1'] ?? 0.4) - (p1x2['2'] ?? 0.3));
  final medio = m.startsWith('1t_');
  final f = _falta(e, medio ? '1t_' : m);
  final lam = g * (medio ? 0.45 : 1) * f;
  final hl = medio ? (e.periodo >= 2 || e.terminado ? (e.htl ?? e.gl) : e.gl) : e.gl;
  final hv = medio ? (e.periodo >= 2 || e.terminado ? (e.htv ?? e.gv) : e.gv) : e.gv;
  bool? gana(int a, int b) {
    switch (m) {
      case '1x2':
      case '1t_1x2':
        return o == 'local' ? a > b : o == 'visitante' ? a < b : a == b;
      case 'doble':
        return o == '1X' ? a >= b : o == 'X2' ? a <= b : a != b;
      case 'btts':
        return o == 'si' ? (a > 0 && b > 0) : !(a > 0 && b > 0);
      case 'btts_o25':
        final x = (a > 0 && b > 0) || a + b > 2.5;
        return o == 'si' ? x : !x;
    }
    return null;
  }
  if (gana(hl, hv) == null) return Avance('Mercado sin seguimiento automático', 'sin datos');
  final txt = '${medio ? '1.er tiempo' : 'Marcador'}: ${e.nl} $hl - $hv ${e.nv}';
  if (e.terminado || (medio && e.periodo >= 2)) {
    final ok = gana(hl, hv)!;
    return Avance(txt, ok ? 'ganada' : 'perdida', ok ? 1 : 0);
  }
  var pv = 0.0;
  final ll = lam * share, lv = lam * (1 - share);
  for (var a = 0; a <= 8; a++) {
    for (var b = 0; b <= 8; b++) {
      final pa = math.exp(-ll) * math.pow(ll, a) / _fact(a), pb = math.exp(-lv) * math.pow(lv, b) / _fact(b);
      if (gana(hl + a, hv + b) == true) pv += pa * pb;
    }
  }
  if (e.estado == 'pre') pv = pp;
  return Avance(txt, e.estado == 'pre' ? 'por empezar' : 'en juego', pv.clamp(0, 1).toDouble());
}

double _fact(int n) => n <= 1 ? 1 : n * _fact(n - 1);

Map<String, double> _probPartido(Estado e) {
  for (final p in repo.partidos) {
    final l = '${p['local']?['nombre'] ?? ''}', v = '${p['visitante']?['nombre'] ?? ''}';
    if (parecido(l, e.nl) >= 0.6 && parecido(v, e.nv) >= 0.6) {
      final pr = Map<String, dynamic>.from(p['prob'] ?? {});
      return {'g': (p['goles_esperados'] as num?)?.toDouble() ?? 2.6, '1': (pr['1'] as num?)?.toDouble() ?? 0.4,
        '2': (pr['2'] as num?)?.toDouble() ?? 0.3};
    }
  }
  return {};
}

/// Probabilidad previa de una pata guardada: la del bot o, si viene de una captura, la que implica su cuota.
double pPrevia(Map<String, dynamic> pata) {
  final p = (pata['p'] as num?)?.toDouble();
  if (p != null && p > 0) return p;
  final c = (pata['cuota'] as num?)?.toDouble();
  if (c != null && c > 1) return (0.94 / c).clamp(0.02, 0.98);
  return 0.6;
}

// ---------------------------------------------------------------- pantalla
class PantallaVivo extends StatefulWidget {
  const PantallaVivo({super.key});
  @override
  State<PantallaVivo> createState() => _PantallaVivoState();
}

class _PantallaVivoState extends State<PantallaVivo> {
  List<Map<String, dynamic>> boletas = [];
  final estados = <String, Estado?>{}; // clave línea → estado
  Timer? reloj;
  bool cargando = true;
  String? aviso;

  @override
  void initState() {
    super.initState();
    _refrescar();
    reloj = Timer.periodic(const Duration(seconds: 60), (_) => _refrescar());
  }

  @override
  void dispose() {
    reloj?.cancel();
    super.dispose();
  }

  static String claveLinea(Map l) => '${l['local']}|${l['visitante']}|${l['inicio']}';

  Future<void> _refrescar() async {
    final b = (await Historial.cargar()).where((x) => x['estado'] == 'pendiente').toList();
    final ahora = DateTime.now();
    var fallos = 0;
    for (final bol in b) {
      for (final l in (bol['lineas'] as List)) {
        final ini = DateTime.tryParse('${l['inicio']}') ?? ahora;
        final k = claveLinea(l);
        final previo = estados[k];
        // antes del partido basta con revisar cada pocos minutos; terminado ya no se vuelve a pedir
        if (previo != null && previo.terminado) continue;
        if (previo == null && ini.difference(ahora).inMinutes > 20 && estados.containsKey(k)) continue;
        final id = await Espn.buscar('${l['liga'] ?? ''}', '${l['local']}', '${l['visitante']}', ini);
        if (id == null) {
          estados[k] = null;
          fallos++;
          continue;
        }
        estados[k] = await Espn.estado(id);
      }
    }
    final liquidadas = await Historial.liquidarEnVivo(estados);
    if (!mounted) return;
    setState(() {
      boletas = b;
      cargando = false;
      aviso = liquidadas > 0 ? '✅ $liquidadas boleta(s) liquidada(s) con el resultado final.'
          : fallos > 0 ? 'Algunos partidos aún no aparecen en ESPN (se reintenta solo).' : null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refrescar,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Row(children: [
          Expanded(child: Text('En vivo', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800))),
          const Text('se actualiza cada minuto', style: TextStyle(color: Col.suave, fontSize: 12)),
        ]),
        const Text('Tus boletas pendientes (apostadas, de seguimiento o leídas de capturas). Datos: ESPN.',
            style: TextStyle(color: Col.suave)),
        if (aviso != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(aviso!, style: const TextStyle(color: Col.naranja))),
        const SizedBox(height: 8),
        if (cargando) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
        if (!cargando && boletas.isEmpty)
          const Text('No tienes boletas pendientes. Guarda una en la Súper boleta («La aposté» o 👁️) o sube una captura '
              'en «Capturas».', style: TextStyle(color: Col.suave)),
        for (final b in boletas) _boleta(b),
      ]),
    );
  }

  Widget _boleta(Map<String, dynamic> b) {
    final ls = (b['lineas'] as List);
    var pTotal = 1.0;
    final filas = <Widget>[];
    for (final l in ls) {
      final e = estados[claveLinea(l)];
      filas.add(_linea(Map<String, dynamic>.from(l), e, (p) => pTotal *= p));
    }
    final tipo = b['tipo'] == 'apostada' ? 'S/${f2((b['monto'] as num).toDouble())} · ' : b['origen'] == 'captura' ? '📷 ' : '👁️ ';
    return Card(
      color: Col.tarjeta,
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('$tipo${ls.length} partido(s) · cuota ${f2((b['cuota'] as num).toDouble())}',
                style: const TextStyle(fontWeight: FontWeight.w800))),
            ChipProb(pTotal),
          ]),
          Text('Prob. de acertar todo ahora (aprox.) · antes: ${pct((b['p'] as num?)?.toDouble() ?? 0)}',
              style: const TextStyle(color: Col.suave, fontSize: 12)),
          const Divider(),
          ...filas,
        ]),
      ),
    );
  }

  Widget _linea(Map<String, dynamic> l, Estado? e, void Function(double) acumular) {
    final cab = e == null
        ? 'Buscando en ESPN… · ${diaHora(DateTime.parse(l['inicio']))}'
        : e.estado == 'pre'
            ? 'Empieza ${e.inicio != null ? diaHora(e.inicio!) : ''}'
            : '${e.nl} ${e.gl} - ${e.gv} ${e.nv} · ${e.terminado ? 'Final' : e.reloj}';
    return InkWell(
      onTap: e == null ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => DetallePartido(e: e, linea: l))),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${l['local']} vs ${l['visitante']}', style: const TextStyle(fontWeight: FontWeight.w700)),
          Text(cab, style: TextStyle(color: e?.enJuego == true ? const Color(0xFF34D399) : Col.suave, fontSize: 13,
              fontWeight: e?.enJuego == true ? FontWeight.w800 : FontWeight.normal)),
          for (final p in (l['patas'] as List)) _pata(Map<String, dynamic>.from(p), e, acumular),
          if (e != null) const Text('Toca para ver todas las estadísticas ›', style: TextStyle(color: Col.naranja, fontSize: 12)),
        ]),
      ),
    );
  }

  Widget _pata(Map<String, dynamic> p, Estado? e, void Function(double) acumular) {
    final a = evaluar(Map<String, dynamic>.from(p['sel'] ?? {}), pPrevia(p), e);
    acumular(a.pVivo ?? pPrevia(p));
    final color = a.estado == 'ganada' ? const Color(0xFF34D399) : a.estado == 'perdida' ? Col.rosa : Col.texto;
    final icono = a.estado == 'ganada' ? '✅' : a.estado == 'perdida' ? '❌' : a.estado == 'en juego' ? '⏱️' : '•';
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(color: Col.panel, borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withValues(alpha: 0.6))),
      child: Row(children: [
        Text(icono),
        const SizedBox(width: 8),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${p['titulo']} · ${p['mercado']}', style: TextStyle(fontWeight: FontWeight.w800, color: color)),
          Text(a.texto, style: const TextStyle(color: Col.suave, fontSize: 12.5)),
        ])),
        if (a.pVivo != null && a.estado != 'ganada' && a.estado != 'perdida') ChipProb(a.pVivo!),
      ]),
    );
  }
}

class DetallePartido extends StatelessWidget {
  final Estado e;
  final Map<String, dynamic> linea;
  const DetallePartido({super.key, required this.e, required this.linea});

  static const _nombres = {
    'possessionPct': 'Posesión %', 'totalShots': 'Tiros', 'shotsOnTarget': 'Tiros al arco', 'wonCorners': 'Córners',
    'foulsCommitted': 'Faltas', 'yellowCards': 'Amarillas', 'redCards': 'Rojas', 'offsides': 'Fueras de juego',
    'saves': 'Atajadas', 'blockedShots': 'Tiros bloqueados', 'accuratePasses': 'Pases buenos', 'totalPasses': 'Pases',
    'totalCrosses': 'Centros', 'totalTackles': 'Entradas', 'interceptions': 'Intercepciones',
  };

  @override
  Widget build(BuildContext context) {
    final marcadas = <String>{for (final p in (linea['patas'] as List)) '${p['sel']?['mercado'] ?? ''}'};
    bool resaltar(String k) =>
        (k == 'wonCorners' && marcadas.any((m) => m.startsWith('corners'))) ||
        ((k == 'yellowCards' || k == 'redCards') && marcadas.contains('tarjetas')) ||
        (k == 'shotsOnTarget' && marcadas.contains('jug_arco'));
    final jugMarcados = [for (final p in (linea['patas'] as List)) if (p['sel']?['jugador_nombre'] != null) '${p['sel']['jugador_nombre']}'];
    final tiradores = [...e.jugadores.where((j) => j.tiros > 0 || jugMarcados.any((n) => parecido(n, j.nombre) > 0.55))]
      ..sort((a, b) => b.tirosArco.compareTo(a.tirosArco) != 0 ? b.tirosArco.compareTo(a.tirosArco) : b.tiros.compareTo(a.tiros));
    return Scaffold(
      appBar: AppBar(backgroundColor: Col.panel, title: Text('${e.nl} vs ${e.nv}')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        Center(child: Text('${e.gl} - ${e.gv}', style: const TextStyle(fontSize: 44, fontWeight: FontWeight.w900))),
        Center(child: Text(e.terminado ? 'Final' : e.estado == 'pre' ? 'Por empezar' : e.reloj,
            style: const TextStyle(color: Col.suave))),
        const SizedBox(height: 10),
        if ((linea['patas'] as List).isNotEmpty)
          const Text('Lo que marcó el bot', style: TextStyle(fontWeight: FontWeight.w800, color: Col.naranja)),
        for (final p in (linea['patas'] as List))
          Builder(builder: (_) {
            final a = evaluar(Map<String, dynamic>.from(p['sel'] ?? {}), pPrevia(Map<String, dynamic>.from(p)), e);
            return ListTile(dense: true, title: Text('${p['titulo']} · ${p['mercado']}'), subtitle: Text(a.texto),
                trailing: Text(a.estado == 'ganada' ? '✅' : a.estado == 'perdida' ? '❌' : a.pVivo != null ? pct(a.pVivo!) : ''));
          }),
        const Divider(),
        Row(children: [
          Expanded(child: Text(e.nl, style: const TextStyle(fontWeight: FontWeight.w800))),
          const Text('Estadística', style: TextStyle(color: Col.suave)),
          Expanded(child: Text(e.nv, textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w800))),
        ]),
        for (final k in _nombres.keys)
          if (e.sl.containsKey(k) || e.sv.containsKey(k))
            Container(
              color: resaltar(k) ? Col.naranja.withValues(alpha: 0.18) : null,
              padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 4),
              child: Row(children: [
                Expanded(child: Text(e.sl[k] ?? '-', style: const TextStyle(fontWeight: FontWeight.w700))),
                Text(_nombres[k]!, style: TextStyle(color: resaltar(k) ? Col.naranja : Col.suave)),
                Expanded(child: Text(e.sv[k] ?? '-', textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w700))),
              ]),
            ),
        if (e.sl.isEmpty) const Text('Las estadísticas aparecen cuando empieza el partido.', style: TextStyle(color: Col.suave)),
        if (tiradores.isNotEmpty) ...[
          const Divider(),
          const Text('Jugadores que remataron (al arco / total)', style: TextStyle(fontWeight: FontWeight.w800)),
          for (final j in tiradores.take(14))
            ListTile(
              dense: true,
              title: Text(j.nombre, style: TextStyle(
                  color: jugMarcados.any((n) => parecido(n, j.nombre) > 0.55) ? Col.naranja : null, fontWeight: FontWeight.w700)),
              subtitle: Text('${j.titular ? 'Titular' : 'Suplente'}${j.goles > 0 ? ' · ⚽ ${j.goles}' : ''}'
                  '${j.amarillas > 0 ? ' · 🟨' : ''}${j.rojas > 0 ? ' · 🟥' : ''}'),
              trailing: Text('${j.tirosArco} / ${j.tiros}', style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
            ),
        ],
        if (e.eventos.isNotEmpty) ...[
          const Divider(),
          const Text('Jugadas clave', style: TextStyle(fontWeight: FontWeight.w800)),
          for (final x in e.eventos.reversed) Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text(x)),
        ],
        const SizedBox(height: 12),
        const Text('Probabilidades en vivo: aproximación con lo que esperaba el bot y el tiempo que falta.',
            style: TextStyle(color: Col.suave, fontSize: 12)),
      ]),
    );
  }
}
