# HT-BDS
 
a desktop interface for automating temperature controlled broadband dielectric spectroscopy (BDS) testing. controls a Keysight E4980A LCR meter, Sun Systems EC1A environmental chamber, and NI-USB-6501 DAQ over USB/GPIB, logs impedance measurements across frequency and temperature sweeps, and plots everything live with the ability to export to Excel.
 
built for real lab hardware. not a simulation.
 
---
 
## what it does
 
BDS testing means sweeping an LCR meter across a range of frequencies at a series of controlled temperatures, measuring capacitance, dissipation factor, and ESR at each point. you end up with a dataset that tells you how a material's dielectric properties change with both frequency and temperature, useful for characterizing capacitors, polymers, biological samples, anything with interesting electrical behavior across conditions.
 
doing this manually is tedious and error prone. HT-BDS automates the whole thing: program the oven, wait for it to hit temperature, verify the user probe has stabilized, switch probes, trigger the LCR sweep, log/plot/organize the data, repeat for each probe, and move to the next step.
 
---
 
## hardware
 
| device | interface | role |
|---|---|---|
| Keysight E4980A LCR Meter | USB (VISA) | sweeps frequency, measures Cp, Df, ESR |
| Sun Systems EC1A Environmental Chamber | GPIB (VISA) | controls temperature, fires SRQ interrupts at breakpoints |
| NI USB-6501 DAQ | NI-DAQmx | digital I/O for probe switching |
 
communication goes through PyVISA for the LCR and oven, and NI-DAQmx for the DAQ. the oven uses GPIB service request (SRQ) interrupts to signal when it's reached temperature, the software blocks on `wait_for_srq()` in 5-second chunks instead of polling, checking for stop/pause requests between each chunk.
 
---
 
## how it works
 
**state machine** — the app runs through a `RUN_STATE` IntFlag enum with combinable states:
 
```python
IDLE | PROGRAMMING | READY | PAUSE | TEMP_CHANGING | PROBE_SWITCHING | LCR_MEASURING | DONE
RUNNING = TEMP_CHANGING | PROBE_SWITCHING | LCR_MEASURING  # bitwise combo
```
 
this lets you check `if state & RUN_STATE.RUNNING` instead of comparing against every possible active state individually. each run state is explicit and allows the program to perform safety checks and proper sequencing without ever leaving the software in a ambiguous state.
 
**temperature plan** — user sets start temp, step size, max temp, dwell time, and ramp rate. there is an option for a second step temperature after a temperature u input to allow for finer granularity at high temperatures. the app generates a full step table with elapsed times and previews it as a matplotlib plot before anything runs. the oven gets programmed via a sequence of GPIB commands (`STORE#0`, `RATE=`, `SET=`, `WAIT=`, `BKPNT`, etc.) that define the temperature profile as a program the oven executes autonomously. software safety limits enforce bounds on all parameters: −70 to 180 °C range, 50 °C max step, 10 °C/min max ramp, 72-hour total run cap, and a confirmation dialog for any run that exceeds 100 °C.
 
**user probe stabilization** — after the oven fires a breakpoint SRQ, the software doesn't immediately start measuring. thermal lag occurs due to heat transfer and thermal mass of the DUT, therefore it is a good idea to ensure the DUT is within tolerated temperature before performing sweep. it polls the USER probe every 5 seconds and waits until the reading is within 1.5 °C of the target for 2 consecutive samples before triggering the LCR sweep. does this by taking the absolute value of the difference between chamber and user probe temps and then comparing it against the tolerance. then adjusts count and compares that to ur set required samples and only then takes data. if stabilization doesn't happen within a set time, it logs a warning and continues with the last reading next step temp. this is so one point cannot cause the entire system to be blocked. (these tolerances can be adjusted, and are currently more lenient as to allow for faster testing)
 
**frequency sweep** — the LCR tab lets you define a logspace sweep (first freq, last freq, points per decade) and add manual spot frequencies on top. the combined list gets sorted and deduplicated before being sent to the instrument. each frequency point runs two back to back measurements: Cp+Df in CPD mode and ESR in CSRS mode, with a bus trigger and `*WAI`/`*OPC?` handshake to ensure the instrument is settled before fetching results.

**probe switching** - NI USB-6501 is a digital I/O DAQ, using NI DAQ-mx digital output patterns can be written to control a custom PCB that implements the switching logic for multi dut testing. each probe had its own bitwise combination, only one probe can be active at all times. before switching probes, the program writes an all off state to create a known intermediate step before writing the target probe pattern, in which a configurable setting delay is implemented to allow for settling delay before a sweep
 
**data acquisition** — during a run, the main run loop logs oven temperatures (set, chamber, user) into a rolling buffer at each wait iteration. a separate `after()` callback on the temperature chart polls for new readings every second and merges the rolling buffer with the master log for display, downsampling to 100 points when the dataset grows large. temperature axis units auto-scale between seconds, minutes, and hours based on elapsed time.
 
**Excel export** — on export, results are written to a structured workbook: Metadata, Summary, Temperature Index, Temperature Plan, Frequency Plan, Measurements, Temperature Log, and one sheet per measured temperature. the Temperature Index sheet includes hyperlinks to each per temperature sheet, with a backlink in each temperature sheet. all sheets get frozen header rows, autofilters, and autosized columns.
 
**live plots** — two tabbed plot views update during the run: measurements vs frequency (Cp, Df, ESR on semilog x-axis) and vs temperature (at a user-selectable focus frequency). a plot filter bar lets you pick which temperature step's frequency data to display and which frequency to track in the temperature view. a third live plot in the test management panel shows rolling oven readings (set, chamber, user) updating every second.
 
**device abstraction** — `devices.py` defines a `Device` base class with `send()` and `wait_interrupt()` interface methods. `KeysightLCR_E4980A`, `SunSystemsOven_EC1A`, and `NIDAQ_USB6501` each implement the appropriate communication layer. `send()` in `devices.py` handles query vs. command routing — anything ending in `?` goes through `dev.query()`, everything else through `dev.write()`, with an optional `read_after_write` flag for commands that return a response without a `?`.

**Example Excel Workbook** - https://1drv.ms/x/c/96da2fc03f155a85/IQD4mGVcUPogSJevcF02TeFoAbbEdrL4u7J5OcH7CsNuQRE?e=ee4Sc5
 
---
 
## files
 
| file | description |
|---|---|
| `main.py` | full GUI application — all UI, state management, run logic, export | (should separate into different files for better organization and future debugging but it works well now)
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
 
