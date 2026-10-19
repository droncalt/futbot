// Capturas: lee tus combinadas de Betano (u otras) con reconocimiento de texto EN el celular (Google ML Kit,
// sin internet ni tokens), las compara con el bot, las guarda para seguirlas en vivo y aprende qué líneas
// ofrece Betano (p. ej. Mbappé tiros al arco solo desde 2+).
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';
import 'vivo.dart';

const mercadosCaptura = {
  '1x2': 'Resultado final', 'doble': 'Doble oportunidad', 'goles': 'Goles Más/Menos', 'goles_local': 'Goles local',
  'goles_visitante': 'Goles visitante', 'btts': 'Ambos anotan', '1t_goles': 'Goles 1.er tiempo',
  '2t_goles': 'Goles 2.º tiempo', '1t_1x2': 'Resultado 1.er tiempo', 'corners': 'Córners Más/Menos',
  'corners_local': 'Córners local', 'corners_visitante': 'Córners visitante', 'tarjetas': 'Tarjetas Más/Menos',
  'jug_arco': 'Jugador tiros al arco', 'otro': 'Otro (seguimiento manual)',
};

class PataCaptura {
  String mercado, opcion, jugador;
  double? linea, cuota;
  int partido; // índice en la lista de partidos detectados
  PataCaptura(this.mercado, this.opcion, {this.linea, this.cuota, this.jugador = '', this.partido = 0});

  Map<String, dynamic> sel(String local, String visitante) => {
        'mercado': mercado, 'opcion': opcion, 'linea': linea, 'jugador_nombre': jugador.isEmpty ? null : jugador,
      };

  String get titulo {
    if (mercado == 'jug_arco') return '$jugador $opcion';
    if (opcion == 'mas' || opcion == 'menos') return '${opcion == 'mas' ? 'Más' : 'Menos'} de ${linea ?? ''}';
    return opcion;
  }
}

class PartidoCaptura {
  String local, visitante;
  PartidoCaptura(this.local, this.visitante);
}

class LecturaCaptura {
  final partidos = <PartidoCaptura>[];
  final patas = <PataCaptura>[];
  double? monto, cuotaTotal;
  DateTime? inicio;
  final lineasVistas = <String, Set<int>>{}; // jugador → líneas k+ que aparecen en la imagen
  String texto = '';
}

// ---------------------------------------------------------------- lectura del texto
final _num = RegExp(r'(\d{1,3}[.,]\d{1,2})');
final _partido = RegExp(r'^(.{3,40}?)\s+(?:-|–|—|vs\.?|v\.?)\s+(.{3,40})$', caseSensitive: false);
final _masMenos = RegExp(r'\b(m[aá]s|menos|over|under)\s*(?:de)?\s*(\d{1,2}[.,]5)', caseSensitive: false);
final _kMas = RegExp(r'(\d)\s*\+');

double? _n(String s) => double.tryParse(s.replaceAll(',', '.'));

