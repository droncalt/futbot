// Historial guardado en el celular: se liquida solo con los resultados que trae el paquete diario.
import 'dart:convert';

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'comunes.dart';
import 'datos.dart';
import 'vivo.dart';

class Historial {
  static const _k = 'boletas';

  static Future<List<Map<String, dynamic>>> cargar() async {
    final t = (await SharedPreferences.getInstance()).getString(_k);
    if (t == null) return [];
    return (jsonDecode(t) as List).map((e) => Map<String, dynamic>.from(e)).toList();
  }

  static Future<void> _guardarTodo(List<Map<String, dynamic>> b) async {
    await (await SharedPreferences.getInstance()).setString(_k, jsonEncode(b));
    await exportarAprendizaje();
  }

  /// Copia para la PC: actualizar_celular.bat la trae por USB y el bot aprende de tus patas y capturas.
  static Future<void> exportarAprendizaje() async {
    try {
      final pref = await SharedPreferences.getInstance();
      final dir = await getExternalStorageDirectory();
      if (dir == null) return;
      final datos = {
        'exportado': DateTime.now().toIso8601String(),
        'boletas': jsonDecode(pref.getString(_k) ?? '[]'),
        'lineas_betano': jsonDecode(pref.getString('lineas_betano') ?? '{}'),
      };
      await File('${dir.path}/futbot_aprendizaje.json').writeAsString(jsonEncode(datos));
    } catch (_) {}
  }

  /// Liquida con los datos de ESPN (incluye córners, tarjetas y tiros de jugadores) y anota cada pata.
  static Future<int> liquidarEnVivo(Map<String, Estado?> estados) async {
    final b = await cargar();
    var cambios = 0, anotadas = 0;
    for (final bol in b.where((x) => x['estado'] == 'pendiente')) {
      var perdio = false, todas = true;
      for (final l in (bol['lineas'] as List)) {
        final e = estados['${l['local']}|${l['visitante']}|${l['inicio']}'];
        for (final p in (l['patas'] as List)) {
          if (e == null) {
            todas = false;
            continue;
          }
          final a = evaluar(Map<String, dynamic>.from(p['sel'] ?? {}), pPrevia(Map<String, dynamic>.from(p)), e);
          if (a.estado == 'ganada' || a.estado == 'perdida') {
            if (p['resultado'] != a.estado) {
              p['resultado'] = a.estado;
              p['fuente_resultado'] = 'espn';
              anotadas++;
            }
            if (a.estado == 'perdida') perdio = true;
          } else {
            todas = false;
          }
        }
      }
      if (perdio) {
        bol['estado'] = 'perdida';
        bol['retorno'] = 0.0;
        cambios++;
      } else if (todas) {
        bol['estado'] = 'ganada';
        bol['retorno'] = (bol['monto'] as num) * (bol['cuota'] as num);
        cambios++;
      }
    }
    if (cambios > 0 || anotadas > 0) await _guardarTodo(b);
    return cambios;
  }

  /// Acierto real por tipo de mercado vs lo que prometía el bot (patas ya resueltas).
  static Map<String, List<double>> porMercado(List<Map<String, dynamic>> b) {
    final out = <String, List<double>>{}; // mercado → [aciertos, total, suma prob]
    for (final bol in b) {
      for (final l in (bol['lineas'] as List)) {
        for (final p in (l['patas'] as List)) {
          final r = p['resultado'];
          if (r != 'ganada' && r != 'perdida') continue;
          final m = '${p['sel']?['mercado'] ?? p['mercado']}';
          final v = out.putIfAbsent(m, () => [0, 0, 0]);
          v[0] += r == 'ganada' ? 1 : 0;
          v[1] += 1;
          v[2] += pPrevia(Map<String, dynamic>.from(p));
        }
      }
    }
    return out;
  }

  static Future<void> guardar(Map<String, dynamic> boleta) async {
    final b = await cargar();
    b.insert(0, boleta);
    await _guardarTodo(b);
  }

  static Future<void> borrar(int id) async {
    final b = await cargar();
    b.removeWhere((x) => x['id'] == id);
    await _guardarTodo(b);
  }

  static Future<void> marcar(int id, String estado, double retorno) async {
    final b = await cargar();
    for (final x in b) {
      if (x['id'] == id) {
        x['estado'] = estado;
        x['retorno'] = retorno;
      }
    }
    await _guardarTodo(b);
  }

