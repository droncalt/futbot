// Chat de FútBot en el celular: le pides fijas con tus palabras ("3 fijas para hoy a cuota 2 con 80%",
// "solo córners del Barcelona con 20 soles") y arma la combinada con las probabilidades del bot.
// Funciona sin internet y sin gastar tokens: entiende frases en español con reglas y busca la mejor combinación
// (máxima probabilidad que llegue a la cuota pedida) con programación dinámica.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'captura.dart';
import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';
import 'vivo.dart';

// ---------------------------------------------------------------- lo que pide el usuario
class Pedido {
  String? nivel, dia;
  double? cuota, pMin, monto;
  int? n;
  final familias = <String>{}; // goles, corners, tarjetas, jugadores, resultado
  final sinFamilias = <String>{};
  final equipos = <String>{}, ligas = <String>{};
  bool get vacio => nivel == null && cuota == null && pMin == null && n == null && familias.isEmpty && equipos.isEmpty && ligas.isEmpty && dia == null;
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
  if (m == 'jug_arco') return 'jugadores';
  if (m == '1x2' || m == 'doble' || m == '1t_1x2') return 'resultado';
  return 'goles';
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
        final o = Opcion(l, e.key, e.value.p, e.value.cuota, e.value.estimada);
        final fams = o.patas.map(familiaDe).toSet();
        if (fams.any(q.sinFamilias.contains)) continue;
        if (q.familias.isNotEmpty && !fams.every(q.familias.contains)) continue;
        if (o.cuota < 1.04) continue;
        final k = '${o.clavePartido}|${o.patas.map((x) => x.titulo).join('+')}';
        if (!out.containsKey(k) || out[k]!.p < o.p) out[k] = o;
      }
    }
  }
  return out.values.toList();
}

/// Máxima probabilidad conjunta que llega a la cuota [objetivo] con a lo sumo [maxN] partidos (uno por partido).
List<Opcion>? mejorParaCuota(List<Opcion> ops, double objetivo, int maxN, {int? exacto}) {
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
    if (exacto != null && k != exacto) continue;
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
  final double monto;
  Mensaje(this.mio, this.texto, {this.boleta, this.monto = 10});
}

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
    return Mensaje(false, _analizar(q.equipos));
  }
  if (q.vacio && !RegExp(r'fija|combinada|boleta|apuesta|parley|pick').hasMatch(t)) {
    return Mensaje(false, 'No te entendí del todo 🤔. Prueba «3 fijas para hoy», «cuota 2 con 80%» o escribe «ayuda».');
  }
  return _armar(q);
}

Mensaje _armar(Pedido q) {
  final ops = opciones(q);
  final monto = q.monto ?? 10;
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
    sel = mejorParaCuota(ops, q.cuota!, math.min(q.n ?? 10, 10), exacto: q.n);
    if (sel == null) {
      final todo = mejoresN(ops, 10, 1.0);
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
  b.write('Cuota ≈${f2(c)} · prob. de acertar todo ${pct(p)} · de cada 10 así, ≈${(p * 10).round()} se ganan.');
  for (final x in notas) {
    b.write('\n$x');
  }
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
        '${m['goles_esperados'] != null ? 'Goles esperados: ${m['goles_esperados']}\n' : ''}\n');
  }
  if (b.isEmpty) return 'Ese equipo no juega en los próximos días en las ligas que analiza el bot.';
  b.write('Pídeme «fijas del ${equipos.first}» para armar una combinada con él.');
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
        '«solo córners de la Premier», «fijas del Barcelona con 20 soles»… Escribe «ayuda» para más ideas.'),
  ];
  final ctrl = TextEditingController();
  final scroll = ScrollController();

  static const sugerencias = ['3 fijas para hoy', 'cuota 2 con 80%', 'ultra segura de mañana', 'cuota 5 equilibrada',
    'solo goles, 4 partidos', '¿el bot acierta?', 'cómo voy'];

  Future<void> _enviar(String texto) async {
    if (texto.trim().isEmpty) return;
    ctrl.clear();
    setState(() => mensajes.add(Mensaje(true, texto)));
    final r = await responder(texto);
    setState(() => mensajes.add(r));
    await Future.delayed(const Duration(milliseconds: 50));
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
          IconButton(tooltip: 'Subir captura', icon: const Icon(Icons.add_a_photo_outlined),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => Scaffold(
                  appBar: AppBar(backgroundColor: Col.panel, title: const Text('Capturas')), body: const PantallaCapturas())))),
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
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * (m.boleta != null ? 0.95 : 0.85)),
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: m.mio ? Col.naranjaOsc.withValues(alpha: 0.85) : Col.tarjeta,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SelectableText(m.texto),
            if (m.boleta != null) BoletaChat(opciones: m.boleta!, montoInicial: m.monto),
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

  Future<void> _guardar(String tipo) async {
    await Historial.guardar({
      'id': DateTime.now().millisecondsSinceEpoch, 'fecha': DateTime.now().toIso8601String(), 'tipo': tipo, 'origen': 'chat',
      'monto': tipo == 'apostada' ? monto : 0, 'cuota': _prod(activas.map((o) => o.cuota)), 'p': _prod(activas.map((o) => o.p)),
      'estado': 'pendiente',
      'lineas': [
        for (final o in activas)
          {'liga': o.linea.liga, 'inicio': o.linea.inicio.toIso8601String(), 'local': o.linea.local.nombre,
            'visitante': o.linea.visitante.nombre, 'cuota': o.cuota, 'p': o.p,
            'patas': [for (final p in o.patas) {'titulo': p.titulo, 'mercado': p.mercado, 'sel': p.sel, 'p': p.p}]},
      ],
    });
    setState(() => guardada = true);
  }

  @override
  Widget build(BuildContext context) {
    final c = _prod(activas.map((o) => o.cuota)), p = _prod(activas.map((o) => o.p));
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
        FilledButton.icon(onPressed: guardada || activas.isEmpty ? null : () => _guardar('apostada'),
            icon: const Icon(Icons.check), label: Text(guardada ? 'Guardada' : 'La aposté')),
        OutlinedButton.icon(onPressed: guardada || activas.isEmpty ? null : () => _guardar('seguimiento'),
            icon: const Icon(Icons.visibility), label: const Text('Seguir')),
        IconButton.filledTonal(tooltip: 'Copiar', icon: const Icon(Icons.copy), onPressed: () {
          Clipboard.setData(ClipboardData(text: _texto()));
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copiada: pégala o arma la boleta en Betano.')));
        }),
        IconButton.filledTonal(tooltip: 'Abrir Betano', icon: const Icon(Icons.open_in_new),
            onPressed: () => abrir(activas.isEmpty ? 'https://www.betano.pe/sport/futbol/' : activas.first.linea.betano)),
      ]),
      if (guardada) const Text('✅ En tu historial y en «En vivo»: la sigo minuto a minuto.', style: TextStyle(color: Color(0xFF34D399))),
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
