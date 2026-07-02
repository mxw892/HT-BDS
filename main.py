# HT-BDS: Hub-Temperature-Controlled BDS Testing Software
# Author: Matthew Wang

# ===============================================================================
# IMPORTS
# ===============================================================================

from dataclasses import dataclass
import colorsys
import time
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
from typing import Literal
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import os
import numpy as np
import pandas as pd
from enum import IntFlag, auto
import threading
from datetime import datetime

try:
    import nidaqmx # type: ignore
    from nidaqmx.constants import LineGrouping  # type: ignore
except Exception as e:
    nidaqmx = None
    LineGrouping = None
    NIDAQMX_IMPORT_ERROR = e
else:
    NIDAQMX_IMPORT_ERROR = None

# ===============================================================================
# DEVICE IMPORTS & OUTPUT SETUP
# ===============================================================================
try:
    import devices as devices
except Exception as e:
    raise ImportError(f"Could not import devices.py: {e}")

# OUTPUT FOLDER SETUP
RUNNING_PATH = os.path.abspath(os.getcwd())
OUTPUT_FOLDER = "HT-BDS Data"
OUTPUT_FILEPATH = os.path.join(RUNNING_PATH, OUTPUT_FOLDER)
os.makedirs(OUTPUT_FILEPATH, exist_ok=True)
DEVICE_NAMES = [dev.name for dev in devices.DEVICE_TYPE_LIST]


# ================================================================================
# CONSTANTS & COLUMNS
# ================================================================================
CHAR_OHM = "\u03a9"
CHAR_THETA = "\u0398"
CHAR_DEG = "\u00b0"
CHAR_DEGC = "\u00b0C"
CHAR_MU = "\u03bc"

UNITS: dict[str, float] = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    CHAR_MU: 1e-6,
    "u": 1e-6,
    "m": 1e-3,
    "c": 1e-2,
    "": 1,
    "k": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}

# Columns
FREQ_STEP_COLUMNS = ("Step #", "Frequency [Hz]", "*")
TEST_DATA_COLUMNS = (
    "Probe Index",
    "Probe Label",
    "Probe Color",
    f"Temp. [{CHAR_DEGC}]",
    "Freq. [Hz]",
    "Cp [F]",
    "Df [1]",
    f"ESR [{CHAR_OHM}]",
)
PROBE_TABLE_COLUMNS = ("Probe Index", "Probe Label", "Probe Color")
TEMPERATURE_READINGS_COLUMNS = (
    "Time [s]",
    "Cycle",
    "Mode",
    f"Set Temp [{CHAR_DEGC}]",
    f"Chamber Temp [{CHAR_DEGC}]",
    f"User Temp [{CHAR_DEGC}]",
)
TEMP_PLAN_COLUMNS = (
    "Step #",
    "Target Temp. [°C]",
    "Dwell Time [min]",
    "Ramp Time [min]",
    "Elapsed Time [min]",
)

# display constants
DEFAULT_FOCUS_FREQ_HZ = 1000.0
MEASUREMENT_DISPLAY_ROWS = 50
DEFAULT_ROLL_ID = os.environ.get("HTBDS_ROLL_ID", "")
DEFAULT_OPERATOR = os.environ.get("HTBDS_OPERATOR") or os.environ.get(
    "USERNAME", os.environ.get("USER", "")
)
BUTTON_COLORS = {
    "primary": ("#d9e8f5", "#c4dcef", "#153a54"),
    "success": ("#cfead6", "#b8dfc3", "#173f25"),
    "warning": ("#fff0bd", "#f5df94", "#4c3b05"),
    "danger": ("#f3c7c2", "#ebb0aa", "#5d1f19"),
    "pause": ("#e3d7f4", "#d3c2ec", "#3a285c"),
    "clear": ("#f8d7bd", "#efc6a4", "#5a2b0d"),
    "export": ("#cfeee6", "#b8e2d7", "#123f34"),
    "neutral": ("#e8edf3", "#d5dde7", "#243244"),
}
PROBE_COLOR_PALETTE = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)
DAQ_DEVICE_NAME = "Dev1"
DAQ_PORT0_LINE_SPEC = f"{DAQ_DEVICE_NAME}/port0/line0:7"
PROBE_SWITCH_PATTERNS = {
    1: 0b00000011,
    2: 0b00001100,
    3: 0b00110000,
    4: 0b11000000,
}
PROBE_ALL_OFF_PATTERN = 0b00000000
PROBE_BREAK_BEFORE_MAKE_SECONDS = 0.10

# conservative software safety limits
SAFETY_MIN_TEMP_C = -70.0
SAFETY_MAX_TEMP_C = 180.0
SAFETY_MAX_STEP_C = 50.0
SAFETY_MAX_DWELL_MIN = 24 * 60.0
SAFETY_MAX_RAMP_C_PER_MIN = 10.0
SAFETY_MAX_TOTAL_HOURS = 72.0
SAFETY_CONFIRM_TEMP_C = 100.0
OVEN_WAIT_CHUNK_SECONDS = 5
OVEN_BREAKPOINT_TIMEOUT_BUFFER_MINUTES = 10
TEMPERATURE_ROLLING_MAX_ROWS = 500

# user temperature limits, after oven breakpoint wait until user probe is within 0.5C for 3 consec readings, with polls every 5 secs with a 5 min max wait
USER_TEMP_TOLERANCE_C = 1.5
USER_TEMP_STABLE_SAMPLES = 2
USER_TEMP_POLL_SECONDS = 5
USER_TEMP_MAX_EXTRA_WAIT_SECONDS = 90

# keysight lcr overrange threshold, it returns this for invalid/out of range measurements
KEYSIGHT_OVERRANGE_THRESHOLD = 9.8e37


# ================================================================================
# ENUMS & DATACLASSES
# ===============================================================================
class RUN_STATE(IntFlag):
    IDLE = (
        auto()
    )  # App just begun, nothing asked yet. Accept user inputs, parameters, etc.
    PROGRAMMING = (
        auto()
    )  # Inputs now become outputs. Begin instructing connected devices on what signals/commands to expect.
    READY = (
        auto()
    )  # After machines have been programmed successfully, review details before comitting to run.
    PAUSE = (
        auto()
    )  # Paused run. User has requested the run be held in place for intervention or analysis.
    TEMP_CHANGING = (
        auto()
    )  # Running. Temperatures are changing towards the set temperature.
    PROBE_SWITCHING = (
        auto()
    )  # Running. Probes are switching for switching frequency measurements.
    LCR_MEASURING = auto()  # Running. LCR is sweeping frequncies for a given probe.
    DONE = auto()  # Run complete / End of programs
    RUNNING = (
        TEMP_CHANGING | PROBE_SWITCHING | LCR_MEASURING
    )  # Combination of states that would be considered 'running'


# dataclass for storing the run configuration, which can be easily passed around and modified as needed
@dataclass(frozen=True)
class RunConfig:
    device: devices.Device | None
    start_temp: float
    step_temp: float
    max_temp: float
    dwell_time: float
    heat_rate: float
    focus_freq: float
    enable_multiprobe: bool
    probe_configs: tuple[tuple[int, str, str], ...]
    probe_settling_delay: float


# ================================================================================
# HELPER FUNCTIONS
# ===============================================================================


def get_default_probe_color(probe_index):
    if probe_index <= len(PROBE_COLOR_PALETTE):
        return PROBE_COLOR_PALETTE[probe_index - 1]

    hue = ((probe_index - 1) * 0.618033988749895) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.65, 0.78)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def build_temperature_plan(
    start_temp,
    step_temp,
    max_temp,
    dwell_time,
    heat_rate,
    use_second_step=False,
    step_change_temp=None,
    step2_temp=None,
):
    if step_temp <= 0:
        raise ValueError("Step temp must be greater than 0.")
    if step_temp > SAFETY_MAX_STEP_C:
        raise ValueError(
            f"Step temp must be {SAFETY_MAX_STEP_C:g} {CHAR_DEGC} or less."
        )
    if max_temp <= start_temp:
        raise ValueError("Max temp must be greater than start temp.")
    if start_temp < SAFETY_MIN_TEMP_C or max_temp > SAFETY_MAX_TEMP_C:
        raise ValueError(
            f"Temperatures must stay between {SAFETY_MIN_TEMP_C:g} and {SAFETY_MAX_TEMP_C:g} {CHAR_DEGC}."
        )
    if dwell_time <= 0:
        raise ValueError("Dwell time must be greater than 0.")
    if dwell_time > SAFETY_MAX_DWELL_MIN:
        raise ValueError(
            f"Dwell time must be {SAFETY_MAX_DWELL_MIN:g} minutes or less."
        )
    if heat_rate <= 0:
        raise ValueError("Heat ramp rate must be greater than 0.")
    if heat_rate > SAFETY_MAX_RAMP_C_PER_MIN:
        raise ValueError(
            f"Heat ramp rate must be {SAFETY_MAX_RAMP_C_PER_MIN:g} {CHAR_DEGC}/min or less."
        )

    if use_second_step:
        if step2_temp is None:
            raise ValueError("Step temp 2 must be specified.")
        if step2_temp <= 0:
            raise ValueError("Step temp 2 must be greater than 0.")
        if step2_temp > SAFETY_MAX_STEP_C:
            raise ValueError(
                f"Step temp 2 must be {SAFETY_MAX_STEP_C:g} {CHAR_DEGC} or less."
            )
        if step_change_temp is None:
            raise ValueError("Step change temp must be specified.")
        if step_change_temp <= start_temp:
            raise ValueError("Step change temp must be greater than start temp.")
        if step_change_temp >= max_temp:
            raise ValueError("Step change temp must be less than max temp.")

    def build_rows(targets):
        rows = []
        elapsed = 0.0
        current_temp = start_temp
        for step, target in enumerate(targets, start=1):
            ramp_time = abs(target - current_temp) / heat_rate
            elapsed += ramp_time + dwell_time
            rows.append([step, target, dwell_time, ramp_time, elapsed])
            current_temp = target

        if elapsed / 60.0 > SAFETY_MAX_TOTAL_HOURS:
            raise ValueError(f"Planned run exceeds {SAFETY_MAX_TOTAL_HOURS:g} hours.")

        return pd.DataFrame(rows, columns=TEMP_PLAN_COLUMNS)

    if not use_second_step:
        rows = []
        elapsed = 0.0
        step = 1
        current_temp = start_temp
        target = start_temp

        while target < max_temp:
            ramp_time = abs(target - current_temp) / heat_rate

            elapsed += ramp_time + dwell_time
            rows.append([step, target, dwell_time, ramp_time, elapsed])

            current_temp = target
            target += step_temp
            step += 1

        if not np.isclose(current_temp, max_temp):
            ramp_time = abs(max_temp - current_temp) / heat_rate
            elapsed += ramp_time + dwell_time
            rows.append([step, max_temp, dwell_time, ramp_time, elapsed])

        if elapsed / 60.0 > SAFETY_MAX_TOTAL_HOURS:
            raise ValueError(f"Planned run exceeds {SAFETY_MAX_TOTAL_HOURS:g} hours.")

        return pd.DataFrame(rows, columns=TEMP_PLAN_COLUMNS)

    targets = [start_temp]
    target = start_temp + step_temp

    while target < step_change_temp and not np.isclose(target, step_change_temp):
        targets.append(target)
        target += step_temp

    if not np.isclose(targets[-1], step_change_temp):
        targets.append(step_change_temp)

    target = step_change_temp + step2_temp
    while target < max_temp and not np.isclose(target, max_temp):
        targets.append(target)
        target += step2_temp

    if not np.isclose(targets[-1], max_temp):
        targets.append(max_temp)

    return build_rows(targets)


def minutes_to_wait(minutes: float) -> str:
    total_seconds = int(round(minutes * 60))
    hours = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{mins:02d}:{seconds:02d}"


# ================================================================================
# CUSTOM TKINTER WIDGETS
# ===============================================================================
class ListVar(tk.StringVar):
    type: str
    name: str

    def __init__(
        self, type: Literal["int", "bool", "float", "str"] = "float", name: str = ""
    ):  # , value=[]):
        self.type = type
        self.name = name
        # self.value = value
        super().__init__(name=name)
        # self.var = tk.StringVar()
        # self.var.trace_add("read", self.get)

    # coverts list to a string
    def set(self, value=None):  # type: ignore
        if value is None:
            value = []
        print(f"Setting {self.name} var... {value}")
        super().set(",".join([str(entry) for entry in value]))
        # self.value = value

    # takes the string, splits it by comma, and converts it back to a list of the correct type
    def get(self) -> list[int | float | str | bool]:  # type: ignore
        try:
            # super().get()
            # Remove spaces and split by comma
            # return super().get()
            values = super().get().split(",")
            print(f"Getting {self.name} var... {values}")
            raw_list = [entry.strip() for entry in values if entry.strip()]
            match (self.type):
                case "int":
                    return [int(int_entry) for int_entry in raw_list]
                case "float":
                    return [float(float_entry) for float_entry in raw_list]
                case "str":
                    return [str_entry for str_entry in raw_list]
                case "bool":
                    return [bool(bool_entry) for bool_entry in raw_list]
        except ValueError:
            return []  # Invalid input


# highlights all text when entry is selected, and formats the text when deselected
class Entry(tk.Entry):
    textvariable: tk.Variable

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "textvariable" in kwargs.keys():
            self.textvariable = kwargs["textvariable"]
        self.bind("<FocusIn>", self.focus_highlight)
        self.bind("<FocusOut>", self.format_input)

    def focus_highlight(self, *args):
        self.selection_range(0, "end")

    def format_input(self, *args):
        self.textvariable.set(self.textvariable.get())


