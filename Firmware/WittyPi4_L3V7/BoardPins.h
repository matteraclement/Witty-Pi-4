// This build owns every compare output and never enables PWM. Compile-time pin
// mapping avoids the general Arduino pin lookup and PWM-disconnect dispatch.
#if !defined(__AVR_ATtiny841__) || !defined(OLD_PINOUT)
#error Scheduled WP4 profile requires the pinned ATtiny841 old pin mapping
#endif

__attribute__((always_inline)) inline byte pinBit(byte pin) {
  if (pin & 64) pin = 10 - (pin & 63);
  return pin < 3 ? _BV(pin) : pin == 11 ? _BV(3) : _BV(10-pin);
}
__attribute__((always_inline)) inline bool pinPortA(byte pin) {
  if (pin & 64) pin = 10 - (pin & 63);
  return pin >= 3 && pin <= 10;
}
__attribute__((always_inline)) inline void boardPinMode(byte pin, byte mode) {
  byte bit=pinBit(pin);
  volatile byte &direction = pinPortA(pin) ? DDRA : DDRB;
  volatile byte &output = pinPortA(pin) ? PORTA : PORTB;
  volatile byte &pullup = pinPortA(pin) ? PUEA : PUEB;
  byte saved = SREG;
  cli();
  if (mode == OUTPUT) { pullup &= ~bit; direction |= bit; }
  else {
    direction &= ~bit;
    if (mode == INPUT_PULLUP) { output |= bit; pullup |= bit; }
    else { output &= ~bit; pullup &= ~bit; }
  }
  SREG=saved;
}
__attribute__((always_inline)) inline void boardWrite(byte pin, byte value) {
  byte bit=pinBit(pin);
  volatile byte &output = pinPortA(pin) ? PORTA : PORTB;
  volatile byte &pullup = pinPortA(pin) ? PUEA : PUEB;
  byte saved=SREG;
  cli();
  if (value) output |= bit; else output &= ~bit;
  pullup &= ~bit;
  SREG=saved;
}
__attribute__((always_inline)) inline byte boardRead(byte pin) {
  return ((pinPortA(pin) ? PINA : PINB) & pinBit(pin)) != 0;
}
