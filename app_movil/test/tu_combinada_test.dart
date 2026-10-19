// La combinada de 8 que el usuario armó desde «Partidos» (imagen compartida de Betano, 18/10/2026).
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:futbot/datos.dart';
import 'package:futbot/lectura.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('opinión de la combinada de 8', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({
      'paquete': File('assets/paquete/paquete.json').readAsStringSync(),
      'paquete_descargado': DateTime.now().toIso8601String(),
    });
    await repo.iniciar();
    final r = leerTexto([
      'Betano', 'Combinada de 8  6.65',
      'Bet Builder  1.44', 'Rodez …  Mañana', 'Montpellier HSC  13:45', 'Más de 2.5', 'Rodez AF Más/Menos', 'Córners',
      'Menos 4.5', 'Goles totales', 'Más/Menos', 'Más de 0.5', 'Goles totales', 'Más/Menos',
      'Más de 0.5  1.08', 'Goles totales', 'RC Celta de Vig…  Más/Menos  Mañana', 'CD Tener…  13:30',
      'Más de 1.5  1.37', 'Goles totales', 'AC Monza  Más/Menos  Mañana', 'Cagliari Calcio  11:30',
      'Bet Builder  1.25', 'Parma Calcio 19…  Mañana', 'Torino FC  13:45', 'Más de 5.5', 'Más/Menos', 'Córners',
      'Más de 0.5', 'Goles totales', 'Más/Menos',
      'Bet Builder  1.25', 'Getafe…  Mañana', 'Rayo Valleca…  14:00', 'Menos 4.5', 'Goles totales', 'Más/Menos',
      'Más de 2.5', 'Getafe CF Más/Menos', 'Córners', 'Más de 1.5', 'Rayo Vallecano Más/Menos', 'Córners',
      'Bet Builder  1.31', 'Trabzons…  Mañana', 'Besiktas JK  12:00', 'Más de 6.5', 'Más/Menos', 'Córners',
      'Más de 1.5', 'Goles totales', 'Más/Menos',
      'Bet Builder  1.25', 'Tottenham Hotspur  Mañana', 'Coventry C…  14:00', 'Más de 1.5', 'Goles totales', 'Más/Menos',
      'Más de 5.5', 'Más/Menos', 'Córners',
      'Bet Builder  1.22', 'SC Braga  Mañana', 'Gil Vicente…  14:15', 'Menos 4.5', 'Goles totales', 'Más/Menos',
      'Más de 0.5', 'Goles totales', 'Más/Menos',
    ]);
    final a = analizar(r);
    // ignore: avoid_print
    print(a.texto);
    expect(r.partidos.length, 8);
  });
}
