/**
 * Firmware for WittyPi 4
 * 
 * Revision: 11
 */
 
#define I2C_TIMEOUT 2
#define SDA_PIN 2
#define SDA_PORT PORTB
#define SCL_PIN 0
#define SCL_PORT PORTA
#include "SoftWireMaster.h"

#include "BoardWire.h"
#include <core_timers.h>
#include <avr/sleep.h>
#include <EEPROM.h>

#define PIN_SYS_UP                0   // pin to listen to SYS_UP
#define PIN_LED                   0   // pin to drive white LED
#define PIN_BUTTON                1   // pin to button
#define PIN_CTRL                  3   // pin to control output
#define PIN_TX_UP                 5   // pin to listen to Raspberry Pi's TXD
#define PIN_VIN                   A1  // pin to ADC1
#define PIN_VOUT                  A2  // pin to ADC2
#define PIN_VK                    A3  // pin to ADC3

#define PIN_SDA                   4   // pin to SDA for I2C (ATtiny841 as slave)
#define PIN_SCL                   6   // pin to SCL for I2C (ATtiny841 as slave)

#define PIN_I_SDA                 2   // pin to SDA for internal I2C (ATtiny841 as master)
#define PIN_I_SCL                 10  // pin to SCL for internal I2C (ATtiny841 as master)

#define ADDRESS_LM75B           0x48  // LM75B address in internal I2C bus
#define ADDRESS_RTC             0x51  // PCF85063 address in internal I2C bus

/*
 * I2C registers
 * 
 * Registers with index 0~15 are readonly
 * Registers with index 16~49 can be read/wrote
 * Registers with index >= 50 are vitual registers
 */

/*
 * read-only registers
 */
#define I2C_ID                      0   // firmware id
#define I2C_VOLTAGE_IN_I            1   // integer part for input voltage
#define I2C_VOLTAGE_IN_D            2   // decimal part (x100) for input voltage
#define I2C_VOLTAGE_OUT_I           3   // integer part for output voltage
#define I2C_VOLTAGE_OUT_D           4   // decimal part (x100) for output voltage
#define I2C_CURRENT_OUT_I           5   // integer part for output current
#define I2C_CURRENT_OUT_D           6   // decimal part (x100) for output current
#define I2C_POWER_MODE              7   // 1 if Witty Pi is powered via the DC input, 0 if direclty use 5V input
#define I2C_LV_SHUTDOWN             8   // 1 if system was shutdown by low voltage, otherwise 0
#define I2C_ALARM1_TRIGGERED        9   // 1 if alarm1 (startup) has been triggered
#define I2C_ALARM2_TRIGGERED        10  // 1 if alarm2 (shutdown) has been triggered
#define I2C_ACTION_REASON           11  // the latest action reason: 1-alarm1; 2-alarm2; 3-click; 4-low voltage; 5-voltage restored; 6-over temperature; 7-below temperature; 8-alarm1 delayed; 10-power connected; 11-reboot; 12-guaranteed wake
#define I2C_FW_REVISION             12  // the firmware revision
#define I2C_RFU_1                   13  // reserve for future usage
#define I2C_RFU_2                   14  // reserve for future usage
#define I2C_RFU_3                   15  // reserve for future usage

/*
 * readable/writable registers
 */
#define I2C_CONF_ADDRESS            16  // I2C slave address: defaul=0x08
#define I2C_CONF_DEFAULT_ON         17  // turn on RPi when power is connected: 1=yes, 0=no
#define I2C_CONF_PULSE_INTERVAL     18  // pulse interval (in seconds, for LED and dummy load): default=4 (4 sec)
#define I2C_CONF_LOW_VOLTAGE        19  // low voltage threshold (x10), 255=disabled
#define I2C_CONF_BLINK_LED          20  // how long the white LED should stay on (in ms), 0 if white LED should not blink.
#define I2C_CONF_POWER_CUT_DELAY    21  // the delay (x10) before power cut: default=70 (7 sec)
#define I2C_CONF_RECOVERY_VOLTAGE   22  // voltage (x10) that triggers recovery, 255=disabled
#define I2C_CONF_DUMMY_LOAD         23  // how long the dummy load should be applied (in ms), 0 if dummy load is off.
#define I2C_CONF_ADJ_VIN            24  // adjustment for measured Vin (x100), range from -127 to 127
#define I2C_CONF_ADJ_VOUT           25  // adjustment for measured Vout (x100), range from -127 to 127
#define I2C_CONF_ADJ_IOUT           26  // adjustment for measured Iout (x100), range from -127 to 127

#define I2C_CONF_SECOND_ALARM1      27  // Second_alarm register for startup alarm (BCD format)
#define I2C_CONF_MINUTE_ALARM1      28  // Minute_alarm register for startup alarm (BCD format)
#define I2C_CONF_HOUR_ALARM1        29  // Hour_alarm register for startup alarm (BCD format)
#define I2C_CONF_DAY_ALARM1         30  // Day_alarm register for startup alarm (BCD format)
#define I2C_CONF_WEEKDAY_ALARM1     31  // Weekday_alarm register for startup alarm (BCD format)

#define I2C_CONF_SECOND_ALARM2      32  // Second_alarm register for shutdown alarm (BCD format)
#define I2C_CONF_MINUTE_ALARM2      33  // Minute_alarm register for shutdown alarm (BCD format)
#define I2C_CONF_HOUR_ALARM2        34  // Hour_alarm register for shutdown alarm (BCD format)
#define I2C_CONF_DAY_ALARM2         35  // Day_alarm register for shutdown alarm (BCD format)
#define I2C_CONF_WEEKDAY_ALARM2     36  // Weekday_alarm register for shutdown alarm (BCD format)

