#include <cassert>
#include <cstdint>
#include <cstring>
#include <array>
#include <vector>
#include <ctime>
#include <iostream>
using byte = unsigned char;
using boolean = bool;
#define ISR(name) void name()
#define PROGMEM
#define pgm_read_byte(p) (*(p))
#define _BV(n) (1U << (n))
constexpr int OUTPUT=1, INPUT_PULLUP=2, CS22=2, CS20=0, TOV2=0, TOIE2=0;
byte TCCR2A, TCCR2B, TIMSK2;
uint16_t TCNT1, TCNT2;
struct Flags {
  byte value=0;
  operator byte() const { return value; }
  void operator=(byte clear) { value &= ~clear; }
} TIFR2;
byte i2cReg[50];
bool powerIsOn, listenToTxd, systemIsUp, turningOff, turnOffFromTXD;
bool buttonPressed, isButtonClickEmulated, wakeupByWatchdog, ledIsOn;
byte lastButton, lastSystemUp, powerCutDelay, skipTempShutdownCount;
byte alarm1Delayed;
int pins[12], modes[12], sleepCount;
char temperature;
int boardRead(int pin) { return pins[pin]; }
void boardWrite(int pin, int value) {
  if (pin != PIN_BUTTON || modes[pin] == OUTPUT) pins[pin] = value;
}
void boardPinMode(int pin, int mode) { modes[pin]=mode; }
void ledOn() { ledIsOn=true; }
void ledOff() { ledIsOn=false; }
void powerOn() { powerIsOn=true; pins[PIN_CTRL]=1; }
void sleep() { ++sleepCount; }
void updateRegister(byte reg, byte value) { assert(reg<50); i2cReg[reg]=value; }
char getTemperature() { return temperature; }
bool contractActive();
void contractInterrupted();

struct HostBus {
  std::vector<byte> request, response;
  size_t index=0;
  int read() { return index<request.size() ? request[index++] : -1; }
  void write(byte b) { response.push_back(b); }
} TinyWireS;
struct Calendar {
  byte bytes[7];
  byte index=0;
  byte marker=0;
  bool available=true;
  int read() {
    byte reg=index++;
    return reg==3 ? marker : reg==0 ? 0 : bytes[reg-4];
  }
} softWireMaster;
byte readFromDevice(byte address, byte index, byte count) {
  assert(address==ADDRESS_RTC && ((index==4 && count==7) || ((index==0 || index==3 || index==4) && count==1)));
  softWireMaster.index=index;
  return softWireMaster.available ? count : 0;
}
byte writeToDevice(byte, byte, byte*, byte) { return 0; }
struct Interrupted {};
struct Eeprom {
  std::array<byte,512> memory;
  int remaining=-1;
  byte read(int address) const { return memory.at(address); }
  void update(int address, byte value) {
    if (remaining==0) throw Interrupted();
    if (remaining>0) --remaining;
    memory.at(address)=value;
  }
} EEPROM;
void eeprom_update_byte(byte* address, byte value) { EEPROM.update(uintptr_t(address),value); }
void eeprom_read_block(void* dest, const void* address, size_t size) {
  std::memcpy(dest, EEPROM.memory.data()+uintptr_t(address), size);
}
void eeprom_update_block(const void* src, void* address, size_t size) {
  // AVR libc scans from high addresses down. Commit marker is separate.
  const auto* bytes=static_cast<const byte*>(src);
  for (size_t i=size; i; --i) EEPROM.update(uintptr_t(address)+i-1, bytes[i-1]);
}
// PRODUCTION HERE

