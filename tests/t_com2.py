import ctypes
from ctypes import byref, c_void_p, c_uint32, c_uint16, c_ubyte, Structure

class GUID(Structure):
    _fields_ = [("D1", c_uint32), ("D2", c_uint16), ("D3", c_uint16), ("D4", c_ubyte * 8)]

def g(d1, d4):
    x = GUID(); x.D1 = d1; x.D2 = 0; x.D3 = 0; x.D4[:] = d4; return x

CLSID = g(0x00021401, [0xC0,0,0,0,0,0,0,0x46])
IID   = g(0x000214F9, [0xC0,0,0,0,0,0,0,0x46])
print("start", flush=True)
ole32 = ctypes.oledll.ole32
ole32.CoInitialize(None)
p = c_void_p()
hr = ole32.CoCreateInstance(byref(CLSID), None, 1, byref(IID), byref(p))
print("CoCreateInstance hr =", hr, "ptr =", p, flush=True)
