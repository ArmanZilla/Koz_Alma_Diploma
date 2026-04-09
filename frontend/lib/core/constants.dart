/// KozAlma AI — App Constants.
///
/// Platform-aware API URL selection:
///   - Web (Chrome): http://localhost:8000
///   - Android emulator: http://10.0.2.2:8000
///   - Physical device / iOS / desktop: http://localhost:8000
///
/// Override at build time:
///   flutter run --dart-define=API_URL=http://192.168.100.152:8000
///   flutter build apk --dart-define=API_URL=https://api.kozalma.kz
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'platform_util.dart';

class AppConstants {
  AppConstants._();

  /// Build-time API URL override via --dart-define.
  static const String _customUrl = String.fromEnvironment('API_URL');

  /// Backend API base URL — auto-selected by platform.
  /// Override with --dart-define=API_URL=http://your-server:8000
  static String get apiBaseUrl {
    if (_customUrl.isNotEmpty) return _customUrl;

    if (kIsWeb) {
      return 'http://localhost:8000';
    }
    if (isAndroid()) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://localhost:8000';
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
