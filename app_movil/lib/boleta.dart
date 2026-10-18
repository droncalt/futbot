// Súper boleta en vivo: marcar/desmarcar líneas y patas, cambiar cuotas y monto recalcula al instante.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';

class EstadoLinea {
  bool on;
  int mask;
  double? manual;
  EstadoLinea(this.on, this.mask);
}

class Calculo {
  double cuota = 1, p = 1, minCuota = 99;
  int n = 0;
  bool mbOk = true, seguroOk = true;
}

class PantallaBoleta extends StatefulWidget {
  const PantallaBoleta({super.key});
  @override
  State<PantallaBoleta> createState() => _PantallaBoletaState();
}

class _PantallaBoletaState extends State<PantallaBoleta> {
  String nivel = 'segura', dia = 'todos';
  int nLineas = 0; // 0 = automático
  bool usarObjetivo = false;
  double objetivo = 3;
  double monto = 10;
  final montoCtrl = TextEditingController(text: '10.00');
  List<Linea> lineas = [];
  final estados = <String, EstadoLinea>{};
  final cuotaCtrls = <String, TextEditingController>{};

  @override
  void initState() {
    super.initState();
    _armar();
  }

  void _armar() {
    final ahora = DateTime.now();
    final hoy = DateTime(ahora.year, ahora.month, ahora.day);
    var ls = repo.lineas(nivel).where((l) => l.inicio.isAfter(ahora)).toList();
    if (dia == 'hoy') ls = ls.where((l) => l.inicio.isBefore(hoy.add(const Duration(days: 1)))).toList();
    if (dia == 'manana') {
      ls = ls.where((l) => !l.inicio.isBefore(hoy.add(const Duration(days: 1))) && l.inicio.isBefore(hoy.add(const Duration(days: 2)))).toList();
    }
    ls.sort((a, b) => b.p.compareTo(a.p));
    final marcadas = <int>[];
    var c = 1.0;
    for (var i = 0; i < ls.length; i++) {
      if (nLineas > 0 && marcadas.length >= nLineas) break;
      if (nLineas == 0 && usarObjetivo && c >= objetivo) break;
      if (nLineas == 0 && !usarObjetivo && marcadas.length >= 4) break;
      marcadas.add(i);
      c *= ls[i].cuota;
      if (marcadas.length >= 10) break;
    }
    lineas = [...marcadas.map((i) => ls[i]), ...List.generate(ls.length, (i) => i).where((i) => !marcadas.contains(i)).take(12).map((i) => ls[i])];
    estados.clear();
    for (var i = 0; i < lineas.length; i++) {
      estados[lineas[i].id] = EstadoLinea(i < marcadas.length, lineas[i].completa);
    }
    for (final l in lineas) {
      cuotaCtrls.putIfAbsent(l.id, () => TextEditingController());
      cuotaCtrls[l.id]!.text = f2(_sub(l).cuota);
    }
  }

  Sub _sub(Linea l) {
    final e = estados[l.id]!;
    return l.sub[e.mask] ?? Sub(l.p, l.cuota, l.estimada);
  }

  double _cuotaLinea(Linea l) => estados[l.id]!.manual ?? _sub(l).cuota;

  Calculo _calcular() {
    final r = Calculo();
    for (final l in lineas) {
      final e = estados[l.id]!;
      if (!e.on || e.mask == 0) continue;
      final c = _cuotaLinea(l);
      r.cuota *= c;
      r.p *= _sub(l).p;
      r.n++;
      final completa = e.mask == l.completa && l.patas.length == 1;
      if (!(l.multibono && completa)) r.mbOk = false;
      if (!(l.seguro && completa)) r.seguroOk = false;
      if (c < r.minCuota) r.minCuota = c;
    }
    if (r.n == 0) {
      r.cuota = 0;
      r.p = 0;
    }
    return r;
  }

  String _tipo(int n) => n == 1 ? 'Simple' : n == 2 ? 'Doble' : n == 3 ? 'Triple' : 'Combinada de $n';

