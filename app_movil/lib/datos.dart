// Datos de FútBot: el paquete diario que calcula la nube (GitHub) y se guarda en el celular.
import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Equipo {
  final String nombre;
  final String? escudo; // ruta relativa: escudos/x.png
  Equipo(this.nombre, this.escudo);
  factory Equipo.de(Map<String, dynamic> j) => Equipo(j['nombre'] ?? '?', j['escudo']);
}

class Pata {
  final String titulo, mercado;
  final double p;
  final Map<String, dynamic> sel;
  Pata(this.titulo, this.mercado, this.p, this.sel);
  factory Pata.de(Map<String, dynamic> j) =>
      Pata(j['titulo'] ?? '', j['mercado'] ?? '', (j['p'] as num).toDouble(), Map<String, dynamic>.from(j['sel'] ?? {}));
}

class Sub {
  final double p, cuota;
  final bool estimada;
  Sub(this.p, this.cuota, this.estimada);
}

class Linea {
  final String id, liga, ligaNombre, betano;
  final DateTime inicio;
  final Equipo local, visitante;
  final List<Pata> patas;
  final Map<int, Sub> sub;
  final double cuota, p;
  final bool estimada, multibono, seguro;
  final List<String> avisos;
  Linea(this.id, this.liga, this.ligaNombre, this.betano, this.inicio, this.local, this.visitante, this.patas, this.sub,
      this.cuota, this.p, this.estimada, this.multibono, this.seguro, this.avisos);

  factory Linea.de(Map<String, dynamic> j) {
    final sub = <int, Sub>{};
    (j['sub'] as Map<String, dynamic>? ?? {}).forEach((k, v) {
      sub[int.parse(k)] = Sub((v['p'] as num).toDouble(), (v['cuota'] as num).toDouble(), v['estimada'] == true);
    });
    return Linea(
      j['id'], j['liga'], j['liga_nombre'] ?? j['liga'], j['betano'] ?? 'https://www.betano.pe/sport/futbol/',
      DateTime.parse(j['inicio']), Equipo.de(j['local']), Equipo.de(j['visitante']),
      (j['patas'] as List).map((e) => Pata.de(Map<String, dynamic>.from(e))).toList(), sub,
      (j['cuota'] as num).toDouble(), (j['p'] as num).toDouble(), j['estimada'] == true, j['multibono_ok'] == true,
      j['seguro_ok'] == true, List<String>.from(j['avisos'] ?? []),
    );
  }

  int get completa => (1 << patas.length) - 1;
}

class Repositorio {
  static const _kUrl = 'url_base', _kPaquete = 'paquete', _kFecha = 'paquete_descargado';
  Map<String, dynamic> paquete = {};
  String urlBase = '';
  String origen = '';
  DateTime? descargado;

  Future<void> iniciar() async {
    final pref = await SharedPreferences.getInstance();
    urlBase = pref.getString(_kUrl) ?? '';
    final guardado = pref.getString(_kPaquete);
    final f = pref.getString(_kFecha);
    descargado = f == null ? null : DateTime.tryParse(f);
    if (guardado != null) {
      paquete = jsonDecode(guardado);
      origen = 'guardado';
    } else {
      paquete = jsonDecode(await rootBundle.loadString('assets/paquete/paquete.json'));
      origen = 'incluido en la app';
    }
  }

  Future<void> guardarUrl(String url) async {
    var u = url.trim();
    if (u.isNotEmpty && !u.endsWith('/')) u = '$u/';
    urlBase = u;
    (await SharedPreferences.getInstance()).setString(_kUrl, u);
  }

  bool get viejo => descargado == null || DateTime.now().difference(descargado!).inHours >= 6;

  /// Descarga el paquete más reciente. Devuelve un mensaje para mostrar.
  Future<String> actualizar() async {
    if (urlBase.isEmpty) return 'Configura primero la dirección de datos en Ajustes.';
    try {
      final r = await http.get(Uri.parse('${urlBase}paquete.json')).timeout(const Duration(seconds: 30));
      if (r.statusCode != 200) return 'No se pudo descargar (HTTP ${r.statusCode}).';
      final texto = utf8.decode(r.bodyBytes);
      final nuevo = jsonDecode(texto);
      if (nuevo is! Map || nuevo['lineas'] == null) return 'El archivo descargado no es un paquete de FútBot.';
      paquete = Map<String, dynamic>.from(nuevo);
      descargado = DateTime.now();
      origen = 'nube';
      final pref = await SharedPreferences.getInstance();
      await pref.setString(_kPaquete, texto);
      await pref.setString(_kFecha, descargado!.toIso8601String());
      return 'Datos actualizados (${paquete['generado_peru'] ?? ''}).';
    } catch (e) {
      return 'Sin conexión: sigo con los datos guardados.';
    }
  }

  List<Linea> lineas(String nivel) =>
      ((paquete['lineas'] ?? {})[nivel] as List? ?? []).map((e) => Linea.de(Map<String, dynamic>.from(e))).toList();

  List<Map<String, dynamic>> get partidos =>
      ((paquete['partidos'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();

  List<Map<String, dynamic>> get resultados =>
      ((paquete['resultados'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();

  List<Map<String, dynamic>> get reglas =>
      ((paquete['reglas'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();

  Map<String, int> get multibono =>
      Map<String, dynamic>.from(paquete['multibono'] ?? {}).map((k, v) => MapEntry(k, (v as num).toInt()));

  double get apuestaMinima => (paquete['apuesta_minima'] as num?)?.toDouble() ?? 0.5;

  Map<String, dynamic> get niveles => Map<String, dynamic>.from(paquete['niveles'] ?? {});

  /// Dirección del escudo: en la nube si hay URL; si no, la copia incluida en la app.
  String? escudo(String? rel) => rel == null ? null : (urlBase.isEmpty ? 'asset:$rel' : '$urlBase$rel');
}

final repo = Repositorio();
