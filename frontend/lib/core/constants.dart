/// KozAlma AI — App Constants.
///
/// Platform-aware API URL selection:
///   - Web (Chrome): http://localhost:8000
///   - Android emulator: http://10.0.2.2:8000  (default for Android)
///   - Physical device: MUST use --dart-define=API_URL=http://<LAN_IP>:8000
///   - iOS / desktop: http://localhost:8000
///
/// Override at build time (REQUIRED for real devices):
///   flutter run --dart-define=API_URL=http://192.168.100.152:8000
///   flutter build apk --dart-define=API_URL=https://api.kozalma.kz
library;

import 'package:flutter/foundation.dart' show debugPrint, kIsWeb;
import 'platform_util.dart';

class AppConstants {
  AppConstants._();

  /// Build-time API URL override via --dart-define.
  static const String _customUrl = String.fromEnvironment('API_URL');

  /// Whether we've already logged the resolved URL.
  static bool _urlLogged = false;

  /// Backend API base URL — auto-selected by platform.
  ///
  /// Priority:
  ///   1. --dart-define=API_URL=...  (highest, always wins)
  ///   2. Web → http://localhost:8000
  ///   3. Android → http://10.0.2.2:8000  (emulator only!)
  ///   4. Other → http://localhost:8000
  ///
  /// ⚠️  For physical Android devices, you MUST pass:
  ///   flutter run --dart-define=API_URL=http://<YOUR_LAN_IP>:8000
  static String get apiBaseUrl {
    final String url;
    final String source;

    if (_customUrl.isNotEmpty) {
      url = _customUrl;
      source = '--dart-define override';
    } else if (kIsWeb) {
      url = 'http://localhost:8000';
      source = 'web default';
    } else if (isAndroid()) {
      url = 'http://10.0.2.2:8000';
      source = 'android emulator default (use --dart-define=API_URL for real device!)';
    } else {
      url = 'http://localhost:8000';
      source = 'desktop/iOS default';
    }

    if (!_urlLogged) {
      _urlLogged = true;
      debugPrint('┌─────────────────────────────────────────────');
      debugPrint('│ API URL: $url');
      debugPrint('│ Source:  $source');
      if (_customUrl.isEmpty && isAndroid() && !kIsWeb) {
        debugPrint('│ ⚠️  Using emulator-only 10.0.2.2 address!');
        debugPrint('│ ⚠️  For real device run:');
        debugPrint('│     flutter run --dart-define=API_URL=http://<LAN_IP>:8000');
      }
      debugPrint('└─────────────────────────────────────────────');
    }

    return url;
  }

  /// Supported languages.
  static const List<String> languages = ['kz', 'ru'];

  /// Default language.
  static const String defaultLang = 'kz';

  /// TTS speed range (user-facing values, normalized to engine range internally).
  static const double minSpeed = 0.7;
  static const double maxSpeed = 3.0;
  static const double defaultSpeed = 1.0;

  /// Light level threshold for auto-flashlight (lux).
  static const double lowLightThreshold = 30.0;

  /// Welcome messages.
  static const Map<String, String> welcomeMessages = {
    'ru': 'Вы запустили виртуального ассистента КозАлма. '
        'Для навигации используйте одно нажатие для озвучки кнопки, '
        'и двойное нажатие для активации.',
    'kz': 'Сіз КозАлма виртуалды көмекшісін іске қостыңыз. '
        'Навигация үшін бір рет басу — батырманы айту, '
        'екі рет басу — іске қосу.',
  };

  /// Language names for TTS.
  static const Map<String, String> languageNames = {
    'ru': 'Русский',
    'kz': 'Қазақша',
  };

  /// Speed change hint.
  static const Map<String, String> speedHint = {
    'ru': 'Для изменения скорости нажмите дважды слева или справа.',
    'kz': 'Жылдамдықты өзгерту үшін сол немесе оң жағын екі рет басыңыз.',
  };
}
