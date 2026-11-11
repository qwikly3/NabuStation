"""SpeexDSP adaptive echo canceller + residual echo suppression.

The station's 5-channel TDM stream carries the live microphones and the
amplifier reference taps.  Speex's adaptive filter handles the room delay
and double-talk; a high-pass keeps loud bass peaks out of the filter and
the Speex preprocessor suppresses the residual echo that remains after
the linear canceller (especially on loud music transients).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os

import numpy as np
from scipy.signal import lfilter

# Debian/Ubuntu: apt install libspeexdsp1
LIB_PATH = (
    os.environ.get("SPEEXDSP_LIB")
    or ctypes.util.find_library("speexdsp")
    or "libspeexdsp.so.1"
)
SPX_INT16 = ctypes.c_int16
RATE = 16000


class _HighPass:
    def __init__(self, fc: float = 100.0) -> None:
        self.alpha = float(np.exp(-2.0 * np.pi * fc / RATE))
        self.zi = np.zeros(1, dtype=np.float64)

    def run(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = lfilter(
            [self.alpha, -self.alpha], [1.0, -self.alpha], x, zi=self.zi
        )
        return y


class SpeexAEC:
    def __init__(self, frame_size: int = 160, filter_length: int = 4096) -> None:
        self.lib = ctypes.CDLL(LIB_PATH)
        self.frame_size = frame_size

        self.lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.speex_echo_state_init.restype = ctypes.c_void_p
        self.lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]
        self.lib.speex_echo_cancellation.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(SPX_INT16),
            ctypes.POINTER(SPX_INT16),
            ctypes.POINTER(SPX_INT16),
        ]
        self.lib.speex_echo_cancellation.restype = None
        self.lib.speex_preprocess_state_init.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
        ]
        self.lib.speex_preprocess_state_init.restype = ctypes.c_void_p
        self.lib.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
        self.lib.speex_preprocess_ctl.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self.lib.speex_preprocess_ctl.restype = ctypes.c_int
        self.lib.speex_preprocess_run.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(SPX_INT16),
        ]
        self.lib.speex_preprocess_run.restype = ctypes.c_int

        self.state = self.lib.speex_echo_state_init(frame_size, filter_length)
        if not self.state:
            raise RuntimeError("speex_echo_state_init failed")
        self.pre = self.lib.speex_preprocess_state_init(frame_size, RATE)
        if not self.pre:
            raise RuntimeError("speex_preprocess_state_init failed")

        # Link the residual-echo suppressor to the echo canceller.
        self.lib.speex_preprocess_ctl(
            self.pre, 24, ctypes.c_void_p(self.state)
        )
        # Keep the noise/VAD/AGC stages out of the way; residual echo only.
        for request in (0, 2):
            value = ctypes.c_int(0)
            self.lib.speex_preprocess_ctl(self.pre, request, ctypes.byref(value))
        echo_suppress = ctypes.c_int(-30)
        self.lib.speex_preprocess_ctl(self.pre, 20, ctypes.byref(echo_suppress))
        echo_active = ctypes.c_int(-15)
        self.lib.speex_preprocess_ctl(self.pre, 22, ctypes.byref(echo_active))

        self._rec = (SPX_INT16 * frame_size)()
        self._play = (SPX_INT16 * frame_size)()
        self._out = (SPX_INT16 * frame_size)()
        self.hp_mic = _HighPass()
        self.hp_ref = _HighPass()

    def process(self, mic_frame: np.ndarray, ref_frame: np.ndarray) -> np.ndarray:
        mic_f = self.hp_mic.run(np.asarray(mic_frame, dtype=np.float32))
        ref_f = self.hp_ref.run(np.asarray(ref_frame, dtype=np.float32))
        mic = np.clip(mic_f, -32768, 32767).astype(np.int16)
        ref = np.clip(ref_f, -32768, 32767).astype(np.int16)
        n = len(mic)
        out = np.empty(n, dtype=np.int16)
        for off in range(0, n, self.frame_size):
            end = min(off + self.frame_size, n)
            count = end - off
            for i in range(count):
                self._rec[i] = int(mic[off + i])
                self._play[i] = int(ref[off + i])
            for i in range(count, self.frame_size):
                self._rec[i] = 0
                self._play[i] = 0
            self.lib.speex_echo_cancellation(
                self.state, self._rec, self._play, self._out
            )
            self.lib.speex_preprocess_run(self.pre, self._out)
            out[off:end] = np.ctypeslib.as_array(self._out)[:count]
        return out
