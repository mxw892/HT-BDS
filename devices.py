import pyvisa  # PyVISA backend for communicating with devices
# from pyvisa.errors import (
#    # VisaIOError,
# )  # PyVISA.Constants.StatusCode for discerning error types
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

import nidaqmx.system as nidaqsys

# RESOURCES ==========================================
VISA_RM = pyvisa.highlevel.ResourceManager()
NIDAQ_SYSTEM = nidaqsys.System.local()

# STARTUP DEBUG ======================================
STARTUP = True
if STARTUP:
    print("Seen devices ...")
    for key, value in VISA_RM.list_resources_info().items():
        print(key, value)
    print("Talking devices ...")
    for val in VISA_RM.list_resources():
        print(val)
    for device in NIDAQ_SYSTEM.devices:
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

    except pyvisa.errors.VisaIOError as e:
        return (-1, f"VISA error: {e}")

    except Exception as e:
        return (-1, f"Error: {type(e).__name__}: {e}")


# BASE DEVICE CLASS =======================================================
class Device:
    name: str
    address: str
    device: Resource | nidaqsys.Device

    def send(self, cmd: str = "", read_after_write: bool = False) -> tuple[int, str]: ...
    def wait_interrupt(self, max_time: int): ...

    # def receive(self) -> str: ...
    # def parse(self, msg:str) -> str: ...


# LCR ================================
class KeysightLCR_E4980A(Device):
    min_freq = LCR_MIN_FREQ
    max_freq = LCR_MAX_FREQ
    name = "Keysight LCR Meter, #E4980A"
    address = "USB0::0x2A8D::0x2F01::MY54412453::INSTR"

    def __init__(self):
        self.device: USBInstrument = VISA_RM.open_resource(self.address, resource_pyclass=USBInstrument)  # type: ignore
        self.device.timeout = 15e3  # ms
        self.device.read_termination = self.device.write_termination = "\n"

    def send(self, cmd: str = "", read_after_write: bool = False):
        return send(self.device, cmd, read_after_write=read_after_write)


# Oven =================================
class SunSystemsOven_EC1A(Device):
    name = "Sun Systems Environmental Chamber, #EC1A"
    address = "GPIB0::6::INSTR"

    def __init__(self):
        self.device: GPIBInstrument = VISA_RM.open_resource(self.address, resource_pyclass=GPIBInstrument)  # type: ignore
        self.device.read_termination = self.device.write_termination = "\n"
        self.device.enable_event(EventType.trig, EventMechanism.queue)

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
    address = "Dev2"

    def __init__(self):
        # self.device = VISA_RM.open_resource(self.address, resource_pyclass=USBInstrument)
        self.device = nidaqsys.Device("Dev2")

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