#define I2C_CONF_RTC_OFFSET         37  // standard value for RTC offset register
#define I2C_CONF_RTC_ENABLE_TC      38  // set to 1 to enable temperature compensation
#define I2C_CONF_FLAG_ALARM1        39  // a flag that indicates alarm1 is triggered and not processed
#define I2C_CONF_FLAG_ALARM2        40  // a flag that indicates alarm2 is triggered and not processed

#define I2C_CONF_IGNORE_POWER_MODE  41  // set 1 to ignore I2C_POWER_MODE for low voltage shutdown and recovery
#define I2C_CONF_IGNORE_LV_SHUTDOWN 42  // set 1 to ignore I2C_LV_SHUTDOWN for low voltage shutdown and recovery

#define I2C_CONF_BELOW_TEMP_ACTION  43  // action for below temperature: 0-do nothing; 1-shutdown; 2-startup
#define I2C_CONF_BELOW_TEMP_POINT   44  // set point for below temperature
#define I2C_CONF_OVER_TEMP_ACTION   45  // action for over temperature: 0-do nothing; 1-shutdown; 2-startup
#define I2C_CONF_OVER_TEMP_POINT    46  // set point for over temperature

#define I2C_CONF_DEFAULT_ON_DELAY   47  // the delay (in second) between MCU initialization and turning on Raspberry Pi, when I2C_CONF_DEFAULT_ON = 1
#define I2C_CONF_MISC               48  // 8 bits for miscellaneous configuration. 
                                        //   bit-0: set to 1 to disable alarm1 (startup) delay
#define I2C_CONF_GUARANTEED_WAKE    49  // 8 bits for guarenteed wake configuration.
                                        //   bit-0~6: guaranteed wake duration (0~127)
                                        //   bit-7: guaranteed wake duration unit (0=hour, 1=day)

#define I2C_REG_COUNT               50  // number of (non-virtual) I2C registers

/*
 * virtual registers (mapped to LM75B or RCF85063)
 */
#define I2C_LM75B_TEMPERATURE       50  // mapped to temperature register in LM75B (2 bytes, readonly)
#define I2C_LM75B_CONF              51  // mapped to configuration register in LM75B
#define I2C_LM75B_THYST             52  // mapped to hysteresis temperature register in LM75B (2 bytes)
#define I2C_LM75B_TOS               53  // mapped to overtemperature register in LM75B (2 bytes)

#define I2C_RTC_CTRL1               54  // mapped to Control_1 register in PCF85063
#define I2C_RTC_CTRL2               55  // mapped to Control_2 register in PCF85063
#define I2C_RTC_OFFSET              56  // mapped to Offset register in PCF85063
#define I2C_RTC_RAM_BYTE            57  // mapped to RAM_byte register in PCF85063
#define I2C_RTC_SECONDS             58  // mapped to Seconds register in PCF85063
#define I2C_RTC_MINUTES             59  // mapped to Minutes register in PCF85063
#define I2C_RTC_HOURS               60  // mapped to Hours register in PCF85063
#define I2C_RTC_DAYS                61  // mapped to Days register in PCF85063
#define I2C_RTC_WEEKDAYS            62  // mapped to Weekdays register in PCF85063
#define I2C_RTC_MONTHS              63  // mapped to Months register in PCF85063
#define I2C_RTC_YEARS               64  // mapped to Years register in PCF85063
#define I2C_RTC_SECOND_ALARM        65  // mapped to Second_alarm register in PCF85063
#define I2C_RTC_MINUTE_ALARM        66  // mapped to Minute_alarm register in PCF85063
#define I2C_RTC_HOUR_ALARM          67  // mapped to Hour_alarm register in PCF85063
#define I2C_RTC_DAY_ALARM           68  // mapped to Day_alarm register in PCF85063
#define I2C_RTC_WEEKDAY_ALARM       69  // mapped to Weekday_alarm register in PCF85063
#define I2C_RTC_TIMER_VALUE         70  // mapped to Timer_value register in PCF85063
#define I2C_RTC_TIMER_MODE          71  // mapped to Timer_mode register in PCF85063

/**
 * Reason for latest action (used by I2C_ACTION_REASON register)
 */
#define REASON_ALARM1             1
#define REASON_ALARM2             2
#define REASON_CLICK              3
#define REASON_LOW_VOLTAGE        4
#define REASON_VOLTAGE_RESTORE    5
#define REASON_OVER_TEMPERATURE   6
#define REASON_BELOW_TEMPERATURE  7
#define REASON_ALARM1_DELAYED     8
#define REASON_POWER_CONNECTED    10
#define REASON_REBOOT             11
#define REASON_GUARANTEED_WAKE    12


volatile byte i2cReg[I2C_REG_COUNT];

volatile char i2cIndex = 0;

volatile boolean buttonPressed = false;

volatile boolean powerIsOn = false;

volatile boolean listenToTxd = false;

volatile boolean systemIsUp = false;

volatile boolean turningOff = false;

volatile boolean wakeupByWatchdog = false;

volatile boolean ledIsOn = false;

volatile byte powerCutDelay = 0;

volatile boolean isButtonClickEmulated = false;

volatile byte skipAdjustRtcCount = 0;

volatile byte skipTempShutdownCount = 0;

volatile byte skipPulseCount = 0;

volatile byte skipLowVoltageDetectCount = 0;

volatile byte alarm1Delayed = 0;

volatile byte ledUpTime = 0;

volatile byte lastButton = 1;

volatile byte lastSystemUp = 0;

volatile boolean turnOffFromTXD = false;

volatile unsigned long guaranteedWakeCounter = 0;

volatile byte lowVoltageCacheInteger = 0;

volatile byte lowVoltageCacheDecimal = 0;

SoftWireMaster softWireMaster;  // software I2C master


#include "BoardPins.h"

