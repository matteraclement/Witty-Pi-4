"""Exercise the exact old-pinout GPIO implementation used by the AVR image."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_firmware_handlers import ROOT


class BoardPins(unittest.TestCase):
    def test_mapping_atomic_register_preservation_and_pullups(self):
        with tempfile.TemporaryDirectory() as d:
            cpp = Path(d) / 'pins.cpp'
            cpp.write_text(r'''
#include <cassert>
#include <initializer_list>
using byte=unsigned char;
#define __AVR_ATtiny841__ 1
#define OLD_PINOUT 1
#define _BV(n) (1U << (n))
constexpr byte OUTPUT=1, INPUT_PULLUP=2, INPUT=0;
volatile byte DDRA, DDRB, PORTA, PORTB, PUEA, PUEB, PINA, PINB, SREG;
void cli() { SREG &= ~128; }
''' + f'\n#include "{ROOT / "WittyPi4" / "BoardPins.h"}"\n' + r'''
int main() {
  const byte bits[]={1,2,4,128,64,32,16,8,4,2,1,8,2,4,8};
  const byte pins[]={0,1,2,3,4,5,6,7,8,9,10,11,65,66,67};
  for (byte i=0;i<15;++i) {
    bool portA=i>=3 && i!=11;
    assert(pinPortA(pins[i])==portA && pinBit(pins[i])==bits[i]);
    for (int initial: {0,85,170,255}) {
      DDRA=DDRB=PORTA=PORTB=PUEA=PUEB=initial;
      SREG=0xC5;
      boardPinMode(pins[i],OUTPUT);
      assert((portA ? DDRA : DDRB)==byte(initial | bits[i]));
      assert((portA ? PUEA : PUEB)==byte(initial & ~bits[i]));
      assert((portA ? PORTA : PORTB)==initial && SREG==0xC5);
      boardPinMode(pins[i],INPUT_PULLUP);
      assert((portA ? DDRA : DDRB)==byte(initial & ~bits[i]));
      assert((portA ? PUEA : PUEB)==byte(initial | bits[i]));
      boardWrite(pins[i],0);
      assert((portA ? PORTA : PORTB)==byte(initial & ~bits[i]));
      assert((portA ? PUEA : PUEB)==byte(initial & ~bits[i]));
      boardWrite(pins[i],1);
      assert((portA ? PORTA : PORTB)==byte(initial | bits[i]));
      boardPinMode(pins[i],INPUT);
      assert((portA ? DDRA : DDRB)==byte(initial & ~bits[i]));
      assert((portA ? PORTA : PORTB)==byte(initial & ~bits[i]));
      assert((portA ? PUEA : PUEB)==byte(initial & ~bits[i]));
      assert((portA ? DDRB : DDRA)==initial);
      assert((portA ? PORTB : PORTA)==initial);
      assert((portA ? PUEB : PUEA)==initial && SREG==0xC5);
      PINA=PINB=0; assert(!boardRead(pins[i]));
      (portA ? PINA : PINB)=bits[i]; assert(boardRead(pins[i]));
    }
  }
}
''')
            binary = Path(d) / 'pins'
            subprocess.run([*shlex.split(os.environ.get('CXX', 'c++')), '-std=c++17',
                '-O2', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
        self.assertEqual((ROOT / 'WittyPi4/BoardPins.h').read_bytes(),
                         (ROOT / 'WittyPi4_L3V7/BoardPins.h').read_bytes())