# alternating color for table rows, with function to update the whole table based on a given dataframe
class Table(ttk.Treeview):
    def __init__(self, header_widths, increment=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tag_configure("evenrow", background="#E8E8E8")
        self.tag_configure("oddrow", background="#FFFFFF")
        self.index_inc = increment
        columns = self.cget("columns")
        self.set_headings(columns, header_widths)

    # sets the column widths and headings based on the given lists
    def set_headings(self, column_list, width_list):
        self.column("#0", width=0, stretch=True)
        self.heading("#0", text="", anchor="w")
        for i, col in enumerate(column_list):
            width = width_list[i] if i < len(width_list) else 80
            self.column(col, minwidth=50, width=width, stretch=True, anchor="w")
            self.heading(col, text=col, anchor="w")

    # updates the whole table based on the given dataframe, with alternating row colors
    def update_table(self, dataframe: pd.DataFrame):
        # Add data with alternating row colors
        self.delete(*self.get_children())
        for i, data in enumerate(dataframe.itertuples(index=False, name=None)):
            if self.index_inc:
                inc_data = [data[0] + 1]
                inc_data.extend(data[1:])
                data = inc_data
            if i % 2 == 0:
                self.insert(parent="", index="end", values=data, tags="evenrow")
            else:
                self.insert(parent="", index="end", values=data, tags="oddrow")

    # adds a single row to the end of the table, with alternating row color
    def appendRow(self, data):
        i = len(self.get_children())
        if self.index_inc:
            data = [i + 1] + list(data)
        tag = "evenrow" if i % 2 == 0 else "oddrow"
        self.insert(parent="", index="end", values=data, tags=tag)
        print("Appending row to table:", data)


# ================================================================================
# PLOT CLASSES
# ================================================================================
# makes the temperature step plot, updates it, and draws it on the canvas when called
class TempStepPlot:
    master: tk.Tk
    plot_figure: Figure
    plot_canvas: FigureCanvasTkAgg
    temperature_axes: Axes
    times: ListVar
    temperature_data: ListVar

    def __init__(self, master_window):
        self.master = master_window
        self.plot_figure = Figure(figsize=(5, 4), dpi=80, layout="constrained")
        self.plot_canvas = FigureCanvasTkAgg(self.plot_figure, master_window)
        self.plot_figure.patch.set_facecolor("#F0F0F0")
        self.temperature_axes = self.plot_figure.subplots(1, 1)
        self.times = ListVar("float", "Times")
        self.temperature_data = ListVar("float", "Temperatures")

    # remade to update the plot based on a given dataframe of the temperature plan, with proper formatting and labels
    def update_plot(self, dataframe: pd.DataFrame, start_temp: float = 25.0, *args):
        print("Updating Temperature Plot...")
        ax = self.temperature_axes
        ax.clear()
        ax.set_title("Temperature Plan Preview")
        ax.set_xlabel("Elapsed Time [min]")
        ax.set_ylabel(r"$T_{set}$" + f" [{CHAR_DEGC}]")
        ax.grid(which="both")

        if dataframe.empty:
            ax.text(
                0.5, 0.5, "No Data", ha="center", va="center", transform=ax.transAxes
            )
            self.plot_canvas.draw()
            return

        times = [0.0]
        temps = [start_temp]
        current_time = 0.0
        for _, row in dataframe.iterrows():
            target = float(row[TEMP_PLAN_COLUMNS[1]])
            dwell_time = float(row[TEMP_PLAN_COLUMNS[2]])
            ramp_time = float(row[TEMP_PLAN_COLUMNS[3]])

            ramp_end = current_time + ramp_time
            dwell_end = ramp_end + dwell_time

            times.append(ramp_end)
            temps.append(target)

            times.append(dwell_end)
            temps.append(target)
            current_time = dwell_end

        if times[-1] > 120:
            times = [t / 60 for t in times]
            ax.set_xlabel("Elapsed Time [hr]")

        ax.plot(times, temps, marker="o", linestyle="-")
        self.plot_canvas.draw()


# remade this to include esr plots and handle general vs frequency and vs temperature plots
class TestDataPlot:
    def __init__(self, master_window):
        self.master = master_window
        self.notebook = ttk.Notebook(master_window)
        self.widget = self.notebook

        self.figures = {}
        self.canvases = {}
        self.axes = {}

        self.build_tab(
            "frequency",
            "Versus Frequency",
            [
                ("Capacitance vs Frequency", "Frequency [Hz]", "Cp [F]"),
                ("Dissipation vs Frequency", "Frequency [Hz]", "Df [1]"),
                ("ESR vs Frequency", "Frequency [Hz]", f"ESR [{CHAR_OHM}]"),
            ],
        )
        self.build_tab(
            "temperature",
            "Versus Temperature",
            [
                ("Capacitance vs Temperature", "Temperature [°C]", "Cp [F]"),
                ("Dissipation vs Temperature", "Temperature [°C]", "Df [1]"),
                ("ESR vs Temperature", "Temperature [°C]", f"ESR [{CHAR_OHM}]"),
            ],
        )

    def build_tab(self, tab_key, tab_title, plot_specs):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=tab_title)
        fig = Figure(figsize=(6, 7), dpi=80, layout="constrained")
        fig.patch.set_facecolor("#F0F0F0")
        axes = fig.subplots(3, 1)

        canvas = FigureCanvasTkAgg(fig, frame)
        canvas.get_tk_widget().pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")

        for ax, (plot_title, x_label, y_label) in zip(axes, plot_specs):
            self._format_empty_axis(ax, plot_title, x_label, y_label)

        # Store references to the figure, canvas, and axes for later updates
        self.figures[tab_key] = fig
        self.canvases[tab_key] = canvas
        self.axes[tab_key] = axes

        canvas.draw()

    def update_plots(
        self,
        dataframe=None,
        selected_temp="Latest",
        selected_freq=DEFAULT_FOCUS_FREQ_HZ,
    ):
        if dataframe is None or dataframe.empty:
            self._draw_empty()
            return

        # check if all required columns are present in the dataframe, if not, draw empty and return
        required_columns = list(TEST_DATA_COLUMNS)
        for col in required_columns:
            if col not in dataframe.columns:
                print(f"Dataframe is missing required column: {col}")
                self._draw_empty()
                return

        # frequency plots
        freq_col = "Freq. [Hz]"
        temp_col = f"Temp. [{CHAR_DEGC}]"
        cp_col = "Cp [F]"
        df_col = "Df [1]"
        esr_col = f"ESR [{CHAR_OHM}]"
        probe_index_col = "Probe Index"
        probe_label_col = "Probe Label"
        probe_color_col = "Probe Color"
        plot_df = dataframe.copy()

        for col in [probe_index_col, freq_col, temp_col, cp_col, df_col, esr_col]:
            plot_df[col] = pd.to_numeric(
                plot_df[col], errors="coerce"
            )  # turn bad vals to NaN

        plot_df = plot_df.dropna(
            subset=[probe_index_col, freq_col, temp_col]
        )  # remove unplottable rows

        if plot_df.empty:
            self._draw_empty()
            return

        # frequency tab will show one temperature slice only
        freq_df, freq_temp_label = self._select_temperature_slice(
            plot_df,
            temp_col=temp_col,
            selected_temp=selected_temp,
        )

        self._plot_frequency_tab(
            freq_df,
            freq_temp_label,
            freq_col,
            cp_col,
            df_col,
            esr_col,
            probe_index_col,
            probe_label_col,
            probe_color_col,
        )

        # temperature tab will show one frequency slice only
        temp_df, temp_freq_label = self._select_frequency_slice(
            plot_df,
            freq_col=freq_col,
            selected_freq=selected_freq,
        )

        self._plot_temperature_tab(
            temp_df,
            temp_freq_label,
            temp_col,
            cp_col,
            df_col,
            esr_col,
            probe_index_col,
            probe_label_col,
            probe_color_col,
        )

    def _select_temperature_slice(self, dataframe, temp_col, selected_temp):
        valid_temps = dataframe[temp_col].dropna()

        if valid_temps.empty:
            return dataframe.iloc[0:0].copy(), "No temperature"

        if selected_temp in (None, "", "Latest"):
            target_temp = float(valid_temps.iloc[-1])
            label = f"latest {target_temp:.2f} {CHAR_DEGC}"
        else:
            try:
                requested = float(str(selected_temp).replace(CHAR_DEGC, "").strip())
                unique_temps = valid_temps.drop_duplicates().to_numpy(dtype=float)
                target_temp = float(
                    unique_temps[np.argmin(np.abs(unique_temps - requested))]
                )
                label = f"{target_temp:.2f} {CHAR_DEGC}"
            except (ValueError, TypeError):
                target_temp = float(valid_temps.iloc[-1])
                label = f"latest {target_temp:.2f} {CHAR_DEGC}"

        mask = np.isclose(dataframe[temp_col], target_temp, rtol=0, atol=0.25)
        sliced = dataframe.loc[mask].sort_values(
            by=["Probe Index", "Freq. [Hz]"]
        )

        return sliced, label

    def _select_frequency_slice(self, dataframe, freq_col, selected_freq):
        valid_freqs = dataframe[freq_col].dropna()

        if valid_freqs.empty:
            return dataframe.iloc[0:0].copy(), "No frequency"

        try:
            requested = float(selected_freq)
        except (ValueError, TypeError):
            requested = DEFAULT_FOCUS_FREQ_HZ

        unique_freqs = valid_freqs.drop_duplicates().to_numpy(dtype=float)
        target_freq = float(unique_freqs[np.argmin(np.abs(unique_freqs - requested))])

        label = f"{target_freq:.6g} Hz"
        mask = np.isclose(dataframe[freq_col], target_freq, rtol=1e-9, atol=1e-9)
        sliced = dataframe.loc[mask].sort_values(
            by=["Probe Index", f"Temp. [{CHAR_DEGC}]"]
        )

        return sliced, label

    def _iter_probe_groups(
        self, dataframe, probe_index_col, probe_label_col, probe_color_col
    ):
        for probe_index, probe_data in dataframe.groupby(
            probe_index_col, sort=True
        ):
            labels = probe_data[probe_label_col].dropna().astype(str)
            label = labels.iloc[0].strip() if not labels.empty else ""
            if not label:
                label = f"Probe {int(probe_index)}"

            colors = probe_data[probe_color_col].dropna().astype(str)
            color = colors.iloc[0].strip() if not colors.empty else ""
            if not color:
                color = get_default_probe_color(int(probe_index))

            yield label, color, probe_data

    def _plot_frequency_tab(
        self,
        dataframe,
        temp_label,
        freq_col,
        cp_col,
        df_col,
        esr_col,
        probe_index_col,
        probe_label_col,
        probe_color_col,
    ):
        freq_axes = self.axes["frequency"]

        freq_specs = [
            (
                freq_axes[0],
                cp_col,
                f"Capacitance vs Frequency @ {temp_label}",
                "Cp [F]",
            ),
            (
                freq_axes[1],
                df_col,
                f"Dissipation Factor vs Frequency @ {temp_label}",
                "Df [1]",
            ),
            (
                freq_axes[2],
                esr_col,
                f"ESR vs Frequency @ {temp_label}",
                f"ESR [{CHAR_OHM}]",
            ),
        ]

        for ax, y_col, title, ylabel in freq_specs:
            ax.clear()
            ax.set_title(title)
            ax.set_xlabel("Frequency [Hz]")
            ax.set_ylabel(ylabel)
            ax.grid(which="both")

            plotted_count = 0
            for label, color, probe_data in self._iter_probe_groups(
                dataframe,
                probe_index_col,
                probe_label_col,
                probe_color_col,
            ):
                probe_data = probe_data.dropna(subset=[freq_col, y_col]).sort_values(
                    by=freq_col
                )
                if probe_data.empty:
                    continue
                ax.semilogx(
                    probe_data[freq_col],
                    probe_data[y_col],
                    color=color,
                    label=label,
                    marker="o",
                    linestyle="-",
                )
                plotted_count += 1

            if plotted_count > 1:
                ax.legend()
            elif plotted_count == 0:
                ax.text(
                    0.5,
                    0.5,
                    "No Data",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )

        self.canvases["frequency"].draw()

    def _plot_temperature_tab(
        self,
        dataframe,
        freq_label,
        temp_col,
        cp_col,
        df_col,
        esr_col,
        probe_index_col,
        probe_label_col,
        probe_color_col,
    ):
        temp_axes = self.axes["temperature"]

        temp_specs = [
            (
                temp_axes[0],
                cp_col,
                f"Capacitance vs Temperature @ {freq_label}",
                "Cp [F]",
            ),
            (
                temp_axes[1],
                df_col,
                f"Dissipation Factor vs Temperature @ {freq_label}",
                "Df [1]",
            ),
            (
                temp_axes[2],
                esr_col,
                f"ESR vs Temperature @ {freq_label}",
                f"ESR [{CHAR_OHM}]",
            ),
        ]

        for ax, y_col, title, ylabel in temp_specs:
            ax.clear()
            ax.set_title(title)
            ax.set_xlabel(f"Temperature [{CHAR_DEGC}]")
            ax.set_ylabel(ylabel)
            ax.grid(which="both")

            plotted_count = 0
            for label, color, probe_data in self._iter_probe_groups(
                dataframe,
                probe_index_col,
                probe_label_col,
                probe_color_col,
            ):
                probe_data = probe_data.dropna(subset=[temp_col, y_col]).sort_values(
                    by=temp_col
                )
                if probe_data.empty:
                    continue
                ax.plot(
                    probe_data[temp_col],
                    probe_data[y_col],
                    color=color,
                    label=label,
                    marker="o",
                    linestyle="-",
                )
                plotted_count += 1

            if plotted_count > 1:
                ax.legend()
            elif plotted_count == 0:
                ax.text(
                    0.5,
                    0.5,
                    "No Data",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )

        self.canvases["temperature"].draw()

    def _draw_empty(self):
        for tab_key, axes in self.axes.items():
            for ax in axes:
                title = ax.get_title()
                xlabel = ax.get_xlabel()
                ylabel = ax.get_ylabel()
                self._format_empty_axis(ax, title, xlabel, ylabel)

            self.canvases[tab_key].draw()

    def _format_empty_axis(self, ax, title, xlabel, ylabel):
        ax.clear()
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(which="both")
        ax.text(0.5, 0.5, "No Data", ha="center", va="center", transform=ax.transAxes)


