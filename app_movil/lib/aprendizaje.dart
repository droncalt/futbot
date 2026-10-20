// «Aprendizaje»: cómo aprende FútBot y qué aprendió — de los partidos (en la nube, cada día), de tus apuestas y
// capturas (en el celular), de los tipsters y de internet. Todo con números reales, nada inventado.
import 'package:flutter/material.dart';

import 'captura.dart' show LineasBetano;
import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';
import 'noticias.dart';

const _nombresMercado = {
  '1x2': 'Resultado del partido', 'doble': 'Doble oportunidad', 'goles': 'Goles Más/Menos', 'btts': 'Ambos anotan',
  'goles_local': 'Goles del local', 'goles_visitante': 'Goles del visitante', '1t_goles': 'Goles 1.er tiempo',
  'corners': 'Córners', 'corners_local': 'Córners del local', 'corners_visitante': 'Córners del visitante',
  'tarjetas': 'Tarjetas', 'tiros_arco': 'Tiros al arco', 'tiros_arco_local': 'Tiros al arco del local',
  'tiros_arco_visitante': 'Tiros al arco del visitante', 'atajadas': 'Atajadas', 'atajadas_local': 'Atajadas portero local',
  'atajadas_visitante': 'Atajadas portero visitante', 'jug_arco': 'Jugador: tiros al arco', 'jug_gol': 'Jugador: marca gol',
  'jug_asist': 'Jugador: asistencia', 'jug_ga': 'Jugador: gol o asistencia',
};

class PantallaAprendizaje extends StatefulWidget {
  const PantallaAprendizaje({super.key});
  @override
  State<PantallaAprendizaje> createState() => _PantallaAprendizajeState();
}