void contractSetup();
void contractPoll();
void contractReceive(int count);
void contractReply();
void contractInterrupted();
boolean contractActive();
boolean calendarTrusted();
boolean calendarPending();
boolean contractLocked();
void calendarWrite();

void setup() {
  TOCPMCOE = 0; // Dedicated controller timers never drive compare-output pins.
  // initialize software I2C master
  softWireMaster.begin();

  // initialize pin states and make sure power is cut
  boardPinMode(PIN_SYS_UP, INPUT);
  boardPinMode(PIN_BUTTON, INPUT_PULLUP);
  boardPinMode(PIN_CTRL, OUTPUT);
  boardPinMode(PIN_TX_UP, INPUT);
  boardPinMode(PIN_VIN, INPUT);
  boardPinMode(PIN_VOUT, INPUT);
  boardPinMode(PIN_VK, INPUT);
  boardPinMode(PIN_SDA, INPUT_PULLUP);
  boardPinMode(PIN_SCL, INPUT_PULLUP);
  cutPower();

  // use internal 1.1V reference
  analogReference(INTERNAL1V1);

  // initlize registers
  initializeRegisters();
  contractSetup();

  // i2c initialization
  TinyWireS.begin((i2cReg[I2C_CONF_ADDRESS] <= 0x07 || i2cReg[I2C_CONF_ADDRESS] >= 0x78) ? 0x08 : i2cReg[I2C_CONF_ADDRESS]);
  TinyWireS.onAddrReceive(addressEvent);
  TinyWireS.onReceive(receiveEvent);
  TinyWireS.onRequest(requestEvent);

  // disable global interrupts
  cli();

  // enable pin change interrupts
  GIMSK = _BV (PCIE0) | _BV (PCIE1);
  PCMSK1 = _BV (PCINT8) | _BV (PCINT9);
  PCMSK0 = _BV (PCINT5);

  // enable Timer1
  timer1_enable();

  // enable watchdog
  watchdog_enable(0);
  
  // enable all interrupts
  sei();

  // power on or sleep
  bool defaultOn = (i2cReg[I2C_CONF_DEFAULT_ON] == 1);
  if (defaultOn) {
    delay(i2cReg[I2C_CONF_DEFAULT_ON_DELAY] * 1000);  // delay if the value is configured
    updateRegister(I2C_ACTION_REASON, REASON_POWER_CONNECTED);
    powerOn();  // power on directly
  } else {
    sleep();    // sleep and wait for button action
  }  
}


void loop() {
  // we don't put anything here
}


// initialize the registers and synchronize with EEPROM
void initializeRegisters() {
#if defined(WITTY_PI_4_MINI)
  i2cReg[I2C_ID] = 0x36;
#else
  i2cReg[I2C_ID] = 0x26;
#endif
  i2cReg[I2C_CONF_ADDRESS] = 0x08;

  i2cReg[I2C_CONF_PULSE_INTERVAL] = 4;
  i2cReg[I2C_CONF_LOW_VOLTAGE] = 255;
  i2cReg[I2C_CONF_BLINK_LED] = 100;
  i2cReg[I2C_CONF_POWER_CUT_DELAY] = 70;
  i2cReg[I2C_CONF_RECOVERY_VOLTAGE] = 255;

  i2cReg[I2C_CONF_ADJ_VIN] = 20;
  i2cReg[I2C_CONF_ADJ_VOUT] = 20;

  i2cReg[I2C_CONF_RTC_ENABLE_TC] = 0x01;

  i2cReg[I2C_CONF_BELOW_TEMP_POINT] = 0x4b;
  i2cReg[I2C_CONF_OVER_TEMP_POINT] = 0x50;

  // synchronize configuration with EEPROM
  for (byte i = 0; i < I2C_REG_COUNT; i ++) {
    byte val = EEPROM.read(i);
    if (val == 255) {
      eeprom_update_byte((byte *)(uintptr_t)i, i2cReg[i]);
    } else {
      i2cReg[i] = val;
    } 
  }
  // Capabilities belong to this firmware, not the EEPROM from an older image.
  i2cReg[I2C_FW_REVISION] = 0x0C;

  // copy some EEPROM backed data to PCF85063 and LM75B
  writeToDevice(ADDRESS_LM75B, I2C_LM75B_TOS - I2C_LM75B_TEMPERATURE, &i2cReg[I2C_CONF_OVER_TEMP_POINT], 1);
  writeToDevice(ADDRESS_LM75B, I2C_LM75B_THYST - I2C_LM75B_TEMPERATURE, &i2cReg[I2C_CONF_BELOW_TEMP_POINT], 1);
  writeToDevice(ADDRESS_RTC, I2C_RTC_OFFSET - I2C_RTC_CTRL1, &i2cReg[I2C_CONF_RTC_OFFSET], 1);
}


// enable watchdog timer with specified wdp (or get it from I2C_CONF_PULSE_INTERVAL)
void watchdog_enable(byte wdp) {
  cli();
  WDTCSR |= _BV(WDIE);
  WDTCSR |= 6;  // trigger every second
  sei();
}


// enable timer1 (for power cut delay)
void timer1_enable() {
  // set entire TCCR1A and TCCR1B register to 0
  TCCR1A = 0;
  TCCR1B = 0;
  
  // set 1024 prescaler
  bitSet(TCCR1B, CS12);
  bitSet(TCCR1B, CS10);

  // clear overflow interrupt flag
  bitSet(TIFR1, TOV1);

  // set timer counter
  TCNT1 = getPowerCutPreloadTimer(true);

  // enable Timer1 overflow interrupt
  bitSet(TIMSK1, TOIE1);
}


// disable timer1
void timer1_disable() {
  // disable Timer1 overflow interrupt
  bitClear(TIMSK1, TOIE1);
}


