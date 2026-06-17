from __future__ import annotations

try:
    import pyvisa  # PyVISA backend for communicating with devices
except Exception as e:
    pyvisa = None
    print(f"PyVISA unavailable; hardware communication disabled: {e}")
# from pyvisa.errors import (
#    # VisaIOError,
# )  # PyVISA.Constants.StatusCode for discerning error types
try:
    from pyvisa.constants import (
        # StatusCode,
        EventType,
        EventMechanism,
    )  # PyVISA.Constants.StatusCode for discerning error/return codes
    from pyvisa.resources import (
        Resource,
        USBInstrument,
        GPIBInstrument,
    )  # PyVISA.Resources.USBInstrument for type-casting the correct device communication format under VISA
except Exception:
    EventType = EventMechanism = None
    Resource = USBInstrument = GPIBInstrument = object

try:
    import nidaqmx.system as nidaqsys
except Exception as e:
    nidaqsys = None
    print(f"NI-DAQmx unavailable; DAQ communication disabled: {e}")

# RESOURCES ==========================================
VISA_RM = None
NIDAQ_SYSTEM = None


def get_visa_rm():
    global VISA_RM
    if pyvisa is None:
        raise RuntimeError("PyVISA is not available.")
    if VISA_RM is None:
        VISA_RM = pyvisa.highlevel.ResourceManager()
    return VISA_RM


def get_nidaq_system():
    global NIDAQ_SYSTEM
    if nidaqsys is None:
        raise RuntimeError("NI-DAQmx is not available.")
    if NIDAQ_SYSTEM is None:
        NIDAQ_SYSTEM = nidaqsys.System.local()
    return NIDAQ_SYSTEM


def close_resource_manager():
    global VISA_RM
    if VISA_RM is not None:
        try:
            VISA_RM.close()
        finally:
            VISA_RM = None


# STARTUP DEBUG ======================================
STARTUP = False
if STARTUP:
    print("Seen devices ...")
    for key, value in get_visa_rm().list_resources_info().items():
        print(key, value)
    print("Talking devices ...")
    for val in get_visa_rm().list_resources():
        print(val)
    for device in get_nidaq_system().devices:
        print(device)
    print("... End of devices.")

# CONSTANTS ==========================================
LCR_MIN_FREQ = 20.0  # Hz, device hardware constant
LCR_MAX_FREQ = 300e3  # Hz, device hardware constant


# VISA SEND HELPER METHOD ================================
def send(dev, cmd: str = "", read_after_write: bool = False):
    cmd = cmd.strip()

    # empty
    if not cmd:
        return (-1, "No command entered.")

    try:
        # if query, send query and return response
        if cmd.endswith("?"):
            reply = dev.query(cmd).strip()
            return (len(cmd), reply)

        # normal command
        write_len = dev.write(cmd)

        # does not have ? but response is expected, so read after write
        if read_after_write:
            reply = dev.read().strip()
            return (write_len, reply)

        return (write_len, "N/A")

    except Exception as e:
        return (-1, f"Error: {type(e).__name__}: {e}")


# BASE DEVICE CLASS =======================================================
class Device:
    name: str
    address: str
    device: Resource | nidaqsys.Device

    def send(
        self, cmd: str = "", read_after_write: bool = False
    ) -> tuple[int, str]: ...
    def wait_interrupt(self, max_time: int): ...

    def close(self):
        dev = getattr(self, "device", None)
        if dev is not None and hasattr(dev, "close"):
            dev.close()

    # def receive(self) -> str: ...
    # def parse(self, msg:str) -> str: ...


# LCR ================================
class KeysightLCR_E4980A(Device):
    min_freq = LCR_MIN_FREQ
    max_freq = LCR_MAX_FREQ
    name = "Keysight LCR Meter, #E4980A"
    address = "USB0::0x2A8D::0x2F01::MY54412453::INSTR"

    def __init__(self):
        self.device: USBInstrument = get_visa_rm().open_resource(self.address, resource_pyclass=USBInstrument)  # type: ignore
        self.device.timeout = 15e3  # ms
        self.device.read_termination = self.device.write_termination = "\n"

    def send(self, cmd: str = "", read_after_write: bool = False):
        return send(self.device, cmd, read_after_write=read_after_write)


# Oven =================================
class SunSystemsOven_EC1A(Device):
    name = "Sun Systems Environmental Chamber, #EC1A"
    address = "GPIB0::6::INSTR"

    def __init__(self):
        self.device: GPIBInstrument = get_visa_rm().open_resource(self.address, resource_pyclass=GPIBInstrument)  # type: ignore
        self.device.read_termination = self.device.write_termination = "\n"
        if EventType is not None and EventMechanism is not None:
            try:
                self.device.enable_event(EventType.trig, EventMechanism.queue)
            except Exception as e:
                print(
                    f"Warning: could not enable SRQ event on oven ({e})"
                    "Oven may still be usable, but breakpoint waiting should be validated."
                )

    def send(self, cmd: str = "", read_after_write: bool = False):
        return send(self.device, cmd, read_after_write=read_after_write)

    def wait_interrupt(self, max_time: int | None):
        if max_time is None:
            print("Max Wait: Inf [s]")
            self.device.wait_for_srq(None)  # type: ignore
        else:
            print(f"Max Wait: {max_time} [s]")
            self.device.wait_for_srq(max_time * 1000)
        # response = self.device.wait_on_event(EventType.service_request, timeout=max_time*1000, capture_timeout=True)
        # print(f"Interrupt Received: {response}")
        # Read status byte to clear SRQ
        # stb = self.device.read_stb()
        # print(f"Status Byte: {stb}")
        # return (stb, response.ret, response.timed_out)


# NIDAQ ============================
class NIDAQ_USB6501(Device):
    name = "National Instruments DAQ, #USB-6501"
    address = "Auto"

    def __init__(self):
        if nidaqsys is None:
            raise RuntimeError("NI-DAQmx is not available.")

        system = get_nidaq_system()

        for dev in system.devices:
            product_type = getattr(dev, "product_type", "")
            if "USB-6501" in product_type:
                self.device = dev
                self.address = dev.name
                print(f"Found NI USB-6501 as {dev.name}")
                return

        available = [f"{dev.name} ({dev.product_type})" for dev in system.devices]
        raise RuntimeError(f"NI USB-6501 not found. Available devices: {available}")

    def send(self, cmd: str = "", read_after_write: bool = False):
        return (-1, "DAQ doesn't support text command.")

    def wait_interrupt(self, max_time: int | None):
        return None


# DEVICE REGISTRY =======================
DEVICE_TYPE_LIST: list[type[Device]] = [
    SunSystemsOven_EC1A,
    KeysightLCR_E4980A,
    NIDAQ_USB6501,
]