  /// ¿Se cumplió la selección con este resultado? null = no se puede saber (p. ej. jugadores).
  static bool? cumple(Map<String, dynamic> s, Map<String, dynamic> r) {
    int? n(String c) => r[c] as int?;
    final m = s['mercado'] as String? ?? '';
    final o = s['opcion'] as String? ?? '';
    final linea = (s['linea'] as num?)?.toDouble() ?? 0;
    final h = n('gl'), a = n('gv');
    if (h == null || a == null) return null;
    bool mas(num v) => o == 'mas' ? v > linea : v < linea;
    switch (m) {
      case '1x2':
        return o == 'local' ? h > a : o == 'visitante' ? h < a : h == a;
      case 'doble':
        return o == '1X' ? h >= a : o == 'X2' ? h <= a : h != a;
      case 'goles':
        return mas(h + a);
      case 'btts':
        return o == 'si' ? (h > 0 && a > 0) : !(h > 0 && a > 0);
      case 'btts_o25':
        final b = (h > 0 && a > 0) || h + a > 2.5;
        return o == 'si' ? b : !b;
      case 'goles_local':
        return mas(h);
      case 'goles_visitante':
        return mas(a);
      case '1t_1x2':
      case '1t_goles':
      case '2t_goles':
        final h1 = n('ht_gl'), a1 = n('ht_gv');
        if (h1 == null || a1 == null) return null;
        if (m == '1t_1x2') return o == 'local' ? h1 > a1 : o == 'visitante' ? h1 < a1 : h1 == a1;
        if (m == '1t_goles') return mas(h1 + a1);
        return mas(h - h1 + a - a1);
      case 'corners':
      case 'corners_local':
      case 'corners_visitante':
        final cl = n('corn_l'), cv = n('corn_v');
        if (cl == null || cv == null) return null;
        return mas(m == 'corners' ? cl + cv : m == 'corners_local' ? cl : cv);
      case 'tarjetas':
        final yl = n('ama_l'), yv = n('ama_v');
        if (yl == null || yv == null) return null;
        return mas(yl + yv + 2 * ((n('roj_l') ?? 0) + (n('roj_v') ?? 0)));
    }
    return null; // tiros al arco de jugadores: se marca a mano
  }

  /// Liquida las boletas pendientes con los resultados del paquete. Devuelve cuántas cambiaron.
  static Future<int> liquidar(List<Map<String, dynamic>> resultados) async {
    final b = await cargar();
    var cambios = 0;
    for (final bol in b.where((x) => x['estado'] == 'pendiente')) {
      var perdio = false, todas = true;
      for (final l in (bol['lineas'] as List)) {
        final ini = DateTime.parse(l['inicio']);
        final r = resultados.where((x) => x['local'] == l['local'] && x['visitante'] == l['visitante'] &&
            DateTime.parse(x['fecha']).difference(DateTime(ini.year, ini.month, ini.day)).inDays.abs() <= 2).firstOrNull;
        if (r == null) { todas = false; continue; }
        for (final p in (l['patas'] as List)) {
          final ok = p['resultado'] == 'ganada' ? true : p['resultado'] == 'perdida' ? false
              : cumple(Map<String, dynamic>.from(p['sel']), r);
          if (ok != null && p['resultado'] == null) p['resultado'] = ok ? 'ganada' : 'perdida';
          if (ok == false) perdio = true;
          if (ok == null) todas = false;
        }
      }
      if (perdio) {
        bol['estado'] = 'perdida';
        bol['retorno'] = 0.0;
        cambios++;
      } else if (todas) {
        bol['estado'] = 'ganada';
        bol['retorno'] = (bol['monto'] as num) * (bol['cuota'] as num);
        cambios++;
      }
    }
    if (cambios > 0) await _guardarTodo(b);
    return cambios;
  }
}

class PantallaHistorial extends StatefulWidget {
  const PantallaHistorial({super.key});
  @override
  State<PantallaHistorial> createState() => _PantallaHistorialState();
}