// put MCU into sleep to save power
void sleep() {
  timer1_disable();                       // disable Timer1
  ADCSRA &= ~_BV(ADEN);                   // ADC off
  set_sleep_mode(SLEEP_MODE_PWR_DOWN);    // power-down mode 
  sleep_enable();                         // sets the Sleep Enable bit in the MCUCR Register (SE BIT)
  
  GIMSK = _BV (PCIE1);                    // only enable interrupt for switch (PCINT9)
  PCMSK1 = _BV (PCINT9);
  sei();

  wakeupByWatchdog = true;
  do {
    sleep_cpu();                          // sleep
    if (wakeupByWatchdog) {               // wake up by watch dog

      boolean guaranteedWake = false;
      unsigned long guaranteedWakeThreshold = (i2cReg[I2C_CONF_GUARANTEED_WAKE] & 0x7F);
      if (guaranteedWakeThreshold > 0) {
        guaranteedWakeCounter ++;
        if (guaranteedWakeCounter >= guaranteedWakeThreshold * ((i2cReg[I2C_CONF_GUARANTEED_WAKE] & 0x80) > 0 ? 86400 : 3600)) {
          uint16_t vin = updatePowerMode();
          if (i2cReg[I2C_POWER_MODE] == 0) {
            guaranteedWake = true;
          } else {
            uint16_t vrec = (i2cReg[I2C_CONF_RECOVERY_VOLTAGE] == 255) ? 0 : ((uint16_t)i2cReg[I2C_CONF_RECOVERY_VOLTAGE]) * 100;
            if (vin >= vrec) {
              guaranteedWake = true;
            } else {
              guaranteedWakeCounter = 0; // input voltage is too low, will try again later
            }
          }
        }
        if (guaranteedWake) {
          wakeupByWatchdog = false;
          updateRegister(I2C_ACTION_REASON, REASON_GUARANTEED_WAKE);  // guarantee wake up in given duration
        }
      }
      
      skipPulseCount ++;
      if (!guaranteedWake && skipPulseCount >= i2cReg[I2C_CONF_PULSE_INTERVAL]) {
        skipPulseCount = 0;

        // blink white LED
        if (i2cReg[I2C_CONF_BLINK_LED] > 0) {
          byte ms = i2cReg[I2C_CONF_BLINK_LED];
          ledOn();
          delay(ms);
          ledOff();
        }
  
        // dummy load
        if (i2cReg[I2C_CONF_DUMMY_LOAD] > 0) {
          byte ms = i2cReg[I2C_CONF_DUMMY_LOAD];
          boardWrite(PIN_CTRL, 1);
          delay(ms);
          cutPower();
        }

        // update power mode and get input voltage
        uint16_t vin = updatePowerMode();
  
        // check input voltage if shutdown because of low voltage, and recovery voltage has been set
        // will skip checking I2C_LV_SHUTDOWN if I2C_CONF_LOW_VOLTAGE is set to 0xFF
        if ((i2cReg[I2C_POWER_MODE] == 1 || i2cReg[I2C_CONF_IGNORE_POWER_MODE] == 1) 
            && (i2cReg[I2C_LV_SHUTDOWN] == 1 || i2cReg[I2C_CONF_LOW_VOLTAGE] == 255 || i2cReg[I2C_CONF_IGNORE_LV_SHUTDOWN] == 1) 
            && i2cReg[I2C_CONF_RECOVERY_VOLTAGE] != 255) {
          uint16_t vrec = ((uint16_t)i2cReg[I2C_CONF_RECOVERY_VOLTAGE]) * 100;
          if (vin >= vrec) {
            wakeupByWatchdog = false;       // recovery from low voltage shutdown
            updateRegister(I2C_ACTION_REASON, REASON_VOLTAGE_RESTORE);
          }
        }
      }
    }
  } while (wakeupByWatchdog);             // quit sleeping if wake up by button

  cli();                                  // disable interrupts
  sleep_disable();                        // clear SE bit
  ADCSRA |= _BV(ADEN);                    // ADC on
  timer1_enable();                        // enable Timer1

  GIMSK = _BV (PCIE0) | _BV (PCIE1);
  PCMSK1 = _BV (PCINT8) | _BV (PCINT9); 
  sei();                                  // enable all required interrupts

  // tap the button to wake up
  listenToTxd = false;
  systemIsUp = false;
  turningOff = false;
  powerOn();
  TCNT1 = getPowerCutPreloadTimer(true);
}


// cut 5V output on GPIO header 
void cutPower() {
  powerIsOn = false;
  boardWrite(PIN_CTRL, 0);
  contractInterrupted();
  turnOffFromTXD = false;
}


// output 5V to GPIO header
void powerOn() {
  powerIsOn = true;
  skipTempShutdownCount = 0;
  guaranteedWakeCounter = 0;
  skipLowVoltageDetectCount = 0;
  boardWrite(PIN_CTRL, 1);
  updatePowerMode();
}


// turn on white LED
void ledOn() {
  ledIsOn = true;
  boardPinMode(PIN_LED, OUTPUT);
  boardWrite(PIN_LED, 1);
  ledUpTime = 0;
}


// turn off white LED
void ledOff() {
  boardWrite(PIN_LED, 0);
  boardPinMode(PIN_LED, INPUT);
  ledIsOn = false;
}


uint16_t adjusted(uint16_t raw, int16_t delta) {
  return delta < 0 && raw < (uint16_t)-delta ? 0 : raw + delta;
}

uint16_t scaledAdc(byte pin, uint16_t fullScale) {
  uint32_t product=(uint32_t)fullScale * analogRead(pin);
  // For this board's fullScale<=62700, high+(product&1023) fits uint16_t.
  // product=high*1023+high+low: exact division without a 32-bit divider.
  uint16_t high=product >> 10;
  return high + (high + (uint16_t)(product & 1023)) / 1023;
}

