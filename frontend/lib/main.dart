import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'core/app_state.dart';
import 'screens/welcome_screen.dart';
import 'screens/camera_screen.dart';
import 'screens/result_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/auth/enter_identifier_screen.dart';
import 'services/token_store.dart';
import 'services/auth_api_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppState(),
      child: const KozAlmaApp(),
    ),
  );
}

class KozAlmaApp extends StatelessWidget {
  const KozAlmaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KozAlma AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF6C63FF),
        brightness: Brightness.dark,
        fontFamily: 'Roboto',
      ),
      home: const AuthGate(),
      routes: {
        '/camera': (context) => const CameraScreen(),
        '/result': (context) => const ResultScreen(),
        '/settings': (context) => const SettingsScreen(),
        '/login': (context) => const EnterIdentifierScreen(),
      },
    );
  }
}

/// Auth gate — validates tokens on EVERY cold start.
///
/// Lifecycle logic:
///   • Cold start (initState) → always validates tokens server-side
///   • Resume from background → no re-auth (user just switched apps)
///   • App killed + relaunched → initState runs again → re-validates
///
/// This ensures:
///   ✔ Minimize/resume = stays logged in
///   ✔ Kill + relaunch = requires valid token (re-login if expired)
class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> with WidgetsBindingObserver {
  bool _checking = true;
  bool _authenticated = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Every cold start triggers full server-side token validation.
    // SharedPreferences tokens persist, but we ALWAYS verify them.
    _validateTokens();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Lifecycle observer — only used for logging/diagnostics.
  /// We do NOT clear tokens on background/detach.
  /// Re-validation happens naturally on the next cold start (initState).
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    debugPrint('AuthGate lifecycle: $state');
    // No action needed:
    // - resumed: user returned from background, already authenticated
    // - inactive/hidden/paused: going to background, keep session
    // - detached: app being killed, next launch = new initState = re-validate
  }

  /// Full server-side token validation.
  ///
  /// 1. Check if tokens exist locally
  /// 2. Try /auth/me with access token
  /// 3. If 401 → try refresh
  /// 4. If refresh fails → clear storage → login screen
  Future<void> _validateTokens() async {
    final tokenStore = TokenStore();
    final hasTokens = await tokenStore.hasTokens();

    if (!hasTokens) {
      // No tokens at all → straight to login
      if (mounted) {
        setState(() {
          _authenticated = false;
          _checking = false;
        });
      }
      return;
    }

    final authApi = AuthApiService(tokenStore: tokenStore);

    // Step 1: Try access token
    final profile = await authApi.me();
    if (profile != null) {
      if (mounted) {
        setState(() {
          _authenticated = true;
          _checking = false;
        });
      }
      return;
    }

    // Step 2: Access token failed → try refresh
    final refreshed = await authApi.refresh();
    if (refreshed) {
      final retryProfile = await authApi.me();
      if (retryProfile != null) {
        if (mounted) {
          setState(() {
            _authenticated = true;
            _checking = false;
          });
        }
        return;
      }
    }

    // Step 3: Both failed → clear tokens and force login
    debugPrint('AuthGate: token validation failed — forcing login');
    await tokenStore.clear();

    if (mounted) {
      setState(() {
        _authenticated = false;
        _checking = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checking) {
      return const Scaffold(
        backgroundColor: Color(0xFF0D0D1A),
        body: Center(
          child: CircularProgressIndicator(
            color: Color(0xFF6C63FF),
          ),
        ),
      );
    }

    return _authenticated
        ? const WelcomeScreen()
        : const EnterIdentifierScreen();
  }
}