LecturaCaptura leerTexto(List<String> lineas) {
  final r = LecturaCaptura()..texto = lineas.join('\n');
  String ctx = '';
  for (var i = 0; i < lineas.length; i++) {
    final t = lineas[i].trim();
    if (t.isEmpty) continue;
    final low = normal(t);
    // monto, cuota total y fecha
    if (RegExp(r'importe|apuesta total|monto|stake', caseSensitive: false).hasMatch(t)) {
      final m = _num.allMatches(t).map((x) => _n(x.group(1)!)).whereType<double>().toList();
      final sig = i + 1 < lineas.length ? _num.firstMatch(lineas[i + 1]) : null;
      r.monto ??= m.isNotEmpty ? m.last : (sig != null ? _n(sig.group(1)!) : null);
      continue;
    }
    if (RegExp(r'cuota(s)? total|cuota combinada|cuotas totales', caseSensitive: false).hasMatch(t)) {
      final m = _num.firstMatch(t) ?? (i + 1 < lineas.length ? _num.firstMatch(lineas[i + 1]) : null);
      if (m != null) r.cuotaTotal = _n(m.group(1)!);
      continue;
    }
    if (RegExp(r'ganancia|pago potencial|retorno', caseSensitive: false).hasMatch(t)) continue;
    final hora = RegExp(r'(\d{1,2}):(\d{2})').firstMatch(t);
    final fecha = RegExp(r'(\d{1,2})/(\d{1,2})').firstMatch(t);
    if (hora != null && r.inicio == null && !_masMenos.hasMatch(t)) {
      final ahora = DateTime.now();
      var d = DateTime(ahora.year, ahora.month, ahora.day);
      if (fecha != null) d = DateTime(ahora.year, int.parse(fecha.group(2)!), int.parse(fecha.group(1)!));
      if (low.contains('manana')) d = d.add(const Duration(days: 1));
      r.inicio = DateTime(d.year, d.month, d.day, int.parse(hora.group(1)!), int.parse(hora.group(2)!));
    }
    // partido "A - B"
    final pm = _partido.firstMatch(t);
    if (pm != null && !_masMenos.hasMatch(t) && !RegExp(r'\d+[.,]\d').hasMatch(t) &&
        RegExp('[a-zA-Z]{3}').hasMatch(pm.group(1)!) && RegExp('[a-zA-Z]{3}').hasMatch(pm.group(2)!)) {
      r.partidos.add(PartidoCaptura(pm.group(1)!.trim(), pm.group(2)!.trim()));
      ctx = '';
      continue;
    }
    final idx = r.partidos.isEmpty ? 0 : r.partidos.length - 1;
    final cuota = () {
      final ms = _num.allMatches(t).map((x) => _n(x.group(1)!)).whereType<double>()
          .where((x) => x >= 1.01 && x <= 500 && x != _n(_masMenos.firstMatch(t)?.group(2) ?? 'x')).toList();
      if (ms.isNotEmpty) return ms.last;
      if (i + 1 < lineas.length && RegExp(r'^\s*\d{1,3}[.,]\d{2}\s*$').hasMatch(lineas[i + 1])) return _n(lineas[i + 1].trim());
      return null;
    }();
    // tiros al arco de jugador: "Kylian Mbappé 2+" o el mercado en el contexto
    final km = _kMas.firstMatch(t);
    final tiros = RegExp(r'tiros? (a puerta|al arco)|remates? (a puerta|al arco)|shots on target').hasMatch('$low ${normal(ctx)}');
    if (km != null && (tiros || RegExp(r"^[A-ZÁÉÍÓÚÑ][\w\s.'-]+\d\s*\+").hasMatch(t))) {
      var nombre = t.substring(0, km.start).replaceAll(RegExp(r'tiros?.*$', caseSensitive: false), '').trim();
      if (nombre.length < 3) nombre = ctx.replaceAll(RegExp(r'tiros?.*$', caseSensitive: false), '').trim();
      final k = int.parse(km.group(1)!);
      if (nombre.length >= 3) {
        r.lineasVistas.putIfAbsent(nombre, () => {}).add(k);
        r.patas.add(PataCaptura('jug_arco', '$k+', linea: k - 0.5, cuota: cuota, jugador: nombre, partido: idx));
      }
      continue;
    }
    // más / menos
    final mm = _masMenos.firstMatch(t);
    if (mm != null) {
      final todo = normal('$ctx $t');
      final mas = RegExp(r'm[aá]s|over', caseSensitive: false).hasMatch(mm.group(1)!);
      var mercado = 'goles';
      final p = r.partidos.isNotEmpty ? r.partidos[idx] : null;
      bool deEquipo(String eq) => eq.isNotEmpty && todo.contains(normal(eq).split(' ').first);
      if (RegExp(r'corner|esquina').hasMatch(todo)) {
        mercado = p != null && deEquipo(p.local) ? 'corners_local' : p != null && deEquipo(p.visitante) ? 'corners_visitante' : 'corners';
      } else if (todo.contains('tarjeta')) {
        mercado = 'tarjetas';
      } else if (RegExp(r'1er tiempo|primer tiempo|1 tiempo|1a mitad|primera mitad|1 parte').hasMatch(todo)) {
        mercado = '1t_goles';
      } else if (RegExp(r'2do tiempo|segundo tiempo|2 tiempo|segunda mitad|2 parte').hasMatch(todo)) {
        mercado = '2t_goles';
      } else if (p != null && deEquipo(p.local) && !deEquipo(p.visitante)) {
        mercado = 'goles_local';
      } else if (p != null && deEquipo(p.visitante) && !deEquipo(p.local)) {
        mercado = 'goles_visitante';
      }
      r.patas.add(PataCaptura(mercado, mas ? 'mas' : 'menos', linea: _n(mm.group(2)!), cuota: cuota, partido: idx));
      continue;
    }
    // ambos anotan
    if (RegExp(r'ambos equipos (marcan|anotan)|ambos anotan|btts').hasMatch('$low ${normal(ctx)}') &&
        RegExp(r'\b(si|no)\b').hasMatch(low)) {
      r.patas.add(PataCaptura('btts', RegExp(r'\bno\b').hasMatch(low) ? 'no' : 'si', cuota: cuota, partido: idx));
      continue;
    }
    // doble oportunidad / resultado final
    if (r.partidos.isNotEmpty && cuota != null) {
      final p = r.partidos[idx];
      final esL = parecido(t, p.local) > 0.5 || low.contains(normal(p.local).split(' ').first);
      final esV = parecido(t, p.visitante) > 0.5 || low.contains(normal(p.visitante).split(' ').first);
      final empate = low.contains('empate');
      final doble = low.contains(' o ') || normal(ctx).contains('doble') || RegExp(r'\b(1x|x2|12)\b').hasMatch(low);
      String? m, o;
      if (doble && (esL || esV || empate)) {
        m = 'doble';
        o = esL && esV ? '12' : esL ? '1X' : 'X2';
      } else if (RegExp(r'\b1x\b').hasMatch(low)) {
        m = 'doble';
        o = '1X';
      } else if (RegExp(r'\bx2\b').hasMatch(low)) {
        m = 'doble';
        o = 'X2';
      } else if (esL || esV || empate) {
        m = normal(ctx).contains('1er tiempo') || normal(ctx).contains('primer tiempo') ? '1t_1x2' : '1x2';
        o = empate ? 'empate' : esL ? 'local' : 'visitante';
      }
      if (m != null) {
        r.patas.add(PataCaptura(m, o!, cuota: cuota, partido: idx));
        continue;
      }
    }
    if (cuota == null) ctx = t; // títulos de mercado ("Más/Menos Córners", "Tiros a puerta"...) dan contexto
  }
  return r;
}

