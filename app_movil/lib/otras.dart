// Partidos, reglas de Betano y ajustes.
import 'dart:async';

import 'package:flutter/material.dart';

import 'comunes.dart';
import 'boleta.dart' show BuscadorEquipos;
import 'captura.dart';
import 'datos.dart';
import 'vivo.dart';

class PantallaPartidos extends StatefulWidget {
  const PantallaPartidos({super.key});
  @override
  State<PantallaPartidos> createState() => _PantallaPartidosState();
}

class _PantallaPartidosState extends State<PantallaPartidos> {
  String busqueda = '';

  @override
  Widget build(BuildContext context) {
    final ahora = DateTime.now();
    final q = normal(busqueda);
    final ps = repo.partidos.where((p) => DateTime.tryParse(p['inicio'].toString().replaceAll(' ', 'T'))?.isAfter(
        ahora.subtract(const Duration(hours: 2))) ?? true)
        .where((p) => q.isEmpty || normal('${p['local']?['nombre']} ${p['visitante']?['nombre']} ${p['liga_nombre']}').contains(q))
        .toList();
    String? diaPrevio;
    final hijos = <Widget>[
      Text('Partidos', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
      const Text('Probabilidades del bot (modelo + mercado). Hora de Perú.', style: TextStyle(color: Col.suave, fontSize: 12)),
      const SizedBox(height: 8),
      BuscadorEquipos(valor: busqueda, alCambiar: (v) => setState(() => busqueda = v)),
    ];
    for (final p in ps) {
      final ini = DateTime.parse(p['inicio'].toString().replaceAll(' ', 'T'));
      final dia = diaHora(ini).substring(0, 9);
      if (dia != diaPrevio) {
        hijos.add(Padding(padding: const EdgeInsets.only(top: 14, bottom: 4),
            child: Text(dia, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))));
        diaPrevio = dia;
      }
      hijos.add(_tarjeta(p, ini));
    }
    if (ps.isEmpty) {
      hijos.add(Padding(padding: const EdgeInsets.all(16), child: Text(busqueda.isEmpty
          ? 'No hay partidos próximos en el paquete.' : 'Ningún partido próximo de «$busqueda» en las ligas del bot.')));
    }
    return ListView(padding: const EdgeInsets.all(12), children: hijos);
  }

  Widget _tarjeta(Map<String, dynamic> p, DateTime ini) {
    final pr = Map<String, dynamic>.from(p['prob'] ?? {});
    double v(String k) => (pr[k] as num?)?.toDouble() ?? 0;
    final local = Equipo.de(Map<String, dynamic>.from(p['local'])), visit = Equipo.de(Map<String, dynamic>.from(p['visitante']));
    final s = v('1') + v('X') + v('2');
    Widget barra(double x, Color c) => Expanded(flex: ((s == 0 ? 0 : x / s) * 1000).round().clamp(1, 1000), child: Container(height: 7, color: c));
    return Card(
      color: Col.tarjeta,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('🕒 ${diaHora(ini).substring(10)} · ${p['liga_nombre']}', style: const TextStyle(color: Col.suave, fontSize: 12)),
          const SizedBox(height: 4),
          EquipoFila(local, color: Col.texto, tam: 22),
          EquipoFila(visit, color: Col.texto, tam: 22),
          const SizedBox(height: 6),
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text('Local ${pct(v('1'))}', style: const TextStyle(color: Col.suave, fontSize: 12)),
            Text('Empate ${pct(v('X'))}', style: const TextStyle(color: Col.suave, fontSize: 12)),
            Text('Visita ${pct(v('2'))}', style: const TextStyle(color: Col.suave, fontSize: 12)),
          ]),
          ClipRRect(borderRadius: BorderRadius.circular(6), child: Row(children: [
            barra(v('1'), const Color(0xFF34D399)), barra(v('X'), const Color(0xFF64748B)), barra(v('2'), const Color(0xFF60A5FA)),
          ])),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            ChipProb(v('Más 1.5'), sufijo: ' Más 1.5'),
            ChipProb(v('Menos 3.5'), sufijo: ' Menos 3.5'),
            ChipProb(v('Ambos anotan'), sufijo: ' Ambos anotan'),
            if (p['goles_esperados'] != null)
              Text('goles esp. ${f2((p['goles_esperados'] as num).toDouble())}', style: const TextStyle(color: Col.suave, fontSize: 12)),
            InkWell(onTap: () => abrir(p['betano']),
                child: const Text('Ver en Betano ↗', style: TextStyle(color: Col.naranja, fontWeight: FontWeight.w800))),
            InkWell(onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VivoPartido(
                    liga: '${p['liga']}', local: local.nombre, visitante: visit.nombre, inicio: ini))),
                child: const Text('📡 En vivo / estadísticas', style: TextStyle(color: Color(0xFF34D399), fontWeight: FontWeight.w800))),
          ]),
        ]),
      ),
    );
  }
}

/// Estadísticas en vivo de cualquier partido (sin necesidad de guardarlo en una boleta).
class VivoPartido extends StatefulWidget {
  final String liga, local, visitante;
  final DateTime inicio;
  const VivoPartido({super.key, required this.liga, required this.local, required this.visitante, required this.inicio});
  @override
  State<VivoPartido> createState() => _VivoPartidoState();
}

class _VivoPartidoState extends State<VivoPartido> {
  Estado? e;
  String? error;
  Timer? reloj;

  @override
  void initState() {
    super.initState();
    _leer();
    reloj = Timer.periodic(const Duration(seconds: 60), (_) => _leer());
  }

  @override
  void dispose() {
    reloj?.cancel();
    super.dispose();
  }

