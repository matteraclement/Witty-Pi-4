// Dedicated Timer2 (the pinned build disables Arduino millis) owns scheduled
// grace. Legacy Timer1 remains available to manual and protection shutdowns.
struct __attribute__((packed)) ContractRecord {
  uint16_t boot;
  uint16_t generation;
  uint32_t due;
  volatile byte phase;
  volatile byte elapsed;
  byte sequence;
  byte crc;
};
ContractRecord contract = {};
byte contractSlot = 0;
boolean contractReset = false;

byte contractCrc(const ContractRecord &r) {
  const byte *p = (const byte *)&r;
  byte crc = 0xA5;
  for (byte i = 0; i < sizeof(r)-1; ++i) {
    crc ^= p[i];
    for (byte b = 0; b < 8; ++b) crc = (crc & 0x80) ? (crc << 1) ^ 0x07 : crc << 1;
  }
  return crc;
}

void contractSave() {
  ++contract.sequence;
  contract.crc = contractCrc(contract);
  contractSlot = (contractSlot + 1) & 31;
  int marker = 64 + contractSlot * (sizeof(contract)+1) + sizeof(contract);
  eeprom_update_byte((byte *)(uintptr_t)marker, 0); // Invalidate before payload.
  eeprom_update_block(&contract, (void *)(uintptr_t)(marker - sizeof(contract)), sizeof(contract));
  eeprom_update_byte((byte *)(uintptr_t)marker, 0xA5); // Publish completed record.
}

boolean contractActive() { return contract.phase == 2; }
boolean contractLocked() { return contract.phase == 1 || contractActive(); }

// RTC-backed RAM survives CPU/host reset; PCF reset clears it to unknown (0).
byte calendarByte(byte index) {
  return readFromDevice(ADDRESS_RTC, index, 1) == 1 ? softWireMaster.read() : 0xFF;
}

boolean calendarSetByte(byte index, byte value) {
  return !writeToDevice(ADDRESS_RTC, index, &value, 1) && calendarByte(index)==value;
}

boolean calendarTrusted() {
  return calendarByte(3) == 0xA5 && !(calendarByte(0) & 0xA2) && !(calendarByte(4) & 0x80);
}

boolean calendarPending() {
  alarm1Delayed = 0; // A replacement calendar cannot inherit an old delayed wake.
  return calendarSetByte(3, 0);
}

void contractInterrupted() {
  if (contract.phase == 1 || contractActive()) {
    contract.phase = 6;
    TIMSK2 = 0;
    contractSave();
  }
}

void contractSetup() {
  ContractRecord candidate;
  boolean found = false;
  for (byte slot=0; slot<32; ++slot) {
    int address = 64 + slot * (sizeof(contract)+1);
    eeprom_read_block(&candidate, (const void *)(uintptr_t)address, sizeof(candidate));
    if (EEPROM.read(address + sizeof(candidate)) != 0xA5 ||
        candidate.crc != contractCrc(candidate) || candidate.phase > 7) continue;
    if (!found || (int8_t)(candidate.sequence-contract.sequence)>0) {
      contract=candidate;
      contractSlot=slot;
      found=true;
    }
  }
  contractReset=true;
  if (!found) {
    contract={}; contract.boot=1; contract.phase=6;
    contractSave(); // Missing/torn evidence is unknown, including first installation.
  }
  if (contract.phase >= 3) return; // Keep unacknowledged event identity through reset.
  if (contract.phase == 1 || contractActive()) contract.phase = 6;
  else { ++contract.boot; contractReset=false; if (!contract.boot) contract.phase=6; }
  contractSave();
}


uint32_t calendarUtc(byte *expected) {
  if (readFromDevice(ADDRESS_RTC, 4, 7) != 7) return 0;
  byte c[7];
  for (byte i=0; i<7; ++i) {
    byte v=softWireMaster.read();
    if (expected && v != expected[i]) return 0;
    if ((v & 15) > 9 || v > 0x99) return 0;
    c[i]=bcd2dec(v);
  }
  if (c[0]>59 || c[1]>59 || c[2]>23 || c[3]<1 || c[3]>31 || c[5]<1 || c[5]>12) return 0;
  uint16_t days=365U*c[6]+(c[6]+3)/4+c[3]-1;
  const static byte months[] PROGMEM = {31,28,31,30,31,30,31,31,30,31,30,31};
  for (byte m=1; m<c[5]; ++m) days+=pgm_read_byte(months+m-1);
  byte maxDay = pgm_read_byte(months+c[5]-1);
  if (c[5]==2 && !(c[6]&3)) ++maxDay;
  if (c[3]>maxDay || c[4]>6) return 0;
  if (c[5]>2 && !(c[6]&3)) ++days;
  return 946684800UL + (uint32_t)getTimestamp(days, c[2], c[1], c[0]);
}

