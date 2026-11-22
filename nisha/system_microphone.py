"""Read the Windows default capture endpoint without changing audio settings."""

import os


def system_default_microphone():
    if os.name != "nt":
        import sounddevice as sd

        device = sd.query_devices(kind="input")
        return str(device["index"]), device["name"]

    import ctypes as ct
    import winreg
    from uuid import UUID

    class GUID(ct.Structure):
        _fields_ = [("data", ct.c_ubyte * 16)]

        def __init__(self, value):
            super().__init__((ct.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le))

    def method(pointer, slot, result, *arguments):
        table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
        return ct.WINFUNCTYPE(result, ct.c_void_p, *arguments)(table[slot])

    ole = ct.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ct.c_void_p, ct.c_ulong]
    ole.CoInitializeEx.restype = ct.c_long
    ole.CoCreateInstance.argtypes = [
        ct.POINTER(GUID),
        ct.c_void_p,
        ct.c_ulong,
        ct.POINTER(GUID),
        ct.POINTER(ct.c_void_p),
    ]
    ole.CoCreateInstance.restype = ct.c_long
    ole.CoTaskMemFree.argtypes = [ct.c_void_p]
    ole.CoUninitialize.argtypes = []
    enumerator, device, identity = ct.c_void_p(), ct.c_void_p(), ct.c_void_p()
    initialized = False
    try:
        result = ole.CoInitializeEx(None, 0)
        initialized = result in {0, 1}
        if result < 0 and result != -2147417850:  # RPC_E_CHANGED_MODE: already initialized.
            raise OSError("Cannot read the Windows default microphone.")
        result = ole.CoCreateInstance(
            ct.byref(GUID("bcde0395-e52f-467c-8e3d-c4579291692e")),
            None,
            1,
            ct.byref(GUID("a95664d2-9614-4f35-a746-de8db63617e6")),
            ct.byref(enumerator),
        )
        if result < 0:
            raise OSError("Cannot access the Windows audio device enumerator.")
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eCapture, eConsole).
        result = method(enumerator, 4, ct.c_long, ct.c_int, ct.c_int, ct.POINTER(ct.c_void_p))(
            enumerator, 1, 0, ct.byref(device)
        )
        if result < 0:
            raise OSError("Windows has no default microphone.")
        result = method(device, 5, ct.c_long, ct.POINTER(ct.c_void_p))(device, ct.byref(identity))
        if result < 0:
            raise OSError("Cannot identify the Windows default microphone.")
        token = ct.wstring_at(identity)
        label = "System default microphone"
        endpoint = token[token.rfind("{") :]
        try:
            path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\{endpoint}\Properties"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                try:
                    label = winreg.QueryValueEx(key, "{a45c254e-df1c-4efd-8020-67d146a850e0},14")[0]
                except OSError:
                    name = winreg.QueryValueEx(key, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")[0]
                    adapter = winreg.QueryValueEx(key, "{b3f8fa53-0004-438e-9003-51a46e139bfc},6")[
                        0
                    ]
                    label = f"{name} ({adapter})"
        except OSError:
            pass
        return token, label
    finally:
        if identity:
            ole.CoTaskMemFree(identity)
        if device:
            method(device, 2, ct.c_ulong)(device)
        if enumerator:
            method(enumerator, 2, ct.c_ulong)(enumerator)
        if initialized:
            ole.CoUninitialize()