  Future<void> _leer() async {
    final id = await Espn.buscar(widget.liga, widget.local, widget.visitante, widget.inicio);
    final x = id == null ? null : await Espn.estado(id);
    if (!mounted) return;
    setState(() {
      e = x;
      error = id == null ? 'Aún no encuentro este partido en ESPN. Se reintenta cada minuto.' : null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (e != null) return DetallePartido(e: e!, linea: const {'patas': []});
    return Scaffold(
      appBar: AppBar(backgroundColor: Col.panel, title: Text('${widget.local} vs ${widget.visitante}')),
      body: Center(child: error == null ? const CircularProgressIndicator()
          : Padding(padding: const EdgeInsets.all(24), child: Text(error!, textAlign: TextAlign.center))),
    );
  }
}

class PantallaReglas extends StatefulWidget {
  const PantallaReglas({super.key});
  @override
  State<PantallaReglas> createState() => _PantallaReglasState();
}

class _PantallaReglasState extends State<PantallaReglas> {
  String q = '';
  @override
  Widget build(BuildContext context) {
    final rs = repo.reglas.where((r) => q.isEmpty || ('${r['titulo']} ${r['texto']} ${(r['claves'] as List?)?.join(' ')}')
        .toLowerCase().contains(q.toLowerCase())).toList();
    return ListView(padding: const EdgeInsets.all(12), children: [
      Text('Reglas de Betano', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
      const Text('Resumen del centro de ayuda oficial de Betano Perú.', style: TextStyle(color: Col.suave, fontSize: 12)),
      const SizedBox(height: 8),
      TextField(decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Buscar: tarjetas, pago anticipado, suspendido…',
          border: OutlineInputBorder()), onChanged: (t) => setState(() => q = t)),
      const SizedBox(height: 8),
      for (final r in rs)
        Card(color: Col.tarjeta, child: ExpansionTile(
          title: Text(r['titulo'] ?? '', style: const TextStyle(fontWeight: FontWeight.w800)),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          children: [
            Text(r['texto'] ?? '', style: const TextStyle(height: 1.45)),
            Align(alignment: Alignment.centerRight, child: TextButton(onPressed: () => abrir(r['url']), child: const Text('Fuente oficial ↗'))),
          ],
        )),
    ]);
  }
}

class PantallaAjustes extends StatefulWidget {
  final VoidCallback alActualizar;
  const PantallaAjustes({super.key, required this.alActualizar});
  @override
  State<PantallaAjustes> createState() => _PantallaAjustesState();
}

class _PantallaAjustesState extends State<PantallaAjustes> {
  late final ctrl = TextEditingController(text: repo.urlBase);
  String mensaje = '';
  bool cargando = false;

  Future<void> _actualizar() async {
    setState(() => cargando = true);
    await repo.guardarUrl(ctrl.text);
    final m = await repo.actualizar();
    setState(() { mensaje = m; cargando = false; });
    widget.alActualizar();
  }

  @override
  Widget build(BuildContext context) {
    final cal = Map<String, dynamic>.from(repo.paquete['calidad'] ?? {});
    final fg = cal['fijas_global'] as Map?;
    return ListView(padding: const EdgeInsets.all(12), children: [
      Text('Más', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
      const SizedBox(height: 8),
      Card(color: Col.tarjeta, child: ListTile(
        leading: const Icon(Icons.document_scanner), title: const Text('Capturas'),
        subtitle: const Text('Lee tu combinada de Betano, opina y la sigue en vivo'), trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => Scaffold(
            appBar: AppBar(backgroundColor: Col.panel, title: const Text('Capturas')), body: const PantallaCapturas()))),
      )),
      Card(color: Col.tarjeta, child: ListTile(
        leading: const Icon(Icons.menu_book), title: const Text('Reglas de Betano'),
        subtitle: const Text('Multi Bono, Seguro, Pago Anticipado, apuesta mínima…'), trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => Scaffold(
            appBar: AppBar(backgroundColor: Col.panel, title: const Text('Reglas de Betano')), body: const PantallaReglas()))),
      )),
      const SizedBox(height: 8),
      const Text('Dirección de datos (tu GitHub Pages)', style: TextStyle(fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      TextField(controller: ctrl, keyboardType: TextInputType.url, decoration: const InputDecoration(
          hintText: 'https://TU-USUARIO.github.io/futbot/', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      FilledButton.icon(onPressed: cargando ? null : _actualizar, icon: cargando
          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.sync),
          label: const Text('Guardar y actualizar ahora')),
      if (mensaje.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(mensaje)),
      const SizedBox(height: 16),
      Card(color: Col.tarjeta, child: Padding(padding: const EdgeInsets.all(12), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Datos: ${repo.paquete['generado_peru'] ?? '—'} (${repo.origen})'),
        if (fg != null)
          Text('Prueba de la temporada pasada: fijas ≥ 75 % del bot acertaron ${pct((fg['acierto_real'] as num).toDouble())} '
              '(${fg['n']} casos). Nada es 100 % seguro.', style: const TextStyle(color: Col.suave)),
      ]))),
      const SizedBox(height: 12),
      const Text('Cómo funciona', style: TextStyle(fontWeight: FontWeight.w800)),
      const Text('• La nube de GitHub calcula todo 2 veces al día (6:00 y 18:00) y la app lo descarga sola al abrirla.\n'
          '• Sin internet usa lo último descargado.\n'
          '• Para una versión nueva de la app solo instalas el APK nuevo (por cable o WhatsApp); tus datos se conservan.\n'
          '• El chat con IA y los videos de tipsters siguen en la PC (no caben en el celular).',
          style: TextStyle(color: Col.suave, height: 1.5)),
      const SizedBox(height: 12),
      const Text('Juega con responsabilidad · Mayores de 18 · Ninguna apuesta es segura.',
          style: TextStyle(color: Col.suave, fontSize: 12)),
    ]);
  }
}
