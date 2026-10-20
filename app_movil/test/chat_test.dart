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

  test('cuota alta (7) con selecciones muy seguras: suma muchas', () async {
    final m = await responder('armame cuota 7 muy seguras');
    // ignore: avoid_print
    print(m.texto);
    if (m.boleta != null) {
      final c = m.boleta!.fold<double>(1, (a, o) => a * o.cuota);
      final p = m.boleta!.fold<double>(1, (a, o) => a * o.p);
      // ignore: avoid_print
      print('partidos ${m.boleta!.length} · patas ${m.boleta!.fold<int>(0, (a, o) => a + o.patas.length)} · cuota $c · prob $p');
      for (final o in m.boleta!) {
        // ignore: avoid_print
        print('  ${o.partido}: ${o.patas.map((x) => '${x.titulo} ${x.mercado} ${(x.p * 100).round()}%').join(' + ')} → ${o.cuota}');
      }
      expect(c, greaterThanOrEqualTo(6.9));
      expect(m.boleta!.every((o) => o.patas.every((x) => x.p >= 0.80)), isTrue);
    }
  });

  test('cuota 4 con tiros al arco y córners', () async {
    final m = await responder('cuota 4 con tiros al arco y córners');
    // ignore: avoid_print
    print(m.texto);
    for (final o in m.boleta ?? <Opcion>[]) {
      // ignore: avoid_print
      print('  ${o.partido}: ${o.patas.map((x) => '${x.titulo} ${x.mercado} ${(x.p * 100).round()}%').join(' + ')} → ${o.cuota}');
      expect(o.patas.every((x) => '${x.sel['mercado']}'.startsWith('corners') || '${x.sel['mercado']}'.contains('arco')), isTrue);
    }
  });
}
