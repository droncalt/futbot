// Dibuja todas las pantallas con el paquete de la nube para detectar errores que dejarían la app en blanco.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:futbot/datos.dart';
import 'package:futbot/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('todas las pantallas se dibujan con el paquete de la nube', (t) async {
    final texto = File(Platform.environment['PAQUETE'] ?? 'assets/paquete/paquete.json').readAsStringSync();
    SharedPreferences.setMockInitialValues({'paquete': texto, 'paquete_descargado': DateTime.now().toIso8601String()});
    await t.runAsync(() => repo.iniciar());
    expect(repo.paquete['lineas'], isNotNull);
    expect(jsonDecode(texto), isA<Map>());
    await t.pumpWidget(const FutBotApp());
    await t.pump(const Duration(seconds: 1));
    for (final nombre in ['Partidos', 'Historial', 'Más', 'Capturas', 'Boleta']) {
      await t.tap(find.text(nombre).last);
      await t.pump(const Duration(milliseconds: 500));
      expect(t.takeException(), isNull, reason: nombre);
    }
    await t.pumpWidget(const SizedBox()); // cierra pantallas con temporizador
  });
}
