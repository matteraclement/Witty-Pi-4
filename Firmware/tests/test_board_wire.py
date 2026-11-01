"""Exercise the production byte-only ATTinyCore slave engine without a board.

The register-event fixture checks callback/buffer semantics, not AVR electrical
clock stretching or interrupt latency; those still require hardware qualification.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_firmware_handlers import ROOT

ARDUINO = r"""
#pragma once
#include <cstdint>
#include <cstddef>
using byte=unsigned char;
using boolean=bool;
#define ISR(name) void name()
#define _BV(bit) (1U<<(bit))
#define B110 6
#define B11111001 249
#define B11110000 240
#define B0011 3
#define B0111 7
#define B0010 2
#define B0110 6
constexpr byte TWC=0,TWBE=1,TWASIF=2,TWDIF=3,TWAS=4,TWDIR=5;
constexpr byte TWSHE=0,TWDIE=1,TWASIE=2,TWEN=3,TWSIE=4;
byte TWSSRA,TWSD,TWSCRB,TWSA,TWSAM,TWSCRA;
"""

SCENARIOS = r"""
#include <cassert>
#include <vector>
#include <iostream>
std::vector<int> received;
int addresses,requests,receives,stops;
uint16_t lastAddress;
byte lastStart;
bool accept=true, consumePointer=false;
int pointer=-1;
bool addressed(uint16_t address,byte start) {
  ++addresses; lastAddress=address; lastStart=start;
  if (consumePointer && TinyWireS.available()) pointer=TinyWireS.read();
  return accept;
}
void receive(size_t count) {
  ++receives;
  assert(size_t(TinyWireS.available())==count);
  received.clear();
  while (TinyWireS.available()) received.push_back(TinyWireS.read());
  assert(TinyWireS.read()==-1);
}
void request() {
  ++requests;
  for (int i=0;i<13;++i) assert(TinyWireS.write(0x80+i)==1);
}
void stopped() { ++stops; }
void event(byte flags,byte data=0) {
  TWSSRA=flags; TWSD=data; TWI_SLAVE_vect();
}
constexpr byte ADDRESS=_BV(TWASIF)|_BV(TWAS), READ=_BV(TWDIR), DATA=_BV(TWDIF);
int main() {
  TinyWireS.begin(8);
  TinyWireS.onAddrReceive(addressed);
  TinyWireS.onReceive(receive);
  TinyWireS.onRequest(request);
  wireState.user_onStop=stopped;
  assert(TWSA==16 && TWSAM==0 && wireState.startCount==-1);
  assert(TWSCRA==(_BV(TWSHE)|_BV(TWDIE)|_BV(TWASIE)|_BV(TWEN)|_BV(TWSIE)));
  event(ADDRESS,16);
  assert(addresses==1 && lastAddress==16 && lastStart==0);
  event(DATA,58); event(DATA,0x59); event(DATA,0x12);
  assert(!receives && TinyWireS.available()==3);
  event(_BV(TWASIF));
  assert(receives==1 && received==std::vector<int>({58,0x59,0x12}));
  assert(wireState.startCount==-1 && !requests && !stops);

  // Register pointer followed by repeated START/read, without a write STOP.
  consumePointer=true;
  event(ADDRESS,16); event(DATA,73);
  event(ADDRESS|READ,17);
  assert(pointer==73 && lastAddress==17 && lastStart==1);
  assert(requests==1 && receives==1 && wireState.txBufferLength==13);
  for (int i=0;i<13;++i) { event(DATA|READ); assert(TWSD==0x80+i); }
  event(DATA|READ); assert(TWSCRB==B0010);
  event(_BV(TWASIF)|READ);
  assert(stops==1 && wireState.startCount==-1 && receives==1);

  // Exact receive and transmit bounds; overflow must never corrupt state.
  consumePointer=false;
  event(ADDRESS,16);
  for (int i=0;i<32;++i) event(DATA,i);
  event(DATA,0xEE);
  assert(TWSCRB==B0110 && wireState.rxBufferLength==32);
  event(_BV(TWASIF));
  assert(receives==2 && received.size()==32 && received.back()==31);
  wireState.txBufferLength=0;
  for (int i=0;i<32;++i) assert(TinyWireS.write(i)==1);
  assert(TinyWireS.write(99)==0 && wireState.txBufferLength==32);

  // Address rejection, bus error and the pinned engine's 10-bit sequence.
  accept=false; int before=requests;
  event(ADDRESS|READ,17);
  assert(TWSCRB==B0111 && requests==before);
  accept=true;
  wireState.Addr=0x8000;
  event(_BV(TWBE));
  assert(!(wireState.Addr&0x8000) && wireState.startCount==-1);
  before=addresses;
  event(ADDRESS,0xF0);
  assert(addresses==before && (wireState.Addr&0x8000));
  event(ADDRESS,0x12);
  assert(addresses==before+1 && lastAddress==0x12 && lastStart==0);
  event(_BV(TWASIF));
  assert(!(wireState.Addr&0x8000));
  event(ADDRESS,16); event(DATA,54); event(_BV(TWASIF));
  assert(received==std::vector<int>({54})); // Registration survives all errors.
  std::cout << "PASS actual slave: write/repeated-start/read, callbacks, bounds, errors, STOP\n";
}
"""


class BoardWire(unittest.TestCase):
    def test_actual_slave_engine_events_and_buffer_bounds(self):
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                directory=Path(d)
                (directory / "Arduino.h").write_text(ARDUINO)
                cpp=directory / "wire.cpp"
                cpp.write_text(f'#include "{ROOT / variant / "BoardWire.h"}"\n'+SCENARIOS)
                binary=directory / "wire"
                subprocess.run([
                    *shlex.split(os.environ.get("CXX", "c++")), "-std=c++17",
                    "-fsigned-char", "-fpermissive", "-I", str(directory),
                    str(cpp), "-o", str(binary),
                ],check=True)
                subprocess.run([str(binary)],check=True)


if __name__=="__main__":
    unittest.main()