// get voltage at specific pin
uint16_t getAdcVoltageAtPin(byte pin) {
  return scaledAdc(pin, 62700);    // 57*1.1/1023~=0.06129
}


// get voltage at cathode
uint16_t getCathVoltage() {
  return scaledAdc(PIN_VK, 1100);   // 1.1/1023~=0.001075
}


// get actual adjust value for given register
int16_t getAdjustValue(byte regId) {
  return (int16_t)((char)i2cReg[regId]) * 10;
}


// update power mode according to input voltage, and return the input voltage
uint16_t updatePowerMode() {
  byte bk = ADCSRA;
  ADCSRA |= _BV(ADEN);
  uint16_t vin = getAdcVoltageAtPin(PIN_VIN);
  ADCSRA = bk;  
  updateRegister(I2C_POWER_MODE, (vin > 5250) ? 1 : 0);
  return vin;
}


// get input voltage
uint16_t getInputVoltage() {
  if (lowVoltageCacheInteger == 0) {
    uint16_t v = getAdcVoltageAtPin(PIN_VIN);
    v = adjusted(v, getAdjustValue(I2C_CONF_ADJ_VIN));
    updateMeasurement(I2C_VOLTAGE_IN_I, v);
    return v;
  } else {
    return (uint16_t)lowVoltageCacheInteger * 1000 + (uint16_t)lowVoltageCacheDecimal * 10;
  }
}


// get output voltage
uint16_t getOutputVoltage() {
  uint16_t v = getAdcVoltageAtPin(PIN_VOUT);
  uint16_t vk = getCathVoltage();
  v = adjusted(v, getAdjustValue(I2C_CONF_ADJ_VOUT) - vk);
  updateMeasurement(I2C_VOLTAGE_OUT_I, v);
  return v;
}


// get output current
uint16_t getOutputCurrent() {
  uint16_t v = scaledAdc(PIN_VK, 22000);
  uint16_t i = adjusted(v, getAdjustValue(I2C_CONF_ADJ_IOUT));
  updateMeasurement(I2C_CURRENT_OUT_I, i);
  return i;
}


// get temperature; false when the LM75B did not return its byte, because
// every value (0xFF is -1 degree) is a valid reading and cannot mark failure
bool getTemperature(char &t) {
  if (readFromDevice(ADDRESS_LM75B, 0, 1) != 1) return false;
  t = softWireMaster.read();
  return true;
}


void updateMeasurement(byte index, uint16_t value) {
  updateRegister(index, value / 1000);
  updateRegister(index + 1, (value / 10) % 100);
}

// get integer part of given number
byte getIntegerPart(uint16_t v) {
  return v / 1000;
}


// get decimal part of given number
byte getDecimalPart(uint16_t v) {
  return (v / 10) % 100;
}


// get the preload timer value for power cut
unsigned int getPowerCutPreloadTimer(boolean reset) {
  if (reset) {
    powerCutDelay = i2cReg[I2C_CONF_POWER_CUT_DELAY];
  }
  byte actualDelay = 0;
  if (powerCutDelay > 83) {
    actualDelay = 83;
  } else {
    actualDelay = powerCutDelay;
  }
  powerCutDelay -= actualDelay;
  return 65535 - 781 * actualDelay;
}


// receives a sequence of start|address|direction bit from i2c master
boolean addressEvent(uint16_t slaveAddress, uint8_t startCount) {
  if (startCount > 0 && TinyWireS.available()) {
    i2cIndex = TinyWireS.read();
  }
  return true;
}


// receives a sequence of data from i2c master (master writes to this device)
void receiveEvent(int count) {
  if (TinyWireS.available()) {
    i2cIndex = TinyWireS.read();
    if (i2cIndex == 72) { contractReceive(count); return; }
    if (i2cIndex == I2C_RTC_RAM_BYTE) return; // Retained transaction state is readonly.
    if (i2cIndex == I2C_RTC_SECONDS) {
      if (count == 8 && !contractLocked()) calendarWrite();
      return;
    }
    if (i2cIndex >= I2C_LM75B_TEMPERATURE && i2cIndex <= I2C_RTC_TIMER_MODE) {
      byte address = ADDRESS_RTC;
      byte index = i2cIndex - I2C_RTC_CTRL1;
      byte length = 1;
      if (i2cIndex <= I2C_LM75B_TOS) {
        address = ADDRESS_LM75B;
        index = i2cIndex - I2C_LM75B_TEMPERATURE;
        length = (i2cIndex == I2C_LM75B_TEMPERATURE) ? 0 : ((i2cIndex == I2C_LM75B_CONF) ? 1 : 2);
      } else if (i2cIndex >= I2C_RTC_SECONDS && i2cIndex <= I2C_RTC_YEARS) {
        return;
      }
      if (i2cIndex == I2C_RTC_CTRL1 && (contractLocked() || !calendarPending())) return;
      if (i2cIndex >= I2C_RTC_SECOND_ALARM && !calendarTrusted()) return;
      if (count != length + 1) return;
      softWireMaster.beginTransmission(address);
      softWireMaster.write(index);
      while (length--) {
        softWireMaster.write(TinyWireS.read());
      }
      softWireMaster.endTransmission();
    } else if (i2cIndex >= I2C_CONF_ADDRESS && i2cIndex < I2C_REG_COUNT) {  // non-virtual, writable i2c register
      if (i2cIndex >= I2C_CONF_SECOND_ALARM1 && i2cIndex <= I2C_CONF_WEEKDAY_ALARM2 && !calendarTrusted()) return;
      if (TinyWireS.available()) {
        // clear alarm triggered flag if alam is changed
        if (i2cIndex >= I2C_CONF_SECOND_ALARM1 && i2cIndex <= I2C_CONF_WEEKDAY_ALARM1) {
          updateRegister(I2C_ALARM1_TRIGGERED, 0);
        }
        if (i2cIndex >= I2C_CONF_SECOND_ALARM2 && i2cIndex <= I2C_CONF_WEEKDAY_ALARM2) {
          updateRegister(I2C_ALARM2_TRIGGERED, 0);
        }

        // update the register value
        updateRegister(i2cIndex, TinyWireS.read());

        // if RTC offset value is changed, immediately update to RTC
        if (i2cIndex == I2C_CONF_RTC_OFFSET) {
          writeToDevice(ADDRESS_RTC, I2C_RTC_OFFSET - I2C_RTC_CTRL1, &i2cReg[I2C_CONF_RTC_OFFSET], 1);
        }
      }
    }
  }
}


