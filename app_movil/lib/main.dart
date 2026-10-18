// FútBot para Android: súper boletas, partidos, historial y reglas de Betano sin depender de la PC.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'boleta.dart';
import 'comunes.dart';
import 'datos.dart';
import 'historial.dart';
import 'otras.dart';

String? errorInicio;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]); // la boleta está pensada en vertical
  // Si algo falla al dibujar, se muestra el error en vez de una pantalla en blanco
  ErrorWidget.builder = (d) => Material(
      color: Col.fondo,
      child: Padding(padding: const EdgeInsets.all(16),
          child: Text('Error: ${d.exceptionAsString()}', style: const TextStyle(color: Colors.white))));
  try {
    await repo.iniciar().timeout(const Duration(seconds: 15));
  } catch (e) {
    errorInicio = '$e';
    print('FutBot iniciar fallo: $e');
    await repo.iniciarIncluido();
  }
  runApp(const FutBotApp());
}

class FutBotApp extends StatelessWidget {
  const FutBotApp({super.key});
  @override
  Widget build(BuildContext context) {
    final esquema = ColorScheme.fromSeed(seedColor: Col.naranja, brightness: Brightness.dark).copyWith(
        surface: Col.fondo, primary: Col.naranja);
    return MaterialApp(
      title: 'FútBot',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: esquema, scaffoldBackgroundColor: Col.fondo, useMaterial3: true,
          cardTheme: const CardThemeData(color: Col.tarjeta)),
      home: const Inicio(),
    );
  }
}

class Inicio extends StatefulWidget {
  const Inicio({super.key});
  @override
  State<Inicio> createState() => _InicioState();
}

class _InicioState extends State<Inicio> {
  int pagina = 0;
  int version = 0; // cambia al descargar datos nuevos para reconstruir las pantallas

  @override
  void initState() {
    super.initState();
    if (errorInicio != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Datos guardados dañados; uso los incluidos. ($errorInicio)'))));
    }
    _autoActualizar();
  }

  Future<void> _autoActualizar() async {
    print('FutBot inicio: origen=${repo.origen} viejo=${repo.viejo} url=${repo.urlBase}');
    if (repo.urlBase.isEmpty || !repo.viejo) return;
    final m = await repo.actualizar();
    await Historial.liquidar(repo.resultados);
    if (!mounted) return;
    setState(() => version++);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  @override
  Widget build(BuildContext context) {
    final paginas = [
      PantallaBoleta(key: ValueKey('b$version')),
      PantallaPartidos(key: ValueKey('p$version')),
      PantallaHistorial(key: ValueKey('h$version')),
      const PantallaReglas(),
      PantallaAjustes(alActualizar: () => setState(() => version++)),
    ];
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Col.panel,
        title: const Text('⚽ FútBot', style: TextStyle(fontWeight: FontWeight.w900)),
        actions: [IconButton(tooltip: 'Actualizar datos', icon: const Icon(Icons.sync), onPressed: () async {
          final m = await repo.actualizar();
          if (!context.mounted) return;
          setState(() => version++);
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
        })],
      ),
      body: SafeArea(child: paginas[pagina]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: pagina,
        backgroundColor: Col.panel,
        onDestinationSelected: (i) => setState(() => pagina = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.receipt_long), label: 'Boleta'),
          NavigationDestination(icon: Icon(Icons.sports_soccer), label: 'Partidos'),
          NavigationDestination(icon: Icon(Icons.history), label: 'Historial'),
          NavigationDestination(icon: Icon(Icons.menu_book), label: 'Reglas'),
          NavigationDestination(icon: Icon(Icons.settings), label: 'Ajustes'),
        ],
      ),
    );
  }
}
