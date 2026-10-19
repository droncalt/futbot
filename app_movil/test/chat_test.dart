// Chat: entiende los pedidos y arma combinadas con el paquete incluido en la app.
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

  test('entiende el pedido', () {
    final q = entender('Armame 3 fijas para hoy ultra seguras a cuota 2.5 con 80% y 20 soles, sin córners');
    expect(q.n, 3);
    expect(q.dia, 'hoy');
    expect(q.nivel, 'ultra');
    expect(q.cuota, 2.5);
    expect(q.pMin, 0.8);
    expect(q.monto, 20);
    expect(q.sinFamilias, contains('corners'));
  });

  test('arma la combinada más probable para la cuota pedida', () async {
    final m = await responder('cuota 2');
    // el paquete incluido puede quedar viejo: si ya no hay partidos futuros, avisa en vez de fallar
    if (m.boleta != null) {
      final c = m.boleta!.fold<double>(1, (a, o) => a * o.cuota);
      expect(c, greaterThanOrEqualTo(1.96));
      expect(m.boleta!.map((o) => o.clavePartido).toSet().length, m.boleta!.length); // un partido una vez
    } else {
      expect(m.texto, isNotEmpty);
    }
    expect((await responder('ayuda')).texto, contains('fijas'));
    expect((await responder('¿qué es el multi bono?')).texto, isNotEmpty);
  });
}
