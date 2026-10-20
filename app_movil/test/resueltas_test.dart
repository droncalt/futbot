// Capturas de apuestas ya resueltas (texto como el OCR del celular): estado, monto, ganancia y patas.
import 'package:flutter_test/flutter_test.dart';
import 'package:futbot/lectura.dart';

void main() {
  test('combinada ganada de «Mis apuestas» compartida', () {
    final r = leerTexto([
      'Betano', 'Combinada de 4 S/60.00  Ganada',
      'Menos de 4.5  1.17', 'Goles totales Más/Menos', 'PAOK  Marcador 2-1', 'Iraklis',
      'Bet Builder  1.55', 'Juventus FC  Marcador 0-3', 'SS Lazio', 'o Más 1.5', 'Goles totales Más/Menos', 'o Menos de 4.5',
      'Goles totales Más/Menos',
      'Bet Builder  2.02', 'Real Madrid  Marcador 4-1', 'Sevilla FC', 'o Más 1.5', 'Goles totales Más/Menos', 'o Real Madrid',
      'Resultado del partido', 'Ganado con Pago Anticipado', 'o 2+', 'Kylian Mbappe Tiros al Arco', 'o Menos de 5.5',
      'Goles totales Más/Menos', 'Apuesta  S/60.00', 'Ganancias  S/345.08',
    ]);
    expect(r.estado, 'ganada');
    expect(r.monto, 60);
    expect(r.ganancia, 345.08);
    expect(r.partidos.length, 3);
    expect(r.partidos.first.marcador, '2-1');
    final mbappe = r.patas.where((p) => p.mercado == 'jug_arco').toList();
    expect(mbappe.single.opcion, '2+');
    expect(mbappe.single.jugador, contains('Mbappe'));
  });

  test('simple con apuesta gratis, fecha de realización y jugadores', () {
    final r = leerTexto([
      'Simple S/10.00  Gan...', 'Bet Builder  1.87', 'Manchester ...  Marcador 2-4', 'Paris Saint-Germ...',
      'o Más de 2.5', 'Goles totales', 'Más/Menos', 'o Sí', 'Ambos equipos', 'anotan', 'o Más de 0.5',
      'Más/Menos Goles en Primer', 'Tiempo', 'o 1+', 'Ferran Torres Tiros al', 'Arco', 'o 1+', 'Erling Haaland Tiros al', 'Arco',
      'ID:  20207561481', 'Fecha de realización:  14/10/2026 - 13:40', 'APUESTA GRATIS  S/10.00', 'Ganancias  S/8.70',
    ]);
    expect(r.estado, 'ganada');
    expect(r.gratis, isTrue);
    expect(r.fechaApuesta, DateTime(2026, 10, 14));
    expect(r.patas.map((p) => p.mercado).toList(), ['goles', 'btts', '1t_goles', 'jug_arco', 'jug_arco']);
  });
}