class _PantallaHistorialState extends State<PantallaHistorial> {
  List<Map<String, dynamic>> boletas = [];

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    await Historial.liquidar(repo.resultados);
    final b = await Historial.cargar();
    if (mounted) setState(() => boletas = b);
  }

  @override
  Widget build(BuildContext context) {
    final cerradas = boletas.where((b) => b['tipo'] == 'apostada' && b['estado'] != 'pendiente').toList();
    final apostado = cerradas.fold<double>(0, (s, b) => s + (b['monto'] as num).toDouble());
    final retorno = cerradas.fold<double>(0, (s, b) => s + ((b['retorno'] ?? 0) as num).toDouble());
    final neto = retorno - apostado;
    final todas = boletas.where((b) => b['estado'] == 'ganada' || b['estado'] == 'perdida').toList();
    final ganadas = todas.where((b) => b['estado'] == 'ganada').length;
    final esperado = todas.isEmpty ? 0.0 : todas.fold<double>(0, (s, b) => s + (b['p'] as num).toDouble()) / todas.length;
    return RefreshIndicator(
      onRefresh: _cargar,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Text('Mi historial', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          _dato('Apostado', 'S/${f2(apostado)}'),
          _dato('Neto', '${neto >= 0 ? '+' : ''}S/${f2(neto)}', color: neto >= 0 ? const Color(0xFF34D399) : Col.rosa),
          _dato('ROI', apostado > 0 ? '${(neto / apostado * 100).toStringAsFixed(1)}%' : '—'),
          _dato('Acierto real', todas.isEmpty ? '—' : '$ganadas/${todas.length}'),
          _dato('Lo que esperaba el bot', todas.isEmpty ? '—' : pct(esperado)),
        ]),
        const SizedBox(height: 10),
        ..._porMercado(),
        if (boletas.isEmpty)
          const Text('Aún no guardaste boletas. En la Súper boleta pulsa «La aposté» o 👁️ (seguimiento).',
              style: TextStyle(color: Col.suave)),
        for (final b in boletas) _tarjeta(b),
      ]),
    );
  }

  List<Widget> _porMercado() {
    final m = Historial.porMercado(boletas);
    if (m.isEmpty) return [];
    final filas = m.entries.toList()..sort((a, b) => b.value[1].compareTo(a.value[1]));
    return [
      const Text('Aprendizaje por mercado (tus patas resueltas)', style: TextStyle(fontWeight: FontWeight.w800)),
      const Text('Real = cuántas acertaron · Bot = lo que prometía. Si «Real» queda muy por debajo con muchas patas, '
          'ese mercado está sobrevalorado.', style: TextStyle(color: Col.suave, fontSize: 12)),
      for (final e in filas)
        ListTile(
          dense: true,
          title: Text(e.key),
          subtitle: Text('${e.value[0].toInt()}/${e.value[1].toInt()} acertadas'),
          trailing: Text('Real ${pct(e.value[0] / e.value[1])} · Bot ${pct(e.value[2] / e.value[1])}',
              style: TextStyle(fontWeight: FontWeight.w800,
                  color: e.value[0] / e.value[1] + 0.05 < e.value[2] / e.value[1] ? Col.rosa : const Color(0xFF34D399))),
        ),
      const SizedBox(height: 8),
    ];
  }

  Widget _dato(String t, String v, {Color? color}) => Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: Col.tarjeta, borderRadius: BorderRadius.circular(12), border: Border.all(color: Col.borde)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: const TextStyle(color: Col.suave, fontSize: 12)),
          Text(v, style: TextStyle(fontWeight: FontWeight.w900, fontSize: 18, color: color)),
        ]),
      );

  Widget _tarjeta(Map<String, dynamic> b) {
    final estado = b['estado'] as String;
    final color = estado == 'ganada' ? const Color(0xFF34D399) : estado == 'perdida' ? Col.rosa : Col.suave;
    final fecha = DateTime.parse(b['fecha']);
    return Card(
      color: Col.tarjeta,
      child: ExpansionTile(
        title: Text('${(b['lineas'] as List).length} línea(s) · cuota ${f2((b['cuota'] as num).toDouble())}'
            '${b['tipo'] == 'apostada' ? ' · S/${f2((b['monto'] as num).toDouble())}' : ' · seguimiento'}'),
        subtitle: Text('${diaHora(fecha)} · ${estado.toUpperCase()} · prob. ${pct((b['p'] as num).toDouble())}',
            style: TextStyle(color: color, fontWeight: FontWeight.w700)),
        children: [
          for (final l in (b['lineas'] as List))
            ListTile(dense: true, title: Text('${l['local']} vs ${l['visitante']}'),
                subtitle: Text((l['patas'] as List).map((p) => '${p['resultado'] == 'ganada' ? '✅ ' : p['resultado'] == 'perdida' ? '❌ ' : ''}'
                    '${p['titulo']} (${p['mercado']})').join(' + ')),
                trailing: Text(f2((l['cuota'] as num).toDouble()))),
          OverflowBar(alignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: () async { await Historial.marcar(b['id'], 'ganada', ((b['monto'] as num) * (b['cuota'] as num)).toDouble()); _cargar(); },
                child: const Text('Marcar ganada')),
            TextButton(onPressed: () async { await Historial.marcar(b['id'], 'perdida', 0); _cargar(); }, child: const Text('Marcar perdida')),
            TextButton(onPressed: () async { await Historial.borrar(b['id']); _cargar(); }, child: const Text('Borrar')),
          ]),
        ],
      ),
    );
  }
}