Future<LecturaCaptura?> leerImagen(String ruta) async {
  final rec = TextRecognizer(script: TextRecognitionScript.latin);
  try {
    final res = await rec.processImage(InputImage.fromFilePath(ruta));
    final lineas = <TextLine>[for (final b in res.blocks) ...b.lines];
    lineas.sort((a, b) {
      final dy = a.boundingBox.top - b.boundingBox.top;
      return dy.abs() < 12 ? a.boundingBox.left.compareTo(b.boundingBox.left) : dy.sign.toInt();
    });
    // une en un renglón lo que está a la misma altura (nombre del mercado + cuota a la derecha)
    final renglones = <String>[];
    double? y;
    for (final l in lineas) {
      if (y != null && (l.boundingBox.top - y).abs() < 12 && renglones.isNotEmpty) {
        renglones[renglones.length - 1] = '${renglones.last}  ${l.text}';
      } else {
        renglones.add(l.text);
        y = l.boundingBox.top;
      }
    }
    return leerTexto(renglones);
  } finally {
    rec.close();
  }
}

// ---------------------------------------------------------------- líneas que ofrece Betano (aprendidas)
class LineasBetano {
  static const _k = 'lineas_betano';

  static Future<Map<String, dynamic>> cargar() async {
    final t = (await SharedPreferences.getInstance()).getString(_k);
    return t == null ? {} : Map<String, dynamic>.from(jsonDecode(t));
  }

