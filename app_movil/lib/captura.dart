// Capturas: lee tus combinadas de Betano (u otras) con reconocimiento de texto EN el celular (Google ML Kit,
// sin internet ni tokens), el bot opina, se guardan para seguirlas en vivo y aprende qué líneas ofrece Betano.
// La lectura y la opinión están en lectura.dart; aquí: OCR, guardar y la pantalla para corregir a mano.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'comunes.dart';
import 'historial.dart';
import 'lectura.dart';
import 'vivo.dart';

export 'lectura.dart';

/// OCR de la imagen → renglones (lo que está a la misma altura se une: selección + cuota, equipo + hora).
Future<LecturaCaptura?> leerImagen(String ruta) async {
  final rec = TextRecognizer(script: TextRecognitionScript.latin);
  try {
    final res = await rec.processImage(InputImage.fromFilePath(ruta));
    final lineas = <TextLine>[for (final b in res.blocks) ...b.lines];
    if (lineas.isEmpty) return null;
    final alto = lineas.map((l) => l.boundingBox.height).reduce((a, b) => a + b) / lineas.length;
    final tol = alto * 0.55;
    lineas.sort((a, b) => a.boundingBox.center.dy.compareTo(b.boundingBox.center.dy));
    final filas = <List<TextLine>>[];
    for (final l in lineas) {
      if (filas.isNotEmpty && (l.boundingBox.center.dy - filas.last.first.boundingBox.center.dy).abs() < tol) {
        filas.last.add(l);
      } else {
        filas.add([l]);
      }
    }
    final renglones = [
      for (final f in filas) (f..sort((a, b) => a.boundingBox.left.compareTo(b.boundingBox.left))).map((l) => l.text).join('  '),
    ];
    return leerTexto(renglones);
  } finally {
    rec.close();
  }
}

Future<LecturaCaptura?> elegirYLeer(ImageSource origen) async {
  final img = await ImagePicker().pickImage(source: origen, imageQuality: 95);
  if (img == null) return null;
  final r = await leerImagen(img.path);
  if (r != null) await LineasBetano.aprender(r.lineasVistas);
  return r ?? LecturaCaptura();
}

/// Guarda la combinada leída en el historial para seguirla en vivo y liquidarla sola.
Future<bool> guardarLectura(LecturaCaptura r, {double? monto, String autor = 'yo', double? cuotaManual}) async {
  final a = analizar(r);
  final ls = <Map<String, dynamic>>[];
  for (final o in a.tarjetas) {
    final pc = o.pc;
    ls.add({
      'liga': pc.liga, 'inicio': (pc.inicio ?? DateTime.now()).toIso8601String(), 'local': pc.local, 'visitante': pc.visitante,
      'cuota': pc.cuota ?? 1.0, if (o.p != null) 'p': o.p,
      'patas': [
        for (final x in o.patas)
          {'titulo': x.$1.titulo, 'mercado': mercadosCaptura[x.$1.mercado] ?? x.$1.textoMercado, 'sel': x.$1.sel,
            'cuota': o.patas.length == 1 ? pc.cuota : null, if (x.$2 != null) 'p': x.$2},
      ],
    });
  }
  final m = monto ?? r.monto ?? 0;
  return Historial.guardar({
    'id': DateTime.now().millisecondsSinceEpoch, 'fecha': DateTime.now().toIso8601String(),
    'tipo': m > 0 ? 'apostada' : 'seguimiento', 'origen': 'captura', 'autor': autor, 'monto': m,
    'cuota': cuotaManual ?? a.cuota ?? 1.0, if (a.pTotal != null) 'p': a.pTotal, 'estado': 'pendiente', 'lineas': ls,
  });
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
    if (vistas.isEmpty) return [];
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

  static int? minimo(Map<String, dynamic> cat, String jugador) {
    final jug = Map<String, dynamic>.from(cat['jug_arco'] ?? {});
    for (final e in jug.entries) {
      if (parecido(e.key, jugador) >= 0.6 && e.value['min'] != null) return (e.value['min'] as num).toInt();
    }
    return null;
  }
}

// ---------------------------------------------------------------- pantalla para corregir a mano
class PantallaCapturas extends StatefulWidget {
  final LecturaCaptura? inicial;
  const PantallaCapturas({super.key, this.inicial});
  @override
  State<PantallaCapturas> createState() => _PantallaCapturasState();
}

