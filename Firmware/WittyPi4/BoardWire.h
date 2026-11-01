/*==============================================================================================================*

    @file     WireS.h
    @license  MIT (c) 2016 Nadav Matalon

    ATtiny841 I2C Slave Library

    Ver. 1.0.0 - First release (1.12.16)

 *===============================================================================================================*
    LICENSE
 *===============================================================================================================*

    The MIT License (MIT)
    Copyright (c) 2016 Nadav Matalon

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
    documentation files (the "Software"), to deal in the Software without restriction, including without
    limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
    the Software, and to permit persons to whom the Software is furnished to do so, subject to the following
    conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial
    portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
    LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
    WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

 *==============================================================================================================*/

// ATTinyCore 1.5.2 WireS slave engine, with its unused Stream/Print
// polymorphism removed: both sketches only consume this fixed byte API.
// The interrupt engine and 32-byte buffering below retain the pinned source.
#pragma once
#include <Arduino.h>
#define I2C_BUFFER_LENGTH 32
#define TWI_HIGH_NOISE_MODE 0
#define I2C_INTR_FLAG_ON do{}while(0)
#define I2C_INTR_FLAG_OFF do{}while(0)
#define SET_TENBIT do { i2c->Addr |= 0x8000; } while(0)
#define CLEAR_TENBIT do { i2c->Addr &= 0x7FFF; } while(0)
#define IS_TENBIT (i2c->Addr & 0x8000)

struct i2cStruct {
    uint8_t  Buffer[I2C_BUFFER_LENGTH];      // Tx/Rx Buffer                      (ISR)
    volatile uint8_t rxBufferIndex;          // bounded by the 32-byte buffer
    volatile uint8_t rxBufferLength;
    volatile uint8_t txBufferIndex;
    volatile uint8_t txBufferLength;
    volatile char     startCount;            // repeated START count              (User&ISR)
    volatile uint16_t Addr;                  // Tx/Rx address                     (User&ISR)
    boolean (*user_onAddrReceive)(uint16_t, uint8_t);  // Slave Addr Callback Function      (User)
    void (*user_onReceive)(size_t);          // Slave Rx Callback Function        (User)
    void (*user_onRequest)(void);            // Slave Tx Callback Function        (User)
    void (*user_onStop)(void);               // Stop Callback Function            (User)
};

static i2cStruct wireState;
struct BoardWire {
  static void begin(uint8_t address) {
    TWSA=(address << 1); TWSAM=0; wireState.startCount=-1;
    TWSCRA=(_BV(TWSHE)|_BV(TWDIE)|_BV(TWASIE)|_BV(TWEN)|_BV(TWSIE));
  }
  static size_t write(uint8_t data) {
    if (wireState.txBufferLength >= I2C_BUFFER_LENGTH) return 0;
    wireState.Buffer[wireState.txBufferLength++]=data;
    return 1;
  }
  static int available() { return wireState.rxBufferLength-wireState.rxBufferIndex; }
  static int read() {
    if (wireState.rxBufferIndex >= wireState.rxBufferLength) return -1;
    return wireState.Buffer[wireState.rxBufferIndex++];
  }
  static void onAddrReceive(boolean (*fn)(uint16_t,uint8_t)) { wireState.user_onAddrReceive=fn; }
  static void onReceive(void (*fn)(size_t)) { wireState.user_onReceive=fn; }
  static void onRequest(void (*fn)()) { wireState.user_onRequest=fn; }
};
static BoardWire TinyWireS;

void i2c_isr_handler() {
    struct i2cStruct *i2c = &wireState;
    byte status = TWSSRA;
    if ((status & (_BV(TWC) | _BV(TWBE)))) {
        i2c->startCount = -1;
        CLEAR_TENBIT;
        TWSSRA |= (_BV(TWASIF) | _BV(TWDIF) | _BV(TWBE));
        return;
    }
    if ((status & _BV(TWASIF)) || IS_TENBIT) {
        if ((status & _BV(TWAS))) {
            if (IS_TENBIT) i2c->Addr = (((i2c->Addr & B110) << 7) | TWSD);
            else {
                i2c->Addr = TWSD;
                i2c->startCount++;
                if ((i2c->Addr & B11111001) == B11110000) {
                    SET_TENBIT;
                    TWSCRB = (B0011 | TWI_HIGH_NOISE_MODE);
                    return;
                }
            }
            if (i2c->user_onAddrReceive != (void *)NULL) {
                i2c->rxBufferIndex = 0;
                if (!i2c->user_onAddrReceive(i2c->Addr, i2c->startCount)) {
                    TWSCRB = (B0111 | TWI_HIGH_NOISE_MODE);
                    return;
                }
            }
            if ((status & _BV(TWDIR))) {
                i2c->txBufferLength = 0;
                if (i2c->user_onRequest != (void *)NULL) i2c->user_onRequest();
                i2c->txBufferIndex = 0;
            } else i2c->rxBufferLength = 0;
        } else {
            if ((status & _BV(TWDIR))) {
                if (i2c->user_onStop != (void *)NULL) i2c->user_onStop();
            } else {
                if (i2c->user_onReceive != (void *)NULL) {
                    i2c->rxBufferIndex = 0;
                    i2c->user_onReceive(i2c->rxBufferLength);
                }
            }
            i2c->startCount = -1;
            CLEAR_TENBIT;
            TWSSRA = _BV(TWASIF);
            return;
        }
    } else if ((status & _BV(TWDIF))) {
        if ((status & _BV(TWDIR))) {
            if (i2c->txBufferIndex < i2c->txBufferLength) TWSD = i2c->Buffer[i2c->txBufferIndex++];
            else {
                TWSCRB = (B0010 | TWI_HIGH_NOISE_MODE);
                return;
            }
        } else {
            if (i2c->rxBufferLength < I2C_BUFFER_LENGTH) i2c->Buffer[i2c->rxBufferLength++] = TWSD;
            else {
                TWSCRB = (B0110 | TWI_HIGH_NOISE_MODE);
                return;
            }
        }
    }
    TWSCRB = (B0011 | TWI_HIGH_NOISE_MODE);
}

ISR(TWI_SLAVE_vect) {
    I2C_INTR_FLAG_ON;
    i2c_isr_handler();
    I2C_INTR_FLAG_OFF;
}