  /// Si una imagen muestra 2 o más líneas del mismo jugador (lista de mercado), la menor es la mínima que ofrece.
  static Future<List<String>> aprender(Map<String, Set<int>> vistas) async {
    final cat = await cargar();
    final jug = Map<String, dynamic>.from(cat['jug_arco'] ?? {});
    final aprendidas = <String>[];
    vistas.forEach((nombre, ks) {
      final n = normal(nombre);
      final prev = Map<String, dynamic>.from(jug[n] ?? {});
      final todas = {...((prev['lineas'] as List?) ?? []).map((e) => (e as num).toInt()), ...ks}.toList()..sort();
      prev['lineas'] = todas;
      prev['visto'] = DateTime.now().toIso8601String().substring(0, 10);
      if (ks.length >= 2) {
        prev['min'] = ks.reduce((a, b) => a < b ? a : b);
        aprendidas.add('$nombre: Betano ofrece tiros al arco desde ${prev['min']}+');
      }
      jug[n] = prev;
    });
    cat['jug_arco'] = jug;
    await (await SharedPreferences.getInstance()).setString(_k, jsonEncode(cat));
    await Historial.exportarAprendizaje();
    return aprendidas;
  }

  /// Línea mínima que Betano ofrece para el jugador (aprendida en el celular), o null si no se sabe.
  static int? minimo(Map<String, dynamic> cat, String jugador) {
    final jug = Map<String, dynamic>.from(cat['jug_arco'] ?? {});
    for (final e in jug.entries) {
      if (parecido(e.key, jugador) >= 0.6 && e.value['min'] != null) return (e.value['min'] as num).toInt();
    }
    return null;
  }
}

// ---------------------------------------------------------------- opinión del bot sobre una pata leída
class Opinion {
  final double? p;
  final String texto;
  Opinion(this.p, this.texto);
}

Opinion opinar(PataCaptura pa, PartidoCaptura? pc) {
  if (pc == null) return Opinion(null, 'Sin partido reconocido');
  // 1) misma pata en las súper boletas del bot
  for (final nivel in ['ultra', 'segura', 'equilibrada']) {
    for (final l in repo.lineas(nivel)) {
      if (parecido(l.local.nombre, pc.local) < 0.6 || parecido(l.visitante.nombre, pc.visitante) < 0.6) continue;
      for (final p in l.patas) {
        final s = p.sel;
        if (s['mercado'] == pa.mercado && '${s['opcion']}' == pa.opcion &&
            (pa.linea == null || (s['linea'] as num?)?.toDouble() == pa.linea)) {
          return _conCuota(p.p, pa.cuota);
        }
        if (pa.mercado == 'jug_arco' && s['mercado'] == 'jug_arco' && parecido('${s['jugador_nombre']}', pa.jugador) > 0.6) {
          final alt = (p.alternativas[pa.opcion]);
          if (alt != null) return _conCuota(alt, pa.cuota);
        }
      }
    }
  }
  // 2) probabilidades del partido que trae el paquete
  for (final m in repo.partidos) {
    if (parecido('${m['local']?['nombre']}', pc.local) < 0.6 || parecido('${m['visitante']?['nombre']}', pc.visitante) < 0.6) continue;
    final pr = Map<String, dynamic>.from(m['prob'] ?? {});
    String? clave;
    if (pa.mercado == '1x2') clave = pa.opcion == 'local' ? '1' : pa.opcion == 'visitante' ? '2' : 'X';
    if (pa.mercado == 'doble') clave = pa.opcion;
    if (pa.mercado == 'goles' && pa.opcion == 'mas' && pa.linea != null) clave = 'Más ${pa.linea}';
    if (pa.mercado == 'goles' && pa.opcion == 'menos' && pa.linea != null) clave = 'Menos ${pa.linea}';
    if (pa.mercado == 'btts' && pa.opcion == 'si') clave = 'Ambos anotan';
    final p = clave == null ? null : (pr[clave] as num?)?.toDouble();
    if (p != null) return _conCuota(p, pa.cuota);
    return Opinion(null, 'El bot no calcula este mercado para este partido');
  }
  return Opinion(null, 'Partido fuera de las ligas que analiza el bot (igual se sigue en vivo)');
}

