# Bug report for the Witty Pi 4 team: a failed LM75B read is decoded as −1 °C, and the thermal setters arm the action before the threshold

- **Origin:** DynAPI architectural correctness audit (DynAPI revision `f61852ee4dd3439a5ace00d502fff855d675c175`). The audit validated fifteen further defects; the thirteen in DynAPI's own repository are fixed there, and the items in the independent Witty Pi checkouts are reported to their owners. Issue 1 is finding 6 (P1, vendor-only). Issue 2 is the vendor mirror of finding 5 (P1; DynAPI's managed copy is already corrected).
- **Priority:** P1 denotes a potential unintended power change, not proof that one occurred on a device.
- **Reviewed checkout:** `Witty-Pi-4` at `4bf3bf7` ("Publish rebuilt WP4 4.25 firmware 11 retained-trust release", 2026-11-01), branch `main`, clean and level with `origin/main` at review time.
- **Nothing in `Witty-Pi-4` was modified** by DynAPI: no firmware source, no committed `.hex`, no release bundle. (The `.ino.lst` listings are gitignored build by-products, not committed files.) This is a report for the WP4 owners to triage and fix in their own repository.
- **Not a claim about current DynAPI deployments.** The firmware runs on the Witty Pi 4's MCU and matters only where a WP4 is attached (supported on Pi 3/4 hosts; a Pi 5 deployment is native-only and runs none of this). DynAPI ships no WP4 firmware change.
- **Status:** both issues were confirmed against `4bf3bf7` and fixed afterwards in the `Witty-Pi-4` working tree; see [Resolution](#resolution). Line numbers below refer to `4bf3bf7`.

## Issue 1 (P1): a failed temperature read becomes a valid −1 °C measurement

### Summary

`getTemperature()` ignores whether the LM75B read succeeded. After an address or data NACK, `requestFrom()` deliberately reports 0 bytes and empties the receive buffer (`SoftWireMaster.h:132-143`), so `softWireMaster.read()` returns `-1`, which narrows to `char -1` (`char` is signed on the pinned ATTinyCore/AVR GCC build), i.e. a valid-looking −1 °C. Both consumers then act on it: a configured below-temperature action can fire, and the RTC temperature compensation applies a shifted offset.

### Where

| File | Lines | Observation |
| --- | --- | --- |
| `Firmware/WittyPi4/WittyPi4.ino` | 568-571 | `char getTemperature() { readFromDevice(ADDRESS_LM75B, 0, 1); return softWireMaster.read(); }`. The byte count returned by `readFromDevice()` (that of `requestFrom()`) is dropped. |
| `Firmware/WittyPi4/SoftWireMaster.h` | 132-143, 172-179 | `requestFrom()` sets the received count to 0 on failure; `int read()` returns `-1` when `rxBufferIndex >= rxBufferLength`. The L3V7 copy is identical. |
| `Firmware/WittyPi4/WittyPi4.ino` | 962-982 | `handleTemperatureActtonsIfNeeded()`: `t > (char)i2cReg[I2C_CONF_OVER_TEMP_POINT]` and `t < (char)i2cReg[I2C_CONF_BELOW_TEMP_POINT]` select the configured action; action 1 or 2 then calls `turnOffIfPowerOn()` / `turnOnIfPowerOff()`. |
| `Firmware/WittyPi4/WittyPi4.ino` | 1078-1097 | `adjustRTCIfNeeded()` with temperature compensation enabled: `adj = (t - 26) * 55 / 434` is written into the RTC offset register. |
| `Firmware/WittyPi4_L3V7/WittyPi4_L3V7.ino` | 596-599, 996, 1086 | The same code in the L3V7 variant (`getTemperature`, `handleTemperatureActtonsIfNeeded`, `adjustRTCIfNeeded`). |

### Consequences

- **Spurious power action.** With a configured below-temperature point above −1 °C (for example 0 °C or any positive point) and the shutdown or startup action enabled, one failed read is enough to emulate the power-button click. With an over-temperature point below −1 °C (the menu accepts −30 to 80) the over-temperature action can fire the same way. The shutdown action additionally requires the Pi to be powered and at least 120 watchdog passes (about two minutes at the one-second watchdog interval) since the last power-on (`turnOffIfPowerOn()`, `powerOn()`); the startup action only acts while the Pi is off.
- **Wrong RTC offset.** With compensation enabled, a failed read gives `adj = (-1 - 26) * 55 / 434 = -3`, which is written to the RTC offset until the next adjustment (every 255th call).
- A real reading of −1 °C is `0xFF` on the LM75B, so the failure cannot be told apart from a valid sample by value. It needs a status.

The same file already uses the right pattern for RTC reads: `if (readFromDevice(ADDRESS_RTC, I2C_RTC_SECONDS - I2C_RTC_CTRL1, 4) != 4) return;` (`WittyPi4.ino:905`, `WittyPi4_L3V7.ino:934`).

### Evidence

The audit compiled the production handler bodies natively with simulated peripherals and reproduced the behaviour for **both** firmware variants. No hardware was used. AVR interrupt behaviour and electrical timing were not qualified. These reproductions are not claims of observed hardware failures.

### Suggested fix (for the WP4 owners to adapt)

Make the read fallible and let callers skip the pass on failure, for example:

```cpp
// true only when the LM75B returned its byte
bool getTemperature(char &t) {
  if (readFromDevice(ADDRESS_LM75B, 0, 1) != 1) return false;
  int value = softWireMaster.read();
  if (value < 0) return false;
  t = (char)value;
  return true;
}
```

Once `requestFrom()` has returned 1, the receive buffer holds that byte, so the `value < 0` branch cannot trigger. Flash is tight (the `4bf3bf7` standard image uses 8090 of 8192 bytes), so the count check alone is sufficient.

- `handleTemperatureActtonsIfNeeded()`: take no action when the read fails (keep the `skipTempShutdownCount` bookkeeping as the owners prefer).
- `adjustRTCIfNeeded()`: leave the RTC offset register alone for that pass.
- Apply the same change to both firmware variants.

### Suggested regression tests

The native harnesses stub `getTemperature()` as returning a global `char temperature`. That stub must follow the new signature.

- `Firmware/tests/test_firmware_handlers.py`: a failed read triggers no action, with a below-temperature point above −1 and either action enabled; a valid −1 °C reading still acts.
- `Firmware/tests/test_numeric_profile.py`: a failed read writes no RTC offset; a valid reading still writes the computed offset.
- `Firmware/tests/shutdown_contract.cpp` and `Firmware/tests/test_shutdown_contract.py` stub the same function.

### Release implications

The committed `.hex` files must be rebuilt from the changed source with the pinned toolchain (ATTinyCore 1.5.2, AVR GCC 7.3.0-atmel3.6.1-arduino7, `tools/build_firmware.py`) and committed together with it. `make release` then rebuilds the committed `REF` and requires byte identity with those HEX files; it does not build working-tree edits. The `.ino.lst` listings are gitignored and not part of the release inputs. DynAPI did not rebuild or flash anything.

## Issue 2 (P1): the thermal setters arm the action before the threshold is written

### Summary

`set_over_temperature_action` and `set_below_temperature_action` write the action register first and the LM75B threshold and configured point afterwards. Between the writes the firmware can act on the new action with the previous threshold.

### Where

| File | Lines | Observation |
| --- | --- | --- |
| `Software/wittypi/utilities.sh` | 843-852 | `set_over_temperature_action`: `I2C_CONF_OVER_TEMP_ACTION`, then `I2C_LM75B_TOS`, then `I2C_CONF_OVER_TEMP_POINT`. |
| `Software/wittypi/utilities.sh` | 854-863 | `set_below_temperature_action`: `I2C_CONF_BELOW_TEMP_ACTION`, then `I2C_LM75B_THYST`, then `I2C_CONF_BELOW_TEMP_POINT`. |
| `Software/wittypi/wittyPi.sh` | 239 and 260 | The callers (interactive menu). |

### Consequences

The firmware compares the temperature against the configured point (`I2C_CONF_*_TEMP_POINT`, not the LM75B registers) once per watchdog pass, i.e. every second (`handleTemperatureActtonsIfNeeded()` in `ISR (WDT_vect)`). Enabling an action on a not-yet-updated threshold can initiate a shutdown or startup that the new configuration would not cause.

The window is not just a few I2C transactions. `i2c_write` reads every write back and retries up to three times with `sleep 1`. The LM75B mirror write between the action and the point is a one-byte `i2cset` to registers 52/53, which the firmware maps to two-byte LM75B registers and drops since `a366797` (`receiveEvent()`: `if (count != length + 1) return;`). Its readback therefore mismatches whenever the new point differs from the LM75B's current value, and the action stays armed against the old point for about three seconds, i.e. about three firmware evaluations (by inspection; not run on a board).

Concrete case: the factory points are below 75 °C (`0x4b`) and over 80 °C (`0x50`) (`initializeRegisters()`, persisted in EEPROM). Configuring "below 5 °C → shutdown" for the first time arms "shut down below 75 °C" for that window, and a Pi at room temperature satisfies it.

"Threshold first, action last" alone is not enough. Changing the over-temperature setting from (shutdown, 40 °C) to (startup, 20 °C) would pass through (shutdown, 20 °C) and can shut a Pi at 30 °C down although the new configuration only starts it. (Choosing "None" in the menu calls `clear_*_temperature_action`, which writes only the action, so that path is not affected.)

### Suggested fix

Disarm, then retarget, then arm:

1. Write action `0x00` (the existing `clear_*_temperature_action` does exactly this).
2. Write the LM75B threshold and the configured point (keep the existing +256 encoding for negative values).
3. Write the new action last.

No intermediate state then combines an enabled action with a threshold that was not set for it. While disarmed, neither the old nor the new action can fire; with the dropped mirror write above, that disarmed window is about three seconds. If a write fails, the safe end state is disarmed: stop after a failed disarm or point write rather than arm the new action. The mirror write's result must not gate arming: the firmware does not use the mirror, and at `4bf3bf7` the write fails whenever the point changes.

### DynAPI's own copy

DynAPI keeps a managed fork of this script (`install/wittypi_software/utilities.sh`, described as differing intentionally from the vendor software). It now uses the disarm, retarget, arm order, with a regression test (`install/tests/installer-ordering.test.mjs`) that records the register write order. That is evidence for the ordering only against a recording stub, not a board.

### Qualifications

- Finding 6 (Issue 1) was reproduced by the audit with the production firmware handler bodies compiled natively against simulated peripherals. AVR interrupt behaviour and electrical timing were not qualified, and no hardware failure was observed.
- Finding 5 (Issue 2) is a host-script ordering defect. The audit exercised DynAPI's managed copy of the setter with simulated I2C writes; the vendor script above has the same write order by inspection and was not run by the audit. No board was involved.
- DynAPI's regression test relies on action value 0 meaning "no action", which matches `clear_*_temperature_action` and the "None" decoding in the same script.

## Scope, limits and hand-off

- `Witty-Pi-4` is read-only for DynAPI; a change there needs the owners' synchronization procedure first.
- No hardware, electrical-timing or power-cut qualification was performed for either issue.
- DynAPI tracks both issues as waiting for the vendor (`docs/open-work.md`, "Waiting for the vendor or a device"). When a WP4 release changes the behaviour, DynAPI synchronizes its checkout by the owners' procedure, re-verifies the issue against it and closes it.
- The six independent-source findings of DynAPI's earlier lifecycle audit (`docs/development.md#lifecycle-ownership-audit-2026-11-24`) are separate and not repeated here.

## Resolution

Both issues are fixed on top of `4bf3bf7` and released as firmware revision 12 with software 4.26 (profile `scheduled-rev12`; the bundle is listed in the README release table). No wire command changes; software 4.26 accepts revision 12 wherever 4.25 accepted revision 11, and 4.25 rejects revision 12.

- **Issue 1:** in both `WittyPi4.ino` and `WittyPi4_L3V7.ino`, `bool getTemperature(char &t)` returns false unless `readFromDevice(ADDRESS_LM75B, 0, 1) == 1`. `handleTemperatureActtonsIfNeeded()` returns after the `skipTempShutdownCount` bookkeeping without selecting an action, and `adjustRTCIfNeeded()` returns without writing the RTC offset for that pass; without temperature compensation the configured offset is still written.
- **Issue 2:** `set_over_temperature_action` and `set_below_temperature_action` call `clear_*_temperature_action || return 1`, write the LM75B mirror (result ignored), write the configured point `|| return 1`, then write the new action. The menu in `wittyPi.sh` reports a failed setter instead of "action is set".
- **LM75B mirror write:** the setters' one-byte write to registers 52/53, dropped by the firmware since `a366797`, is replaced by `lm75b_limit_write`: an `i2cset` word write (point byte, then a zero fraction byte; the same three-byte form `daemon.sh` already sends at boot) with a one-byte readback of the point and no retry delay. The menu, which reads the displayed point back from 52/53, now shows the new point immediately (previously the old one until the next MCU reset), the ~3 s retry stall and its "I2C write … failed" log are gone, and the disarmed window shrinks to a few I2C transactions. `i2c_write` and the firmware are unchanged.
- **Tests:** the three native harness stubs follow the new signature. New cases cover a failed read with every over/below × shutdown/startup combination (no action, unchanged action reason) against a genuine −1 °C reading (acts), a failed read with and without temperature compensation, and the setters' exact write order (including the word-mode mirror write and the menu reading the new point back) plus failed disarm, point and mirror writes. A firmware harness case pins the wire format: a three-byte write to 52/53 reaches the LM75B and a two-byte write does not. The new firmware cases fail when the stub restores the old −1 decoding; the new setter cases fail against the `4bf3bf7` script. `Firmware/tests` and `tools/tests` pass.
- **HEX:** the pinned toolchain first reproduced all three committed `4bf3bf7` HEX files byte-identically, then rebuilt the changed source. Flash grows by 52 bytes (L3V7: 54): standard and Mini 8142 of 8192, L3V7 8110 of 8192; static RAM is unchanged at 174 bytes. The published `wp4-4.25-fw11-286a7d43c1b4` bundle is unchanged and still has both defects; the release tool now refuses to publish changed firmware under an already published revision.
- Real LM75B behaviour for the word write is not qualified on a board; the evidence is the firmware forwarding path under test and `daemon.sh`'s existing use of the same form.
- No board was flashed or qualified.