// i2c master requests data from this device (master reads from this device)
void requestEvent() {
  if (i2cIndex == 73) { contractReply(); return; }
  if (i2cIndex == 74) { TinyWireS.write(calendarTrusted()); return; }
  if (i2cIndex >= I2C_RTC_SECONDS && i2cIndex <= I2C_RTC_WEEKDAY_ALARM && !calendarTrusted()) {
    byte count = i2cIndex == I2C_RTC_SECONDS ? 7 : 1;
    while (count--) TinyWireS.write((byte)0xFF);
    return;
  }
  switch (i2cIndex) {
    case I2C_VOLTAGE_IN_I:
      getInputVoltage();
      break;
    case I2C_VOLTAGE_OUT_I:
      getOutputVoltage();
      break;
    case I2C_CURRENT_OUT_I:
      getOutputCurrent();
      break;
    case I2C_POWER_MODE:
      updatePowerMode();
      break;
  }

  if (i2cIndex >= I2C_LM75B_TEMPERATURE && i2cIndex <= I2C_RTC_TIMER_MODE) {
    byte address = ADDRESS_RTC;
    byte index = i2cIndex - I2C_RTC_CTRL1;
    // Seconds starts a complete calendar snapshot, including weekday.
    byte count = (i2cIndex == I2C_RTC_SECONDS) ? 7 : 1;
    if (i2cIndex <= I2C_LM75B_TOS) {
      address = ADDRESS_LM75B;
      index = i2cIndex - I2C_LM75B_TEMPERATURE;
      count = (i2cIndex == I2C_LM75B_CONF) ? 1 : 2;
    }
    readFromDevice(address, index, count);
    // An empty receive buffer yields 0xFF, an invalid calendar/failure marker.
    while (count--) {
      TinyWireS.write(softWireMaster.read());
    }
  } else {
    TinyWireS.write((byte)i2cIndex < I2C_REG_COUNT ? i2cReg[(byte)i2cIndex] : 0xFF);  // bounded register
  }
}


// watchdog interrupt routine
ISR (WDT_vect) {
  contractPoll();
  // turn off white LED after delay
  ledUpTime++;
  if (ledUpTime == 3) {
    ledUpTime = 0;
    ledOff();
  }

  // process low voltage
  if (skipLowVoltageDetectCount < 255) {
    skipLowVoltageDetectCount ++;
  }
  processLowVoltageIfNeeded();

  // handle temperature related actions
  handleTemperatureActtonsIfNeeded();

  // process RTC alarms
  processAlarmIfNeeded();

  // adjust RTC
  adjustRTCIfNeeded();

  // process delayed Alarm1 (startup)
  if (!powerIsOn && alarm1Delayed > 0) {
    alarm1Delayed ++;
    if (alarm1Delayed == 4) {
      alarm1Delayed = 0;
      updateRegister(I2C_ACTION_REASON, REASON_ALARM1_DELAYED);
      emulateButtonClick();
    }
  }
}


// pin state change interrupt routine for PCINT0_vect (PCINT0~7) 
ISR (PCINT0_vect) {
  if (contractActive()) return; // TXD cannot complete or renew a scheduled contract.
  if (boardRead(PIN_TX_UP) == 1) {
    if (!listenToTxd) {
      // start listen to TXD pin;
      listenToTxd = true;
    }
  } else {
    if (listenToTxd && systemIsUp) {
     listenToTxd = false;
     systemIsUp = false;
     turningOff = true;
     turnOffFromTXD = true;
     ledOff(); // turn off the white LED
     TCNT1 = getPowerCutPreloadTimer(true);
    }
  }
}


// pin state change interrupt routine for PCINT1_vect (PCINT8~15)
ISR (PCINT1_vect) {
  byte button = boardRead(PIN_BUTTON);
  byte systemUp = boardRead(PIN_SYS_UP);

  if (button != lastButton) {
    if (button == 0) {   // button is pressed, PCINT9
      // restore from emulated button clicking
      boardWrite(PIN_BUTTON, 1);
      boardPinMode(PIN_BUTTON, INPUT_PULLUP);
      
      // turn on the white LED
      ledOn();
      
      if (!buttonPressed) {
        buttonPressed = true;
        if (!isButtonClickEmulated) {
          updateRegister(I2C_ACTION_REASON, REASON_CLICK);
        }
        if (powerIsOn) {
          if (systemIsUp && !(contractActive() && isButtonClickEmulated && i2cReg[I2C_ACTION_REASON] == REASON_ALARM2)) {
            turningOff = true;
            systemIsUp = false;
          }
        } else {
          wakeupByWatchdog = false; // will quit sleeping
          powerOn();
        }
      }
      TCNT1 = getPowerCutPreloadTimer(true);
      isButtonClickEmulated = false;
    } else {  // button is released
      buttonPressed = false;
    } 
  }
  
  if (systemUp != lastSystemUp) {
    if (!ledIsOn && powerIsOn && !turningOff && !systemIsUp && systemUp == 1)  {  // system is up, PCINT8
      // clear the low-voltage shutdown flag when sys_up signal arrives
      updateRegister(I2C_LV_SHUTDOWN, 0);
    
      // mark system is up
      systemIsUp = true;
    }
  }

  lastButton = button;
  lastSystemUp = systemUp;
}