Opinion _conCuota(double p, double? cuota) {
  if (cuota == null) return Opinion(p, 'Bot: ${pct(p)} (cuota justa ${f2(1 / p)})');
  final ev = p * cuota - 1;
  final juicio = ev > 0.03 ? '✅ paga más de lo justo' : ev < -0.08 ? '⚠️ paga poco para su riesgo' : '≈ precio justo';
  return Opinion(p, 'Bot: ${pct(p)} · justa ${f2(1 / p)} vs Betano ${f2(cuota)} → $juicio');
}

// ---------------------------------------------------------------- pantalla
class PantallaCapturas extends StatefulWidget {
  const PantallaCapturas({super.key});
  @override
  State<PantallaCapturas> createState() => _PantallaCapturasState();
}

class _PantallaCapturasState extends State<PantallaCapturas> {
  LecturaCaptura? lectura;
  bool leyendo = false;
  String? mensaje;
  bool verTexto = false;
  final montoCtrl = TextEditingController();
  final cuotaCtrl = TextEditingController();
  bool mia = true; // false = me la mandaron (tipster, grupo de Telegram…)
  final autorCtrl = TextEditingController();

  Future<void> _elegir(ImageSource origen) async {
    final img = await ImagePicker().pickImage(source: origen, imageQuality: 95);
    if (img == null) return;
    setState(() {
      leyendo = true;
      mensaje = null;
    });
    try {
      final r = await leerImagen(img.path);
      final aprendidas = r == null ? <String>[] : await LineasBetano.aprender(r.lineasVistas);
      setState(() {
        lectura = r;
        montoCtrl.text = r?.monto == null ? '' : f2(r!.monto!);
        cuotaCtrl.text = r?.cuotaTotal == null ? '' : f2(r!.cuotaTotal!);
        if (r != null && r.partidos.isEmpty) r.partidos.add(PartidoCaptura('', ''));
        mensaje = aprendidas.isNotEmpty ? '📚 Aprendí: ${aprendidas.join('; ')}'
            : (r == null || r.patas.isEmpty) ? 'No reconocí selecciones. Agrégalas a mano abajo o prueba con una captura más nítida.' : null;
      });
    } catch (e) {
      setState(() => mensaje = 'No pude leer la imagen: $e');
    } finally {
      setState(() => leyendo = false);
    }
  }

  double get _cuota {
    final manual = double.tryParse(cuotaCtrl.text.replaceAll(',', '.'));
    if (manual != null && manual > 1) return manual;
    var c = 1.0;
    for (final p in lectura?.patas ?? <PataCaptura>[]) {
      c *= p.cuota ?? 1;
    }
    return c;
  }

