// Lectura de combinadas de Betano a partir del texto del OCR, y opinión del bot.
// Formatos reales de Betano (vistos en capturas del usuario, 18/10/2026):
//  - Cupón: "Más de 1.5   1.14" / "Goles totales Más/Menos" / equipo local / equipo visitante.
//  - Bet Builder: "Bet Builder 2/13  1.57" / local / visitante / (selección / mercado) × n.
//  - Mis apuestas: igual, con "Marcador 3-2", ✓ y "Combinada de 3 S/30.00 Ganada".
//  - Imagen compartida: "Combinada de 8  6.65", equipos cortados ("Getafe…"), "Mañana 13:45" a la derecha,
//    mercados partidos en dos renglones ("Rodez AF Más/Menos" / "Córners").
import 'dart:math' as math;

import 'comunes.dart';
import 'datos.dart';
import 'vivo.dart';

const mercadosCaptura = {
  '1x2': 'Resultado del partido', 'doble': 'Doble oportunidad', 'goles': 'Goles totales Más/Menos',
  'goles_local': 'Goles del local', 'goles_visitante': 'Goles del visitante', 'btts': 'Ambos equipos anotan',
  '1t_goles': 'Goles 1.er tiempo', '2t_goles': 'Goles 2.º tiempo', '1t_1x2': 'Resultado 1.er tiempo',
  'corners': 'Más/Menos Córners', 'corners_local': 'Córners del local', 'corners_visitante': 'Córners del visitante',
  'tarjetas': 'Tarjetas Más/Menos', 'tiros_arco': 'Tiros al Arco (partido)', 'tiros_arco_local': 'Tiros al Arco del local',
  'tiros_arco_visitante': 'Tiros al Arco del visitante', 'jug_arco': 'Jugador tiros al arco', 'otro': 'Otro (seguimiento manual)',
};

class PataCaptura {
  String mercado, opcion, jugador, textoSel, textoMercado;
  double? linea, cuota;
  int partido;
  PataCaptura(this.mercado, this.opcion,
      {this.linea, this.cuota, this.jugador = '', this.partido = 0, this.textoSel = '', this.textoMercado = ''});

  Map<String, dynamic> get sel => {'mercado': mercado, 'opcion': opcion, 'linea': linea,
        'jugador_nombre': jugador.isEmpty ? null : jugador};

  String get titulo {
    if (mercado == 'jug_arco') return '$jugador $opcion';
    if (opcion == 'mas' || opcion == 'menos') return '${opcion == 'mas' ? 'Más' : 'Menos'} de ${linea ?? ''}';
    if (opcion == 'si' || opcion == 'no') return opcion == 'si' ? 'Sí' : 'No';
    return textoSel.isNotEmpty ? textoSel : opcion;
  }
}

class PartidoCaptura {
  String local, visitante, liga = '';
  DateTime? inicio;
  double? cuota; // cuota de la tarjeta (simple o Bet Builder)
  String? marcador;
  Map<String, dynamic>? paquete; // partido del paquete del bot (si se reconoció)
  PartidoCaptura(this.local, this.visitante);
  Map<String, dynamic> get mercados => Map<String, dynamic>.from(paquete?['mercados'] ?? {});
}

class LecturaCaptura {
  final partidos = <PartidoCaptura>[];
  final patas = <PataCaptura>[];
  double? monto, cuotaTotal, ganancia;
  final lineasVistas = <String, Set<int>>{};
  String texto = '';
  DateTime? get inicio => partidos.map((p) => p.inicio).whereType<DateTime>().fold<DateTime?>(null, (a, b) => a == null || b.isBefore(a) ? b : a);
}

// ---------------------------------------------------------------- limpieza de renglones
class _Renglon {
  String texto;
  double? cuota;
  String? marcador;
  int? hora, minuto, dia; // dia: 0 hoy, 1 mañana, null = no dice
  DateTime? fecha;
  String tipo = ''; // ruido | pie | bb | mercado | seleccion | equipo
  _Renglon(this.texto);
  String get n => normal(texto);
}

double? _num(String s) => double.tryParse(s.replaceAll(',', '.'));

const _diasSemana = {'lun': 1, 'mar': 2, 'mie': 3, 'jue': 4, 'vie': 5, 'sab': 6, 'dom': 7};