// timer1 overflow interrupt routine
ISR (TIM1_OVF_vect) {
  if (powerCutDelay == 0) {
    // cut the power after delay
    TCNT1 = getPowerCutPreloadTimer(true);
    forcePowerCutIfNeeded();
    if (turningOff) {
      if (turnOffFromTXD && boardRead(PIN_TX_UP) == 1) {  // if it is rebooting
        turningOff = false;
        turnOffFromTXD = false; // reboot consumed this TXD shutdown
        updateRegister(I2C_ACTION_REASON, REASON_REBOOT);
        ledOn();
      } else {  // cut the power and enter sleep
        cutPower();
        sleep();
      }
    }
  } else {
    TCNT1 = getPowerCutPreloadTimer(false);
    forcePowerCutIfNeeded();
  }
}


// update I2C register and save to EEPROM
void updateRegister(byte index, byte value) {
  if (index < I2C_REG_COUNT) {
    i2cReg[index] = value;
    eeprom_update_byte((byte *)(uintptr_t)index, value);
  }
}


// emulate button clicking
void emulateButtonClick() {
  isButtonClickEmulated = true;
  boardPinMode(PIN_BUTTON, OUTPUT);
  boardWrite(PIN_BUTTON, 0);
}


// temporarily turn on ADC to get input voltage 
uint16_t turnOnAdcAndGetInputVoltage() {
  byte bk = ADCSRA;
  ADCSRA |= _BV(ADEN);
  uint16_t vin = getInputVoltage();
  ADCSRA = bk;
  return vin;
}


// check wether alarm can be triggered
boolean canTriggerAlarm() {
  if (powerIsOn || i2cReg[I2C_POWER_MODE] == 0) {
    return true;
  }
  uint16_t vin = turnOnAdcAndGetInputVoltage();
  uint16_t vlow = ((uint16_t)i2cReg[I2C_CONF_LOW_VOLTAGE]) * 100;
  if (i2cReg[I2C_LV_SHUTDOWN] == 1) {
    if (vin > vlow) {
      uint16_t vrec = ((uint16_t)i2cReg[I2C_CONF_RECOVERY_VOLTAGE]) * 100;
      if (i2cReg[I2C_CONF_RECOVERY_VOLTAGE] == 255 || vin > vrec) {
        return true;
      }
    }
  } else {
    if (vin > vlow || i2cReg[I2C_CONF_LOW_VOLTAGE] == 255) {
      return true;
    } else {
      // this will update the I2C_LV_SHUTDOWN flag when Vin drop under Vlow after shutdown
      updateRegister(I2C_LV_SHUTDOWN, 1);
    }
  }
  return false;
}


// process the alarm from RTC, if exists
void processAlarmIfNeeded() {
  if (!calendarTrusted()) return;
  // Keep seconds through day in one RTC access across clock rollovers.
  if (readFromDevice(ADDRESS_RTC, I2C_RTC_SECONDS - I2C_RTC_CTRL1, 4) != 4) return;
  byte seconds = softWireMaster.read();
  if (seconds & 0x80) return;  // oscillator stopped: no reliable alarm time
  seconds = bcd2dec(seconds);
  byte minutes = bcd2dec(softWireMaster.read());
  byte hours = bcd2dec(softWireMaster.read());
  byte date = bcd2dec(softWireMaster.read());
  long cur_ts = getTimestamp(date, hours, minutes, seconds);
  
  boolean canTrigger = canTriggerAlarm();
  byte prepare = 0;
  for (byte alarm=0; alarm<2; ++alarm) {
    byte offset = I2C_CONF_SECOND_ALARM1 + alarm*5;
    long alarm_ts = getAlarmTimestamp(offset);
    if (alarm_ts == 0 || i2cReg[I2C_ALARM1_TRIGGERED + alarm]) continue;
    long overdue = cur_ts - alarm_ts;
    if (canTrigger && overdue >= 0 && overdue < 2) {
      updateRegister(I2C_ALARM1_TRIGGERED + alarm, 1);
      updateRegister(I2C_CONF_FLAG_ALARM1 + alarm, 1);
      if (alarm == 0) {
        if (powerIsOn) {
          if (!(i2cReg[I2C_CONF_MISC] & 1)) alarm1Delayed = 1;
        } else {
          updateRegister(I2C_ACTION_REASON, REASON_ALARM1);
          emulateButtonClick();
        }
      } else if (powerIsOn && !turningOff && !contractActive()) {
        updateRegister(I2C_ACTION_REASON, REASON_ALARM2);
        emulateButtonClick();
        turningOff = true;
        systemIsUp = false;
      }
      return;
    }
    if (!prepare && overdue < 0 && overdue >= -2) prepare = offset;
  }
  if (prepare) {
    reset_rtc_alarm();
    copyAlarm(prepare);
  }
}


// enable alarm and clear the alarm flag (if exists)
void reset_rtc_alarm() {
  byte data = 0x80;
  writeToDevice(ADDRESS_RTC, 0x01, &data, 1);
}


// copy alarm data to RTC's alarm registers
void copyAlarm(byte offset) {
  writeToDevice(ADDRESS_RTC, 0x0B, &i2cReg[offset], 4);
}


