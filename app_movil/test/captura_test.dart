// Lector de capturas (texto como lo devuelve el OCR) y avance en vivo de las patas.
import 'package:flutter_test/flutter_test.dart';
import 'package:futbot/captura.dart';
import 'package:futbot/vivo.dart';

void main() {
  test('combinada con varios mercados', () {
    final r = leerTexto([
      'Combinada (4)',
      'Real Madrid - Sevilla',
      'Dom 19/10 13:45',
      'Total de goles Más/Menos',
      'Menos de 4.5  1.28',
      'Más/Menos Córners',
      'Más de 6.5  1.30',
      'Juventus vs Lazio',
      'Doble oportunidad',
      'Juventus o Empate  1.22',
      'Ambos equipos marcan',
      'No  1.85',
      'Cuota total  3.76',
      'Importe  S/ 10.00',
      'Ganancias potenciales  S/ 37.60',
    ]);
    expect(r.partidos.map((p) => '${p.local}|${p.visitante}'), ['Real Madrid|Sevilla', 'Juventus|Lazio']);
    expect(r.patas.map((p) => '${p.partido}:${p.mercado}:${p.opcion}:${p.linea}:${p.cuota}'), [
      '0:goles:menos:4.5:1.28',
      '0:corners:mas:6.5:1.3',
      '1:doble:1X:null:1.22',
      '1:btts:no:null:1.85',
    ]);
    expect(r.monto, 10.0);
    expect(r.cuotaTotal, 3.76);
    expect(r.inicio?.hour, 13);
  });

  test('lista de tiros al arco de un jugador: aprende la línea mínima', () {
    final r = leerTexto(['Real Madrid - Sevilla', 'Tiros a puerta del jugador', 'Kylian Mbappé 2+  1.40', 'Kylian Mbappé 3+  2.30']);
    expect(r.lineasVistas['Kylian Mbappé'], {2, 3});
    expect(r.patas.first.mercado, 'jug_arco');
    expect(r.patas.first.opcion, '2+');
  });

  test('nombres parecidos', () {
    expect(parecido('Manchester United', 'Man United'), greaterThan(0.5));
    expect(parecido('AC Milan', 'Milan'), greaterThan(0.8));
    expect(parecido('Real Madrid', 'Sevilla'), lessThan(0.3));
    expect(parecido('Kylian Mbappe-Lottin', 'Kylian Mbappé'), greaterThan(0.6));
  });

  test('avance en vivo de córners y resultado', () {
    final e = Estado()
      ..estado = 'in'
      ..minuto = 60
      ..periodo = 2
      ..nl = 'Real Madrid'
      ..nv = 'Sevilla'
      ..gl = 1
      ..gv = 0
      ..sl = {'wonCorners': '5'}
      ..sv = {'wonCorners': '2'};
    final c = evaluar({'mercado': 'corners', 'opcion': 'mas', 'linea': 6.5}, 0.8, e);
    expect(c.estado, 'ganada');
    final c2 = evaluar({'mercado': 'corners', 'opcion': 'mas', 'linea': 9.5}, 0.6, e);
    expect(c2.estado, 'en juego');
    expect(c2.pVivo, inInclusiveRange(0.05, 0.9));
    final g = evaluar({'mercado': 'goles', 'opcion': 'menos', 'linea': 3.5}, 0.75, e);
    expect(g.pVivo, greaterThan(0.75)); // 1 gol al minuto 60: más seguro que antes
    final d = evaluar({'mercado': 'doble', 'opcion': '1X'}, 0.8, e);
    expect(d.pVivo, greaterThan(0.8));
    e.estado = 'post';
    expect(evaluar({'mercado': 'goles', 'opcion': 'mas', 'linea': 1.5}, 0.7, e).estado, 'perdida');
  });
}