class _PantallaCapturasState extends State<PantallaCapturas> {
  LecturaCaptura? lectura;
  bool leyendo = false, verTexto = false, mia = true;
  String? mensaje;
  final montoCtrl = TextEditingController(), cuotaCtrl = TextEditingController(), autorCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    if (widget.inicial != null) _poner(widget.inicial!);
  }

  void _poner(LecturaCaptura r) {
    lectura = r;
    montoCtrl.text = r.monto == null ? '' : f2(r.monto!);
    cuotaCtrl.text = r.cuotaTotal == null ? '' : f2(r.cuotaTotal!);
    if (r.partidos.isEmpty) r.partidos.add(PartidoCaptura('', ''));
  }

  Future<void> _elegir(ImageSource origen) async {
    setState(() {
      leyendo = true;
      mensaje = null;
    });
    try {
      final r = await elegirYLeer(origen);
      if (r != null) setState(() => _poner(r));
    } catch (e) {
      setState(() => mensaje = 'No pude leer la imagen: $e');
    } finally {
      setState(() => leyendo = false);
    }
  }

  Future<void> _guardar() async {
    final r = lectura;
    if (r == null || r.patas.isEmpty) return;
    await guardarLectura(r,
        monto: double.tryParse(montoCtrl.text.replaceAll(',', '.')) ?? 0,
        cuotaManual: double.tryParse(cuotaCtrl.text.replaceAll(',', '.')),
        autor: mia ? 'yo' : 'tipster:${autorCtrl.text.trim().isEmpty ? 'sin nombre' : autorCtrl.text.trim()}');
    if (!mounted) return;
    setState(() {
      lectura = null;
      mensaje = '✅ Guardada. Mírala en «En vivo»: se sigue y se liquida sola.';
    });
  }

  @override
  Widget build(BuildContext context) {
    final r = lectura;
    return ListView(padding: const EdgeInsets.all(12), children: [
      const Text('Corrige lo que leí si algo salió mal. Lo más fácil: manda la captura en el Chat y te respondo directo.',
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

  List<Widget> _revision(LecturaCaptura r) {
    final a = analizar(r);
    return [
      const SizedBox(height: 10),
      Container(padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: Col.tarjeta, borderRadius: BorderRadius.circular(12)),
          child: Text(a.texto)),
      const SizedBox(height: 10),
      Wrap(spacing: 6, children: [
        ChoiceChip(label: const Text('Mi apuesta'), selected: mia, onSelected: (_) => setState(() => mia = true)),
        ChoiceChip(label: const Text('Me la mandaron'), selected: !mia, onSelected: (_) => setState(() => mia = false)),
      ]),
      if (!mia)
        TextField(controller: autorCtrl, decoration: const InputDecoration(
            labelText: '¿Quién? (ej. lasfijas, grupo Telegram)', helperText: 'Así mido cuánto acierta cada uno')),
      for (var i = 0; i < r.partidos.length; i++) _partido(r, i),
      TextButton.icon(onPressed: () => setState(() => r.partidos.add(PartidoCaptura('', ''))),
          icon: const Icon(Icons.add), label: const Text('Agregar partido')),
      Row(children: [
        Expanded(child: TextField(controller: montoCtrl, keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Monto S/ (0 = solo seguir)'), onChanged: (_) => setState(() {}))),
        const SizedBox(width: 8),
        Expanded(child: TextField(controller: cuotaCtrl, keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Cuota total'), onChanged: (_) => setState(() {}))),
      ]),
      const SizedBox(height: 8),
      FilledButton.icon(onPressed: r.patas.isEmpty ? null : _guardar, icon: const Icon(Icons.check), label: const Text('Guardar y seguir en vivo')),
      TextButton(onPressed: () => setState(() => verTexto = !verTexto), child: Text(verTexto ? 'Ocultar texto leído' : 'Ver texto leído')),
      if (verTexto) SelectableText(r.texto, style: const TextStyle(color: Col.suave, fontSize: 12)),
    ];
  }

  Widget _partido(LecturaCaptura r, int i) {
    final pc = r.partidos[i];
    return Card(
      color: Col.tarjeta,
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: TextFormField(key: ValueKey('l$i${pc.local}'), initialValue: pc.local,
                decoration: const InputDecoration(labelText: 'Local'), onChanged: (v) => pc.local = v)),
            const Padding(padding: EdgeInsets.symmetric(horizontal: 6), child: Text('vs')),
            Expanded(child: TextFormField(key: ValueKey('v$i${pc.visitante}'), initialValue: pc.visitante,
                decoration: const InputDecoration(labelText: 'Visitante'), onChanged: (v) => pc.visitante = v)),
            SizedBox(width: 70, child: TextFormField(initialValue: pc.cuota == null ? '' : f2(pc.cuota!),
                keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Cuota'),
                onChanged: (v) => setState(() => pc.cuota = double.tryParse(v.replaceAll(',', '.'))))),
          ]),
          for (final p in r.patas.where((p) => p.partido == i)) _pata(r, p, pc),
          TextButton.icon(onPressed: () => setState(() => r.patas.add(PataCaptura('goles', 'mas', linea: 1.5, partido: i))),
              icon: const Icon(Icons.add), label: const Text('Agregar selección')),
        ]),
      ),
    );
  }

  Widget _pata(LecturaCaptura r, PataCaptura p, PartidoCaptura pc) {
    final prob = probPata(p, pc);
    final opciones = p.mercado == 'jug_arco' ? ['1+', '2+', '3+', '4+']
        : ['1x2', '1t_1x2'].contains(p.mercado) ? ['local', 'empate', 'visitante']
        : p.mercado == 'doble' ? ['1X', 'X2', '12'] : p.mercado == 'btts' ? ['si', 'no']
        : p.mercado == 'otro' ? [p.opcion] : ['mas', 'menos'];
    if (!opciones.contains(p.opcion)) p.opcion = opciones.first;
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
          TextFormField(initialValue: p.jugador, decoration: const InputDecoration(labelText: 'Jugador'), onChanged: (v) => setState(() => p.jugador = v)),
        Row(children: [
          DropdownButton<String>(value: p.opcion, items: [for (final o in opciones) DropdownMenuItem(value: o, child: Text(o))],
              onChanged: (v) => setState(() {
                    p.opcion = v ?? p.opcion;
                    if (p.mercado == 'jug_arco') p.linea = int.parse(p.opcion[0]) - 0.5;
                  })),
          const SizedBox(width: 8),
          if (p.opcion == 'mas' || p.opcion == 'menos')
            SizedBox(width: 70, child: TextFormField(initialValue: p.linea?.toString() ?? '',
                keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Línea'),
                onChanged: (v) => setState(() => p.linea = double.tryParse(v.replaceAll(',', '.'))))),
          const Spacer(),
          Text(prob == null ? 'sin dato' : pct(prob), style: TextStyle(fontWeight: FontWeight.w900, color: prob == null ? Col.suave : colorProb(prob))),
        ]),
      ]),
    );
  }
}