  Future<void> _guardar() async {
    final r = lectura;
    if (r == null || r.patas.isEmpty) return;
    final monto = double.tryParse(montoCtrl.text.replaceAll(',', '.')) ?? 0;
    final inicio = r.inicio ?? DateTime.now();
    final ls = <Map<String, dynamic>>[];
    var pTot = 1.0;
    for (var i = 0; i < r.partidos.length; i++) {
      final pc = r.partidos[i];
      final patas = r.patas.where((p) => p.partido == i).toList();
      if (patas.isEmpty) continue;
      var c = 1.0;
      final lista = <Map<String, dynamic>>[];
      for (final p in patas) {
        final op = opinar(p, pc);
        pTot *= op.p ?? (p.cuota != null ? (0.94 / p.cuota!).clamp(0.02, 0.98) : 0.6);
        c *= p.cuota ?? 1;
        lista.add({'titulo': p.titulo, 'mercado': mercadosCaptura[p.mercado] ?? p.mercado, 'sel': p.sel(pc.local, pc.visitante),
          'cuota': p.cuota, if (op.p != null) 'p': op.p});
      }
      final liga = _ligaDe(pc);
      ls.add({'liga': liga, 'inicio': inicio.toIso8601String(), 'local': pc.local, 'visitante': pc.visitante,
        'cuota': c, 'patas': lista});
    }
    await Historial.guardar({
      'id': DateTime.now().millisecondsSinceEpoch, 'fecha': DateTime.now().toIso8601String(),
      'tipo': monto > 0 ? 'apostada' : 'seguimiento', 'origen': 'captura', 'monto': monto,
      'autor': mia ? 'yo' : 'tipster:${autorCtrl.text.trim().isEmpty ? 'sin nombre' : autorCtrl.text.trim()}', 'cuota': _cuota, 'p': pTot,
      'estado': 'pendiente', 'lineas': ls,
    });
    if (!mounted) return;
    setState(() {
      lectura = null;
      mensaje = '✅ Guardada. Mírala en «En vivo»: se sigue y se liquida sola.';
    });
  }

  String _ligaDe(PartidoCaptura pc) {
    for (final m in repo.partidos) {
      if (parecido('${m['local']?['nombre']}', pc.local) >= 0.6 && parecido('${m['visitante']?['nombre']}', pc.visitante) >= 0.6) {
        return '${m['liga']}';
      }
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final r = lectura;
    return ListView(padding: const EdgeInsets.all(12), children: [
      Text('Capturas', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
      const Text('Sube la captura de tu combinada de Betano (o de un mercado, p. ej. la lista de tiros al arco de un '
          'jugador). Se lee en el celular, el bot opina de cada selección y la sigues en vivo.',
          style: TextStyle(color: Col.suave)),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(child: FilledButton.icon(onPressed: leyendo ? null : () => _elegir(ImageSource.gallery),
            icon: const Icon(Icons.photo_library), label: const Text('Elegir captura'))),
        const SizedBox(width: 8),
        IconButton.filledTonal(tooltip: 'Tomar foto', onPressed: leyendo ? null : () => _elegir(ImageSource.camera),
            icon: const Icon(Icons.photo_camera)),
      ]),
      if (leyendo) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
      if (mensaje != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(mensaje!, style: const TextStyle(color: Col.naranja))),
      if (r != null) ..._revision(r),
    ]);
  }

