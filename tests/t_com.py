import ctypes, sys
print("step1")
ole32 = ctypes.oledll.ole32
print("step2 loaded")
hr = ole32.CoInitialize(None)
print("CoInitialize ->", hr)