_Renglon _limpiar(String crudo) {
  var t = crudo;
  final r = _Renglon('');
  final m = RegExp(r'Marcador\s*(\d+)\s*[-:]\s*(\d+)', caseSensitive: false).firstMatch(t);
  if (m != null) {
    r.marcador = '${m.group(1)}-${m.group(2)}';
    t = t.replaceRange(m.start, m.end, ' ');
  }
  final h = RegExp(r'(\d{1,2}):(\d{2})').firstMatch(t);
  if (h != null) {
    r.hora = int.parse(h.group(1)!);
    r.minuto = int.parse(h.group(2)!);
    t = t.replaceRange(h.start, h.end, ' ');
  }
  final f = RegExp(r'\b(\d{1,2})/(\d{1,2})\b(?![.,]?\d)').firstMatch(t); // Betano escribe 19/10 (1.5 es una línea)
  if (f != null && !RegExp(r'\d+[.,]\d{2}').hasMatch(f.group(0)!)) {
    final d = int.tryParse(f.group(1)!), mes = int.tryParse(f.group(2)!);
    if (d != null && mes != null && d <= 31 && mes <= 12 && !t.toLowerCase().contains('bet builder')) {
      r.fecha = DateTime(DateTime.now().year, mes, d);
      t = t.replaceRange(f.start, f.end, ' ');
    }
  }
  final nl = normal(t);
  if (RegExp(r'\b(manana)\b').hasMatch(nl)) {
    r.dia = 1;
    t = t.replaceAll(RegExp(r'ma[ñn]ana', caseSensitive: false), ' ');
  } else if (RegExp(r'\bhoy\b').hasMatch(nl)) {
    r.dia = 0;
    t = t.replaceAll(RegExp(r'\bhoy\b', caseSensitive: false), ' ');
  } else {
    for (final e in _diasSemana.entries) {
      if (RegExp('^${e.key}[a-z]*\\b').hasMatch(nl) && nl.split(' ').length <= 2) {
        final hoy = DateTime.now();
        r.dia = (e.value - hoy.weekday) % 7;
        t = '';
      }
    }
  }
  final c = RegExp(r'(\d{1,3}[.,]\d{2})\s*$').firstMatch(t.trim());
  if (c != null && !RegExp(r'(s/|S/)\s*$').hasMatch(t.trim().substring(0, c.start))) {
    r.cuota = _num(c.group(1)!);
    t = t.trim().substring(0, c.start);
  }
  t = t
      .replaceAll(RegExp(r'[✓✔✅©®Øø⊘ⓘ•●○◦@√]'), ' ')
      .replaceAll(RegExp(r'\(\s*\+?\d\s*\)'), ' ')
      .replaceAll(RegExp(r'\(?\bSM\b\)?'), ' ')
      .replaceAll(RegExp(r'SuperCuotas', caseSensitive: false), ' ')
      .replaceAll(RegExp(r'(…|\.{2,})'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  r.texto = t;
  return r;
}

const _ruido = ['betano', 'cupon apuestas', 'guardar', 'compartir', 'simple', 'combinadas', 'sistema', 'abiertas',
  'resueltas', 'ganadas', 'cash out', 'perdidas', 'anuladas', 'deposito', 'inicio', 'en vivo', 'deportes', 'apuestas',
  'social', 'ganado con pago anticipado', 'pago anticipado', 'ganada', 'perdida', 'anulada', 'mis apuestas', 'cuota'];

const _claveMercado = ['mas menos', 'goles totales', 'resultado partido', 'resultado final', 'corner', 'tiros al arco',
  'tiros arco', 'tiros puerta', 'tiros a puerta', 'ambos equipos', 'doble oportunidad', 'tarjeta', 'primer tiempo',
  'segundo tiempo', 'mitad', 'handicap', 'goleador', 'descanso', 'total goles', 'goles equipo'];

final _palabrasMercado = RegExp(
    r'goles totales|m[aá]s ?/ ?menos|c[oó]rners?|resultado del partido|resultado final|tiros al arco|tiros a puerta|'
    r'tarjetas?( totales)?|ambos equipos (marcan|anotan)|doble oportunidad|primer tiempo|segundo tiempo',
    caseSensitive: false);

bool _esMercado(String n) => _claveMercado.any(n.contains) && !RegExp(r'^(mas|menos) \d').hasMatch(n);
bool _pareceSeleccion(String crudo, String n) =>
    RegExp(r'^(m[aá]s|menos|over|under)\s*(de\s*)?\d', caseSensitive: false).hasMatch(crudo) ||
    RegExp(r'^(si|no|empate)$').hasMatch(n) || RegExp(r'\d\s*\+').hasMatch(crudo);

// ---------------------------------------------------------------- lectura
LecturaCaptura leerTexto(List<String> crudos) {
  final r = LecturaCaptura()..texto = crudos.join('\n');
  final rs = <_Renglon>[];
  for (final c in crudos) {
    final n0 = normal(c);
    if (n0.startsWith('combinada') || n0.contains('colocar apuesta') || n0.contains('ganancia potencial') ||
        n0.contains('importe') || n0.contains('apuesta total')) {
      final monto = RegExp(r'[sS]/\.?\s*(\d{1,6}(?:[.,]\d{1,2})?)').firstMatch(c);
      if (n0.contains('ganancia')) {
        if (monto != null) r.ganancia = _num(monto.group(1)!);
        continue;
      }
      if (monto != null) r.monto ??= _num(monto.group(1)!);
      final sinMonto = c.replaceAll(RegExp(r'[sS]/\.?\s*\d{1,6}(?:[.,]\d{1,2})?'), ' ');
      final cuotas = RegExp(r'(\d{1,4}[.,]\d{2})').allMatches(sinMonto).map((m) => _num(m.group(1)!)).whereType<double>();
      if (cuotas.isNotEmpty && n0.startsWith('combinada')) r.cuotaTotal = cuotas.last;
      continue;
    }
    final x = _limpiar(c);
    if (x.texto.isEmpty && x.cuota == null && x.hora == null && x.dia == null && x.marcador == null && x.fecha == null) continue;
    final n = x.n;
    if (x.texto.isEmpty || RegExp(r'^\d+ ?\d*$').hasMatch(n) || _ruido.contains(n) ||
        RegExp(r'^\d+/\d+$').hasMatch(x.texto)) {
      x.tipo = 'aux';
    } else if (n.contains('bet builder') || n.contains('crear apuesta')) {
      x.tipo = 'bb';
    } else if (_esMercado(n)) {
      x.tipo = 'mercado';
    }
    rs.add(x);
  }
  // selección = renglón seguido de un mercado (o con forma de selección); el resto, equipos
  for (var i = 0; i < rs.length; i++) {
    if (rs[i].tipo.isNotEmpty) continue;
    final sig = rs.skip(i + 1).firstWhere((x) => x.tipo != 'aux', orElse: () => _Renglon('')..tipo = 'fin');
    rs[i].tipo = sig.tipo == 'mercado' || _pareceSeleccion(rs[i].texto, rs[i].n) ? 'seleccion' : 'equipo';
  }
  // tarjetas: simple (selección con cuota) o Bet Builder (cabecera + equipos + patas sin cuota)
  final tarjetas = <_Tarjeta>[];
  _Tarjeta? cur;
  PataCaptura? ultima;
  for (final x in rs) {
    if (cur != null) {
      if (x.marcador != null) cur.p.marcador ??= x.marcador;
      if (x.hora != null) cur.hora ??= x.hora;
      if (x.minuto != null) cur.minuto ??= x.minuto;
      if (x.dia != null) cur.dia ??= x.dia;
      if (x.fecha != null) cur.fecha ??= x.fecha;
    }
    switch (x.tipo) {
      case 'bb':
        cur = _Tarjeta(true)..p.cuota = x.cuota;
        tarjetas.add(cur);
        ultima = null;
      case 'seleccion':
        final nueva = cur == null || x.cuota != null || !cur.bb && cur.equipos.length >= 2;
        if (nueva) {
          cur = _Tarjeta(false)..p.cuota = x.cuota;
          tarjetas.add(cur);
        }
        ultima = PataCaptura('otro', '', textoSel: x.texto, cuota: nueva ? x.cuota : null);
        cur!.patas.add(ultima);
      case 'mercado':
        // en la imagen compartida el nombre del equipo puede quedar pegado al mercado: "RC Celta de Vig… Más/Menos"
        final resto = x.texto.replaceAll(_palabrasMercado, ' ').replaceAll(RegExp(r'\s+'), ' ').trim();
        if (cur != null && !cur.bb && cur.equipos.length < 2 && ultima != null && ultima.textoMercado.isNotEmpty &&
            RegExp(r'[A-Za-zÁÉÍÓÚÑáéíóúñ]{4}').hasMatch(resto)) {
          cur.equipos.add(resto);
          ultima.textoMercado = '${ultima.textoMercado} ${x.texto.replaceAll(resto, '')}'.trim();
        } else if (ultima != null) {
          ultima.textoMercado = '${ultima.textoMercado} ${x.texto}'.trim();
        }
      case 'equipo':
        if (cur != null && cur.equipos.length < 2) cur.equipos.add(x.texto);
      case 'aux':
        if (x.cuota != null && cur != null && cur.p.cuota == null) cur.p.cuota = x.cuota;
    }
    if (x.dia != null && cur == null && tarjetas.isEmpty) {
      // fecha suelta antes de la primera tarjeta: se aplica a la siguiente
    }
  }
  // interpretar cada tarjeta
  for (final t in tarjetas) {
    if (t.patas.isEmpty) continue;
    final pc = t.p;
    pc.local = t.equipos.isNotEmpty ? t.equipos[0] : '';
    pc.visitante = t.equipos.length > 1 ? t.equipos[1] : '';
    _reconocer(pc, [for (final p in t.patas) p.textoMercado]);
    final ahora = DateTime.now();
    if (pc.inicio == null && t.hora != null) {
      final base = t.fecha ?? DateTime(ahora.year, ahora.month, ahora.day).add(Duration(days: t.dia ?? 0));
      pc.inicio = DateTime(base.year, base.month, base.day, t.hora!, t.minuto ?? 0);
    }
    final idx = r.partidos.length;
    r.partidos.add(pc);
    for (final p in t.patas) {
      _interpretar(p, pc);
      p.partido = idx;
      if (p.mercado == 'jug_arco' && p.jugador.isNotEmpty) r.lineasVistas.putIfAbsent(p.jugador, () => {}).add((p.linea ?? 0.5).ceil());
      r.patas.add(p);
    }
  }
  return r;
}

class _Tarjeta {
  final bool bb;
  final p = PartidoCaptura('', '');
  final equipos = <String>[];
  final patas = <PataCaptura>[];
  int? hora, minuto, dia;
  DateTime? fecha;
  _Tarjeta(this.bb);
}

/// Busca el partido en el paquete del bot (nombres cortados o abreviados incluidos) y completa nombres, liga y hora.
void _reconocer(PartidoCaptura pc, List<String> mercados) {
  Map<String, dynamic>? mejor;
  var puntos = 0.0;
  for (final m in repo.partidos) {
    final l = '${m['local']?['nombre'] ?? ''}', v = '${m['visitante']?['nombre'] ?? ''}';
    final sl = math.max(parecido(pc.local, l), _prefijo(pc.local, l));
    final sv = math.max(parecido(pc.visitante, v), _prefijo(pc.visitante, v));
    // los dos equipos deben parecerse (o uno casi igual si el otro no se pudo leer)
    final ok = (sl >= 0.6 && sv >= 0.6) || (sl >= 0.9 && normal(pc.visitante).length < 3) ||
        (sv >= 0.9 && normal(pc.local).length < 3);
    if (!ok) continue;
    var s = sl + sv;
    for (final t in mercados) {
      if (_prefijo(t, l) >= 0.8) s += 0.3;
      if (_prefijo(t, v) >= 0.8) s += 0.3;
    }
    if (s > puntos) {
      puntos = s;
      mejor = m;
    }
  }
  if (mejor == null || puntos < 0.75) return;
  pc.paquete = mejor;
  pc.local = '${mejor['local']?['nombre']}';
  pc.visitante = '${mejor['visitante']?['nombre']}';
  pc.liga = '${mejor['liga']}';
  pc.inicio = DateTime.tryParse('${mejor['inicio']}'.replaceAll(' ', 'T'));
}

/// 0..1: el texto (posiblemente cortado, "Rayo Valleca") empieza como el nombre ("Rayo Vallecano").
double _prefijo(String corto, String largo) {
  final a = normal(corto), b = normal(largo);
  if (a.length < 3 || b.isEmpty) return 0;
  if (b.startsWith(a) || a.startsWith(b)) return 0.95;
  final pa = a.split(' '), pb = b.split(' ');
  if (pa.isNotEmpty && pb.isNotEmpty && pa.first.length >= 4 && pb.first.startsWith(pa.first)) return 0.8;
  if (pb.any((w) => w.length >= 4 && a.contains(w))) return 0.75;
  return 0;
}

bool _nombra(String texto, String equipo) => equipo.isNotEmpty && (_prefijo(texto, equipo) >= 0.75 ||
    normal(equipo).split(' ').where((w) => w.length >= 4).any((w) => normal(texto).contains(w)));

void _interpretar(PataCaptura p, PartidoCaptura pc) {
  final n = normal(p.textoMercado), s = p.textoSel, ns = normal(s);
  final lm = RegExp(r'(\d{1,2}[.,]5)').firstMatch(s);
  p.linea = lm == null ? null : _num(lm.group(1)!);
  final mas = RegExp(r'^(m[aá]s|over)', caseSensitive: false).hasMatch(s.trim());
  final menos = RegExp(r'^(menos|under)', caseSensitive: false).hasMatch(s.trim());
  final mm = mas ? 'mas' : menos ? 'menos' : '';
  final antes = n.split('mas menos').first; // "rodez af" en "Rodez AF Más/Menos Córners"
  final deLocal = _nombra(antes, pc.local), deVisit = _nombra(antes, pc.visitante);
  final km = RegExp(r'(\d)\s*\+').firstMatch(s);
  if ((n.contains('tiros') || n.contains('remate')) && (km != null || n.contains('jugador'))) {
    p.mercado = 'jug_arco';
    final k = km == null ? 1 : int.parse(km.group(1)!);
    p.opcion = '$k+';
    p.linea = k - 0.5;
    p.jugador = s.substring(0, km?.start ?? s.length).trim();
    if (p.jugador.isEmpty) p.jugador = p.textoMercado.replaceAll(RegExp(r'tiros.*', caseSensitive: false), '').trim();
  } else if (n.contains('tiros') && mm.isNotEmpty) {
    p.mercado = deLocal ? 'tiros_arco_local' : deVisit ? 'tiros_arco_visitante' : 'tiros_arco';
    p.opcion = mm;
  } else if (n.contains('corner') && mm.isNotEmpty) {
    p.mercado = deLocal ? 'corners_local' : deVisit ? 'corners_visitante' : 'corners';
    p.opcion = mm;
  } else if (n.contains('tarjeta') && mm.isNotEmpty) {
    p.mercado = 'tarjetas';
    p.opcion = mm;
  } else if (n.contains('ambos')) {
    p.mercado = 'btts';
    p.opcion = RegExp(r'^no\b').hasMatch(ns) ? 'no' : 'si';
  } else if (mm.isNotEmpty) {
    p.mercado = RegExp(r'primer tiempo|1er tiempo|1 tiempo|1a mitad|primera mitad').hasMatch(n) ? '1t_goles'
        : RegExp(r'segundo tiempo|2do tiempo|2 tiempo|segunda mitad').hasMatch(n) ? '2t_goles'
        : deLocal && !deVisit ? 'goles_local' : deVisit && !deLocal ? 'goles_visitante' : 'goles';
    p.opcion = mm;
  } else if (n.contains('doble')) {
    p.mercado = 'doble';
    final l = _nombra(s, pc.local), v = _nombra(s, pc.visitante), e = ns.contains('empate');
    p.opcion = RegExp(r'\b1x\b').hasMatch(ns) ? '1X' : RegExp(r'\bx2\b').hasMatch(ns) ? 'X2'
        : l && v ? '12' : l || (e && !v && ns.indexOf('empate') > 2) ? '1X' : 'X2';
  } else if (n.contains('resultado') || n.contains('ganador') || n.contains('1x2')) {
    p.mercado = RegExp(r'primer tiempo|descanso|1a mitad').hasMatch(n) ? '1t_1x2' : '1x2';
    p.opcion = ns.contains('empate') ? 'empate'
        : math.max(parecido(s, pc.visitante), _prefijo(s, pc.visitante)) > math.max(parecido(s, pc.local), _prefijo(s, pc.local))
            ? 'visitante' : 'local';
  } else {
    p.mercado = 'otro';
    p.opcion = s;
  }
}

// ---------------------------------------------------------------- opinión del bot
String _clave(String m, String o, double? l) => '$m|$o|${l == null ? '' : l.toString()}';

/// Probabilidad del bot para una pata (sola), o null si no la calcula.
double? probPata(PataCaptura p, PartidoCaptura pc) {
  final mer = pc.mercados;
  final v = mer[_clave(p.mercado, p.opcion, p.linea)];
  if (v is num) return v.toDouble();
  if (p.mercado == 'jug_arco') {
    for (final nivel in ['ultra', 'segura', 'equilibrada']) {
      for (final l in repo.lineas(nivel)) {
        for (final pa in l.patas) {
          if (pa.sel['mercado'] == 'jug_arco' && parecido('${pa.sel['jugador_nombre']}', p.jugador) > 0.6) {
            return pa.alternativas[p.opcion] ?? (pa.sel['opcion'] == p.opcion ? pa.p : null);
          }
        }
      }
    }
  }
  // líneas fuera de la grilla (p. ej. Más 13.5 córners): sin dato
  return null;
}

class OpinionTarjeta {
  final PartidoCaptura pc;
  final List<(PataCaptura, double?)> patas;
  final double? p; // conjunta de la tarjeta
  final bool aprox;
  OpinionTarjeta(this.pc, this.patas, this.p, this.aprox);
}

/// Probabilidad conjunta de las patas de UN partido. Las líneas del mismo conteo (goles, córners, tarjetas,
/// tiros) se combinan exactas como intervalo (Más 0.5 + Menos 4.5 = entre 1 y 4 goles); entre conteos distintos se
/// multiplica (aproximación avisada, como en el combinador).
OpinionTarjeta opinarTarjeta(PartidoCaptura pc, List<PataCaptura> patas) {
  final lista = [for (final p in patas) (p, probPata(p, pc))];
  if (lista.any((x) => x.$2 == null)) return OpinionTarjeta(pc, lista, null, false);
  final mer = pc.mercados;
  var p = 1.0, grupos = 0;
  final porConteo = <String, List<PataCaptura>>{};
  for (final x in patas) {
    if ((x.opcion == 'mas' || x.opcion == 'menos') && x.linea != null) {
      porConteo.putIfAbsent(x.mercado, () => []).add(x);
    } else {
      p *= probPata(x, pc)!;
      grupos++;
    }
  }
  for (final e in porConteo.entries) {
    double? lo, hi;
    for (final x in e.value) {
      if (x.opcion == 'mas') lo = lo == null ? x.linea : math.max(lo, x.linea!);
      if (x.opcion == 'menos') hi = hi == null ? x.linea : math.min(hi, x.linea!);
    }
    double? pi;
    final pLo = lo == null ? 1.0 : (mer[_clave(e.key, 'mas', lo)] as num?)?.toDouble();
    final pHi = hi == null ? 0.0 : (mer[_clave(e.key, 'mas', hi)] as num?)?.toDouble();
    if (pLo != null && pHi != null) pi = lo != null && hi != null && hi <= lo ? 0.0 : (pLo - pHi).clamp(0.0, 1.0).toDouble();
    p *= pi ?? e.value.map((x) => probPata(x, pc)!).reduce((a, b) => math.min(a, b));
    grupos++;
  }
  return OpinionTarjeta(pc, lista, p, grupos > 1);
}

class Analisis {
  final List<OpinionTarjeta> tarjetas;
  final double? pTotal, cuota;
  final String texto;
  Analisis(this.tarjetas, this.pTotal, this.cuota, this.texto);
}

Analisis analizar(LecturaCaptura r) {
  final ops = <OpinionTarjeta>[];
  for (var i = 0; i < r.partidos.length; i++) {
    final patas = r.patas.where((p) => p.partido == i).toList();
    if (patas.isNotEmpty) ops.add(opinarTarjeta(r.partidos[i], patas));
  }
  final cuotaCartas = ops.every((o) => o.pc.cuota != null) ? ops.fold<double>(1, (a, o) => a * o.pc.cuota!) : null;
  final cuota = r.cuotaTotal ?? cuotaCartas;
  final b = StringBuffer();
  if (ops.isEmpty) {
    return Analisis(ops, null, cuota, 'No reconocí selecciones en la imagen. Prueba con una captura más nítida del cupón '
        'o de «Mis apuestas», o ábrela en «Editar» para cargarlas a mano.');
  }
  final conProb = ops.where((o) => o.p != null).toList();
  final pTotal = conProb.length == ops.length ? ops.fold<double>(1, (a, o) => a * o.p!) : null;
  b.writeln('📋 Leí ${ops.length == 1 ? '1 partido' : '${ops.length} partidos'} con ${r.patas.length} selecciones'
      '${cuota != null ? ' · cuota ${f2(cuota)}' : ''}${r.monto != null ? ' · S/${f2(r.monto!)}' : ''}.');
  b.writeln();
  for (final o in ops) {
    final nom = o.pc.local.isEmpty && o.pc.visitante.isEmpty ? 'Partido sin nombre' : '${o.pc.local} vs ${o.pc.visitante}';
    b.write('⚽ $nom');
    if (o.pc.marcador != null) b.write(' (terminó ${o.pc.marcador})');
    if (o.pc.paquete == null) b.write(' — fuera de las ligas del bot');
    b.writeln();
    for (final x in o.patas) {
      final p = x.$2;
      b.writeln('   • ${x.$1.titulo} ${mercadosCaptura[x.$1.mercado] == null || x.$1.mercado == 'otro' ? x.$1.textoMercado : '· ${mercadosCaptura[x.$1.mercado]}'}'
          '${p != null ? ' → ${pct(p)}' : ' → sin dato'}');
    }
    if (o.p != null) {
      final c = o.pc.cuota;
      final valor = c == null ? '' : o.p! * c >= 1.03 ? ' ✅ paga más de lo justo' : o.p! * c < 0.92 ? ' ⚠️ paga poco' : ' ≈ justo';
      b.writeln('   = ${pct(o.p!)}${o.aprox ? ' (aprox.)' : ''} · cuota justa ${f2(1 / o.p!)}${c != null ? ' vs Betano ${f2(c)}$valor' : ''}');
    }
  }
  b.writeln();
  if (pTotal != null) {
    b.writeln('🎯 Probabilidad de acertar TODO: ${pct(pTotal)} → ${deCada10(pTotal)}.');
    if (cuota != null) {
      final ev = pTotal * cuota - 1;
      b.writeln(ev >= 0.03 ? '💰 La cuota ${f2(cuota)} paga más de lo que vale (justa ${f2(1 / pTotal)}): tiene valor.'
          : ev <= -0.08 ? '⚠️ La cuota ${f2(cuota)} paga menos de lo que vale (justa ${f2(1 / pTotal)}): a la larga pierde.'
          : '≈ La cuota ${f2(cuota)} está cerca de lo justo (${f2(1 / pTotal)}).');
    }
    final orden = [...conProb]..sort((a, b) => a.p!.compareTo(b.p!));
    if (orden.length > 1) {
      final debil = orden.first;
      final sin = pTotal / debil.p!;
      b.writeln('🔎 Lo más flojo: ${debil.pc.local} vs ${debil.pc.visitante} (${pct(debil.p!)}). '
          'Sin ese partido subirías a ${pct(sin)}${cuota != null && debil.pc.cuota != null ? ' con cuota ${f2(cuota / debil.pc.cuota!)}' : ''}.');
    }
    if (ops.length >= 6) {
      b.writeln('💡 Con ${ops.length} partidos, aunque cada uno sea muy probable, las probabilidades se multiplican. '
          'Combinadas más cortas fallan menos.');
    }
  } else {
    b.writeln('Algunas selecciones no las calcula el bot (otra liga o mercado): no puedo dar la probabilidad total. '
        'Igual las sigo en vivo si las guardas.');
  }
  return Analisis(ops, pTotal, cuota, b.toString().trim());
}
