# HT-BDS Interface

High Temperature Broadband Spectroscopy (HT-BDS) interface for automated capacitor characterization.

This project was designed to communicate with a Sun Systems environmental oven and an LCR meter in order to automate dielectric spectroscopy testing of capacitors across temperature and frequency sweeps.

The software provides:

* automated temperature planning
* frequency sweep generation
* live plotting
* measurement logging
* device communication tools
* Excel export support
* GUI-based test setup and monitoring

The interface is written in Python using Tkinter and is intended to function as a lightweight automated test platform for dielectric spectroscopy and capacitor evaluation.

---

# Current Features

## Temperature Planning

The interface supports a step-based temperature workflow.

Users can define:

* start temperature
* step size
* maximum temperature
* dwell time
* heat ramp rate

The software automatically generates a full temperature plan including:

* target temperatures
* estimated ramp times
* elapsed runtime estimates

A preview graph is generated to visualize the complete temperature profile before running a test.

---

## Frequency Sweep Generation

Supports:

* logarithmic frequency sweeps
* configurable points-per-decade
* custom manually-entered frequencies
* merged sweep tables

Frequency data is managed through Pandas DataFrames and displayed in live GUI tables.

---

## Live Plotting

Current plotting system includes:

* Capacitance vs Frequency
* Dissipation Factor vs Frequency
* ESR plotting placeholders
* Temperature-domain plotting placeholders

Plots are embedded directly into the GUI using Matplotlib.

The GUI is currently transitioning toward a notebook-tabbed plotting interface with:

* Versus Frequency tab
* Versus Temperature tab

Each containing:

* Cp plots
* Df plots
* ESR plots

---

# GUI Layout

The GUI uses a resizable multi-panel layout built around:

```python
tk.PanedWindow
```

Main sections:

* Test Setup
* Test Management
* Data Plots

Notebook tabs are used inside the setup section for:

* Temperature
* Frequency
* Devices
* Probes

---

# Device Communication

The interface communicates with external hardware using:

* PyVISA
* SCPI-style command communication
* NI-DAQ integration support

Communication is abstracted into a separate `devices.py` module.

Current implementation includes:

* manual device command terminal
* device response window
* active device selection

An exception handler is included so the GUI can still launch without hardware connected.

---

# Hardware

## Environmental Oven

Current implementation is designed around a Sun Systems oven.

Communication method:

* serial/VISA-based communication through PyVISA

Specific model information may vary depending on deployment.

---

## LCR Meter

The interface communicates with an LCR meter for:

* capacitance measurement
* dissipation factor measurement
* ESR characterization
* frequency sweeps

Communication method:

* VISA/SCPI command interface

Current implementation supports automated sweep coordination with the oven temperature profile.

If deployed with the intended hardware stack, the system was originally developed around the Keysight/Agilent E4980-series style workflow.

---

# Core Libraries

## GUI

* Tkinter
* ttk

## Plotting

* Matplotlib

## Data Management

* Pandas
* Openpyxl

## Device Communication

* PyVISA
* NI-DAQmx

## Concurrency

* threading

---

# Major Classes

## App

Main application controller.

Responsible for:

* GUI construction
* runtime coordination
* data synchronization
* device management
* plotting integration

---

## Table

Custom wrapper around `ttk.Treeview`.

Provides:

* dataframe-backed tables
* dynamic updates
* row append support
* scrollbar integration

---

## TempStepPlot

Creates and updates:

* temperature profile preview plots
* ramp/dwell visualization

---

## TestDataPlot

Handles:

* measurement visualization
* frequency-domain plots
* temperature-domain plots

---

## ListVar

Custom Tkinter variable class allowing list storage and automatic type conversion.

---

# Data Flow

Typical workflow:

1. Configure temperature plan
2. Configure frequency sweep
3. Generate plan
4. Program devices
5. Run automated test
6. Gather measurement data
7. Visualize results live
8. Export results to Excel

---

# Current Development Status

## Completed

* Step-based temperature planning
* Frequency sweep generation
* GUI reconstruction
* Resizable panel architecture
* Temperature preview plotting
* Dataframe-backed tables
* Embedded Matplotlib plots

## In Progress

* Measurement data table integration
* ESR plotting
* Expanded notebook plotting system
* Backend migration from legacy cycle-based execution

## Planned

* Full automated runtime execution
* Improved export formatting
* Multi-device synchronization
* Probe management support
* Real-time measurement plotting

---

# Notes

This project is currently under active development and undergoing a transition from an older cycle-based temperature architecture to a newer step-based temperature plan workflow.

The GUI and dataflow systems have largely been migrated, while portions of the backend execution logic are still being updated to match the new architecture.
