/// KozAlma AI — Enter Code Screen.
///
/// Second step of OTP auth: user enters the 6-digit code.
/// Includes countdown timer and resend button.
///
/// Accessibility: EdgeVolumeController for volume gestures,
/// AccessibleTapHandler for 1-tap speak / 2-tap action pattern.
library;

import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/accessibility.dart';
import '../../services/auth_api_service.dart';
import '../../services/tts_service.dart';
import '../../widgets/edge_volume_controller.dart';
import '../welcome_screen.dart';

class EnterCodeScreen extends StatefulWidget {
  final String channel;
  final String identifier;
  final int cooldownSeconds;

  const EnterCodeScreen({
    super.key,
    required this.channel,
    required this.identifier,
    required this.cooldownSeconds,
  });

  @override
  State<EnterCodeScreen> createState() => _EnterCodeScreenState();
}

class _EnterCodeScreenState extends State<EnterCodeScreen> {
  final _codeCtrl = TextEditingController();
  final _authApi = AuthApiService();
  final _tts = TtsService();
  bool _loading = false;
  String _error = '';
  late int _countdown;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _countdown = widget.cooldownSeconds;
    _startTimer();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _tts.stop();
      _tts.speak(
        'Введите шестизначный код, отправленный на ${widget.identifier}',
        lang: 'ru',
      );
    });
  }

  void _startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (_countdown <= 0) {
        t.cancel();
      } else {
        setState(() => _countdown--);
      }
    });
  }

  Future<void> _verify() async {
    final code = _codeCtrl.text.trim();
    if (code.length != 6) {
      setState(() => _error = 'Код должен содержать 6 цифр');
      _tts.stop();
      _tts.speak('Код должен содержать 6 цифр', lang: 'ru');
      return;
    }

    setState(() {
      _loading = true;
      _error = '';
    });

    try {
      await _authApi.verifyCode(
        channel: widget.channel,
        identifier: widget.identifier,
        code: code,
      );
      _tts.stop();
      _tts.speak('Вход выполнен успешно', lang: 'ru');

      if (!mounted) return;
      // Navigate to main app, clearing auth stack
      Navigator.pushAndRemoveUntil(
        context,
        MaterialPageRoute(builder: (_) => const WelcomeScreen()),
        (route) => false,
      );
    } on AuthException catch (e) {
      setState(() => _error = e.message);
      _tts.stop();
      _tts.speak(e.message, lang: 'ru');
    } catch (e) {
      setState(() => _error = 'Ошибка сети');
      _tts.stop();
      _tts.speak('Ошибка сети', lang: 'ru');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _resend() async {
    if (_countdown > 0) return;

    setState(() {
      _loading = true;
      _error = '';
    });

    try {
      final cooldown = await _authApi.requestCode(
        channel: widget.channel,
        identifier: widget.identifier,
      );
      setState(() => _countdown = cooldown);
      _startTimer();
      _tts.stop();
      _tts.speak('Код отправлен повторно', lang: 'ru');
    } on AuthException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Ошибка сети');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _codeCtrl.dispose();
    _tts.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D0D1A),
      // EdgeVolumeController: enables left/right edge double-tap for volume
      // headerExcludeHeight: 80 to exclude Back button area
      body: EdgeVolumeController(
        ttsService: _tts,
        lang: 'ru',
        headerExcludeHeight: 80,
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: 16),

                // Back button — AccessibleTapHandler:
                // 1-tap: speaks "Назад"
                // 2-tap: navigates back
                Align(
                  alignment: Alignment.centerLeft,
                  child: AccessibleTapHandler(
                    label: 'Назад',
                    hint: 'Нажмите дважды чтобы вернуться',
                    onSpeak: (text) {
                      _tts.stop();
                      _tts.speak(text, lang: 'ru');
                    },
                    onAction: () => Navigator.pop(context),
                    child: const Padding(
                      padding: EdgeInsets.all(8.0),
                      child: Icon(Icons.arrow_back, color: Colors.white, size: 28),
                    ),
                  ),
                ),

                const SizedBox(height: 32),

                // Title
                const Text(
                  'Введите код',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  'Код отправлен на\n${widget.identifier}',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.6),
                    fontSize: 15,
                  ),
                ),

                const SizedBox(height: 40),

                // Code input
                // NOTE: autofocus removed to prevent keyboard from stealing
                // gestures on screen launch. User taps field to focus.
                TextField(
                  controller: _codeCtrl,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 32,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 16,
                  ),
                  decoration: InputDecoration(
                    counterText: '',
                    hintText: '• • • • • •',
                    hintStyle: TextStyle(
                      color: Colors.white.withValues(alpha: 0.2),
                      fontSize: 32,
                      letterSpacing: 16,
                    ),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.08),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(16),
                      borderSide: BorderSide.none,
                    ),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 20,
                    ),
                  ),
                  onSubmitted: (_) => _verify(),
                ),

                if (_error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      _error,
                      style: const TextStyle(color: Colors.redAccent, fontSize: 14),
                      textAlign: TextAlign.center,
                    ),
                  ),

                const SizedBox(height: 24),

                // Verify button — AccessibleTapHandler:
                // 1-tap: speaks "Подтвердить"
                // 2-tap: executes _verify()
                AccessibleTapHandler(
                  label: 'Подтвердить',
                  hint: 'Нажмите дважды чтобы подтвердить код',
                  onSpeak: (text) {
                    _tts.stop();
                    _tts.speak(text, lang: 'ru');
                  },
                  onAction: _loading ? () {} : _verify,
                  child: Container(
                    height: 56,
                    decoration: BoxDecoration(
                      color: _loading
                          ? const Color(0xFF6C63FF).withValues(alpha: 0.5)
                          : const Color(0xFF6C63FF),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    alignment: Alignment.center,
                    child: _loading
                        ? const SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(
                              strokeWidth: 2.5,
                              color: Colors.white,
                            ),
                          )
                        : const Text(
                            'Подтвердить',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 18,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                  ),
                ),

                const SizedBox(height: 20),

                // Resend button — AccessibleTapHandler:
                // 1-tap: speaks resend status (countdown or "Отправить повторно")
                // 2-tap: resends code (only if countdown == 0)
                Center(
                  child: AccessibleTapHandler(
                    label: _countdown > 0
                        ? 'Отправить повторно через $_countdown секунд'
                        : 'Отправить повторно',
                    hint: _countdown > 0
                        ? 'Подождите $_countdown секунд'
                        : 'Нажмите дважды чтобы отправить код повторно',
                    onSpeak: (text) {
                      _tts.stop();
                      _tts.speak(text, lang: 'ru');
                    },
                    onAction: _countdown > 0 ? () {} : _resend,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
                      child: Text(
                        _countdown > 0
                            ? 'Отправить повторно через $_countdown с'
                            : 'Отправить повторно',
                        style: TextStyle(
                          color: _countdown > 0
                              ? Colors.white.withValues(alpha: 0.3)
                              : const Color(0xFF6C63FF),
                          fontSize: 15,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
