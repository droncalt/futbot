// Colores, escudos y piezas visuales compartidas.
import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'datos.dart';

class Col {
  static const fondo = Color(0xFF0F1720), panel = Color(0xFF17212C), tarjeta = Color(0xFF1C2836);
  static const borde = Color(0xFF2A3A4D), texto = Color(0xFFE7EDF3), suave = Color(0xFF9DB0C4);
  static const naranja = Color(0xFFFF8A3D), naranjaOsc = Color(0xFFE8590C);
  static const verde = Color(0xFF16A34A), lima = Color(0xFF65A30D), ambar = Color(0xFFD97706), rosa = Color(0xFFE11D48);
  static const tinta = Color(0xFF1D2433), gris = Color(0xFF5B6B8C);
}

Color colorProb(double p) => p >= 0.85 ? Col.verde : p >= 0.75 ? Col.lima : p >= 0.65 ? Col.ambar : Col.rosa;

String f2(double x) => x.toStringAsFixed(2);
String pct(double p) => '${(p * 100).round()}%';

class Escudo extends StatelessWidget {
  final Equipo equipo;
  final double tam;
  const Escudo(this.equipo, {super.key, this.tam = 20});

  Widget _inicial() => Container(
        width: tam, height: tam, alignment: Alignment.center,
        decoration: const BoxDecoration(color: Color(0xFFE6E9EF), shape: BoxShape.circle),
        child: Text(equipo.nombre.isEmpty ? '?' : equipo.nombre[0],
            style: TextStyle(fontSize: tam * 0.5, fontWeight: FontWeight.w800, color: Col.gris)),
      );

  @override
  Widget build(BuildContext context) {
    final url = repo.escudo(equipo.escudo);
    if (url == null) return _inicial();
    final asset = equipo.escudo == null ? null : 'assets/paquete/${equipo.escudo}';
    Widget desdeAsset() => asset == null
        ? _inicial()
        : Image.asset(asset, width: tam, height: tam, fit: BoxFit.contain, errorBuilder: (_, _, _) => _inicial());
    if (url.startsWith('asset:')) return desdeAsset();
    return CachedNetworkImage(imageUrl: url, width: tam, height: tam, fit: BoxFit.contain,
        errorWidget: (_, _, _) => desdeAsset(), placeholder: (_, _) => SizedBox(width: tam, height: tam));
  }
}

class EquipoFila extends StatelessWidget {
  final Equipo equipo;
  final Color color;
  final double tam;
  const EquipoFila(this.equipo, {super.key, this.color = Col.tinta, this.tam = 20});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Escudo(equipo, tam: tam), const SizedBox(width: 7),
          Expanded(child: Text(equipo.nombre, overflow: TextOverflow.ellipsis, style: TextStyle(color: color, fontSize: 14.5))),
        ]),
      );
}

class ChipProb extends StatelessWidget {
  final double p;
  final String sufijo;
  const ChipProb(this.p, {super.key, this.sufijo = ' prob.'});
  @override
  Widget build(BuildContext context) {
    final c = colorProb(p);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      decoration: BoxDecoration(border: Border.all(color: c), borderRadius: BorderRadius.circular(99)),
      child: Text('${pct(p)}$sufijo', style: TextStyle(color: c, fontWeight: FontWeight.w800, fontSize: 12)),
    );
  }
}

Future<void> abrir(String url) async {
  final uri = Uri.parse(url);
  if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
    await launchUrl(uri);
  }
}

String diaHora(DateTime d) {
  const dias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
  String dos(int x) => x.toString().padLeft(2, '0');
  return '${dias[d.weekday - 1]} ${dos(d.day)}/${dos(d.month)} ${dos(d.hour)}:${dos(d.minute)}';
}

/// "de cada 10 así, ≈7 se ganan" (o "menos de 1 se gana").
String deCada10(double p) {
  final n = (p * 10).round();
  return n == 0 ? 'de cada 10 así, menos de 1 se gana' : n == 1 ? 'de cada 10 así, ≈1 se gana' : 'de cada 10 así, ≈$n se ganan';
}

/// Límites de Betano Perú (centro de ayuda + cupón real "3/30"): máximo 30 selecciones por cupón, un partido una sola
/// vez (varias del mismo partido = un Bet Builder de 2 a 13 mercados), apuesta mínima S/0.50.
class LimitesBetano {
  static const maxSelecciones = 30, maxPatasBB = 13;
  static double get minima => repo.apuestaMinima;

  /// Problemas para apostar esta boleta en Betano (vacío = se puede). [monto] null = solo seguimiento.
  static List<String> revisar({required int selecciones, double? monto, List<int> patasPorPartido = const []}) => [
        if (selecciones > maxSelecciones) 'Betano permite máximo $maxSelecciones selecciones por cupón (tienes $selecciones).',
        if (patasPorPartido.any((n) => n > maxPatasBB)) 'Un Bet Builder admite máximo $maxPatasBB mercados del mismo partido.',
        if (monto != null && monto < minima) 'La apuesta mínima en Betano es S/${f2(minima)}.',
      ];
}
