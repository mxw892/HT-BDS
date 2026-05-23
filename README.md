# signal-chain

> ⚠️ **work in progress** — core device communication and GUI are functional, but the full measurement run loop, probe switching, and Excel export are still being built out.

a desktop GUI for automating temperature-controlled broadband dielectric spectroscopy (BDS) testing. controls a Keysight E4980A LCR meter and a Sun Systems EC1A environmental chamber over USB/GPIB, logs impedance measurements across frequency and temperature sweeps, and plots everything live.

built for real lab hardware. not a simulation.

---

## what it does

BDS testing means sweeping an LCR meter across a range of frequencies at a series of controlled temperatures, measuring capacitance, dissipation factor, and ESR at each point. you end up with a dataset that tells you how a material's dielectric properties change with both frequency and temperature, useful for characterizing capacitors, polymers, biological samples, anything with interesting electrical behavior across conditions.

doing this manually is tedious and error prone. signal chain automates the whole thing: program the oven, wait for it to hit temperature, trigger the LCR sweep, log the data, move to the next step.

---

## hardware

| device | interface | role |
|---|---|---|
| Keysight E4980A LCR Meter | USB (VISA) | sweeps frequency, measures Cp, Df, ESR |
| Sun Systems EC1A Environmental Chamber | GPIB (VISA) | controls temperature, fires SRQ interrupts at breakpoints |
| NI USB-6501 DAQ | NI-DAQmx | digital I/O for probe switching (in progress) |

communication goes through PyVISA for the LCR and oven, and NI-DAQmx for the DAQ. the oven uses GPIB service request (SRQ) interrupts to signal when it's reached temperature, the software blocks on `wait_for_srq()` instead of polling, so it's not burning cycles guessing when the oven is ready.

---

## how it works

**state machine** — the app runs through a `RUN_STATE` IntFlag enum with combinable states:

```python
IDLE | PROGRAMMING | READY | PAUSE | TEMP_CHANGING | PROBE_SWITCHING | LCR_MEASURING | DONE
RUNNING = TEMP_CHANGING | PROBE_SWITCHING | LCR_MEASURING  # bitwise combo
```

this lets you check `if state & RUN_STATE.RUNNING` instead of comparing against every possible active state individually.

**temperature plan** — user sets start temp, step size, max temp, dwell time, and ramp rate. the app generates a full step table with elapsed times and previews it as a matplotlib plot before anything runs. the oven gets programmed via a sequence of GPIB commands (`STORE0`, `EDIT0`, `RATE=`, `SET=`, `BKPNT`, etc.) that define the temperature profile as a program the oven executes autonomously.

**data acquisition** — during a run, a background thread reads chamber and user temperatures from the oven every 10 seconds via `CHAM?` and `USER?` queries and appends to a rolling dataframe. a separate thread flushes that rolling buffer to Excel every 30 seconds using `openpyxl` in append mode, so data is saved incrementally and nothing is lost if something crashes mid-run.

**frequency sweep** — the LCR tab lets you define a logspace sweep (first freq, last freq, points per decade) and add manual spot frequencies on top. the combined list gets sorted and deduplicated before being sent to the instrument.

**live plots** — two tabbed plot views update during the run: measurements vs frequency (Cp, Df, ESR on semilog x-axis) and vs temperature. a third plot shows the rolling oven temperature readings (set, chamber, user) updating every second via a tkinter `after()` callback.

**device abstraction** — `devices.py` defines a `Device` base class with `send()` and `wait_interrupt()` interface methods. `KeysightLCR_E4980A`, `SunSystemsOven_EC1A`, and `NIDAQ_USB6501` each implement the appropriate communication layer. `DEFAULT_SEND` handles retry logic on VISA timeouts, write length validation, and query vs. command routing.

---

## files

| file | description |
|---|---|
| `main.py` | full GUI application — all UI, state management, run logic |
| `devices.py` | device classes and VISA/DAQmx communication layer |

---

## requirements

```
pip install pyvisa pyvisa-py nidaqmx openpyxl matplotlib pandas numpy
```

also requires:
- NI-VISA runtime (for GPIB/USB instrument communication)
- NI-DAQmx driver (for the USB-6501)
- physical hardware or a VISA simulation environment for testing

---

## status

- [x] device connection and manual command interface
- [x] temperature plan generation and preview
- [x] frequency sweep configuration
- [x] oven programming over GPIB
- [x] background temperature logging with incremental Excel save
- [x] live temperature plot
- [x] live LCR data plots (vs frequency and vs temperature)
- [ ] full automated run loop (temperature step → LCR sweep → next step)
- [ ] probe switching via DAQ
- [ ] Excel export for LCR measurement data
- [ ] probe selection UI
