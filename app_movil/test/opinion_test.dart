// Conversación sobre una apuesta escrita: opinión, cambios y cuota de Betano.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:futbot/chat.dart';
import 'package:futbot/datos.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({
      'paquete': File('assets/paquete/paquete.json').readAsStringSync(),
      'paquete_descargado': DateTime.now().toIso8601String(),
    });
    await repo.iniciar();
  });

  test('conversación sobre Barcelona vs PSG', () async {
    final hay = repo.partidos.any((m) => '${m['visitante']?['nombre']}' == 'Barcelona');
    final m1 = await responder('¿cómo ves Barcelona gana y más de 2.5 goles contra el PSG? me pagan 2.40');
    // ignore: avoid_print
    print('1) ${m1.texto}\n');
    if (!hay) return;
    expect(m1.apuesta, isNotNull);
    expect(m1.apuesta!.sels.map((s) => s.clave), containsAll(['1x2|visitante|', 'goles|mas|2.5']));
    final m2 = await responder('agrégale ambos anotan y Raphinha tira al arco', apuesta: m1.apuesta);
    // ignore: avoid_print
    print('2) ${m2.texto}\n');
    expect(m2.apuesta!.sels.length, 4);
    final m3 = await responder('quítale el gana el barcelona', apuesta: m2.apuesta);
    // ignore: avoid_print
    print('3) ${m3.texto}\n');
    expect(m3.apuesta!.sels.length, 3);
    final m4 = await responder('cámbiala a más de 1.5', apuesta: m3.apuesta);
    // ignore: avoid_print
    print('4) ${m4.texto}\n');
    expect(m4.apuesta!.sels.any((s) => s.clave == 'goles|mas|1.5'), isTrue);
    final m5 = await responder('¿qué tan segura es?', apuesta: m4.apuesta);
    expect(m5.texto, contains('%'));
  });

  test('Haaland y córners del City', () async {
    final m = await responder('¿qué tan segura es Haaland 1+ tiros al arco y más de 7.5 córners en el Manchester City?');
    // ignore: avoid_print
    print(m.texto);
    expect(m.texto, isNot(contains('liquida Betano')));
  });
}
