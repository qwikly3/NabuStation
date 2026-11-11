"""Streaming FIR AEC fallback for the Station 1 mic array.

The voice server passes the live microphone mix (ch1-3) and the amplifier
reference (ch4).  This causal FIR echo canceller is only used when SpeexDSP
is unavailable; SpeexDSP is the recommended path.

The filter is fitted by regularized least squares while TTS is playing; it
cancels roughly 25 dB of the station's own echo.  The remaining signal is
used for barge-in detection and wake-word scoring.  It is reset for every
TTS utterance.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.linalg import solve_toeplitz
from scipy.signal import correlate

RATE = 16000
log = logging.getLogger("station-voice")


class _HighPass:
    """First-order DC blocker, used to keep the subwoofer out of the AEC."""

    def __init__(self, fc: float = 100.0, rate: int = RATE) -> None:
        self.alpha = float(np.exp(-2.0 * np.pi * fc / rate))
        self.prev_x = 0.0
        self.prev_y = 0.0

    def reset(self) -> None:
        self.prev_x = 0.0
        self.prev_y = 0.0

    def run(self, x: np.ndarray) -> np.ndarray:
        out = np.empty_like(x, dtype=np.float32)
        px = self.prev_x
        py = self.prev_y
        a = self.alpha
        for i, v in enumerate(x):
            y = a * (py + float(v) - px)
            out[i] = y
            px = float(v)
            py = y
        self.prev_x = px
        self.prev_y = py
        return out


class StreamAEC:
    def __init__(
        self,
        taps: int = 1024,
        hop: int = 1280,
        fit_seconds: float = 1.5,
        hp_hz: float = 100.0,
        ref_active_rms: float = 40.0,
    ) -> None:
        self.taps = taps
        self.hop = hop
        self.fit_samples_target = int(fit_seconds * RATE)
        self.ref_active_rms = ref_active_rms
        self.hp_mic = _HighPass(hp_hz)
        self.hp_ref = _HighPass(hp_hz)
        self.reset()

    def reset(self) -> None:
        self.ref_hist = np.zeros(self.taps - 1, dtype=np.float32)
        self.fit_mic: list[np.ndarray] = []
        self.fit_ref: list[np.ndarray] = []
        self.fit_samples = 0
        self.settle_frames = 0
        self.active_seen = False
        self.w: np.ndarray | None = None
        self.ready = False
        self.fit_ref_rms = 0.0
        self.fit_raw_rms = 0.0
        self.hp_mic.reset()
        self.hp_ref.reset()

    def process(
        self, mic_frame: np.ndarray, ref_frame: np.ndarray
    ) -> np.ndarray | None:
        """Return cleaned mic samples for one hop, or None while fitting."""
        mic = np.asarray(mic_frame, dtype=np.float32)
        ref = np.asarray(ref_frame, dtype=np.float32)
        if len(mic) != self.hop:
            if len(mic) < self.hop:
                mic = np.pad(mic, (0, self.hop - len(mic)))
                ref = np.pad(ref, (0, self.hop - len(ref)))
            else:
                mic = mic[: self.hop]
                ref = ref[: self.hop]

        mic = self.hp_mic.run(mic)
        ref = self.hp_ref.run(ref)
        ref_rms = float(np.sqrt(np.mean(ref * ref)))
        raw_rms = float(np.sqrt(np.mean(mic * mic)))

        if self.w is None:
            # Skip the playback onset transient.  Learn only while the
            # speaker is active and skip obvious double-talk.
            if ref_rms >= self.ref_active_rms:
                if not self.active_seen:
                    self.active_seen = True
                    self.settle_frames = 0
                self.settle_frames += 1
            else:
                self.active_seen = False
                self.settle_frames = 0
            if (
                self.active_seen
                and self.settle_frames > 5
                and raw_rms < ref_rms * 3.0
            ):
                self.fit_mic.append(mic.copy())
                self.fit_ref.append(ref.copy())
                self.fit_samples += self.hop
            if self.fit_samples >= self.fit_samples_target:
                self._fit()
            self._push_ref(ref)
            return None

        x = np.concatenate([self.ref_hist, ref])
        self._push_ref(ref)
        X = np.lib.stride_tricks.sliding_window_view(x, self.taps)
        y = X @ self.w
        clean = np.clip(mic - y, -32768, 32767).astype(np.int16)
        return clean

    def _push_ref(self, ref: np.ndarray) -> None:
        self.ref_hist = np.concatenate([self.ref_hist, ref])[-self.taps + 1 :]

    def _solve(self, mic: np.ndarray, ref: np.ndarray) -> np.ndarray | None:
        # Autocorrelation r[k] = sum ref[n]*ref[n+k]
        ac = correlate(ref, ref, mode="full", method="fft")
        mid = len(ref) - 1
        r = ac[mid : mid + self.taps].copy()
        # Cross-correlation p[k] = sum mic[m]*ref[m-(taps-1-k)]
        cc = correlate(mic, ref, mode="full", method="fft")
        p = np.empty(self.taps, dtype=np.float64)
        for k in range(self.taps):
            lag = self.taps - 1 - k
            p[k] = cc[mid + lag]
        # Tikhonov regularization proportional to the mean diagonal.
        r[0] += 1e-3 * (r[0] / self.taps)
        try:
            w = solve_toeplitz(r, p)
        except Exception:  # noqa: BLE001
            log.exception("AEC fit failed")
            return None
        if not np.all(np.isfinite(w)) or np.max(np.abs(w)) > 20.0:
            return None
        return w

    def _fit(self) -> None:
        mic = np.concatenate(self.fit_mic)
        ref = np.concatenate(self.fit_ref)
        n = len(mic)
        split = int(n * 0.8)
        if split < self.taps + self.hop:
            return
        w = self._solve(mic[:split], ref[:split])
        if w is None:
            log.warning("AEC fit rejected (unstable filter)")
            self._clear_fit()
            return
        # Validate on the last 20% of the buffer, which was not used for
        # fitting.  A filter that only fits the training seconds is worse
        # than no barge-in at all.
        ctx = ref[split - (self.taps - 1) :]
        Xv = np.lib.stride_tricks.sliding_window_view(ctx, self.taps)
        target_v = mic[split:]
        if len(Xv) != len(target_v):
            self._clear_fit()
            return
        err = target_v - Xv @ w
        p_t = float(np.mean(target_v * target_v)) + 1e-12
        p_e = float(np.mean(err * err)) + 1e-12
        val_erle = 10.0 * np.log10(p_t / p_e)
        if val_erle < 10.0:
            log.warning(
                "AEC fit rejected (validation %.1f dB, wnorm %.2f)",
                val_erle,
                float(np.linalg.norm(w)),
            )
            self._clear_fit()
            return
        # The fitted FIR expects a window [ref[n] .. ref[n+taps-1]] for
        # target mic[n+taps-1]; the streaming window uses the same order.
        self.w = w.astype(np.float32)
        self.ready = True
        self.fit_ref_rms = float(np.sqrt(np.mean(ref * ref)))
        self.fit_raw_rms = float(np.sqrt(np.mean(mic * mic)))
        log.info(
            "AEC ready (taps=%d frames=%d ref_rms=%.0f mic_rms=%.0f "
            "wnorm=%.2f val=%.1f dB)",
            self.taps,
            n // self.hop,
            self.fit_ref_rms,
            self.fit_raw_rms,
            float(np.linalg.norm(w)),
            val_erle,
        )
        self._clear_fit()

    def _clear_fit(self) -> None:
        self.fit_mic.clear()
        self.fit_ref.clear()
        self.fit_samples = 0