  String _texto(Calculo r) {
    final t = <String>['${_tipo(r.n)} · propuesta de FútBot (verifica cuotas en Betano)', ''];
    for (final l in lineas) {
      final e = estados[l.id]!;
      if (!e.on || e.mask == 0) continue;
      final patas = [for (var i = 0; i < l.patas.length; i++) if ((e.mask >> i) & 1 == 1) l.patas[i]];
      final c = f2(_cuotaLinea(l));
      if (patas.length > 1) {
        t.add('⚽ Bet Builder [$c] · ${l.local.nombre} vs ${l.visitante.nombre} · ${diaHora(l.inicio)}');
        for (final p in patas) {
          t.add('   • ${p.titulo} — ${p.mercado}');
        }
      } else {
        t.add('⚽ ${patas.first.titulo} — ${patas.first.mercado} [$c]');
        t.add('   ${l.local.nombre} vs ${l.visitante.nombre} · ${diaHora(l.inicio)}');
      }
    }
    t.addAll(['', 'Cuota total: ${f2(r.cuota)}', 'Apuesta: S/${f2(monto)}', 'Ganancias potenciales: S/${f2(monto * r.cuota)}',
      'Probabilidad de acertar todo: ${pct(r.p)}']);
    return t.join('\n');
  }

  Future<void> _guardar(String tipo) async {
    final r = _calcular();
    if (r.n == 0) return;
    final ls = <Map<String, dynamic>>[];
    for (final l in lineas) {
      final e = estados[l.id]!;
      if (!e.on || e.mask == 0) continue;
      ls.add({
        'liga': l.liga, 'inicio': l.inicio.toIso8601String(), 'local': l.local.nombre, 'visitante': l.visitante.nombre,
        'cuota': _cuotaLinea(l), 'p': _sub(l).p,
        'patas': [for (var i = 0; i < l.patas.length; i++) if ((e.mask >> i) & 1 == 1) {'titulo': l.patas[i].titulo, 'mercado': l.patas[i].mercado, 'sel': l.patas[i].sel}],
      });
    }
    await Historial.guardar({
      'id': DateTime.now().millisecondsSinceEpoch, 'fecha': DateTime.now().toIso8601String(), 'tipo': tipo,
      'monto': tipo == 'apostada' ? monto : 0, 'cuota': r.cuota, 'p': r.p, 'estado': 'pendiente', 'lineas': ls,
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(tipo == 'apostada' ? '✅ Guardada en tu historial. Se liquida sola con los resultados.'
              : '👁️ Guardada en seguimiento (sin dinero).')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _calcular();
    final niveles = repo.niveles;
    return Column(children: [
      Expanded(
        child: ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 16), children: [
          Text('Súper boleta segura', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
          Text('Datos: ${repo.paquete['generado_peru'] ?? '—'} (${repo.origen})', style: const TextStyle(color: Col.suave, fontSize: 12)),
          const SizedBox(height: 10),
          SegmentedButton<String>(
            segments: [
              for (final k in ['ultra', 'segura', 'equilibrada'])
                ButtonSegment(value: k, label: Text('${niveles[k]?['emoji'] ?? ''} ${niveles[k]?['nombre'] ?? k}',
                    style: const TextStyle(fontSize: 12))),
            ],
            selected: {nivel},
            onSelectionChanged: (s) => setState(() { nivel = s.first; _armar(); }),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 6, children: [
            for (final d in [('todos', 'Próximos días'), ('hoy', 'Hoy'), ('manana', 'Mañana')])
              ChoiceChip(label: Text(d.$2), selected: dia == d.$1, onSelected: (_) => setState(() { dia = d.$1; _armar(); })),
          ]),
          const SizedBox(height: 4),
          Wrap(spacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            const Text('Líneas:', style: TextStyle(color: Col.suave)),
            for (final n in [0, 2, 3, 4, 5, 6, 8, 10])
              ChoiceChip(label: Text(n == 0 ? 'Auto' : '$n'), selected: nLineas == n,
                  onSelected: (_) => setState(() { nLineas = n; _armar(); })),
          ]),
          Row(children: [
            Switch(value: usarObjetivo, onChanged: (v) => setState(() { usarObjetivo = v; nLineas = 0; _armar(); })),
            const Text('Cuota objetivo'),
            if (usarObjetivo)
              Expanded(child: Slider(value: objetivo, min: 1.5, max: 20, divisions: 37, label: f2(objetivo),
                  onChanged: (v) => setState(() { objetivo = v; _armar(); }))),
            if (usarObjetivo) Text(f2(objetivo), style: const TextStyle(fontWeight: FontWeight.w800)),
          ]),
          const SizedBox(height: 6),
          if (lineas.isEmpty)
            const Card(child: Padding(padding: EdgeInsets.all(16),
                child: Text('No hay partidos que cumplan el nivel para ese día. Prueba otro día o baja el nivel.')))
          else
            _ticket(r),
          const SizedBox(height: 8),
          const Text('Cada línea suelta es muy probable, pero la combinada entera no: mira «Prob. de acertar todo». '
              'Las cuotas «≈» son estimadas: escribe la real de Betano.', style: TextStyle(color: Col.suave, fontSize: 12)),
        ]),
      ),
      _barraResumen(r),
    ]);
  }

