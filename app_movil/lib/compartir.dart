// Compartir una apuesta como IMAGEN (no texto): se dibuja una tarjeta tipo cupón de Betano con la marca FútBot,
// se convierte en PNG y se abre el menú de compartir de Android (WhatsApp, guardar, copiar…).
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import 'comunes.dart';

const _tinta = Color(0xFF1D2433), _gris = Color(0xFF6B7690), _naranja = Color(0xFFE8590C), _verde = Color(0xFF16A34A),
    _rojo = Color(0xFFE11D48);

/// Tarjeta de la boleta (formato del historial: lineas → patas) lista para convertirse en imagen.
class ImagenBoleta extends StatelessWidget {
  final Map<String, dynamic> b;
  const ImagenBoleta(this.b, {super.key});

  @override
  Widget build(BuildContext context) {
    final ls = (b['lineas'] as List? ?? []);
    final estado = '${b['estado'] ?? 'pendiente'}';
    final monto = (b['monto'] as num?)?.toDouble() ?? 0;
    final cuota = (b['cuota'] as num?)?.toDouble() ?? 1;
    final p = (b['p'] as num?)?.toDouble();
    final n = ls.length;
    return Container(
      width: 360,
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18)),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          decoration: const BoxDecoration(gradient: LinearGradient(colors: [Color(0xFFFF8A3D), _naranja])),
          child: Row(children: [
            const Text('⚽ FútBot', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 20)),
            const Spacer(),
            if (estado != 'pendiente')
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
                child: Text(estado == 'ganada' ? '✅ GANADA' : '❌ PERDIDA',
                    style: TextStyle(color: estado == 'ganada' ? _verde : _rojo, fontWeight: FontWeight.w900, fontSize: 13)),
              ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
          child: Row(children: [
            Text(n == 1 ? 'Simple' : n == 2 ? 'Doble' : n == 3 ? 'Triple' : 'Combinada de $n',
                style: const TextStyle(color: _tinta, fontWeight: FontWeight.w900, fontSize: 16)),
            const Spacer(),
            Text(f2(cuota), style: const TextStyle(color: _tinta, fontWeight: FontWeight.w900, fontSize: 18)),
          ]),
        ),
        for (final l in ls) _linea(Map<String, dynamic>.from(l)),
        const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (p != null && p > 0)
                Text('Prob. FútBot: ${pct(p)}', style: TextStyle(color: colorProb(p), fontWeight: FontWeight.w900, fontSize: 14)),
              Text(diaHora(DateTime.tryParse('${b['fecha']}') ?? DateTime.now()), style: const TextStyle(color: _gris, fontSize: 11)),
            ])),
            if (monto > 0)
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text('Apuesta S/${f2(monto)}', style: const TextStyle(color: _gris, fontSize: 12)),
                Text('${estado == 'ganada' ? 'Ganó' : 'Ganancia'} S/${f2(monto * cuota)}',
                    style: const TextStyle(color: _tinta, fontWeight: FontWeight.w900, fontSize: 16)),
              ]),
          ]),
        ),
      ]),
    );
  }

  Widget _linea(Map<String, dynamic> l) {
    final patas = (l['patas'] as List? ?? []);
    final c = (l['cuota'] as num?)?.toDouble();
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 6),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(border: Border.all(color: const Color(0xFFE3E7EF)), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(patas.length > 1 ? 'Bet Builder' : '${patas.isEmpty ? '' : patas.first['titulo']}',
              style: TextStyle(color: patas.length > 1 ? _naranja : _tinta, fontWeight: FontWeight.w900, fontSize: 15))),
          if (c != null && c > 1) Text(f2(c), style: const TextStyle(color: _tinta, fontWeight: FontWeight.w800)),
        ]),
        if (patas.length == 1) Text('${patas.first['mercado']}', style: const TextStyle(color: _gris, fontSize: 12.5)),
        const SizedBox(height: 3),
        Text('${l['local']}', style: const TextStyle(color: _tinta, fontSize: 13.5)),
        Text('${l['visitante']}', style: const TextStyle(color: _tinta, fontSize: 13.5)),
        if (patas.length > 1)
          for (final p in patas)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(p['resultado'] == 'ganada' ? '✅ ' : p['resultado'] == 'perdida' ? '❌ ' : '○ ',
                    style: const TextStyle(color: _naranja, fontSize: 12.5)),
                Expanded(child: Text.rich(TextSpan(children: [
                  TextSpan(text: '${p['titulo']}  ', style: const TextStyle(color: _tinta, fontWeight: FontWeight.w800, fontSize: 13)),
                  TextSpan(text: '${p['mercado']}', style: const TextStyle(color: _gris, fontSize: 12)),
                ]))),
              ]),
            ),
        if (patas.length == 1 && patas.first['resultado'] != null)
          Text(patas.first['resultado'] == 'ganada' ? '✅ Acertada' : '❌ Fallada',
              style: TextStyle(color: patas.first['resultado'] == 'ganada' ? _verde : _rojo, fontWeight: FontWeight.w800, fontSize: 12)),
      ]),
    );
  }
}

/// Muestra la imagen y abre el menú de compartir de Android con el PNG.
Future<void> compartirBoleta(BuildContext context, Map<String, dynamic> b) async {
  final clave = GlobalKey();
  await showDialog(
    context: context,
    builder: (c) => Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(12),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Flexible(child: SingleChildScrollView(child: RepaintBoundary(key: clave, child: ImagenBoleta(b)))),
        const SizedBox(height: 10),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          FilledButton.icon(
            icon: const Icon(Icons.share),
            label: const Text('Compartir imagen'),
            onPressed: () async {
              final r = clave.currentContext?.findRenderObject() as RenderRepaintBoundary?;
              if (r == null) return;
              final img = await r.toImage(pixelRatio: 3);
              final bytes = await img.toByteData(format: ui.ImageByteFormat.png);
              if (bytes == null) return;
              final dir = await getTemporaryDirectory();
              final f = File('${dir.path}/futbot_boleta_${DateTime.now().millisecondsSinceEpoch}.png');
              await f.writeAsBytes(bytes.buffer.asUint8List());
              await SharePlus.instance.share(ShareParams(files: [XFile(f.path, mimeType: 'image/png')], text: 'Mi apuesta en FútBot ⚽'));
            },
          ),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: () => Navigator.pop(c), child: const Text('Cerrar', style: TextStyle(color: Colors.white))),
        ]),
      ]),
    ),
  );
}