class _PantallaAprendizajeState extends State<PantallaAprendizaje> {
  List<Map<String, dynamic>> boletas = [], inv = [];
  Map<String, dynamic> lineas = {};
  bool listo = false;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    final b = await Historial.cargar();
    final i = await investigaciones();
    final l = await LineasBetano.cargar();
    if (mounted) {
      setState(() {
        boletas = b;
        inv = i;
        lineas = l;
        listo = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final cal = Map<String, dynamic>.from(repo.paquete['calidad'] ?? {});
    final fg = Map<String, dynamic>.from(cal['fijas_global'] ?? {});
    final est = Map<String, dynamic>.from(cal['estimaciones'] ?? {});
    final jug = Map<String, dynamic>.from(cal['jugadores'] ?? {});
    final porM = Historial.porMercado(boletas);
    final porA = Historial.porAutor(boletas);
    final resueltas = boletas.where((b) => b['estado'] == 'ganada' || b['estado'] == 'perdida').toList();
    final patas = porM.values.fold<int>(0, (a, v) => a + v.total);
    final conP = porM.values.fold<int>(0, (a, v) => a + v.conP);
    final jugLineas = Map<String, dynamic>.from(lineas['jug_arco'] ?? {});
    return Scaffold(
      appBar: AppBar(backgroundColor: Col.panel, title: const Text('🧠 Aprendizaje')),
      body: !listo
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _cargar,
              child: ListView(padding: const EdgeInsets.all(12), children: [
                _tarjeta('Cómo aprende FútBot', [
                  const Text('1️⃣ Cada día, en la nube (6:00 y 18:00): baja los resultados y estadísticas de miles de partidos, '
                      'vuelve a ajustar sus modelos y revisa con partidos pasados si sus porcentajes se cumplen. Si un mercado '
                      'se equivoca, su probabilidad se corrige (calibración).'),
                  const SizedBox(height: 6),
                  const Text('2️⃣ En tu celular: cada apuesta que guardas (de la Súper boleta, del chat o de una captura, tuya o '
                      'de un tipster) se sigue en vivo con ESPN. Al terminar, cada selección queda como acertada o fallada y eso '
                      'corrige las probabilidades del chat para ese tipo de mercado (con prudencia: pesa más cuantas más tengas).'),
                  const SizedBox(height: 6),
                  const Text('3️⃣ Capturas de apuestas ya resueltas: mándalas al chat (🖼️). Si dicen «Ganada» o «Perdida» se '
                      'guardan solas en tu historial y suman a tu acierto por mercado.'),
                  const SizedBox(height: 6),
                  const Text('4️⃣ Internet: antes de opinar busca noticias y pronósticos del partido (Google Noticias) y te avisa '
                      'de posibles bajas. No cambia los porcentajes con opiniones sueltas: las cuotas de las casas ya reúnen lo '
                      'que saben miles de apostadores y analistas, y el bot las usa en su «modelo de mercado».'),
                  const SizedBox(height: 6),
                  const Text('5️⃣ Al conectar el cable (actualizar_celular.bat), la PC trae lo aprendido; las líneas de Betano '
                      'que viste en capturas se suben a la nube para todos los cálculos.', style: TextStyle(color: Col.suave)),
                ]),
                if (fg.isNotEmpty || est.isNotEmpty || jug.isNotEmpty)
                  _tarjeta('Lo que la nube comprobó con partidos pasados', [
                    if (fg.isNotEmpty)
                      Text('Fijas del bot: ${fg['n']} predicciones (${cal['partidos']} partidos, ${cal['periodo']}). Decía '
                          '${pct((fg['prob_media'] as num).toDouble())} y acertaron ${pct((fg['acierto_real'] as num).toDouble())}.'),
                    if (est.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text('Córners, tarjetas, tiros al arco y atajadas por promedios (${est['periodo']}):',
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                      for (final e in Map<String, dynamic>.from(est['mercados'] ?? {}).entries)
                        Text('• ${e.key.replaceAll('|', ' ')}: decía ${pct((e.value['prob'] as num).toDouble())}, pasó '
                            '${pct((e.value['real'] as num).toDouble())} (${e.value['n']} casos)', style: const TextStyle(fontSize: 12.5)),
                    ],
                    if (jug.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      const Text('Jugadores (titulares):', style: TextStyle(fontWeight: FontWeight.w700)),
                      for (final e in jug.entries)
                        for (final x in (e.value as List))
                          Text('• ${x['evento']}: decía ${pct((x['prob'] as num).toDouble())}, pasó ${pct((x['real'] as num).toDouble())} '
                              '(${x['n']} casos)', style: const TextStyle(fontSize: 12.5)),
                      const Text('Ni los mejores delanteros pasan de ~60% de marcar: por eso «jugador marca gol» nunca es muy segura.',
                          style: TextStyle(color: Col.suave, fontSize: 12)),
                    ],
                  ]),
                _tarjeta('Lo que aprendió de ti', [
                  Text('${boletas.length} apuestas guardadas · ${resueltas.length} terminadas · $patas selecciones resueltas'
                      '${conP > 0 ? ' ($conP con probabilidad del bot: son las que corrigen el chat)' : ''}.'),
                  if (porM.isEmpty)
                    const Text('Todavía no hay selecciones resueltas. Guarda tus apuestas o manda capturas de «Mis apuestas».',
                        style: TextStyle(color: Col.suave)),
                  for (final e in (porM.entries.toList()..sort((a, b) => b.value.total.compareTo(a.value.total))))
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      title: Text(_nombresMercado[e.key] ?? e.key),
                      subtitle: Text('${e.value.aciertos}/${e.value.total} acertadas'
                          '${e.value.conP > 0 ? ' · el bot prometía ${pct(e.value.prometido)}' : ''}'),
                      trailing: Text(pct(e.value.real), style: TextStyle(fontWeight: FontWeight.w900, color: colorProb(e.value.real))),
                    ),
                ]),
                if (porA.isNotEmpty)
                  _tarjeta('¿Quién acierta más?', [
                    for (final e in porA.entries)
                      Text('${e.key}: ${e.value[0].toInt()}/${e.value[1].toInt()} apuestas ganadas (${pct(e.value[0] / e.value[1])})'),
                  ]),
                if (jugLineas.isNotEmpty)
                  _tarjeta('Líneas de Betano aprendidas de tus capturas', [
                    for (final e in jugLineas.entries)
                      Text('• ${e.key}: tiros al arco desde ${e.value['min'] ?? (e.value['lineas'] as List?)?.first ?? '?'}+'),
                  ]),
                _tarjeta('Investigaciones en internet', [
                  if (inv.isEmpty) const Text('Aún no investigó ningún partido: pídele «analiza Barcelona» o mándale una captura.',
                      style: TextStyle(color: Col.suave)),
                  for (final x in inv.take(12))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Text('🔎 ${x['partido']} · ${diaHora(DateTime.tryParse('${x['fecha']}') ?? DateTime.now())} · '
                          '${x['n']} noticias${(x['bajas'] ?? 0) > 0 ? ' · ⚠️ ${x['bajas']} sobre bajas' : ''}'
                          '${(x['titulares'] as List?)?.isNotEmpty == true ? '\n   «${(x['titulares'] as List).first}»' : ''}',
                          style: const TextStyle(fontSize: 12.5)),
                    ),
                ]),
              ]),
            ),
    );
  }

  Widget _tarjeta(String titulo, List<Widget> hijos) => Card(
        color: Col.tarjeta,
        margin: const EdgeInsets.only(bottom: 12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(titulo, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15, color: Col.naranja)),
            const SizedBox(height: 6),
            ...hijos,
          ]),
        ),
      );
}