void utc(uint32_t value) {
  time_t timestamp=value;
  tm calendar=*gmtime(&timestamp);
  int fields[]={calendar.tm_sec, calendar.tm_min, calendar.tm_hour,
    calendar.tm_mday, calendar.tm_wday, calendar.tm_mon+1, calendar.tm_year-100};
  for (int i=0;i<7;++i) softWireMaster.bytes[i]=(fields[i]/10)*16+fields[i]%10;
  softWireMaster.available=true;
}
void command(byte action, uint16_t boot, uint16_t generation, uint32_t due) {
  TinyWireS.request={1,action};
  for (auto value: {boot,generation}) {
    TinyWireS.request.push_back(value & 255);
    TinyWireS.request.push_back(value >> 8);
  }
  for (byte i=0;i<4;++i) TinyWireS.request.push_back((due >> (8*i)) & 255);
  TinyWireS.index=0;
  contractReceive(11); // Includes the consumed command-register byte.
}
void command(byte action) { command(action,contract.boot,contract.generation,contract.due); }
constexpr uint32_t T=1793534400; // 2026-11-01 12:00 UTC.
void resetRam() {
  contract={}; contractSlot=0; contractReset=false; TIMSK2=0; TIFR2.value=0;
  powerIsOn=false; pins[PIN_CTRL]=0;
  contractSetup(); // Real setup physically cuts before loading the journal.
}
void ready() {
  softWireMaster.marker=0;
  EEPROM.memory.fill(255); EEPROM.remaining=-1;
  std::memset(i2cReg,0,sizeof i2cReg);
  utc(T-10); resetRam();
  assert(contract.phase==6 && contract.boot);
  command(4); assert(contract.phase==0);
  command(5); assert(i2cReg[13]==1);
  powerOn(); systemIsUp=true; listenToTxd=true;
  turningOff=turnOffFromTXD=buttonPressed=isButtonClickEmulated=false;
  wakeupByWatchdog=ledIsOn=false;
  pins[PIN_TX_UP]=pins[PIN_BUTTON]=1; pins[PIN_SYS_UP]=0;
  lastButton=1; lastSystemUp=0; sleepCount=0;
  modes[PIN_BUTTON]=INPUT_PULLUP; skipTempShutdownCount=120;
  i2cReg[I2C_CONF_POWER_CUT_DELAY]=250;
  command(1,contract.boot,1,T);
  assert(contract.phase==0); // Erased retained trust blocks arm.
  softWireMaster.marker=0xA5;
  command(1,contract.boot,1,T);
  assert(contract.phase==1 && contract.due==T);
}
void activate() { utc(T); contractPoll(); assert(contractActive()); }
void second() { TIFR2.value=0; TIMER2_OVF_vect(); }
void age(int n) { for (int i=0;i<n;++i) second(); }
void finishClick() {
  assert(isButtonClickEmulated); PCINT1_vect();
  pins[PIN_BUTTON]=1; PCINT1_vect();
}
int main() {
  // Board activates and cuts without any host progress or callback.
  ready(); activate(); finishClick();
  assert(!turningOff && systemIsUp);
  softWireMaster.marker=0;
  assert(contractUtc()==0); // Pending calendar cannot suspend active Timer2.
  age(119); assert(powerIsOn && contract.elapsed==119);
  second(); assert(!powerIsOn && contract.phase==5 && contract.elapsed==120);
  assert(sleepCount==1); auto expired=contract;
  resetRam(); assert(contract.phase==5 && contract.boot==expired.boot);
  assert(contract.generation==expired.generation && contract.due==expired.due);

  // Repeated arm, TXD/SYS_UP, wall-clock reversal, edits and cancellation cannot renew.
  ready(); activate(); finishClick(); age(40);
  uint16_t timer=TCNT2;
  for (int i=0;i<10;++i) {
    command(1); command(2); command(1,contract.boot,2,T+600);
    pins[PIN_TX_UP]=0; PCINT0_vect(); pins[PIN_TX_UP]=1; PCINT0_vect();
    pins[PIN_SYS_UP]=1; PCINT1_vect(); pins[PIN_SYS_UP]=0; PCINT1_vect();
  }
  utc(T-86400); contractPoll(); softWireMaster.available=false;
  assert(contract.elapsed==40 && TCNT2==timer && contract.due==T);
  age(80); assert(contract.phase==5 && !powerIsOn);

  for (int elapsed: {0,59,60,119,120}) {
    ready(); activate(); age(elapsed);
    command(3,contract.boot+1,1,T); // Stale incarnation cannot complete.
    if (elapsed<120) assert(powerIsOn);
    command(3);
    assert(!powerIsOn && contract.phase==(elapsed<60 ? 3 : elapsed<120 ? 4 : 5));
    auto before=EEPROM.memory; command(1,contract.boot,2,T+600);
    assert(EEPROM.memory==before); // An unimported result cannot be replaced.
  }
  ready(); activate(); age(119); TIFR2.value=_BV(TOV2); command(3);
  assert(contract.phase==5 && contract.elapsed==120); // Expiry wins a pending IRQ.

  ready(); utc(T+65); command(2);
  assert(contractActive() && contract.elapsed==65); age(55);
  assert(contract.phase==5); // A late cancellation cannot erase T.
  ready(); command(2); assert(contract.phase==7); auto cancelled=contract;
  resetRam(); assert(contract.phase==7 && contract.boot==cancelled.boot);
  command(4); assert(contract.phase==0 && contract.boot!=cancelled.boot);
  command(1,contract.boot,1,T); assert(contract.phase==0); // Ordering fence survives ack.
  command(1,contract.boot,1,T+1); assert(contract.phase==1);
  ready(); command(2); command(4);
  command(1,contract.boot,2,4102444800U); assert(contract.phase==0);

  // Actual legacy protection path remains available during scheduled grace.
  ready(); activate(); finishClick();
  temperature=90; i2cReg[I2C_CONF_OVER_TEMP_POINT]=80;
  i2cReg[I2C_CONF_OVER_TEMP_ACTION]=1;
  handleTemperatureActtonsIfNeeded(); finishClick();
  powerCutDelay=0; TIM1_OVF_vect();
  assert(!powerIsOn && contract.phase==6 && TIMSK2==0);

  // Reset never grants a new grace period, and repeated reset keeps the same incident.
  ready(); activate(); age(30); resetRam();
  assert(contract.phase==6 && !powerIsOn); auto interrupted=contract;
  resetRam(); assert(contract.phase==6 && contract.boot==interrupted.boot);

  // Fault every journal byte publication. Recovery is an unknown interruption or
  // the fully published expiry; no torn bytes can claim a normal completion.
  ready(); activate(); auto active=EEPROM.memory; auto activeRecord=contract; byte activeSlot=contractSlot;
  int cuts=0;
  for (int fault=0;fault<=14;++fault) {
    EEPROM.memory=active; EEPROM.remaining=-1;
    contract=activeRecord; contractSlot=activeSlot;
    // Use known active RAM and allow one complete cut transition to fault.
    contract.phase=2; contract.elapsed=119; powerOn();
    EEPROM.remaining=fault;
    try { second(); } catch (const Interrupted&) { ++cuts; }
    assert(!powerIsOn);
    EEPROM.remaining=-1; resetRam();
    assert(contract.phase==6 || contract.phase==5);
  }
  assert(cuts==14);

  // More than one sequence wrap with all 32 wear-levelled slots. An MCU reset
  // retains the exact cancelled event until ack; ordinary cycles do not consume
  // a new incarnation, and old commands remain fenced by generation/due.
  ready(); auto incarnation=contract.boot;
  for (int cycle=0;cycle<300;++cycle) {
    command(2); assert(contract.phase==7);
    auto event=contract;
    if (cycle%50==0) {
      resetRam(); assert(contract.phase==7 && contract.due==event.due);
      command(4); assert(contract.boot==uint16_t(incarnation+1));
      incarnation=contract.boot;
    } else {
      command(4); assert(contract.boot==incarnation);
    }
    command(4); assert(contract.phase==0); // Lost ack replay is inert.
    command(1,contract.boot,1,T+cycle+1); assert(contract.phase==1);
  }
  for (int slot=0;slot<32;++slot) assert(EEPROM.memory[64+slot*13+12]==0xA5);

  ready(); contract.boot=65535; contract.phase=5; contractSave(); resetRam();
  command(4); assert(contract.phase==6 && contract.boot==0);
  resetRam(); assert(contract.phase==6 && contract.boot==0);
  command(1,0,2,T+100); assert(contract.phase==6); // Exhaustion never wraps to a fresh identity.

  // Calendar parser uses real Gregorian limits and survives the 2038 boundary.
  softWireMaster.marker=0xA5;
  for (uint32_t time: {946684800U,1709164799U,2147483648U,4102444799U}) {
    utc(time); assert(contractUtc()==time);
  }
  utc(T); softWireMaster.bytes[0]|=0x80; assert(contractUtc()==0);
  utc(1709164799); softWireMaster.bytes[3]=0x30; assert(contractUtc()==0);
  utc(T); softWireMaster.bytes[4]=7; assert(contractUtc()==0);
  std::cout << "PASS: controller deadline, actual GPIO paths, 15 EEPROM cut points\n";
}