  Widget _ticket(Calculo r) {
    return Container(
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: const BoxDecoration(gradient: LinearGradient(colors: [Color(0xFFFF7A1A), Col.naranjaOsc])),
          child: Text('${r.n == 0 ? 'Sin selecciones' : '${_tipo(r.n)} · ${r.n} ${r.n > 1 ? 'selecciones' : 'selección'}'}'
              '   ·   para copiar en Betano', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
        ),
        for (final l in lineas) _linea(l),
      ]),
    );
  }

  Widget _linea(Linea l) {
    final e = estados[l.id]!;
    final activas = [for (var i = 0; i < l.patas.length; i++) if ((e.mask >> i) & 1 == 1) l.patas[i]];
    final bb = activas.length > 1;
    final sub = _sub(l);
    final estimada = e.manual == null && sub.estimada;
    return Opacity(
      opacity: e.on && e.mask != 0 ? 1 : 0.45,
      child: Container(
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFFE6E9EF)))),
        padding: const EdgeInsets.fromLTRB(4, 8, 12, 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Checkbox(value: e.on, activeColor: Col.naranja, onChanged: (v) => setState(() => e.on = v ?? false)),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text('⚽ ${bb ? 'Bet Builder' : (activas.isEmpty ? l.patas.first : activas.first).titulo}',
                    style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15, color: bb ? const Color(0xFFC2410C) : Col.tinta))),
                if (estimada) const Text('≈ ', style: TextStyle(color: Color(0xFF8A94A8), fontWeight: FontWeight.w800)),
                SizedBox(
                  width: 64,
                  child: TextField(
                    controller: cuotaCtrls[l.id],
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    textAlign: TextAlign.right,
                    style: const TextStyle(fontWeight: FontWeight.w800, color: Col.tinta),
                    decoration: const InputDecoration(isDense: true, filled: true, fillColor: Color(0xFFF1F3F7),
                        border: OutlineInputBorder(borderSide: BorderSide.none), contentPadding: EdgeInsets.symmetric(horizontal: 6, vertical: 6)),
                    onChanged: (t) => setState(() {
                      final v = double.tryParse(t.replaceAll(',', '.'));
                      e.manual = v != null && v > 1 ? v : null;
                    }),
                  ),
                ),
              ]),
              if (!bb && activas.isNotEmpty) Text(activas.first.mercado, style: const TextStyle(color: Col.gris, fontSize: 13)),
              const SizedBox(height: 4),
              EquipoFila(l.local),
              EquipoFila(l.visitante),
              if (l.patas.length > 1)
                for (var i = 0; i < l.patas.length; i++)
                  Container(
                    margin: const EdgeInsets.only(top: 4),
                    padding: const EdgeInsets.only(left: 6),
                    decoration: const BoxDecoration(border: Border(left: BorderSide(color: Color(0xFFF0A37A), width: 2))),
                    child: Row(children: [
                      SizedBox(width: 30, height: 30, child: Checkbox(
                          value: (e.mask >> i) & 1 == 1, activeColor: Col.naranja,
                          onChanged: (_) => setState(() {
                            e.mask ^= (1 << i);
                            e.manual = null;
                            e.on = e.mask != 0;
                            cuotaCtrls[l.id]!.text = f2(_sub(l).cuota);
                          }))),
                      Expanded(child: Text.rich(TextSpan(children: [
                        TextSpan(text: '${l.patas[i].titulo} ', style: const TextStyle(fontWeight: FontWeight.w800, color: Col.tinta)),
                        TextSpan(text: '${l.patas[i].mercado} · ${pct(l.patas[i].p)}', style: const TextStyle(color: Col.gris, fontSize: 12.5)),
                      ]))),
                    ]),
                  ),
              const SizedBox(height: 6),
              Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                ChipProb(sub.p),
                Text('🕒 ${diaHora(l.inicio)}', style: const TextStyle(color: Col.gris, fontSize: 12)),
                Text(l.ligaNombre, style: const TextStyle(color: Col.gris, fontSize: 12)),
                InkWell(onTap: () => abrir(l.betano),
                    child: const Text('Ver en Betano ↗', style: TextStyle(color: Col.naranjaOsc, fontWeight: FontWeight.w800, fontSize: 12.5))),
              ]),
              for (final a in l.avisos.take(2))
                Padding(padding: const EdgeInsets.only(top: 3),
                    child: Text('⚠️ $a', style: const TextStyle(color: Color(0xFF8A6D1D), fontSize: 11))),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _barraResumen(Calculo r) {
    final gan = monto * r.cuota;
    String mb = '';
    if (r.n >= 3 && r.mbOk && r.minCuota >= 1.5) {
      final p = repo.multibono['${r.n > 24 ? 24 : r.n}'] ?? 0;
      if (p > 0) mb = '🎁 Multi Bono +$p %: ≈ +S/${f2((gan - monto) * p / 100)} si acierta';
    }
    return Material(
      color: Col.panel,
      elevation: 8,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              const Text('Monto S/ ', style: TextStyle(fontWeight: FontWeight.w800)),
              SizedBox(width: 78, child: TextField(
                controller: montoCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 17),
                decoration: const InputDecoration(isDense: true, border: OutlineInputBorder(), contentPadding: EdgeInsets.all(8)),
                onChanged: (t) => setState(() => monto = double.tryParse(t.replaceAll(',', '.')) ?? 0),
              )),
              const SizedBox(width: 6),
              Expanded(child: SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
                for (final a in [5, 10, 20, 50])
                  Padding(padding: const EdgeInsets.only(right: 4), child: ActionChip(
                    label: Text('+$a'), visualDensity: VisualDensity.compact,
                    onPressed: () => setState(() { monto += a; montoCtrl.text = f2(monto); }))),
                ActionChip(label: const Text('Borrar'), visualDensity: VisualDensity.compact,
                    onPressed: () => setState(() { monto = 0; montoCtrl.text = '0'; })),
              ]))),
            ]),
            const SizedBox(height: 6),
            Row(children: [
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Cuota ${r.n == 0 ? '—' : f2(r.cuota)} · acertar todo ${r.n == 0 ? '—' : pct(r.p)}',
                    style: TextStyle(color: r.n == 0 ? Col.suave : colorProb(r.p), fontWeight: FontWeight.w800)),
                if (r.n > 0) Text('De cada 10 boletas así, ≈ ${((1 - r.p) * 10).round()} se caen.',
                    style: const TextStyle(color: Col.suave, fontSize: 11.5)),
                if (mb.isNotEmpty) Text(mb, style: const TextStyle(color: Color(0xFF34D399), fontSize: 11.5)),
                if (monto > 0 && monto < repo.apuestaMinima)
                  Text('Mínimo en Betano: S/${f2(repo.apuestaMinima)}', style: const TextStyle(color: Col.rosa, fontSize: 11.5)),
              ])),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                const Text('Ganancias potenciales', style: TextStyle(color: Col.suave, fontSize: 11.5)),
                Text('S/${f2(gan)}', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
              ]),
            ]),
            const SizedBox(height: 6),
            Row(children: [
              Expanded(child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: Col.naranjaOsc),
                onPressed: r.n == 0 ? null : () => _guardar('apostada'),
                icon: const Icon(Icons.check), label: const Text('La aposté'))),
              const SizedBox(width: 6),
              IconButton.filledTonal(tooltip: 'Solo seguimiento', onPressed: r.n == 0 ? null : () => _guardar('seguimiento'),
                  icon: const Icon(Icons.visibility_outlined)),
              IconButton.filledTonal(tooltip: 'Copiar texto', onPressed: r.n == 0 ? null : () {
                Clipboard.setData(ClipboardData(text: _texto(r)));
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('📋 Boleta copiada')));
              }, icon: const Icon(Icons.copy)),
              IconButton.filledTonal(tooltip: 'Abrir Betano', onPressed: () => abrir('https://www.betano.pe/sport/futbol/'),
                  icon: const Icon(Icons.open_in_new)),
            ]),
          ]),
        ),
      ),
    );
  }
}
