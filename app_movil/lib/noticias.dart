// Investigación en internet en tiempo real: Google Noticias (RSS público) sobre el partido — pronósticos de
// otros analistas, alineaciones, lesionados y suspendidos. Marca las noticias que hablan de bajas.
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Noticia {
  final String titulo, fuente, enlace;
  final DateTime? fecha;
  final bool baja; // habla de lesión, baja, suspensión o duda
  Noticia(this.titulo, this.fuente, this.enlace, this.fecha, this.baja);
}

final _cache = <String, (DateTime, List<Noticia>)>{};

const _palabrasBaja = ['lesi', 'baja', 'bajas', 'duda', 'no estar', 'suspend', 'sancion', 'descart', 'se pierde',
  'injur', 'ruled out', 'out for', 'doubt', 'suspended', 'misses', 'will miss', 'sin '];

String _limpio(String t) => t
    .replaceAll('<![CDATA[', '').replaceAll(']]>', '').replaceAll('&amp;', '&').replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>').trim();

/// Noticias recientes del partido (últimos 4 días), primero las que hablan de bajas. Se guardan 30 minutos.
Future<List<Noticia>> buscarNoticias(String local, String visitante, {int max = 6}) async {
  final clave = '$local|$visitante';
  final c = _cache[clave];
  if (c != null && DateTime.now().difference(c.$1).inMinutes < 30) return c.$2;
  final out = <Noticia>[];
  final vistos = <String>{};
  for (final q in ['$local $visitante pronóstico', '$local $visitante alineaciones bajas']) {
    try {
      final u = Uri.https('news.google.com', '/rss/search', {'q': '$q when:4d', 'hl': 'es-419', 'gl': 'PE', 'ceid': 'PE:es-419'});
      final r = await http.get(u).timeout(const Duration(seconds: 15));
      if (r.statusCode != 200) continue;
      final xml = r.body;
      for (final m in RegExp(r'<item>([\s\S]*?)</item>').allMatches(xml)) {
        final it = m.group(1)!;
        String campo(String n) => _limpio(RegExp('<$n[^>]*>([\\s\\S]*?)</$n>').firstMatch(it)?.group(1) ?? '');
        var titulo = campo('title');
        final fuente = campo('source');
        if (fuente.isNotEmpty && titulo.endsWith(' - $fuente')) titulo = titulo.substring(0, titulo.length - fuente.length - 3);
        if (titulo.isEmpty || !vistos.add(titulo.toLowerCase())) continue;
        final t = titulo.toLowerCase();
        out.add(Noticia(titulo, fuente, campo('link'), _fecha(campo('pubDate')), _palabrasBaja.any(t.contains)));
      }
    } catch (_) {}
  }
  out.sort((a, b) => a.baja != b.baja ? (a.baja ? -1 : 1) : (b.fecha ?? DateTime(2000)).compareTo(a.fecha ?? DateTime(2000)));
  final res = out.take(max).toList();
  _cache[clave] = (DateTime.now(), res);
  await _anotar('$local vs $visitante', res);
  return res;
}

/// Registro de lo investigado (para la sección «Aprendizaje»): últimas 40 búsquedas.
Future<void> _anotar(String partido, List<Noticia> ns) async {
  try {
    final pref = await SharedPreferences.getInstance();
    final lista = (jsonDecode(pref.getString('investigaciones') ?? '[]') as List).cast<dynamic>();
    lista.insert(0, {'fecha': DateTime.now().toIso8601String(), 'partido': partido, 'n': ns.length,
      'bajas': ns.where((n) => n.baja).length, 'titulares': [for (final n in ns.take(3)) n.titulo]});
    await pref.setString('investigaciones', jsonEncode(lista.take(40).toList()));
  } catch (_) {}
}

Future<List<Map<String, dynamic>>> investigaciones() async {
  try {
    final pref = await SharedPreferences.getInstance();
    return (jsonDecode(pref.getString('investigaciones') ?? '[]') as List).map((e) => Map<String, dynamic>.from(e)).toList();
  } catch (_) {
    return [];
  }
}

const _meses = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12};

DateTime? _fecha(String s) {
  final m = RegExp(r'(\d{1,2}) (\w{3}) (\d{4}) (\d{2}):(\d{2})').firstMatch(s);
  if (m == null) return null;
  return DateTime.utc(int.parse(m.group(3)!), _meses[m.group(2)] ?? 1, int.parse(m.group(1)!), int.parse(m.group(4)!),
          int.parse(m.group(5)!))
      .toLocal();
}

/// Texto corto para el chat: "🔎 Investigué en internet…" con las noticias y los avisos de bajas.
String resumenNoticias(String partido, List<Noticia> ns) {
  if (ns.isEmpty) return '🔎 $partido: no encontré noticias recientes en internet.';
  final b = StringBuffer('🔎 $partido — lo que encontré en internet:\n');
  for (final n in ns.take(4)) {
    b.writeln('${n.baja ? '⚠️' : '•'} ${n.titulo}${n.fuente.isNotEmpty ? ' (${n.fuente})' : ''}');
  }
  if (ns.any((n) => n.baja)) b.writeln('⚠️ Hay noticias de posibles bajas: revisa la alineación antes de apostar.');
  return b.toString().trim();
}