// handle temperature related actions (if configured)
void handleTemperatureActtonsIfNeeded() {
  // this counter makes sure not turning off your Pi too quickly
  if (skipTempShutdownCount < 120) {
    skipTempShutdownCount ++;
  }
  char t;
  if (!getTemperature(t)) return;  // no measurement, no action
  byte action = 0;
  byte reason = 0;
  if (t > (char)i2cReg[I2C_CONF_OVER_TEMP_POINT]) {
    action = i2cReg[I2C_CONF_OVER_TEMP_ACTION];
    reason = REASON_OVER_TEMPERATURE;
  } else if (t < (char)i2cReg[I2C_CONF_BELOW_TEMP_POINT]) {
    action = i2cReg[I2C_CONF_BELOW_TEMP_ACTION];
    reason = REASON_BELOW_TEMPERATURE;
  }
  if (action == 1 || action == 2) {
    updateRegister(I2C_ACTION_REASON, reason);
    if (action == 1) turnOffIfPowerOn();
    else turnOnIfPowerOff();
  }
}


// process low voltage
void processLowVoltageIfNeeded() {
  lowVoltageCacheInteger = 0;
  // do not detect low voltage too soon since power on
  if (skipLowVoltageDetectCount < 180) {
    return;
  }
  // if input voltage is not fixed 5V, detect low voltage
  if (powerIsOn && systemIsUp 
      && (i2cReg[I2C_POWER_MODE] == 1 || i2cReg[I2C_CONF_IGNORE_POWER_MODE] == 1)
      && (i2cReg[I2C_LV_SHUTDOWN] == 0 || i2cReg[I2C_CONF_IGNORE_LV_SHUTDOWN] == 1)
      && i2cReg[I2C_CONF_LOW_VOLTAGE] != 255) {
    uint16_t vin = getInputVoltage();
    uint16_t vlow = ((uint16_t)i2cReg[I2C_CONF_LOW_VOLTAGE]) * 100;
    if (vin < vlow) {  // input voltage is below the low voltage threshold
      lowVoltageCacheInteger = i2cReg[I2C_VOLTAGE_IN_I];
      lowVoltageCacheDecimal = i2cReg[I2C_VOLTAGE_IN_D];
      updateRegister(I2C_LV_SHUTDOWN, 1);
      updateRegister(I2C_ACTION_REASON, REASON_LOW_VOLTAGE);
      emulateButtonClick();
      turningOff = true;
      systemIsUp = false;
    }
  }
}


// turn off Raspberry Pi only if it is on
void turnOffIfPowerOn() {
  if (skipTempShutdownCount >= 120 && powerIsOn && !turningOff) {
    emulateButtonClick();
    turningOff = true;
    systemIsUp = false;
  }
}


// turn on Raspberry Pi only if it is off
void turnOnIfPowerOff() {
   if (!powerIsOn) {
    emulateButtonClick();
  }
}


// Read one internal-bus transaction into SoftWireMaster's receive buffer.
byte readFromDevice(byte address, byte index, byte count) {
  softWireMaster.beginTransmission(address);
  softWireMaster.write(index);
  return softWireMaster.requestFrom((int)address, (int)count);
}


// software I2C master write data to device on internal I2C bus
byte writeToDevice(byte address, byte index, byte* data, byte count) {
  softWireMaster.beginTransmission(address);
  softWireMaster.write(index);
  for (byte i = 0; i < count; i ++) {
    softWireMaster.write(data[i]);
  }
  return softWireMaster.endTransmission();
}


// convert BCD data to DEC data
byte bcd2dec(byte bcd) {
  return bcd - 6 * (bcd >> 4);
}


long getAlarmTimestamp(byte start) {
  byte fields[4];
  for (byte i=0; i<4; ++i) fields[i]=bcd2dec(i2cReg[start+i]);
  return getTimestamp(fields[3], fields[2], fields[1], fields[0]);
}

// get timestamp for given date and time
uint32_t getTimestamp(uint16_t date, byte hours, byte minutes, byte seconds) {
  return (uint32_t)date * 86400UL + ((uint16_t)hours * 60 + minutes) * 60UL + seconds;
}


// force power cut, if button is pressed and hold for a few seconds
void forcePowerCutIfNeeded() {
 if (buttonPressed && boardRead(PIN_BUTTON) == 0) {
    systemIsUp = false;
    cutPower();
    sleep();
  }
}


// adjust the RTC with offset value and the temperature compensation data (when TC is enabled)
void adjustRTCIfNeeded() {
  skipAdjustRtcCount ++;
  if (skipAdjustRtcCount == 255) {  // no need to adjust too frequently
    skipAdjustRtcCount = 0;
  
    if (i2cReg[I2C_CONF_RTC_ENABLE_TC] == 1) {
      char t;
      if (!getTemperature(t)) return;  // keep the current RTC offset
      char adj = 0;
      if (t < 26) {
        adj = (t - 26) * 55 / 434;
      } else if (t > 42) {
        adj = (-200 - (t - 42) * 60) / 217;
      }
      byte data = value2Offset(offset2Value(i2cReg[I2C_CONF_RTC_OFFSET]) + adj);
      writeToDevice(ADDRESS_RTC, I2C_RTC_OFFSET - I2C_RTC_CTRL1, &data, 1);
    } else {
      writeToDevice(ADDRESS_RTC, I2C_RTC_OFFSET - I2C_RTC_CTRL1, &i2cReg[I2C_CONF_RTC_OFFSET], 1);
    }
  }
}


// convert stored offset value to actual signed value
char offset2Value(byte offset) {
  if ( (offset & 0x40) == 0) {
    return (offset & 0x3F);
  } else {
    return (offset & 0x3F) - 0x40;
  }
}


// convert actual signed value to offset value
byte value2Offset(char value) {
  return (byte)value & 0x7F;
}

#include "ScheduledContract.h"