uint32_t contractUtc() {
  return calendarTrusted() ? calendarUtc(0) : 0;
}

void calendarWrite() {
  byte data[7];
  for (byte i=0; i<7; ++i) data[i]=TinyWireS.read();
  // Publish and verify pending BEFORE even STOP can change the RTC.
  if (!calendarPending()) return;
  byte control=calendarByte(0);
  if (control==0xFF) return;
  control &= ~0xA2; // Establish normal 24-hour RUN, preserving CAP_SEL and CIE.
  if (!calendarSetByte(0, control | 0x20) ||
      writeToDevice(ADDRESS_RTC, 4, data, 7) || !calendarUtc(data)) return;
  if (!calendarSetByte(0, control) || (calendarByte(4) & 0x80)) return;
  // Only a complete, valid, frozen readback followed by verified RUN commits.
  calendarSetByte(3, 0xA5);
}

void contractCut(byte phase) {
  contract.phase = phase;
  TIMSK2 = 0;
  cutPower(); // Physical cut precedes EEPROM latency.
  contractSave();
  sleep();
}

void contractPoll() {
  if (contract.phase != 1) return;
  uint32_t now = contractUtc();
  if (!now || now < contract.due) return;
  uint32_t late = now - contract.due;
  if (late >= 120) { contract.elapsed = 120; contractCut(5); return; }
  contract.phase = 2;
  contract.elapsed = late;
  // 16-bit Timer2 cannot be renewed by legacy Timer1/reset/reboot handling.
  TCCR2A = 0;
  TCCR2B = _BV(CS22) | _BV(CS20);
  TCNT2 = 65536UL - 7812;
  TIFR2 = _BV(TOV2);
  TIMSK2 = _BV(TOIE2);
  contractSave();
  updateRegister(I2C_ACTION_REASON, REASON_ALARM2);
  emulateButtonClick();
}

ISR(TIMER2_OVF_vect) {
  TCNT2 += 65536UL - 7812; // Preserve subsecond phase across bounded ISR latency.
  if (++contract.elapsed >= 120) {
    contract.elapsed = 120;
    contractCut(5);
  }
}

void contractReceive(int count) {
  if (count != 11 || TinyWireS.read() != 1) { return; }
  byte action=TinyWireS.read();
  struct __attribute__((packed)) { uint16_t boot, generation; uint32_t due; } fields;
  byte *bytes=(byte *)&fields;
  for (byte i=0; i<8; ++i) bytes[i]=TinyWireS.read();
  contractPoll(); // An edit received after T cannot cancel a not-yet-serviced obligation.
  if (fields.boot != contract.boot || !contract.boot) return;
  bool same=fields.generation==contract.generation && fields.due==contract.due;
  byte phase=contract.phase; // This I2C handler runs with interrupts masked.
  if (action==1) {
    if (same && (phase==1 || phase==2)) { return; }
    if (phase>1 || !fields.generation || fields.due>4102444799UL || i2cReg[13]!=1) return;
    if (fields.generation<contract.generation || (fields.generation==contract.generation && fields.due<=contract.due)) return;
    uint32_t now=contractUtc();
    if (!now || fields.due<=now) return;
    contract.generation=fields.generation; contract.due=fields.due; contract.phase=1; contract.elapsed=0;
  } else if (action==5 && phase==0) {
    // Explicit UTC-profile migration, while disarmed. The host must then set and verify RTC UTC.
    updateRegister(13, 1);
  } else if (!same) return;
  else if (action==2 && phase==1) contract.phase=7;
  else if (action==3 && phase==2) {
    // A pending overflow wins even if this I2C ISR was entered just before expiry.
    contract.elapsed += (TIFR2 & _BV(TOV2)) != 0;
    contractCut(contract.elapsed<60 ? 3 : contract.elapsed<120 ? 4 : 5);
    return;
  } else if (action==4 && phase>=3) {
    contract.phase=0;
    if (contractReset) { ++contract.boot; contractReset=false; if (!contract.boot) contract.phase=6; }
  }
  else return;
  contractSave();
}

void contractReply() {
  TinyWireS.write(1);
  TinyWireS.write(contract.phase);
  TinyWireS.write((byte)0); // Reserved. Acceptance requires complete readback, never a status bit.
  TinyWireS.write(i2cReg[13]==1 ? 1 : 0);
  const byte *p=(const byte *)&contract;
  for (byte i=0; i<8; ++i) TinyWireS.write(p[i]);
  TinyWireS.write(contract.elapsed);
}