# ===============================================================================
# MAIN APPLICATION CLASS
# ===============================================================================
class App:
    app_root: tk.Tk
    state: RUN_STATE

    # APP INITIALIZATION --------------------------
    def __init__(self):
        # Init app vars/entries/etc.
        self.app_root = tk.Tk()
        self.state = RUN_STATE.DONE
        self.run_thread = None
        self.program_thread = None
        self.pause_requested = False
        self.stop_requested = False
        self.shutdown_in_progress = False

        # reference for test setup
        self.temperature_setup_controls = []
        self.frequency_setup_controls = []
        self.probe_setup_controls = []
        self.manual_command_controls = []
        self.setup_notebook = None

        # temp setup vars
        self.start_temp = tk.DoubleVar(value=25.0)
        self.step_temp = tk.DoubleVar(value=20.0)
        self.use_second_step = tk.BooleanVar(value=False)
        self.step_change_temp = tk.DoubleVar(value=100.0)
        self.step2_temp = tk.DoubleVar(value=10.0)
        self.max_temp = tk.DoubleVar(value=125.0)
        self.dwell_time = tk.DoubleVar(value=5.0)
        self.heat_rate = tk.DoubleVar(value=5.0)

        # multiprobe setup vars
        self.enable_multiprobe = tk.BooleanVar(value=False)
        self.number_of_probes = tk.IntVar(value=1)
        self.probe_settling_delay = tk.DoubleVar(value=0.0)
        self.probe_labels = {1: "Probe 1"}
        self.probe_name_vars = {
            1: tk.StringVar(value="Probe 1"),
            2: tk.StringVar(value="Probe 2"),
            3: tk.StringVar(value="Probe 3"),
            4: tk.StringVar(value="Probe 4"),
        }
        self.probe_colors = {1: PROBE_COLOR_PALETTE[0]}
        self.daq_task = None
        self.daq_line_spec = DAQ_PORT0_LINE_SPEC
        self.active_probe_index = None

        self.first_freq_dvar = tk.DoubleVar(value=devices.LCR_MIN_FREQ)
        self.last_freq_dvar = tk.DoubleVar(value=devices.LCR_MAX_FREQ)
        self.points_per_decade_ivar = tk.IntVar(value=8)
        self.custom_freq_dvar = tk.DoubleVar()

        self.selected_plot_temp_strvar = tk.StringVar(value="Latest")
        self.selected_plot_freq_strvar = tk.StringVar(
            value=f"{DEFAULT_FOCUS_FREQ_HZ:.6G}"
        )
        self.roll_id_strvar = tk.StringVar(value=DEFAULT_ROLL_ID)
        self.operator_strvar = tk.StringVar(value=DEFAULT_OPERATOR)
        self.traceability_confirmed = bool(DEFAULT_ROLL_ID and DEFAULT_OPERATOR)

        self.temp_step_data = pd.DataFrame(columns=TEMP_PLAN_COLUMNS)
        self.custom_freq_data = pd.DataFrame(columns=FREQ_STEP_COLUMNS[1:])
        self.freq_step_data = pd.DataFrame(columns=FREQ_STEP_COLUMNS[1:])
        self.test_data = pd.DataFrame(columns=TEST_DATA_COLUMNS)
        self.probe_table_data = pd.DataFrame(
            [(1, "Probe 1", PROBE_COLOR_PALETTE[0])],
            columns=PROBE_TABLE_COLUMNS,
        )

        self.device_strvar = tk.StringVar(value=devices.DEVICE_TYPE_LIST[0].name)
        self.message_strvar = tk.StringVar()
        self.response_strvar = tk.StringVar()
        self.device_list = [None] * len(devices.DEVICE_TYPE_LIST)  # type: ignore
        for index, dev in enumerate(devices.DEVICE_TYPE_LIST):
            try:
                self.device_list[index] = dev()
                print(f"{DEVICE_NAMES[index]} successfully connected!")
            except Exception as e:
                self.device_list[index] = None  # type: ignore
                print(f"{DEVICE_NAMES[index]} could not connect!")
                print(f"Connection error: {e}")
        self.active_device = self.device_list[0]

        self.temperature_readings_table = pd.DataFrame(
            columns=TEMPERATURE_READINGS_COLUMNS
        )  # master table; huge after hours
        self.temperature_rolling_table = pd.DataFrame(
            columns=TEMPERATURE_READINGS_COLUMNS
        )  # rolling table, ~30 entries
        self.temperature_table_lock = threading.Lock()
        self.readings_lock = threading.Lock()
        self.rolling_lock = threading.Lock()
        self.last_temperature_readings_length = 0

        self.build_app()
        self.app_root.mainloop()

    # switched to a paned window setup
    def build_app(self):
        # Do some setup
        self.app_root.title("Temperature-Controlled BDS Testing")
        # self.app_window.iconphoto(True, tk.PhotoImage(file="peak-nano-logo-blue.png"))
        # self.app_root.iconbitmap("peak-nano-logo-blue.ico")
        self.app_root.state("zoomed")
        self.app_root.protocol("WM_DELETE_WINDOW", self.on_closing)
        plt.ioff()
        self.build_menubar(self.app_root)
        outer = tk.PanedWindow(
            self.app_root,
            orient="horizontal",
            sashrelief="raised",
            sashwidth=6,
            bg="#1E1E2E",
        )
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        left = tk.LabelFrame(
            outer, text="Test Setup", font=("default", 14, "bold"), padx=10, pady=10
        )
        middle = tk.LabelFrame(
            outer,
            text="Test Management",
            font=("default", 14, "bold"),
            padx=10,
            pady=10,
        )
        right = tk.LabelFrame(
            outer, text="Data Plots", font=("default", 14, "bold"), padx=10, pady=10
        )

        outer.add(left, minsize=300, width=420)
        outer.add(middle, minsize=340, width=420)
        outer.add(right, minsize=400, width=600)

        self.build_test_setup(left)
        self.build_test_management(middle)
        self.build_data_plots(right)
        self.style_buttons(self.app_root)
        return self.app_root

    # function for confirmation before closing
    def on_closing(self):
        if bool(self.state & RUN_STATE.RUNNING) or self.state == RUN_STATE.PAUSE:
            if not messagebox.askokcancel(
                "Force Stop", "A sequence is active. Force stop the run and exit?"
            ):
                return
            self.on_stop_pressed()
            if self.run_thread is not None and self.run_thread.is_alive():
                self.run_thread.join(timeout=5)
            self.close_devices_and_resources()
            self.app_root.destroy()
            return
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.close_devices_and_resources()
            self.app_root.destroy()

    def close_devices_and_resources(self):
        try:
            self.close_daq_switching()
        except Exception as e:
            print(f"DAQ close error: {type(e).__name__}: {e}")

        for device in self.device_list:
            try:
                if device is not None and hasattr(device, "close"):
                    device.close()
            except Exception as e:
                print(f"Device close error: {e}")
        try:
            if hasattr(devices, "close_resource_manager"):
                devices.close_resource_manager()
        except Exception as e:
            print(f"VISA close error: {e}")

    def padding(
        self, master, x=0, y=0, side="top", fill="both", expand=False, **kwargs
    ):
        tk.Frame(master, width=x, height=y, **kwargs).pack(side=side, fill=fill, expand=expand)  # type: ignore

    # helper function to create labeled entries
    def _labeled_entry(self, parent, label: str, variable: tk.Variable, width=10):
        row = tk.Frame(parent)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, width=22, anchor="w").pack(side="left")
        entry = Entry(row, textvariable=variable, width=width, justify="right")
        entry.pack(side="left")
        return entry

    def _button_variant_for_text(self, text: str):
        text = text.lower()
        if "stop" in text or "all off" in text:
            return "danger"
        if "clear" in text or "remove" in text:
            return "clear"
        if text in ("run", "running"):
            return "success"
        if "pause" in text or "resume" in text:
            return "pause"
        if "export" in text:
            return "export"
        if "program" in text or "generate" in text or text == "set":
            return "warning"
        if "new" in text or "refresh" in text or "update" in text or "send" in text:
            return "primary"
        if "add" in text:
            return "success"
        return "neutral"

    def configure_pastel_button(self, button: tk.Button, variant: str | None = None):
        variant = variant or self._button_variant_for_text(str(button.cget("text")))
        bg, activebackground, fg = BUTTON_COLORS.get(
            variant, BUTTON_COLORS["neutral"]
        )
        button.configure(
            bg=bg,
            activebackground=activebackground,
            fg=fg,
            activeforeground=fg,
            disabledforeground="#7f8790",
            relief="raised",
            bd=2,
            padx=7,
            pady=3,
            wraplength=105,
            justify="center",
            overrelief="ridge",
        )

    def style_buttons(self, widget):
        if widget.__class__.__name__ == "NavigationToolbar2Tk" or hasattr(
            widget, "toolitems"
        ):
            return
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                self.configure_pastel_button(child)
            self.style_buttons(child)

    def make_action_button(self, master, text, command, variant=None, **kwargs):
        button = tk.Button(
            master=master,
            text=text,
            command=command,
            font=("default", 9, "bold"),
            height=1,
            **kwargs,
        )
        self.configure_pastel_button(button, variant=variant)
        return button

    def arrange_management_buttons(self, event=None):
        if not hasattr(self, "management_buttons"):
            return

        width = (
            event.width
            if event is not None
            else self.management_button_box.winfo_width()
        )
        if width < 260:
            columns = 1
        elif width < 380:
            columns = 2
        else:
            columns = 4

        if columns == getattr(self, "management_button_columns", None):
            return
        self.management_button_columns = columns

        for button in self.management_buttons:
            button.grid_forget()
        for column in range(4):
            self.management_button_box.grid_columnconfigure(
                column, weight=0, minsize=0
            )
        for column in range(columns):
            self.management_button_box.grid_columnconfigure(
                column, weight=1, minsize=86
            )

        for index, button in enumerate(self.management_buttons):
            button.grid(
                row=index // columns,
                column=index % columns,
                padx=4,
                pady=3,
                sticky="ew",
            )

    # MENUBAR ---------------------------
    # menubar with file options
    def build_menubar(self, master):
        menubar = tk.Menu(master, tearoff=False)
        fileMenu = tk.Menu(menubar, tearoff=False)
        fileMenu.add_command(
            label="Export Results to Excel",
            command=self.export_results,
        )
        fileMenu.add_separator()
        fileMenu.add_command(label="Exit", command=self.on_closing)
        menubar.add_cascade(label="File", menu=fileMenu)
        self.app_root.config(menu=menubar)

    # MAIN GUI PANELS ---------------------------
    # test setup tab with temperature plan, frequency steps, device communication, and probe selection subtabs
    def build_test_setup(self, master):
        self.setup_notebook = ttk.Notebook(
            master,
            style="TNotebook",
        )
        notebook = self.setup_notebook
        notebook.pack(side="top", fill="both", expand=True)

        # Temperature Tab
        temperature_tab = tk.Frame(
            master=notebook,
            width=400,
            height=280,
        )
        temperature_tab.pack(side="top", fill="both", expand=True)
        notebook.add(temperature_tab, text="Temperature")
        self.build_test_temp_tab(temperature_tab)

        # Frequency Tab
        frequency_tab = tk.Frame(
            master=notebook,
            width=400,
            height=280,
        )
        frequency_tab.pack(side="top", fill="both", expand=True)
        notebook.add(frequency_tab, text="Frequency")
        self.build_test_freq_tab(frequency_tab)

        # (Device Communication) Testing Tab
        devices_tab = tk.Frame(
            master=notebook,
            width=400,
            height=280,
        )
        devices_tab.pack(side="top", fill="both", expand=True)
        notebook.add(devices_tab, text="Devices")  # renamed
        self.build_devices_tab(devices_tab)

        # (Probe Selection) Probe Tab
        probes_tab = tk.Frame(
            master=notebook,
            width=400,
            height=280,
        )
        probes_tab.pack(side="top", fill="both", expand=True)
        notebook.add(probes_tab, text="Probes")
        self.build_probes_tab(probes_tab)

    # test management tab with controls, data table, and temperature cycle plot
    def build_test_management(self, master):
        controls_labelframe = tk.LabelFrame(
            master,
            text="Controls",
            font=("default", 12),
            padx=6,
            pady=6,
        )
        controls_labelframe.pack(side="top", fill="x")
        button_box = tk.Frame(
            master=controls_labelframe,
            padx=4,
            pady=4,
            bg="#E8E8E8",
        )
        button_box.pack(side="top", fill="x")

        self.management_button_box = button_box
        self.management_button_columns = None

        self.program_button = self.make_action_button(
            button_box, "Program", self.on_program_pressed, variant="warning"
        )
        self.run_button = self.make_action_button(
            button_box,
            "Run",
            self.on_run_pressed,
            variant="success",
            state="disabled",
        )
        self.pause_button = self.make_action_button(
            button_box,
            "Pause",
            self.on_pause_pressed,
            variant="pause",
            state="disabled",
        )
        self.stop_button = self.make_action_button(
            button_box,
            "Stop",
            self.on_stop_pressed,
            variant="danger",
            state="disabled",
        )
        self.new_run_button = self.make_action_button(
            button_box, "New Run", self.on_new_run_pressed, variant="primary"
        )
        self.clear_data_button = self.make_action_button(
            button_box, "Clear Data", self.on_clear_data_pressed, variant="clear"
        )
        self.export_button = self.make_action_button(
            button_box, "Export", self.export_results, variant="export"
        )
        self.management_buttons = (
            self.program_button,
            self.run_button,
            self.pause_button,
            self.stop_button,
            self.new_run_button,
            self.clear_data_button,
            self.export_button,
        )
        button_box.bind("<Configure>", self.arrange_management_buttons)
        self.app_root.after(0, self.arrange_management_buttons)

        self.padding(master, y=10, side="top")

        table_labelframe = tk.LabelFrame(
            master,
            text="Data Table",
            font=("default", 12),
            padx=10,
            pady=10,
        )
        table_labelframe.pack(side="top", fill="both")
        table_with_scroll_frame = tk.Frame(
            master=table_labelframe,
        )
        table_with_scroll_frame.pack(side="top", fill="y")
        self.padding(master, y=10, side="top")

        # table data and update function for measurement data table and plot
        self.measurement_data_table = Table(
            master=table_with_scroll_frame,
            columns=TEST_DATA_COLUMNS,
            displaycolumns="#all",
            show="headings",
            selectmode="none",
            height=16,
            header_widths=[70, 80, 75, 60, 60, 60, 60, 60],
            increment=False,
        )
        self.measurement_data_table.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            table_with_scroll_frame,
            orient="vertical",
            command=self.measurement_data_table.yview,
        )
        scrollbar.pack(side="left", fill="y")
        self.measurement_data_table.configure(yscrollcommand=scrollbar.set)

        self.measurement_data_table.update_table(self.test_data)

        temp_chart_labelframe = tk.LabelFrame(
            master,
            text="Temperature Chart",
            font=("default", 12),
            padx=10,
            pady=10,
        )
        temp_chart_labelframe.pack(side="top", fill="both", expand=True)

        temp_cycle_fig = Figure(figsize=(5, 4), dpi=80, layout="constrained")
        temp_cycle_fig.patch.set_facecolor("#F0F0F0")
        self.temp_cycle_axis = temp_cycle_fig.add_subplot()
        axis = self.temp_cycle_axis
        self.temp_cycle_canvas = FigureCanvasTkAgg(
            temp_cycle_fig, temp_chart_labelframe
        )
        self.temp_cycle_canvas.get_tk_widget().pack(
            side="top", fill="both", expand=True
        )
        MAX_LENGTH = 100
        HEADER_LIST = [TEMPERATURE_READINGS_COLUMNS[x] for x in [0, 3, 4, 5]]
        axis.text(
            0.5, 0.5, "No Data", ha="center", va="center", transform=axis.transAxes
        )

        def apply_cosmetics(
            ax: Axes,
            domain="min",
            times=[0.0],
            sets=[0.0],
            chambs=[0.0],
            users=[0.0],
        ):
            ax.set_title("Oven Readings (100 Samples)")
            axis.set_xlabel(f"Time [{domain}]")
            ax.set_ylabel(f"Sampled Temp [{CHAR_DEGC}]")
            ax.grid(which="both")
            axis.plot(times, sets, linestyle="-", color="blue")
            axis.plot(times, chambs, linestyle=":", color="orange")
            axis.plot(times, users, linestyle="--", color="red")
            axis.legend(labels=["Set", "Chamber", "User"])

        apply_cosmetics(axis)

        def t_update_temps(*args):
            if self.state & RUN_STATE.RUNNING:
                with self.temperature_table_lock:
                    master_table = self.temperature_readings_table.copy()
                    rolling_table = self.temperature_rolling_table.copy()
                master_length = len(master_table)
                rolling_length = len(rolling_table)
                total_length = master_length + rolling_length
                if total_length - self.last_temperature_readings_length <= 0:
                    print("Updating Temp Cycle Plot... No Changes")
                    pass
                else:
                    print("Updating Temp Cycle Plot... New Data")
                    if total_length > MAX_LENGTH:
                        indicies = list(
                            np.linspace(
                                0, total_length - 1, MAX_LENGTH, True, dtype=int
                            )
                        )
                        master_indicies = [
                            index for index in indicies if index < master_length
                        ]
                        rolling_indicies = [
                            index - master_length
                            for index in indicies
                            if index >= master_length
                        ]
                        master_slice = master_table.loc[master_indicies, HEADER_LIST]
                        rolling_slice = rolling_table.loc[rolling_indicies, HEADER_LIST]
                    else:
                        master_slice = master_table[HEADER_LIST]
                        rolling_slice = rolling_table[HEADER_LIST]
                    self.last_temperature_readings_length = total_length
                    combined_table = pd.concat(
                        [master_slice, rolling_slice]
                    )  # indicies unused for now
                    times = combined_table[TEMPERATURE_READINGS_COLUMNS[0]].tolist()
                    sets = combined_table[TEMPERATURE_READINGS_COLUMNS[3]].tolist()
                    chambs = combined_table[TEMPERATURE_READINGS_COLUMNS[4]].tolist()
                    users = combined_table[TEMPERATURE_READINGS_COLUMNS[5]].tolist()
                    last_time = times[-1]
                    if last_time > 3600:  # 3600 s = 1 hr
                        times = [x / 3600 for x in times]
                        domain = "hr"
                    elif 60 < last_time <= 3600:  # 60 s = 1 min
                        times = [x / 60 for x in times]
                        domain = "min"
                    else:
                        domain = "s"

                    axis.clear()

                    apply_cosmetics(axis, domain, times, sets, chambs, users)
                    self.temp_cycle_canvas.draw()
                    # print(times)
                    # print(temps)
            self.temp_cycle_canvas.get_tk_widget().after(1000, t_update_temps)

        # update_thread = threading.Thread(target=t_update_temps, args=[], daemon=True)
        self.temp_cycle_canvas.get_tk_widget().after(1000, t_update_temps)

    # build plots with specified temp and freq with refresh functionality
    def build_plot_controls(self, master):
        filter_frame = tk.LabelFrame(
            master,
            text="Plot Filters",
            font=("default", 10),
            padx=8,
            pady=6,
        )
        filter_frame.pack(side="top", fill="x", pady=(0, 6))

        tk.Label(filter_frame, text="Frequency plots temperature:").pack(side="left")

        self.plot_temp_combobox = ttk.Combobox(
            filter_frame,
            textvariable=self.selected_plot_temp_strvar,
            values=["Latest"],
            width=14,
            state="normal",
        )
        self.plot_temp_combobox.pack(side="left", padx=(4, 12))
        self.plot_temp_combobox.bind(
            "<<ComboboxSelected>>",
            lambda *args: self.sync_measurement_data(),
        )

        tk.Label(filter_frame, text="Temperature plots frequency [Hz]:").pack(
            side="left"
        )

        self.plot_freq_combobox = ttk.Combobox(
            filter_frame,
            textvariable=self.selected_plot_freq_strvar,
            values=[f"{DEFAULT_FOCUS_FREQ_HZ:.6g}"],
            width=12,
        )
        self.plot_freq_combobox.pack(side="left", padx=(4, 12))
        self.plot_freq_combobox.bind(
            "<<ComboboxSelected>>",
            lambda *args: self.sync_measurement_data(),
        )
        self.plot_freq_combobox.bind(
            "<Return>",
            lambda *args: self.sync_measurement_data(),
        )

        tk.Button(
            filter_frame,
            text="Refresh",
            command=self.sync_measurement_data,
        ).pack(side="left")

    def build_data_plots(self, master):
        self.build_plot_controls(master)

        self.test_plot = TestDataPlot(master)
        self.test_plot.widget.pack(side="top", fill="both", expand=True)
        self.test_plot.update_plots(self.test_data)

    # TEST SETUP NOTEBOOK TABS ---------------------------
    def build_test_temp_tab(self, temperature_tab):
        params = tk.LabelFrame(temperature_tab, text="Step Parameters", padx=8, pady=8)
        params.pack(fill="x", pady=6)

        self.entry_start_temp = self._labeled_entry(
            params, f"Start Temp [{CHAR_DEGC}]", self.start_temp
        )
        self.entry_step_temp = self._labeled_entry(
            params, f"Step Size 1 [{CHAR_DEGC}]", self.step_temp
        )
        self.use_second_step_checkbutton = tk.Checkbutton(
            params,
            text="Use second step size",
            variable=self.use_second_step,
            command=self.update_second_step_controls,
            anchor="w",
        )
        self.use_second_step_checkbutton.pack(fill="x", pady=(6, 2))
        self.entry_step_change_temp = self._labeled_entry(
            params, f"Step Change Temp [{CHAR_DEGC}]", self.step_change_temp
        )
        self.entry_step2_temp = self._labeled_entry(
            params, f"Step Size 2 [{CHAR_DEGC}]", self.step2_temp
        )
        self.entry_max_temp = self._labeled_entry(
            params, f"Max Temp [{CHAR_DEGC}]", self.max_temp
        )
        self.entry_dwell_time = self._labeled_entry(
            params, "Dwell Time [min]", self.dwell_time
        )
        self.entry_heat_rate = self._labeled_entry(
            params, f"Heat Ramp [{CHAR_DEGC}/min]", self.heat_rate
        )

        self.generate_plan_button = tk.Button(
            params,
            text="Generate Plan",
            command=self.generate_temperature_plan,
            fg="royalblue",
        )
        self.generate_plan_button.pack(pady=(6, 0))

        # store temperature entry widgets
        self.temperature_setup_controls = [
            self.entry_start_temp,
            self.entry_step_temp,
            self.use_second_step_checkbutton,
            self.entry_step_change_temp,
            self.entry_step2_temp,
            self.entry_max_temp,
            self.entry_dwell_time,
            self.entry_heat_rate,
            self.generate_plan_button,
        ]
        self.second_step_controls = [
            self.entry_step_change_temp,
            self.entry_step2_temp,
        ]
        self.update_second_step_controls()

        table_frame = tk.LabelFrame(
            temperature_tab, text="Temperature Plan", padx=6, pady=6
        )
        table_frame.pack(fill="both", expand=True, pady=4)

        table_with_scroll_frame = tk.Frame(table_frame)
        table_with_scroll_frame.pack(fill="both", expand=True)

        self.temp_step_table = Table(
            master=table_with_scroll_frame,
            columns=TEMP_PLAN_COLUMNS,
            displaycolumns="#all",
            show="headings",
            selectmode="none",
            height=8,
            header_widths=[40, 80, 80, 80, 80, 80],
            increment=False,
        )
        self.temp_step_table.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            master=table_with_scroll_frame,
            orient="vertical",
            command=self.temp_step_table.yview,
        )
        scrollbar.pack(side="left", fill="y")
        self.temp_step_table.configure(yscrollcommand=scrollbar.set)

        plot_frame = tk.LabelFrame(temperature_tab, text="Plan Preview", padx=6, pady=6)
        plot_frame.pack(fill="both", expand=True, pady=4)

        self.temp_step_plot = TempStepPlot(plot_frame)
        self.temp_step_plot.plot_canvas.get_tk_widget().pack(fill="both", expand=True)
        self.temp_step_plot.update_plot(self.temp_step_data)

    def build_test_freq_tab(self, frequency_tab):
        sweep_params_box = tk.LabelFrame(
            master=frequency_tab,
            text="Primary Frequencies: Sweep",
            font=("default", 10),
            padx=10,
            pady=10,
        )
        sweep_params_box.pack(side="top", fill="x")
        frequency_logspace_box = tk.Frame(
            master=sweep_params_box,
        )
        frequency_logspace_box.pack(side="top", fill="x")

        low_freq_frame = tk.Frame(
            master=frequency_logspace_box,
        )
        low_freq_frame.pack(side="left")
        low_freq_label = tk.Label(master=low_freq_frame, text="First [Hz] ")
        low_freq_label.pack(side="left", fill="y")
        self.low_freq_entry = Entry(
            master=low_freq_frame,
            width=10,
            justify="right",
            textvariable=self.first_freq_dvar,
        )
        self.low_freq_entry.pack(side="left", fill="y")

        high_freq_frame = tk.Frame(
            master=frequency_logspace_box,
        )
        high_freq_frame.pack(side="left")
        high_freq_label = tk.Label(master=high_freq_frame, text=" to Last [Hz] ")
        high_freq_label.pack(side="left", fill="y")
        self.high_freq_entry = Entry(
            master=high_freq_frame,
            width=10,
            justify="right",
            textvariable=self.last_freq_dvar,
        )
        self.high_freq_entry.pack(side="left", fill="y")

        points_per_decade_frame = tk.Frame(
            master=frequency_logspace_box,
        )
        points_per_decade_frame.pack(side="left")
        points_per_decade_label = tk.Label(
            master=points_per_decade_frame, text=" @ Points/Dec. "
        )
        points_per_decade_label.pack(side="left", fill="y")
        self.points_per_decade_entry = Entry(
            master=points_per_decade_frame,
            width=7,
            justify="right",
            textvariable=self.points_per_decade_ivar,
        )
        self.points_per_decade_entry.pack(side="left", fill="y")
        # points_per_decade_entry.bind("<Return>", lambda *args: print(self.first_freq_dvar.get(), self.last_freq_dvar.get(), self.points_per_decade_ivar.get()))

        def sync_freq_tables():
            custom_df = self.custom_freq_data
            logspace_df = self.freq_step_data
            self.custom_freq_table.update_table(self.custom_freq_data)
            # custom_df[FREQ_STEP_COLUMNS[2]] = '*'
            # logspace_df[FREQ_STEP_COLUMNS[2]] = ''
            df = pd.concat([logspace_df, custom_df], ignore_index=True)
            df = df.sort_values(by=FREQ_STEP_COLUMNS[1])
            df = df.reset_index(drop=True)
            self.freq_step_table.update_table(df)

        def set_freq_logspace_pressed():
            try:
                minimum_frequency = float(self.first_freq_dvar.get())
                maximum_frequency = float(self.last_freq_dvar.get())
                points_per_decade = int(self.points_per_decade_ivar.get())
            except (ValueError, tk.TclError):
                messagebox.showerror(
                    "Invalid Frequencies", "Frequency inputs must be numeric."
                )
                return
            if not all(
                np.isfinite(value)
                for value in [minimum_frequency, maximum_frequency, points_per_decade]
            ):
                messagebox.showerror(
                    "Invalid Frequencies", "Frequency inputs must be finite numbers."
                )
                return
            if minimum_frequency < devices.LCR_MIN_FREQ:
                messagebox.showerror(
                    "Invalid Frequencies",
                    f"First frequency must be at least {devices.LCR_MIN_FREQ:g} Hz.",
                )
                return
            if maximum_frequency > devices.LCR_MAX_FREQ:
                messagebox.showerror(
                    "Invalid Frequencies",
                    f"Last frequency must be no more than {devices.LCR_MAX_FREQ:g} Hz.",
                )
                return
            if minimum_frequency >= maximum_frequency:
                messagebox.showerror(
                    "Invalid Frequencies",
                    "First frequency must be less than last frequency.",
                )
                return
            if points_per_decade < 1:
                messagebox.showerror(
                    "Invalid Frequencies", "Points per decade must be at least 1."
                )
                return
            print(minimum_frequency, maximum_frequency, points_per_decade)
            low_decade = np.log10(minimum_frequency)
            high_decade = np.log10(maximum_frequency)
            num_decades = high_decade - low_decade
            if num_decades < 1:
                data_points = np.linspace(
                    minimum_frequency, maximum_frequency, num=points_per_decade
                )
            else:
                num_points = int(num_decades) * points_per_decade
                data_points = np.logspace(
                    start=low_decade,
                    stop=high_decade,
                    num=num_points,
                    endpoint=True,
                    base=10,
                )
            data_points = [float(f"{x:.6g}") for x in data_points]
            print("Logspace frequencies:", data_points)
            df = self.freq_step_data
            if len(df):
                df = pd.DataFrame(columns=FREQ_STEP_COLUMNS[1:])
            df[FREQ_STEP_COLUMNS[1]] = data_points
            df[FREQ_STEP_COLUMNS[2]] = ""
            self.freq_step_data = df
            self.freq_step_table.update_table(df)
            sync_freq_tables()
            # var.frequency_array = list(data_points)

        tk.Frame(master=sweep_params_box, height=10).pack(side="top", fill="x")

        logspace_button_box = tk.Frame(
            master=sweep_params_box,
        )
        logspace_button_box.pack(side="top", fill="x")

        self.set_logspace_button = tk.Button(
            master=logspace_button_box,
            text="Set Logspace",
            command=set_freq_logspace_pressed,
        )
        self.set_logspace_button.pack(side="top")
        self.points_per_decade_entry.bind(
            "<Return>", lambda *args: self.set_logspace_button.invoke()
        )

        # Frequency list tables
        tk.Frame(master=frequency_tab, height=10).pack(side="top", fill="x")
        both_freq_table_frame = tk.Frame(
            master=frequency_tab,
        )
        both_freq_table_frame.pack(side="top", fill="both", expand=True)
        left_side_box = tk.LabelFrame(
            master=both_freq_table_frame,
            text="Secondary Frequencies",
            font=("default", 10),
            padx=10,
            pady=10,
        )
        left_side_box.pack(side="left", fill="y", expand=True)
        tk.Frame(master=both_freq_table_frame, width=10).pack(side="left")
        right_side_box = tk.LabelFrame(
            master=both_freq_table_frame,
            text="Frequency Steps",
            font=("default", 10),
            padx=10,
            pady=10,
        )
        right_side_box.pack(side="left", fill="y", expand=True)

        # Test settings button inputs
        setting_buttons_box = tk.Frame(
            master=left_side_box,
        )
        setting_buttons_box.pack(side="top", fill="x")

        manual_freq_frame = tk.Frame(
            master=setting_buttons_box,
        )
        manual_freq_frame.pack(side="top", fill="x")
        manual_freq_label = tk.Label(master=manual_freq_frame, text="Manual [Hz] ")
        manual_freq_label.pack(side="left")
        self.manual_freq_entry = Entry(
            master=manual_freq_frame,
            width=10,
            justify="right",
            textvariable=self.custom_freq_dvar,
        )
        self.manual_freq_entry.pack(side="left")
        button_row = tk.Frame(
            master=setting_buttons_box,
            padx=10,
            pady=10,
        )
        button_row.pack(side="top", fill="x", expand=True)

        def add_manual_freq_pressed(*args):
            print("add step")
            try:
                freq = float(self.custom_freq_dvar.get())
            except (ValueError, tk.TclError):
                messagebox.showerror(
                    "Invalid Frequency", "Manual frequency must be numeric."
                )
                return
            if not np.isfinite(freq):
                messagebox.showerror(
                    "Invalid Frequency", "Manual frequency must be finite."
                )
                return
            if freq < devices.LCR_MIN_FREQ or freq > devices.LCR_MAX_FREQ:
                messagebox.showerror(
                    "Invalid Frequency",
                    f"Manual frequency must be between {devices.LCR_MIN_FREQ:g} and {devices.LCR_MAX_FREQ:g} Hz.",
                )
                return
            df = self.custom_freq_data
            existing = pd.concat(
                [self.freq_step_data, self.custom_freq_data],
                ignore_index=True,
            )
            existing_freqs = pd.to_numeric(
                existing.get(FREQ_STEP_COLUMNS[1], pd.Series(dtype=float)),
                errors="coerce",
            )
            if any(np.isclose(existing_freqs.dropna(), freq, rtol=1e-9, atol=1e-9)):
                messagebox.showwarning(
                    "Duplicate Frequency",
                    f"{freq:g} Hz already exists in the frequency list.",
                )
                return
            print([freq, "*"])
            print(self.custom_freq_data)
            self.custom_freq_data.loc[len(df)] = [freq, "*"]
            print(self.custom_freq_data)
            sync_freq_tables()

        self.add_freq_button = tk.Button(
            master=button_row,
            text="Add Step",
            command=add_manual_freq_pressed,
        )
        self.add_freq_button.pack(side="left", expand=True)
        self.manual_freq_entry.bind(
            "<Return>", lambda *args: self.add_freq_button.invoke()
        )

        def drop_manual_freq_pressed(*args):
            df = self.custom_freq_data
            if len(df) == 0:
                return
            self.custom_freq_data = df.drop(df.tail(1).index)
            sync_freq_tables()

        self.remove_freq_button = tk.Button(
            master=button_row,
            text="Drop Step",
            command=drop_manual_freq_pressed,
        )
        self.remove_freq_button.pack(side="left", expand=True)
        self.manual_freq_entry.bind(
            "<Shift-Return>", lambda *args: self.remove_freq_button.invoke()
        )

        def clear_manual_freqs_pressed(*args):
            df = self.custom_freq_data
            if len(df) == 0:
                return
            self.custom_freq_data = pd.DataFrame(columns=FREQ_STEP_COLUMNS[1:])
            sync_freq_tables()

        self.clear_freq_button = tk.Button(
            master=setting_buttons_box,
            text="Clear List",
            command=clear_manual_freqs_pressed,
        )
        self.clear_freq_button.pack(side="top", expand=True)

        self.frequency_setup_controls = [
            self.low_freq_entry,
            self.high_freq_entry,
            self.points_per_decade_entry,
            self.set_logspace_button,
            self.manual_freq_entry,
            self.add_freq_button,
            self.remove_freq_button,
            self.clear_freq_button,
        ]

        # Custom freq table
        tk.Frame(master=left_side_box, height=10).pack(side="top", fill="x")

        custom_table_labelframe = tk.Frame(
            master=left_side_box,
        )
        custom_table_labelframe.pack(side="top", fill="y", expand=True)
        custom_table_with_scroll_frame = tk.Frame(
            master=custom_table_labelframe,
        )
        custom_table_with_scroll_frame.pack(side="left", fill="y", expand=True)
        self.custom_freq_table = Table(
            master=custom_table_with_scroll_frame,
            columns=FREQ_STEP_COLUMNS[:2],
            displaycolumns="#all",
            show="headings",
            selectmode="none",
            height=20,
            header_widths=[40, 100],
            increment=False,
        )
        self.custom_freq_table.pack(side="left", fill="both", expand=True)
        custom_table_scrollbar = ttk.Scrollbar(
            master=custom_table_with_scroll_frame,
            orient="vertical",
            command=self.custom_freq_table.yview,
        )
        custom_table_scrollbar.pack(side="left", fill="y")
        self.custom_freq_table.configure(yscrollcommand=custom_table_scrollbar.set)

        # Full list table
        full_table_labelframe = tk.Frame(
            master=right_side_box,
        )
        full_table_labelframe.pack(side="left", fill="y", expand=True)
        full_table_with_scroll_frame = tk.Frame(
            master=full_table_labelframe,
        )
        full_table_with_scroll_frame.pack(side="left", fill="y", expand=True)
        self.freq_step_table = Table(
            master=full_table_with_scroll_frame,
            columns=FREQ_STEP_COLUMNS,
            displaycolumns="#all",
            show="headings",
            selectmode="none",
            height=20,
            header_widths=[40, 100, 16],
            increment=False,
        )
        self.freq_step_table.pack(side="left", fill="both", expand=True)
        full_table_scrollbar = ttk.Scrollbar(
            master=full_table_with_scroll_frame,
            orient="vertical",
            command=self.freq_step_table.yview,
        )
        full_table_scrollbar.pack(side="left", fill="y")
        self.freq_step_table.configure(yscrollcommand=full_table_scrollbar.set)

    def build_devices_tab(self, devices_tab):
        self.padding(devices_tab, y=10, side="top")
        device_labelframe = tk.LabelFrame(
            master=devices_tab,
            text="Active Devices",
            font=("default", 12),
            padx=10,
            pady=10,
        )
        device_labelframe.pack(side="top", fill="x")

        def set_device(*args):
            index = DEVICE_NAMES.index(self.device_strvar.get())
            self.active_device = self.device_list[index]

        device_combobox = ttk.Combobox(
            master=device_labelframe,
            textvariable=self.device_strvar,
            values=DEVICE_NAMES,
        )
        device_combobox.pack(side="left", fill="x", expand=True)
        self.device_strvar.trace_add("write", set_device)

        self.padding(devices_tab, y=10, side="top")
        message_labelframe = tk.LabelFrame(
            master=devices_tab,
            text="Manual Command",
            font=("default", 12),
            padx=10,
            pady=10,
        )
        message_labelframe.pack(side="top", fill="x")
        self.manual_message_entry = Entry(
            master=message_labelframe,
            justify="left",
            textvariable=self.message_strvar,
        )
        self.manual_message_entry.pack(side="left", fill="x", expand=True)

        try:
            # self.device_list = devices.SunSystemsOven_EC1A()
            pass
        except Exception as e:
            print(f"Connection error: {e}")
            pass  # TODO: Separate process looping device connection/communication

        self.padding(message_labelframe, x=10, side="left")

        def manual_send_pressed():
            if self.is_sequence_active():
                messagebox.showwarning(
                    "Sequence Active",
                    "Manual device commands are disabled while a sequence is active.",
                )
                return
            threading.Thread(target=self.device_msg, daemon=True).start()

        self.manual_send_button = tk.Button(
            master=message_labelframe,
            text="Send",
            command=manual_send_pressed,
        )
        self.manual_send_button.pack(side="right")
        self.manual_message_entry.bind(
            "<Return>", lambda *args: self.manual_send_button.invoke()
        )
        self.manual_command_controls = [
            self.manual_message_entry,
            self.manual_send_button,
        ]

        self.padding(devices_tab, y=10, side="top")
        response_frame = tk.LabelFrame(
            master=devices_tab,
            text="Response",
            font=("default", 12),
            padx=10,
            pady=10,
        )
        response_frame.pack(side="top", fill="both")
        response_box = tk.Text(
            master=response_frame,
            width=10,
        )
        response_box.pack(side="top", fill="both")
        self.response_strvar.trace_add(
            "write",
            lambda *args: response_box.replace(
                "1.0", "end", self.response_strvar.get()
            ),
        )

    def build_probes_tab(self, probes_tab):
        self.padding(probes_tab, y=10, side="top")
        probes_labelframe = tk.LabelFrame(
            master=probes_tab,
            text="Multiprobe",
            font=("default", 12),
            padx=10,
            pady=10,
        )
        probes_labelframe.pack(side="top", fill="x")

        self.enable_multiprobe_checkbutton = tk.Checkbutton(
            probes_labelframe,
            text="Enable multiprobe",
            variable=self.enable_multiprobe,
            command=self.sync_probe_table,
            anchor="w",
        )
        self.enable_multiprobe_checkbutton.pack(fill="x", pady=(0, 4))

        self.entry_number_of_probes = self._labeled_entry(
            probes_labelframe, "Number of probes", self.number_of_probes, width=8
        )

        self.probe_name_entries = {}
        for probe_index in range(1, 5):
            self.probe_name_entries[probe_index] = self._labeled_entry(
                probes_labelframe,
                f"Probe {probe_index} Name",
                self.probe_name_vars[probe_index],
                width=12,
            )

        self.entry_probe_settling_delay = self._labeled_entry(
            probes_labelframe,
            "Settling Delay [s]",
            self.probe_settling_delay,
            width=8,
        )

        self.update_probe_list_button = tk.Button(
            probes_labelframe,
            text="Update Probe List",
            command=self.sync_probe_table,
            fg="royalblue",
        )
        self.update_probe_list_button.pack(pady=(6, 0))

        self.padding(probes_tab, y=10, side="top")
        probe_table_frame = tk.LabelFrame(
            probes_tab, text="Probe List", padx=6, pady=6
        )
        probe_table_frame.pack(fill="both", expand=True)

        probe_table_with_scroll_frame = tk.Frame(probe_table_frame)
        probe_table_with_scroll_frame.pack(fill="both", expand=True)

        self.probe_table = Table(
            master=probe_table_with_scroll_frame,
            columns=PROBE_TABLE_COLUMNS,
            displaycolumns="#all",
            show="headings",
            selectmode="none",
            height=8,
            header_widths=[90, 180, 100],
            increment=False,
        )
        self.probe_table.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            master=probe_table_with_scroll_frame,
            orient="vertical",
            command=self.probe_table.yview,
        )
        scrollbar.pack(side="left", fill="y")
        self.probe_table.configure(yscrollcommand=scrollbar.set)

        self.padding(probes_tab, y=10, side="top")
        probe_test_frame = tk.LabelFrame(
            probes_tab, text="Manual Switch Test", padx=6, pady=6
        )
        probe_test_frame.pack(fill="x")

        self.probe_test_buttons = []
        for button_index, probe_index in enumerate(PROBE_SWITCH_PATTERNS):
            button = tk.Button(
                probe_test_frame,
                text=f"Test Probe {probe_index}",
                command=lambda index=probe_index: self.on_test_probe_pressed(index),
            )
            button.grid(
                row=button_index // 3,
                column=button_index % 3,
                padx=3,
                pady=3,
                sticky="ew",
            )
            self.probe_test_buttons.append(button)

        self.probe_all_off_button = tk.Button(
            probe_test_frame,
            text="All Off",
            command=self.on_test_all_off_pressed,
        )
        self.probe_all_off_button.grid(row=1, column=1, padx=3, pady=3, sticky="ew")
        self.probe_test_buttons.append(self.probe_all_off_button)
        for column_index in range(3):
            probe_test_frame.grid_columnconfigure(column_index, weight=1)

        self.probe_setup_controls = [
            self.enable_multiprobe_checkbutton,
            self.entry_number_of_probes,
            self.entry_probe_settling_delay,
            self.update_probe_list_button,
            *self.probe_test_buttons,
        ]
        self.sync_probe_table(show_errors=False)

    # DATA / MODEL METHODS -----------------------------

    def update_second_step_controls(self, setup_enabled=None):
        if setup_enabled is None:
            setup_enabled = not self.is_sequence_active()
        state_value = (
            "normal" if setup_enabled and self.use_second_step.get() else "disabled"
        )
        for widget in getattr(self, "second_step_controls", []):
            try:
                widget.config(state=state_value)
            except Exception:
                pass

    def get_probe_count(self):
        try:
            count = int(self.number_of_probes.get())
        except (ValueError, TypeError, tk.TclError):
            return 1
        return max(1, count)

    def get_probe_settling_delay(self):
        try:
            delay = float(self.probe_settling_delay.get())
        except (ValueError, TypeError, tk.TclError):
            return 0.0
        return max(0.0, delay)

    def get_probe_color(self, probe_index):
        if probe_index not in self.probe_colors:
            self.probe_colors[probe_index] = get_default_probe_color(probe_index)
        return self.probe_colors[probe_index]

    def get_probe_configs(self):
        count = self.get_probe_count() if self.enable_multiprobe.get() else 1
        configs = []
        for probe_index in range(1, count + 1):
            label = self.probe_name_vars[probe_index].get().strip()
            if not label:
                label = f"Probe {probe_index}"
            color = self.get_probe_color(probe_index)
            configs.append((probe_index, label, color))
        return configs

    def validate_probe_settings(self):
        if not self.enable_multiprobe.get():
            return
        try:
            count = int(self.number_of_probes.get())
        except (ValueError, TypeError, tk.TclError):
            raise ValueError("Number of probes must be an integer.")
        if count < 1:
            raise ValueError("Number of probes must be at least 1.")
        if count > len(PROBE_SWITCH_PATTERNS):
            raise ValueError(
                f"Only {len(PROBE_SWITCH_PATTERNS)} probes are currently mapped "
                "for USB-6501 switching."
            )
        try:
            delay = float(self.probe_settling_delay.get())
        except (ValueError, TypeError, tk.TclError):
            raise ValueError("Probe settling delay must be numeric.")
        if delay < 0:
            raise ValueError("Probe settling delay cannot be negative.")

    def sync_probe_table(self, show_errors=True):
        try:
            self.validate_probe_settings()
        except ValueError as e:
            if show_errors:
                messagebox.showerror("Invalid Probe Settings", str(e))
            return False

        self.probe_table_data = pd.DataFrame(
            self.get_probe_configs(), columns=PROBE_TABLE_COLUMNS
        )
        if hasattr(self, "probe_table"):
            self.probe_table.update_table(self.probe_table_data)
        return True

    def on_test_probe_pressed(self, probe_index):
        if self.is_sequence_active():
            messagebox.showwarning(
                "Sequence Active",
                "Manual probe switching is disabled while a sequence is active.",
            )
            return
        if not self.enable_multiprobe.get():
            messagebox.showwarning(
                "Multiprobe Disabled",
                "Enable multiprobe before using the manual probe test buttons.",
            )
            return
        try:
            self.validate_probe_settings()
            if probe_index > self.get_probe_count():
                messagebox.showwarning(
                    "Probe Not Enabled",
                    f"Probe {probe_index} is not enabled. "
                    "Increase Number of probes first.",
                )
                return
            self.switch_to_probe(probe_index, self.get_probe_configs())
        except Exception as e:
            messagebox.showerror(
                "Probe Switch Error", f"{type(e).__name__}: {e}"
            )

    def on_test_all_off_pressed(self):
        if self.is_sequence_active():
            messagebox.showwarning(
                "Sequence Active",
                "Manual probe switching is disabled while a sequence is active.",
            )
            return
        self.switch_all_probes_off(initialize_if_needed=True)

    # helper function utilizing the build_temperature_plan function to generate the temperature plan dataframe based on the current input parameters
    def generate_temperature_plan(self):
        if self.is_sequence_active():
            messagebox.showwarning(
                "Sequence Active",
                "Temperature plan cannot be edited while a sequence is active.",
            )
            return False
        try:
            self.temp_step_data = build_temperature_plan(
                self.start_temp.get(),
                self.step_temp.get(),
                self.max_temp.get(),
                self.dwell_time.get(),
                self.heat_rate.get(),
                self.use_second_step.get(),
                self.step_change_temp.get(),
                self.step2_temp.get(),
            )

            self.temp_step_table.update_table(self.temp_step_data)
            self.temp_step_plot.update_plot(
                self.temp_step_data,
                start_temp=self.start_temp.get(),
            )
            return True

        except (ValueError, tk.TclError) as e:
            messagebox.showerror("Invalid Temperature Plan", str(e))
            return False

    # sync function to update temp step table and plot with new temperature plan data
    def sync_temp_step(self, dataframe: pd.DataFrame, *args):
        self.temp_step_table.update_table(dataframe)
        self.temp_step_plot.update_plot(dataframe)

    # combine into one dataframe for export
    def get_temperature_log(self):
        with self.temperature_table_lock:
            return pd.concat(
                [self.temperature_readings_table, self.temperature_rolling_table],
                ignore_index=True,
            )

    def append_temperature_log_row(self, row):
        with self.temperature_table_lock:
            self.temperature_rolling_table.loc[len(self.temperature_rolling_table)] = (
                row
            )
            if len(self.temperature_rolling_table) >= TEMPERATURE_ROLLING_MAX_ROWS:
                self.temperature_readings_table = pd.concat(
                    [self.temperature_readings_table, self.temperature_rolling_table],
                    ignore_index=True,
                )
                self.temperature_rolling_table = pd.DataFrame(
                    columns=TEMPERATURE_READINGS_COLUMNS
                )

    # gets most recent measurement
    def get_display_measurements(self):
        return self.test_data.tail(MEASUREMENT_DISPLAY_ROWS).reset_index(drop=True)

    def get_selected_plot_frequency(self):
        try:
            return float(self.selected_plot_freq_strvar.get())
        except (ValueError, TypeError, tk.TclError):
            return DEFAULT_FOCUS_FREQ_HZ

    def get_selected_plot_temperature(self):
        try:
            value = self.selected_plot_temp_strvar.get()
        except (ValueError, TypeError, tk.TclError):
            value = "Latest"
        return value or "Latest"

    def get_traceability_values(self) -> tuple[str, str]:
        return self.roll_id_strvar.get().strip(), self.operator_strvar.get().strip()

    def ensure_traceability_metadata(self) -> bool:
        roll_id, operator_name = self.get_traceability_values()
        if self.traceability_confirmed and roll_id and operator_name:
            return True
        return self.prompt_traceability_metadata()

    def prompt_traceability_metadata(self) -> bool:
        result = {"confirmed": False}
        dialog = tk.Toplevel(self.app_root)
        dialog.title("Run Traceability")
        dialog.transient(self.app_root)
        dialog.resizable(False, False)
        dialog.grab_set()

        roll_id_var = tk.StringVar(value=self.roll_id_strvar.get())
        operator_var = tk.StringVar(value=self.operator_strvar.get())

        body = ttk.Frame(dialog, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Roll ID").grid(row=0, column=0, sticky="w", pady=4)
        roll_entry = Entry(body, textvariable=roll_id_var, width=30)
        roll_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(body, text="Operator").grid(row=1, column=0, sticky="w", pady=4)
        operator_entry = Entry(body, textvariable=operator_var, width=30)
        operator_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)

        button_frame = ttk.Frame(body)
        button_frame.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def accept():
            roll_id = roll_id_var.get().strip()
            operator_name = operator_var.get().strip()
            if not roll_id or not operator_name:
                messagebox.showwarning(
                    "Required Fields",
                    "Roll ID and Operator are required.",
                    parent=dialog,
                )
                if not roll_id:
                    roll_entry.focus_set()
                else:
                    operator_entry.focus_set()
                return

            self.roll_id_strvar.set(roll_id)
            self.operator_strvar.set(operator_name)
            self.traceability_confirmed = True
            result["confirmed"] = True
            dialog.destroy()

        def cancel():
            result["confirmed"] = False
            dialog.destroy()

        ttk.Button(button_frame, text="Cancel", command=cancel).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(button_frame, text="OK", command=accept).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Return>", lambda *_: accept())
        dialog.bind("<Escape>", lambda *_: cancel())

        if not roll_id_var.get().strip():
            roll_entry.focus_set()
        else:
            operator_entry.focus_set()
        self.app_root.wait_window(dialog)
        return result["confirmed"]

    # updates the dropdown options
    def update_plot_filter_options(self):
        if self.test_data.empty:
            temp_values = ["Latest"]
            freq_values = [f"{DEFAULT_FOCUS_FREQ_HZ:.6g}"]
        else:
            temp_col = f"Temp. [{CHAR_DEGC}]"
            freq_col = "Freq. [Hz]"

            temps = (
                pd.to_numeric(self.test_data[temp_col], errors="coerce")
                .dropna()
                .drop_duplicates()
                .tolist()
            )

            freqs = (
                pd.to_numeric(self.test_data[freq_col], errors="coerce")
                .dropna()
                .drop_duplicates()
                .sort_values()
                .tolist()
            )

            temp_values = ["Latest"] + [f"{temp:.2f}" for temp in temps]
            freq_values = [f"{freq:.6g}" for freq in freqs] or [
                f"{DEFAULT_FOCUS_FREQ_HZ:.6g}"
            ]

        if hasattr(self, "plot_temp_combobox"):
            self.plot_temp_combobox.configure(values=temp_values)

            if self.selected_plot_temp_strvar.get() not in temp_values:
                self.selected_plot_temp_strvar.set("Latest")

        if hasattr(self, "plot_freq_combobox"):
            self.plot_freq_combobox.configure(values=freq_values)

            if (
                self.selected_plot_freq_strvar.get() not in freq_values
                and self.test_data.empty
            ):
                self.selected_plot_freq_strvar.set(f"{DEFAULT_FOCUS_FREQ_HZ:.6g}")

    # refreshes plots
    def sync_measurement_data(self):
        self.measurement_data_table.update_table(self.get_display_measurements())
        self.update_plot_filter_options()

        self.test_plot.update_plots(
            self.test_data,
            selected_temp=self.get_selected_plot_temperature(),
            selected_freq=self.get_selected_plot_frequency(),
        )

    # clears data func
    def reset_measurement_data(self):
        self.test_data = pd.DataFrame(columns=TEST_DATA_COLUMNS)
        with self.temperature_table_lock:
            self.temperature_readings_table = pd.DataFrame(
                columns=TEMPERATURE_READINGS_COLUMNS
            )
            self.temperature_rolling_table = pd.DataFrame(
                columns=TEMPERATURE_READINGS_COLUMNS
            )

        self.last_temperature_readings_length = 0

        self.sync_measurement_data()

    def reset_temperature_log_and_chart(self):
        with self.temperature_table_lock:
            self.temperature_readings_table = pd.DataFrame(
                columns=TEMPERATURE_READINGS_COLUMNS
            )
            self.temperature_rolling_table = pd.DataFrame(
                columns=TEMPERATURE_READINGS_COLUMNS
            )
        self.last_temperature_readings_length = 0
        self.reset_temperature_chart()

    # reset test setup
    def reset_test_setup(self):
        self.temp_step_data = pd.DataFrame(columns=TEMP_PLAN_COLUMNS)

        self.freq_step_data = pd.DataFrame(columns=FREQ_STEP_COLUMNS[1:])
        self.custom_freq_data = pd.DataFrame(columns=FREQ_STEP_COLUMNS[1:])

        self.temp_step_table.update_table(self.temp_step_data)

        self.temp_step_plot.update_plot(
            self.temp_step_data,
            start_temp=self.start_temp.get(),
        )

        self.freq_step_table.update_table(pd.DataFrame(columns=FREQ_STEP_COLUMNS))

        self.custom_freq_table.update_table(self.custom_freq_data)

        # reset temp chart

    def reset_temperature_chart(self):
        self.temp_cycle_axis.clear()
        self.temp_cycle_axis.set_title("Oven Readings (100 Samples)")
        self.temp_cycle_axis.set_xlabel("Time [min]")
        self.temp_cycle_axis.set_ylabel(f"Sampled Temp [{CHAR_DEGC}]")
        self.temp_cycle_axis.grid(which="both")
        self.temp_cycle_axis.text(
            0.5,
            0.5,
            "No Data",
            ha="center",
            va="center",
            transform=self.temp_cycle_axis.transAxes,
        )
        self.temp_cycle_canvas.draw()

    # button for reset data, will ask for confirmation
    def on_clear_data_pressed(self):
        if (self.state & RUN_STATE.RUNNING) or self.state == RUN_STATE.PAUSE:
            messagebox.showwarning("Run Active", "Stop the run before clearing data.")
            return

        if not self.test_data.empty:
            proceed = messagebox.askyesno(
                "Clear Data",
                "Clear displayed and stored measurement data? This does not erase exported Excel files.",
            )

            if not proceed:
                return

        self.reset_measurement_data()

    # resets the run, clears old data and returns everything to idle state
    def on_new_run_pressed(self):
        if (self.state & RUN_STATE.RUNNING) or self.state == RUN_STATE.PAUSE:
            messagebox.showwarning(
                "Run Active", "Stop the current run before starting a new run."
            )
            return

        self.pause_requested = False
        self.stop_requested = False
        self.state = RUN_STATE.IDLE

        self.reset_test_setup()
        self.reset_temperature_chart()
        self.reset_measurement_data()
        self.roll_id_strvar.set(DEFAULT_ROLL_ID)
        self.operator_strvar.set(DEFAULT_OPERATOR)
        self.traceability_confirmed = bool(DEFAULT_ROLL_ID and DEFAULT_OPERATOR)
        self.set_controls_idle()

    # name error checking
    def make_excel_name_safe(self, name: str):
        invalid_chars = ["\\", "/", "*", "[", "]", ":", "?"]

        safe_name = str(name)
        for char in invalid_chars:
            safe_name = safe_name.replace(char, "_")

        safe_name = safe_name.strip()

        if not safe_name:
            safe_name = "Sheet"

        return safe_name[:31]

    # makes the export file name
    def make_temperature_sheet_name(self, temp_c: float, existing_names: set[str]):
        base_name = f"T_{temp_c:.2f}C".replace("-", "neg_").replace(".", "_")
        sheet_name = self.make_excel_name_safe(base_name)

        if sheet_name not in existing_names:
            existing_names.add(sheet_name)
            return sheet_name

        counter = 2
        while True:
            suffix = f"_{counter}"
            candidate = self.make_excel_name_safe(
                sheet_name[: 31 - len(suffix)] + suffix
            )

            if candidate not in existing_names:
                existing_names.add(candidate)
                return candidate

            counter += 1

    # autosize columns to make data easier to read
    def autosize_excel_columns(self, worksheet, max_width=28):
        for column_cells in worksheet.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter

            for cell in column_cells:
                try:
                    value_length = len(str(cell.value)) if cell.value is not None else 0
                    max_length = max(max_length, value_length)
                except Exception:
                    pass
            worksheet.column_dimensions[column_letter].width = min(
                max_length + 2, max_width
            )

    # exporting function
    def export_results(self):

        if self.is_sequence_active():
            messagebox.showwarning(
                "Sequence Active",
                "Export is disabled while programming or running. Stop or finish the run before exporting.",
            )
            return

        if not self.ensure_traceability_metadata():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"HT-BDS_{timestamp}.xlsx"

        filepath = filedialog.asksaveasfilename(
            title="Export HT-BDS Results",
            initialdir=OUTPUT_FILEPATH,
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")],
        )

        if not filepath:
            return

        try:
            freq_col = "Freq. [Hz]"
            temp_col = f"Temp. [{CHAR_DEGC}]"
            probe_index_col = "Probe Index"
            cp_col = "Cp [F]"
            df_col = "Df [1]"
            esr_col = f"ESR [{CHAR_OHM}]"

            freq_plan = pd.DataFrame({"Frequency [Hz]": self.get_frequency_list()})
            temp_log = self.get_temperature_log()
            measurements = self.test_data.copy()
            roll_id, operator_name = self.get_traceability_values()

            if not measurements.empty:
                for col in [
                    probe_index_col,
                    freq_col,
                    temp_col,
                    cp_col,
                    df_col,
                    esr_col,
                ]:
                    if col in measurements.columns:
                        measurements[col] = pd.to_numeric(
                            measurements[col], errors="coerce"
                        )
                sort_columns = [temp_col, freq_col]
                if probe_index_col in measurements.columns:
                    sort_columns = [temp_col, probe_index_col, freq_col]
                measurements = measurements.sort_values(
                    by=sort_columns,
                    ignore_index=True,
                )
            # metadata
            metadata = pd.DataFrame(
                [
                    ["Export Time", datetime.now().isoformat(timespec="seconds")],
                    ["Output Path", filepath],
                    ["Roll ID", roll_id],
                    ["Operator", operator_name],
                    ["Start Temp [C]", self.start_temp.get()],
                    ["Step Temp 1 [C]", self.step_temp.get()],
                    ["Use Second Step", self.use_second_step.get()],
                    ["Step Change Temp [C]", self.step_change_temp.get()],
                    ["Step Temp 2 [C]", self.step2_temp.get()],
                    ["Max Temp [C]", self.max_temp.get()],
                    ["Dwell Time [min]", self.dwell_time.get()],
                    ["Heat Ramp [C/min]", self.heat_rate.get()],
                    [
                        "Selected Plot Frequency [Hz]",
                        self.get_selected_plot_frequency(),
                    ],
                    ["Measurement Rows", len(measurements)],
                    ["Temperature Log Rows", len(temp_log)],
                    ["Frequency Points Requested", len(freq_plan)],
                ],
                columns=["Field", "Value"],
            )

            if measurements.empty:
                summary = pd.DataFrame(
                    [
                        ["Status", "No measurement rows collected."],
                        ["Measurement Rows", 0],
                    ],
                    columns=["Metric", "Value"],
                )

                temperature_index = pd.DataFrame(
                    columns=[
                        "Measured Temp [C]",
                        "Sheet",
                        "Measurement Count",
                        "Min Frequency [Hz]",
                        "Max Frequency [Hz]",
                    ]
                )

                per_temp_sheets = []

            else:
                summary = pd.DataFrame(
                    [
                        ["Measurement Rows", len(measurements)],
                        [
                            "Unique Temperatures",
                            measurements[temp_col].dropna().nunique(),
                        ],
                        [
                            "Unique Frequencies",
                            measurements[freq_col].dropna().nunique(),
                        ],
                        ["Min Frequency [Hz]", measurements[freq_col].min()],
                        ["Max Frequency [Hz]", measurements[freq_col].max()],
                        ["Min Temperature [C]", measurements[temp_col].min()],
                        ["Max Temperature [C]", measurements[temp_col].max()],
                        ["Failed Cp Count", measurements[cp_col].isna().sum()],
                        ["Failed Df Count", measurements[df_col].isna().sum()],
                        ["Failed ESR Count", measurements[esr_col].isna().sum()],
                    ],
                    columns=["Metric", "Value"],
                )

                per_temp_sheets = []
                index_rows = []
                existing_sheet_names = {
                    "Metadata",
                    "Summary",
                    "Temperature Index",
                    "Temperature Plan",
                    "Frequency Plan",
                    "Measurements",
                    "Temperature Log",
                }

                # group by temperature
                measurements["_Export Temp Group [C]"] = measurements[temp_col].round(2)

                for temp_value, temp_df in measurements.groupby(
                    "_Export Temp Group [C]", dropna=True
                ):
                    temp_value = float(temp_value)
                    sheet_name = self.make_temperature_sheet_name(
                        temp_value, existing_sheet_names
                    )

                    temp_export_df = (
                        temp_df.drop(columns=["_Export Temp Group [C]"])
                        .sort_values(
                            by=[probe_index_col, freq_col]
                            if probe_index_col in temp_df.columns
                            else freq_col
                        )
                        .reset_index(drop=True)
                    )

                    per_temp_sheets.append((temp_value, sheet_name, temp_export_df))

                    index_rows.append(
                        {
                            "Measured Temp [C]": temp_value,
                            "Sheet": sheet_name,
                            "Measurement Count": len(temp_export_df),
                            "Min Frequency [Hz]": temp_export_df[freq_col].min(),
                            "Max Frequency [Hz]": temp_export_df[freq_col].max(),
                        }
                    )

                measurements = measurements.drop(columns=["_Export Temp Group [C]"])

                temperature_index = pd.DataFrame(index_rows).sort_values(
                    by="Measured Temp [C]",
                    ignore_index=True,
                )

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                metadata.to_excel(writer, sheet_name="Metadata", index=False)
                summary.to_excel(writer, sheet_name="Summary", index=False)
                temperature_index.to_excel(
                    writer, sheet_name="Temperature Index", index=False
                )
                self.temp_step_data.to_excel(
                    writer, sheet_name="Temperature Plan", index=False
                )
                freq_plan.to_excel(writer, sheet_name="Frequency Plan", index=False)
                measurements.to_excel(writer, sheet_name="Measurements", index=False)
                temp_log.to_excel(writer, sheet_name="Temperature Log", index=False)

                # writes each individual temperatures data into its own sheet
                for _, sheet_name, temp_export_df in per_temp_sheets:
                    temp_export_df.to_excel(writer, sheet_name=sheet_name, index=False)

                workbook = writer.book

                # add links to each temp sheet
                if "Temperature Index" in writer.sheets:
                    index_ws = writer.sheets["Temperature Index"]

                    for row_num in range(2, len(temperature_index) + 2):
                        sheet_name = index_ws.cell(row=row_num, column=2).value

                        if sheet_name:
                            cell = index_ws.cell(row=row_num, column=2)
                            cell.hyperlink = f"#'{sheet_name}'!A1"
                            cell.style = "Hyperlink"

                    index_ws.freeze_panes = "A2"
                    index_ws.auto_filter.ref = index_ws.dimensions

                # Add a return link on each temperature sheet.
                for _, sheet_name, _ in per_temp_sheets:
                    if sheet_name in writer.sheets:
                        ws = writer.sheets[sheet_name]
                        ws.freeze_panes = "A2"
                        ws.auto_filter.ref = ws.dimensions

                        ws["H1"] = "Back to Temperature Index"
                        ws["H1"].hyperlink = "#'Temperature Index'!A1"
                        ws["H1"].style = "Hyperlink"

                # keep headers visible
                for sheet_name in [
                    "Metadata",
                    "Summary",
                    "Temperature Index",
                    "Temperature Plan",
                    "Frequency Plan",
                    "Measurements",
                    "Temperature Log",
                ]:
                    if sheet_name in writer.sheets:
                        ws = writer.sheets[sheet_name]

                        if ws.max_row > 1:
                            ws.freeze_panes = "A2"
                            ws.auto_filter.ref = ws.dimensions  # filter

                # Autosize columns across all sheets.
                for ws in workbook.worksheets:
                    self.autosize_excel_columns(ws)

            messagebox.showinfo("Export Complete", f"Results exported to:\n{filepath}")

        except Exception as e:
            messagebox.showerror(
                "Export Failed",
                f"Could not export results:\n{type(e).__name__}: {e}",
            )

    # helper function to get run data from user inputs and return as RunConfig dataclass
    def get_run_data(self, *args):
        return RunConfig(
            device=self.active_device,
            start_temp=self.start_temp.get(),
            step_temp=self.step_temp.get(),
            max_temp=self.max_temp.get(),
            dwell_time=self.dwell_time.get(),
            heat_rate=self.heat_rate.get(),
            focus_freq=DEFAULT_FOCUS_FREQ_HZ,
            enable_multiprobe=self.enable_multiprobe.get(),
            probe_configs=tuple(self.get_probe_configs()),
            probe_settling_delay=self.get_probe_settling_delay(),
        )

    # get the full frequency list from the tables
    def get_frequency_list(self):
        combined = pd.concat(
            [self.freq_step_data, self.custom_freq_data],
            ignore_index=True,
        )

        if combined.empty or FREQ_STEP_COLUMNS[1] not in combined.columns:
            return [self.get_run_data().focus_freq]

        freqs = (
            combined[FREQ_STEP_COLUMNS[1]]
            .dropna()
            .astype(float)
            .drop_duplicates()
            .sort_values()
            .tolist()
        )

        if not freqs:
            return [self.get_run_data().focus_freq]

        return freqs

    # DEVICE BACKEND METHODS -----------------------------
    # return device type from list
    def get_device_by_type(self, device_type):
        for device in self.device_list:
            if isinstance(device, device_type):
                return device
        return None

    def log_oven_temperature(self, oven, start_time, step_num, target, mode="Running"):
        _, chamber_reply = self.device_msg(device=oven, query="CHAM?", hushed=True)
        _, user_reply = self.device_msg(device=oven, query="USER?", hushed=True)

        try:
            chamber_temp = float(chamber_reply)
        except (ValueError, TypeError):
            chamber_temp = np.nan

        try:
            user_temp = float(user_reply)
        except (ValueError, TypeError):
            user_temp = np.nan

        elapsed_time = time.time() - start_time
        self.append_temperature_log_row(
            [
                elapsed_time,
                step_num,
                mode,
                target,
                chamber_temp,
                user_temp,
            ]
        )
        return chamber_temp, user_temp

    # general function for sending commands
    def device_msg(
        self,
        query: str = "",
        device=None,
        hushed=False,
        read_after_write=False,
    ):
        if device is None:
            device = self.active_device
            if device is None:
                if not hushed:
                    print(f"Device not set! Cannot send: {query}!")
                return (-1, np.nan)

        command = (
            query if query else self.message_strvar.get()
        )  # use query if provided, otherwise use entry text

        code, reply = device.send(cmd=command, read_after_write=read_after_write)

        display_text = f"Length: {str(code)} -->\n{reply}"
        self.app_root.after(0, lambda: self.response_strvar.set(display_text))

        if not hushed:
            print(f"Command: '{command}' ({code})\n\tReturn: '{reply}'")

        return (code, reply)

    def show_error_threadsafe(self, title: str, message: str):
        self.app_root.after(0, lambda: messagebox.showerror(title, message))

    # TODO: implement for robustness
    def checked_device_msg(
        self,
        device,
        query: str,
        context: str = "Device Command",
        read_after_write=False,
    ):
        code, reply = self.device_msg(
            device=device,
            query=query,
            hushed=True,
            read_after_write=read_after_write,
        )

        if code < 0:
            raise RuntimeError(f"{context} failed: {query} -> {reply}")

        return code, reply

    # function to program the device with the generated temperature plan
    def program_device(self, cfg: RunConfig):
        self.state = RUN_STATE.PROGRAMMING
        oven = self.get_device_by_type(devices.SunSystemsOven_EC1A)

        print("Programming ...")
        if oven is None:
            print("... Programming failed! No device attached!")
            self.show_error_threadsafe("Error!", "No device connected!")
            self.state = RUN_STATE.IDLE
            return
        if not oven:
            print("... Programming failed! Active device is not a SunSystemsOven_EC1A!")
            self.show_error_threadsafe("Error!", "Device is not a compatible oven!")
            self.state = RUN_STATE.IDLE
            return

        if self.temp_step_data.empty:
            print("... Programming failed! Temperature plan is empty!")
            self.state = RUN_STATE.IDLE
            return

        self.device_msg(device=oven, query="ON")
        self.device_msg(device=oven, query="STOP")
        self.device_msg(device=oven, query="DELP#0")

        self.device_msg(device=oven, query="STORE#0")

        self.device_msg(device=oven, query="HON")
        self.device_msg(device=oven, query="SINT=NNNNNNYNNY0")  # interrupt configuration

        for _, row in self.temp_step_data.iterrows():
            step_num = int(row[TEMP_PLAN_COLUMNS[0]])
            target = float(row[TEMP_PLAN_COLUMNS[1]])
            dwell = float(row[TEMP_PLAN_COLUMNS[2]])

            self.device_msg(device=oven, query=f"RATE={cfg.heat_rate:.2f}")
            self.device_msg(device=oven, query=f"SET={target:.1f}")
            self.device_msg(device=oven, query=f"WAIT={minutes_to_wait(dwell)}")

            self.device_msg(device=oven, query=f"BKPNT {step_num}")

        self.device_msg(device=oven, query="HOFF")
        self.device_msg(device=oven, query="COFF")
        self.device_msg(device=oven, query="END")

        print("... Programming successful!")
        self.state = RUN_STATE.READY

    def wait_for_user_temp_stable(
        self,
        oven,
        start_time,
        step_num,
        target,
        tolerance=USER_TEMP_TOLERANCE_C,
        stable_samples_required=USER_TEMP_STABLE_SAMPLES,
        poll_seconds=USER_TEMP_POLL_SECONDS,
        max_extra_wait_seconds=USER_TEMP_MAX_EXTRA_WAIT_SECONDS,
    ):
        print(
            f"Step {step_num}: waiting for USER probe to reach "
            f"{target:.2f} {CHAR_DEGC} ± {tolerance:.2f} {CHAR_DEGC}"
        )

        stable_count = 0
        wait_start = time.time()
        last_chamber_temp = np.nan
        last_user_temp = np.nan

        while not self.stop_requested:
            chamber_temp, user_temp = self.log_oven_temperature(
                oven, start_time, step_num, target, mode="User temp stabilizing"
            )

            last_chamber_temp = chamber_temp
            last_user_temp = user_temp

            if not np.isnan(user_temp) and abs(user_temp - target) <= tolerance:
                stable_count += 1
            else:
                stable_count = 0

            if stable_count >= stable_samples_required:
                print(
                    f"Step {step_num} user probe stabilized at"
                    f"{user_temp:.2f} {CHAR_DEGC}"
                )
                return chamber_temp, user_temp, True
            if time.time() - wait_start > max_extra_wait_seconds:
                print(
                    f"Step {step_num}: user probe did not stabilize within {max_extra_wait_seconds} seconds. Continuing with last reading"
                )
                return last_chamber_temp, last_user_temp, False

            for _ in range(int(poll_seconds * 2)):
                if self.stop_requested:
                    break
                time.sleep(0.5)

        return last_chamber_temp, last_user_temp, False

    # helper function to parse LCR meter reply and extract relevant measurement values, with error handling for unexpected formats
    def parse_lcr_reply(self, reply: str):
        parts = str(reply).strip().split(",")
        values = []
        for part in parts:
            try:
                value = float(part.strip())
                if abs(value) >= KEYSIGHT_OVERRANGE_THRESHOLD:
                    value = np.nan
                values.append(value)
            except ValueError:
                pass

        if len(values) >= 2:
            return values[0], values[1]

        return np.nan, np.nan

    # measure lcr at a specific frequency
    def measure_lcr_at_freq(self, lcr, freq_hz: float):
        def checked_send(command):
            code, reply = self.device_msg(device=lcr, query=command, hushed=True)
            if code < 0:
                raise RuntimeError(f"LCR command failed: {command} -> {reply}")
            return reply

        for command in [
            "*CLS",
            ":FUNC:IMP:TYPE CPD",
            f":FREQ:CW {freq_hz}",
            ":FUNC:IMP:RANG:AUTO ON",
            ":TRIG:SOUR BUS",
            ":INIT:CONT OFF",
            ":INIT",
            "*TRG",
            "*WAI",
        ]:
            checked_send(command)
        checked_send("*OPC?")

        cpd_reply = checked_send(":FETC:IMP:FORM?")
        cp, df = self.parse_lcr_reply(cpd_reply)

        for command in [
            ":FUNC:IMP:TYPE CSRS",
            f":FREQ:CW {freq_hz}",
            ":INIT",
            "*TRG",
            "*WAI",
        ]:
            checked_send(command)
        checked_send("*OPC?")

        csrs_reply = checked_send(":FETC:IMP:FORM?")
        _, esr = self.parse_lcr_reply(csrs_reply)

        return cp, df, esr

    @staticmethod
    def probe_pattern_to_bits(pattern: int):
        if not isinstance(pattern, int) or isinstance(pattern, bool):
            raise ValueError("Probe switch pattern must be an integer.")
        if pattern < 0 or pattern > 0xFF:
            raise ValueError("Probe switch pattern must be between 0 and 255.")
        return [bool(pattern & (1 << bit_index)) for bit_index in range(8)]

    def get_daq_line_spec(self):
        daq = self.get_device_by_type(devices.NIDAQ_USB6501)
        if daq is not None and getattr(daq, "address", None):
            return f"{daq.address}/port0/line0:7"
        return self.daq_line_spec

    def initialize_daq_switching(self):
        if self.daq_task is not None:
            return self.daq_task
        if nidaqmx is None or LineGrouping is None:
            detail = (
                f" Import error: {NIDAQMX_IMPORT_ERROR}"
                if NIDAQMX_IMPORT_ERROR is not None
                else ""
            )
            raise RuntimeError(
                "NI-DAQmx Python support is unavailable. Install NI-DAQmx and "
                f"the nidaqmx package before enabling multiprobe switching.{detail}"
            )

        task = None
        line_spec = self.get_daq_line_spec()
        try:
            task = nidaqmx.Task()
            task.do_channels.add_do_chan(
                line_spec,
                line_grouping=LineGrouping.CHAN_PER_LINE,
            )
            self.daq_task = task
            self.write_probe_pattern(
                PROBE_ALL_OFF_PATTERN, reason="DAQ initialization"
            )
            print(f"USB-6501 output task initialized on {line_spec}")
            return self.daq_task
        except Exception as e:
            self.daq_task = None
            if task is not None:
                try:
                    task.close()
                except Exception:
                    pass
            raise RuntimeError(
                f"Could not initialize USB-6501 output task on "
                f"{line_spec}: {type(e).__name__}: {e}"
            ) from e

    def write_probe_pattern(self, pattern: int, reason: str = ""):
        bits = self.probe_pattern_to_bits(pattern)
        if self.daq_task is None:
            self.initialize_daq_switching()

        reason_text = f" ({reason})" if reason else ""
        try:
            self.daq_task.write(bits, auto_start=True)
        except Exception as e:
            raise RuntimeError(
                f"USB-6501 write failed for pattern {pattern:08b} "
                f"(decimal {pattern}){reason_text}: {type(e).__name__}: {e}"
            ) from e

        print(
            f"USB-6501 write{reason_text}: pattern {pattern:08b}, "
            f"decimal {pattern}, bits P0.0-P0.7={bits}"
        )
        return True

    def switch_all_probes_off(self, initialize_if_needed=False):
        self.active_probe_index = None

        if self.daq_task is None:
            if not initialize_if_needed:
                return True
            try:
                self.initialize_daq_switching()
            except Exception as e:
                print(f"Could not switch all probes off: {type(e).__name__}: {e}")
                return False

        try:
            self.write_probe_pattern(
                PROBE_ALL_OFF_PATTERN, reason="all probes off"
            )
            return True
        except Exception as e:
            print(f"Could not switch all probes off: {type(e).__name__}: {e}")
            return False

    def close_daq_switching(self):
        task = self.daq_task
        if task is None:
            self.active_probe_index = None
            return

        self.switch_all_probes_off()
        try:
            task.close()
        finally:
            self.daq_task = None
            self.active_probe_index = None

    def switch_to_probe(self, probe_index: int, probe_configs=None):
        configs = tuple(probe_configs) if probe_configs is not None else tuple(
            self.get_probe_configs()
        )
        labels_by_index = {config[0]: config[1] for config in configs}
        if probe_index not in labels_by_index:
            raise ValueError(f"Invalid probe index: {probe_index}")
        if probe_index not in PROBE_SWITCH_PATTERNS:
            raise ValueError(
                f"Probe {probe_index} does not have a mapped USB-6501 pattern."
            )

        pattern = PROBE_SWITCH_PATTERNS[probe_index]
        self.initialize_daq_switching()
        self.write_probe_pattern(
            PROBE_ALL_OFF_PATTERN,
            reason=f"break before selecting probe {probe_index}",
        )
        self.active_probe_index = None
        time.sleep(PROBE_BREAK_BEFORE_MAKE_SECONDS)
        self.write_probe_pattern(pattern, reason=f"select probe {probe_index}")
        self.active_probe_index = probe_index
        print(
            f"Selected probe {probe_index} ({labels_by_index[probe_index]}): "
            f"pattern {pattern:08b}, decimal {pattern}"
        )
        return True

    def is_sequence_active(self):
        return bool(self.state & RUN_STATE.RUNNING) or self.state in (
            RUN_STATE.PROGRAMMING,
            RUN_STATE.PAUSE,
        )

    def set_widgets_enabled(self, widgets, enabled: bool):
        state_value = "normal" if enabled else "disabled"
        for widget in widgets:
            try:
                widget.config(state=state_value)
            except Exception:
                pass

    def set_setup_controls_enabled(self, enabled: bool):
        self.set_widgets_enabled(self.temperature_setup_controls, enabled)
        self.set_widgets_enabled(self.frequency_setup_controls, enabled)
        self.set_widgets_enabled(self.probe_setup_controls, enabled)
        self.update_second_step_controls(setup_enabled=enabled)
        if self.setup_notebook is not None:
            for index in (0, 1, 3):
                try:
                    self.setup_notebook.tab(
                        index, state="normal" if enabled else "disabled"
                    )
                except Exception:
                    pass

    def set_manual_command_enabled(self, enabled: bool):
        self.set_widgets_enabled(self.manual_command_controls, enabled)

    def validate_frequency_list(self, freqs):
        if not freqs:
            raise ValueError("Frequency list is empty.")
        for freq in freqs:
            try:
                value = float(freq)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid frequency value: {freq!r}")
            if not np.isfinite(value):
                raise ValueError("Frequency list contains a non-finite value.")
            if value < devices.LCR_MIN_FREQ or value > devices.LCR_MAX_FREQ:
                raise ValueError(
                    f"Frequency {value:g} Hz is outside the LCR range "
                    f"{devices.LCR_MIN_FREQ:g} to {devices.LCR_MAX_FREQ:g} Hz."
                )

    def frequency_plan_is_empty(self):
        return self.freq_step_data.empty and self.custom_freq_data.empty

    # state controls
    def set_controls_idle(self):
        self.program_button.config(state="normal", text="Program")
        self.run_button.config(state="disabled", text="Run")
        self.pause_button.config(state="disabled", text="Pause")
        self.stop_button.config(state="disabled", text="Stop")
        self.set_setup_controls_enabled(True)
        self.set_manual_command_enabled(True)

        if hasattr(self, "new_run_button"):
            self.new_run_button.config(state="normal")
            self.clear_data_button.config(state="normal")
            self.export_button.config(state="normal")

    def set_controls_programmed(self):
        self.program_button.config(state="normal", text="Program")
        self.run_button.config(state="normal", text="Run")
        self.pause_button.config(state="disabled", text="Pause")
        self.stop_button.config(state="normal", text="Stop")
        self.set_setup_controls_enabled(True)
        self.set_manual_command_enabled(True)

        if hasattr(self, "new_run_button"):
            self.new_run_button.config(state="normal")
            self.clear_data_button.config(state="normal")
            self.export_button.config(state="normal")

    def set_controls_running(self):
        self.program_button.config(state="disabled", text="Program")
        self.run_button.config(state="disabled", text="Running")
        self.pause_button.config(state="normal", text="Pause")
        self.stop_button.config(state="normal", text="Stop")
        self.set_setup_controls_enabled(False)
        self.set_manual_command_enabled(False)

        if hasattr(self, "new_run_button"):
            self.new_run_button.config(state="disabled")
            self.clear_data_button.config(state="disabled")
            self.export_button.config(state="disabled")

    def set_controls_programming(self):
        self.program_button.config(state="disabled", text="Programming")
        self.run_button.config(state="disabled", text="Run")
        self.pause_button.config(state="disabled", text="Pause")
        self.stop_button.config(state="disabled", text="Stop")
        self.set_setup_controls_enabled(False)
        self.set_manual_command_enabled(False)

        if hasattr(self, "new_run_button"):
            self.new_run_button.config(state="disabled")
            self.clear_data_button.config(state="disabled")
            self.export_button.config(state="disabled")

    def on_program_pressed(self):
        if self.is_sequence_active():
            messagebox.showwarning(
                "Sequence Active", "Cannot program while a sequence is active."
            )
            return
        if not self.generate_temperature_plan():
            return
        if self.temp_step_data.empty:
            return
        self.reset_temperature_log_and_chart()
        cfg = self.get_run_data()
        self.state = RUN_STATE.PROGRAMMING
        self.set_controls_programming()

        def worker():
            self.program_device(cfg)

            def finish_programming():
                if self.state == RUN_STATE.READY:
                    self.set_controls_programmed()
                else:
                    self.set_controls_idle()

            self.app_root.after(0, finish_programming)

        self.program_thread = threading.Thread(target=worker, daemon=True)
        self.program_thread.start()

    def on_run_pressed(self):
        if self.run_thread is not None and self.run_thread.is_alive():
            messagebox.showwarning("Run Active", "A run is already active.")
            return
        if not self.ensure_traceability_metadata():
            return
        try:
            self.validate_probe_settings()
        except ValueError as e:
            messagebox.showerror("Invalid Probe Settings", str(e))
            return
        self.sync_probe_table(show_errors=False)
        cfg = self.get_run_data()
        freqs = self.get_frequency_list()
        try:
            self.validate_frequency_list(freqs)
        except ValueError as e:
            messagebox.showerror("Invalid Frequency List", str(e))
            return
        if self.frequency_plan_is_empty() and freqs == [DEFAULT_FOCUS_FREQ_HZ]:
            if not messagebox.askyesno(
                "No Frequency Plan",
                f"No frequency plan is selected. Continue with only {DEFAULT_FOCUS_FREQ_HZ:g} Hz?",
            ):
                return
        if cfg.max_temp >= SAFETY_CONFIRM_TEMP_C:
            confirmed = messagebox.askyesno(
                "High Temperature Confirmation",
                f"This run reaches {cfg.max_temp:g} {CHAR_DEGC}.\n\nConfirm the sample, fixture, chamber, and safety conditions are ready.",
            )
            if not confirmed:
                return
        self.pause_requested = False
        self.stop_requested = False
        self.set_controls_running()
        frozen_freqs = tuple(freqs)

        self.run_thread = threading.Thread(
            target=lambda: self.run(cfg, frozen_freqs),
            daemon=True,
        )
        self.run_thread.start()

    def on_pause_pressed(self):
        oven = self.get_device_by_type(devices.SunSystemsOven_EC1A)

        if oven is None:
            print("Pause failed: oven not connected")
            return

        if not self.pause_requested:
            self.pause_requested = True
            self.state = RUN_STATE.PAUSE
            self.pause_button.config(text="Resume")
            self.device_msg(device=oven, query="BKPNT")
        else:
            self.pause_requested = False
            self.state = RUN_STATE.TEMP_CHANGING
            self.pause_button.config(text="Pause")
            self.device_msg(device=oven, query="BKPNTC")

    def on_stop_pressed(self):
        self.stop_requested = True
        self.pause_requested = False
        self.state = RUN_STATE.DONE
        self.stop_button.config(text="Stopping...", state="disabled")
        self.pause_button.config(state="disabled")
        self.run_button.config(state="disabled")

        oven = self.get_device_by_type(devices.SunSystemsOven_EC1A)

        if oven is not None:
            self.device_msg(device=oven, query="STOP")
            self.device_msg(device=oven, query="COFF")
            self.device_msg(device=oven, query="HOFF")

        self.switch_all_probes_off()

        if self.run_thread is None or not self.run_thread.is_alive():
            self.set_controls_idle()

    def wait_for_oven_breakpoint(
        self, oven, start_time, step_num, target, max_wait_seconds
    ):
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            if self.stop_requested:
                return False
            while self.pause_requested and not self.stop_requested:
                time.sleep(0.5)
            chamber_temp, user_temp = self.log_oven_temperature(
                oven, start_time, step_num, target, mode="Temp Changing"
            )
            try:
                chunk = max(
                    1, min(OVEN_WAIT_CHUNK_SECONDS, int(deadline - time.time()))
                )
                oven.wait_interrupt(chunk)
                return True
            except Exception:
                print(f"Step {step_num}: no SRQ yet; continuing to wait...")
            for _ in range(10):
                if self.stop_requested:
                    return False
                time.sleep(0.5)
        raise TimeoutError(f"Breakpoint wait timed out at step {step_num}.")

    # function to execute the programmed temperature plan and perform measurements at each step, with error handling and timeouts to ensure safe operation
    def run(self, cfg: RunConfig, frequency_list=None):
        self.state = RUN_STATE.TEMP_CHANGING
        # devices
        oven = self.get_device_by_type(devices.SunSystemsOven_EC1A)
        lcr = self.get_device_by_type(devices.KeysightLCR_E4980A)
        if cfg.enable_multiprobe:
            self.switch_all_probes_off(initialize_if_needed=True)
        else:
            self.switch_all_probes_off(initialize_if_needed=False)

        # check devices
        if all(device is None for device in self.device_list):
            print("Run failed: No devices connected")
            self.show_error_threadsafe("Error!", "No devices are connected!")
            self.state = RUN_STATE.IDLE
            self.app_root.after(0, self.set_controls_idle)
            return
        if lcr is None:
            print("Run failed: LCR is not connected")
            self.show_error_threadsafe("Error!", "LCR is not connected!")
            self.state = RUN_STATE.IDLE
            self.app_root.after(0, self.set_controls_idle)
            return
        if oven is None:
            print("Run Failed: No oven connected")
            self.show_error_threadsafe("Error!", "No oven connected!")
            self.state = RUN_STATE.IDLE
            self.app_root.after(0, self.set_controls_idle)
            return
        if not isinstance(oven, devices.SunSystemsOven_EC1A):
            print("Run Failed: Active device is not a SunSystemsOven_EC1A")
            self.state = RUN_STATE.IDLE
            self.app_root.after(0, self.set_controls_idle)
            return
        if self.temp_step_data.empty:
            print("Run Failed: Temperature plan is empty")
            self.show_error_threadsafe("Error!", "No temperature plan!")
            self.state = RUN_STATE.IDLE
            self.app_root.after(0, self.set_controls_idle)
            return

        freqs = (
            list(frequency_list)
            if frequency_list is not None
            else self.get_frequency_list()
        )
        start_time = time.time()

        try:
            self.device_msg(device=oven, query="RUN#0")

            for _, row in self.temp_step_data.iterrows():

                if self.stop_requested:
                    print("Run stopped by user.")
                    break

                step_num = int(row[TEMP_PLAN_COLUMNS[0]])
                target = float(row[TEMP_PLAN_COLUMNS[1]])
                dwell = float(row[TEMP_PLAN_COLUMNS[2]])
                ramp_time = float(row[TEMP_PLAN_COLUMNS[3]])

                print(
                    f"Running Step {step_num}: Target={target}, Dwell={dwell} min, Ramp Time={ramp_time} min"
                )

                self.state = RUN_STATE.TEMP_CHANGING

                max_wait_seconds = int(
                    (ramp_time + dwell + OVEN_BREAKPOINT_TIMEOUT_BUFFER_MINUTES) * 60
                )  # add buffer time to ensure step completion before timeout

                breakpoint_reached = self.wait_for_oven_breakpoint(
                    oven, start_time, step_num, target, max_wait_seconds
                )
                if not breakpoint_reached:
                    print("Stop requested while waiting.")
                    break

                if self.stop_requested:
                    print(
                        "Stop requested before user temperature stabilization can be reached."
                    )
                    self.state = RUN_STATE.DONE
                    self.app_root.after(0, self.set_controls_idle)
                    return

                self.state = RUN_STATE.TEMP_CHANGING
                chamber_temp, user_temp, user_stable = self.wait_for_user_temp_stable(
                    oven,
                    start_time,
                    step_num,
                    target,
                )

                if self.stop_requested:
                    print(
                        "Stop requested before user temperature stabilization can be reached."
                    )
                    self.state = RUN_STATE.DONE
                    self.app_root.after(0, self.set_controls_idle)
                    return

                elapsed_time = time.time() - start_time

                self.append_temperature_log_row(
                    [
                        elapsed_time,
                        step_num,
                        "Measurement Start",
                        target,
                        chamber_temp,
                        user_temp,
                    ]
                )

                print(
                    f"Step {step_num} ready for measurememt. "
                    f"Target {target}, Chamber={chamber_temp}, User={user_temp}, "
                    f"User Stable = {user_stable}"
                )

                if self.stop_requested:
                    break
                for probe_index, probe_label, probe_color in cfg.probe_configs:
                    if self.stop_requested:
                        break
                    while self.pause_requested and not self.stop_requested:
                        time.sleep(0.5)
                    if self.stop_requested:
                        break

                    if cfg.enable_multiprobe:
                        self.state = RUN_STATE.PROBE_SWITCHING
                        self.switch_to_probe(probe_index, cfg.probe_configs)
                        settle_until = time.time() + cfg.probe_settling_delay
                        while time.time() < settle_until and not self.stop_requested:
                            time.sleep(min(0.5, settle_until - time.time()))

                    self.state = RUN_STATE.LCR_MEASURING
                    for freq in freqs:
                        if self.stop_requested:
                            print("Stop requested during LCR sweep.")
                            break
                        while self.pause_requested and not self.stop_requested:
                            time.sleep(0.5)
                        if self.stop_requested:
                            print("Stop requested before LCR measurement.")
                            break
                        try:
                            cp, df, esr = self.measure_lcr_at_freq(lcr, freq)
                        except Exception as e:
                            print(
                                f"LCR measurement failed at step {step_num}, "
                                f"probe {probe_index}, frequency {freq:g} Hz: "
                                f"{type(e).__name__}: {e}"
                            )
                            cp, df, esr = np.nan, np.nan, np.nan
                        self.test_data.loc[len(self.test_data)] = [
                            probe_index,
                            probe_label,
                            probe_color,
                            user_temp,
                            freq,
                            cp,
                            df,
                            esr,
                        ]

                self.app_root.after(0, self.sync_measurement_data)

                if self.stop_requested:
                    print("Run stopped during LCR sweep. Not continuing oven program.")
                    self.state = RUN_STATE.DONE
                    self.app_root.after(0, self.set_controls_idle)
                    return

                self.device_msg(device=oven, query="BKPNTC")
            self.switch_all_probes_off()
            print("Run complete!")
            self.state = RUN_STATE.DONE
            self.app_root.after(0, self.set_controls_idle)

        except Exception as e:
            print(f"Run Failed: {e}")
            self.pause_requested = False
            self.stop_requested = False
            self.switch_all_probes_off()
            if oven is not None:
                self.device_msg(device=oven, query="STOP", hushed=True)
                self.device_msg(device=oven, query="COFF", hushed=True)
                self.device_msg(device=oven, query="HOFF", hushed=True)
            self.state = RUN_STATE.IDLE
            self.show_error_threadsafe("Run Error", f"{type(e).__name__}: {e}")
            self.app_root.after(0, self.set_controls_idle)

    def stop(self):
        self.state = RUN_STATE.DONE
        pass


app: App
if __name__ == "__main__":
    print("App started...")
    app = App()
    print("...App ended!")
