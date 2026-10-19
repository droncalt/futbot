// Lector de capturas con los formatos reales de Betano (renglones como los deja el OCR) y avance en vivo.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:futbot/datos.dart';
import 'package:futbot/lectura.dart';
import 'package:futbot/vivo.dart';
import 'package:shared_preferences/shared_preferences.dart';

String resumen(LecturaCaptura r) => [
      for (var i = 0; i < r.partidos.length; i++)
        '${r.partidos[i].local}|${r.partidos[i].visitante}|${r.partidos[i].cuota}: '
            '${r.patas.where((p) => p.partido == i).map((p) => '${p.mercado}:${p.opcion}:${p.linea ?? ''}').join(', ')}',
    ].join('\n');

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({
      'paquete': File('assets/paquete/paquete.json').readAsStringSync(),
      'paquete_descargado': DateTime.now().toIso8601String(),
    });
    await repo.iniciar();
  });

  test('cupón de apuestas (simple + 2 Bet Builder)', () {
    final r = leerTexto([
      'Cupón de apuestas  3/30', 'Guardar  Compartir', 'Simple  Combinadas  Sistema',
      'Más de 1.5  1.14', 'Goles totales Más/Menos', 'Columbus Crew SC', 'Inter Miami CF',
      'Bet Builder  2/13  1.57', 'Japón', 'Venezuela', 'Japón', 'Resultado del partido', 'Más de 1.5', 'Goles totales Más/Menos',
      'Bet Builder  2/13  2.05', 'Bélgica', 'Francia', 'Más de 1.5', 'Goles totales Más/Menos', 'Francia (+2)', 'Resultado del partido',
      'Combinada de 3 = 1  3.66  S/40', 'COLOCAR APUESTA S/40.00', 'Ganancia potencial S/146.76',
    ]);
    expect(resumen(r), 'Columbus Crew SC|Inter Miami CF|1.14: goles:mas:1.5\n'
        'Japón|Venezuela|1.57: 1x2:local:, goles:mas:1.5\n'
        'Bélgica|Francia|2.05: goles:mas:1.5, 1x2:visitante:');
    expect(r.cuotaTotal, 3.66);
    expect(r.monto, 40);
    expect(r.ganancia, 146.76);
  });

  test('mis apuestas (resueltas, con marcador)', () {
    final r = leerTexto([
      'Abiertas (0)  Resueltas', 'Ganadas  Cash Out  Perdidas  Anuladas', 'Combinada de 3 S/30.00  Ganada',
      'Sport Huancayo (SM) ✓  1.24', 'Resultado del partido SuperCuotas', 'Sport Huancayo  Marcador 3-2', 'UTC De Cajamarca',
      'Bet Builder ✓  1.85', 'Olympique Marseille  Marcador 1-2', 'Paris Saint-Germain', 'Paris Saint-Germain ✓',
      'Resultado del partido', 'Más 1.5 ✓', 'Goles totales Más/Menos', 'Más 5.5 ✓', 'Más/Menos Córners', 'Más 7.5 ✓', 'Tiros al Arco',
    ]);
    expect(resumen(r), 'Sport Huancayo|UTC De Cajamarca|1.24: 1x2:local:\n'
        'Olympique Marseille|Paris Saint-Germain|1.85: 1x2:visitante:, goles:mas:1.5, corners:mas:5.5, tiros_arco:mas:7.5');
    expect(r.monto, 30);
    expect(r.partidos.first.marcador, '3-2');
  });

  test('imagen compartida (nombres cortados, mercados en 2 renglones) y opinión', () {
    final r = leerTexto([
      'Betano', 'Combinada de 8  6.65',
      'Bet Builder  1.44', 'Rodez …  Mañana', 'Montpellier HSC  13:45', 'Más de 2.5', 'Rodez AF Más/Menos', 'Córners',
      'Menos 4.5', 'Goles totales', 'Más/Menos', 'Más de 0.5', 'Goles totales', 'Más/Menos',
      'Más de 0.5  1.08', 'Goles totales', 'RC Celta de Vig…  Más/Menos  Mañana', 'CD Tener…  13:30',
      'Bet Builder  1.25', 'Getafe…  Mañana', 'Rayo Valleca…  14:00', 'Menos 4.5', 'Goles totales', 'Más/Menos',
      'Más de 2.5', 'Getafe CF Más/Menos', 'Córners', 'Más de 1.5', 'Rayo Vallecano Más/Menos', 'Córners',
    ]);
    expect(r.cuotaTotal, 6.65);
    expect(r.partidos.length, 3);
    final t = resumen(r).split('\n');
    expect(t[0], endsWith('corners_local:mas:2.5, goles:menos:4.5, goles:mas:0.5'));
    expect(t[1], endsWith('goles:mas:0.5'));
    expect(t[2], endsWith('goles:menos:4.5, corners_local:mas:2.5, corners_visitante:mas:1.5'));
    // si el paquete trae esos partidos, el bot los reconoce y da probabilidades
    final a = analizar(r);
    expect(a.texto, contains('Probabilidad'));
    if (repo.partidos.any((m) => '${m['local']?['nombre']}' == 'Getafe')) {
      expect(r.partidos[2].local, 'Getafe');
      expect(r.partidos[2].visitante, 'Rayo Vallecano');
      expect(a.tarjetas[0].p, isNotNull);
      // Más 0.5 y Menos 4.5 del mismo partido = entre 1 y 4 goles (más probable que la pata más floja)
      expect(a.tarjetas[0].p!, lessThan(1));
    }
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
      ..sl = {'wonCorners': '5', 'shotsOnTarget': '4'}
      ..sv = {'wonCorners': '2', 'shotsOnTarget': '1'};
    expect(evaluar({'mercado': 'corners', 'opcion': 'mas', 'linea': 6.5}, 0.8, e).estado, 'ganada');
    final c2 = evaluar({'mercado': 'corners', 'opcion': 'mas', 'linea': 9.5}, 0.6, e);
    expect(c2.estado, 'en juego');
    expect(c2.pVivo, inInclusiveRange(0.05, 0.9));
    expect(evaluar({'mercado': 'tiros_arco', 'opcion': 'mas', 'linea': 4.5}, 0.7, e).estado, 'ganada');
    expect(evaluar({'mercado': 'goles', 'opcion': 'menos', 'linea': 3.5}, 0.75, e).pVivo, greaterThan(0.75));
    expect(evaluar({'mercado': 'doble', 'opcion': '1X'}, 0.8, e).pVivo, greaterThan(0.8));
    e.estado = 'post';
    expect(evaluar({'mercado': 'goles', 'opcion': 'mas', 'linea': 1.5}, 0.7, e).estado, 'perdida');
  });
}