  List<Widget> _revision(LecturaCaptura r) => [
        const SizedBox(height: 10),
        const Text('Revisa y corrige lo que leí', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
        Wrap(spacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
          ChoiceChip(label: const Text('Mi apuesta'), selected: mia, onSelected: (_) => setState(() => mia = true)),
          ChoiceChip(label: const Text('Me la mandaron'), selected: !mia, onSelected: (_) => setState(() => mia = false)),
        ]),
        if (!mia)
          TextField(controller: autorCtrl, decoration: const InputDecoration(
              labelText: '¿Quién? (ej. lasfijas, grupo Telegram)', helperText: 'Así mido cuánto acierta cada uno')),
        for (var i = 0; i < r.partidos.length; i++) ..._partido(r, i),
        TextButton.icon(onPressed: () => setState(() => r.partidos.add(PartidoCaptura('', ''))),
            icon: const Icon(Icons.add), label: const Text('Agregar partido')),
        Row(children: [
          Expanded(child: TextField(controller: montoCtrl, keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Monto S/ (0 = solo seguimiento)'), onChanged: (_) => setState(() {}))),
          const SizedBox(width: 8),
          Expanded(child: TextField(controller: cuotaCtrl, keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Cuota total'), onChanged: (_) => setState(() {}))),
        ]),
        const SizedBox(height: 6),
        Text('Cuota ${f2(_cuota)} · ganancias S/${f2((double.tryParse(montoCtrl.text.replaceAll(',', '.')) ?? 0) * _cuota)}'
            '${r.inicio != null ? ' · ${diaHora(r.inicio!)}' : ' · hora no leída: se busca hoy'}',
            style: const TextStyle(fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        FilledButton.icon(onPressed: r.patas.isEmpty ? null : _guardar, icon: const Icon(Icons.check),
            label: const Text('Guardar y seguir en vivo')),
        TextButton(onPressed: () => setState(() => verTexto = !verTexto), child: Text(verTexto ? 'Ocultar texto leído' : 'Ver texto leído')),
        if (verTexto) SelectableText(r.texto, style: const TextStyle(color: Col.suave, fontSize: 12)),
      ];

  List<Widget> _partido(LecturaCaptura r, int i) {
    final pc = r.partidos[i];
    return [
      Card(
        color: Col.tarjeta,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: TextFormField(initialValue: pc.local, decoration: const InputDecoration(labelText: 'Local'),
                  onChanged: (v) => setState(() => pc.local = v))),
              const Padding(padding: EdgeInsets.symmetric(horizontal: 6), child: Text('vs')),
              Expanded(child: TextFormField(initialValue: pc.visitante, decoration: const InputDecoration(labelText: 'Visitante'),
                  onChanged: (v) => setState(() => pc.visitante = v))),
            ]),
            for (final p in r.patas.where((p) => p.partido == i)) _pata(r, p, pc),
            TextButton.icon(onPressed: () => setState(() => r.patas.add(PataCaptura('goles', 'mas', linea: 1.5, partido: i))),
                icon: const Icon(Icons.add), label: const Text('Agregar selección')),
          ]),
        ),
      ),
    ];
  }

  Widget _pata(LecturaCaptura r, PataCaptura p, PartidoCaptura pc) {
    final op = opinar(p, pc);
    final opciones = p.mercado == 'jug_arco' ? ['1+', '2+', '3+', '4+']
        : ['1x2', '1t_1x2'].contains(p.mercado) ? ['local', 'empate', 'visitante']
        : p.mercado == 'doble' ? ['1X', 'X2', '12'] : p.mercado == 'btts' ? ['si', 'no'] : ['mas', 'menos'];
    if (!opciones.contains(p.opcion)) p.opcion = opciones.first;
    final conLinea = ['mas', 'menos'].contains(p.opcion);
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(color: Col.panel, borderRadius: BorderRadius.circular(10), border: Border.all(color: Col.borde)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: DropdownButton<String>(
            isExpanded: true, value: p.mercado,
            items: [for (final e in mercadosCaptura.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) => setState(() => p.mercado = v ?? p.mercado),
          )),
          IconButton(onPressed: () => setState(() => r.patas.remove(p)), icon: const Icon(Icons.delete_outline)),
        ]),
        if (p.mercado == 'jug_arco')
          TextFormField(initialValue: p.jugador, decoration: const InputDecoration(labelText: 'Jugador'),
              onChanged: (v) => setState(() => p.jugador = v)),
        Row(children: [
          DropdownButton<String>(value: p.opcion, items: [for (final o in opciones) DropdownMenuItem(value: o, child: Text(o))],
              onChanged: (v) => setState(() {
                    p.opcion = v ?? p.opcion;
                    if (p.mercado == 'jug_arco') p.linea = int.parse(p.opcion[0]) - 0.5;
                  })),
          const SizedBox(width: 8),
          if (conLinea)
            SizedBox(width: 70, child: TextFormField(initialValue: p.linea?.toString() ?? '',
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Línea'), onChanged: (v) => setState(() => p.linea = _n(v)))),
          const Spacer(),
          SizedBox(width: 80, child: TextFormField(initialValue: p.cuota == null ? '' : f2(p.cuota!),
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Cuota'), onChanged: (v) => setState(() => p.cuota = _n(v)))),
        ]),
        Text(op.texto, style: TextStyle(color: op.p == null ? Col.suave : colorProb(op.p!), fontSize: 12.5, fontWeight: FontWeight.w700)),
      ]),
    );
  }
}
