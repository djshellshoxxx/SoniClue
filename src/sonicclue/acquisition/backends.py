"""Audio backends.

Selected backend (ADR-0003): PortAudio through ``sounddevice``. The official
Windows wheels bundle a PortAudio DLL with MME, DirectSound, WASAPI and WDM-KS
host APIs. On Linux, PortAudio provides ALSA (and JACK when available), and
PulseAudio/PipeWire are reached through their ALSA plugins. ASIO is not in the
bundled DLL: the Steinberg SDK licence forbids redistributing it without an
agreement, so ASIO is deferred (DEC-003a).

WASAPI exclusive mode is opt-in. It bypasses the Windows shared-mode mixer and
sample-rate converter, and with it any "audio enhancements" (AGC, noise
suppression) that the shared-mode path may apply.

``SimulatedBackend`` produces synthetic signals from a ``SimWorld`` model for
demos, training and end-to-end tests. Captures from it are always marked
``source="simulated"`` and carry the SIMULATED_DATA flag.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from ..domain.errors import DeviceError
from ..dsp import signals


@dataclass(frozen=True)
class DeviceDescriptor:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    backend: str = "portaudio"


# callback(block[frames, ch] float32, frame_index, status_flags: set[str])
InputCallback = Callable[[np.ndarray, int, set], None]


class StreamHandle(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class AudioBackend(Protocol):
    name: str

    def list_devices(self) -> list[DeviceDescriptor]: ...
    def check_input(self, device: int, samplerate: float, channels: int) -> None: ...
    def open_input(self, device: int, samplerate: float, channels: int, blocksize: int, callback: InputCallback,
                   on_finished: Callable[[str | None], None], exclusive: bool = False) -> StreamHandle: ...
    def open_output(self, device: int, samplerate: float, channels: int, blocksize: int,
                    fill: Callable[[int], np.ndarray], on_finished: Callable[[str | None], None]) -> StreamHandle: ...


class PortAudioBackend:
    name = "portaudio"

    def __init__(self):
        try:
            import sounddevice as sd  # noqa: F401
        except OSError as exc:  # PortAudio library missing
            raise DeviceError(f"PortAudio unavailable: {exc}", code="SC_NO_AUDIO_BACKEND") from exc
        self._sd = sd

    def list_devices(self) -> list[DeviceDescriptor]:
        sd = self._sd
        try:
            apis = sd.query_hostapis()
            devs = sd.query_devices()
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(f"device query failed: {exc}") from exc
        return [DeviceDescriptor(i, d["name"], apis[d["hostapi"]]["name"], d["max_input_channels"],
                                 d["max_output_channels"], float(d["default_samplerate"])) for i, d in enumerate(devs)]

    def check_input(self, device: int, samplerate: float, channels: int) -> None:
        try:
            self._sd.check_input_settings(device=device, samplerate=samplerate, channels=channels, dtype="float32")
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(f"device {device} rejects {channels} ch @ {samplerate:g} Hz: {exc}", code="SC_DEVICE_FORMAT") from exc

    def _extra(self, device: int, exclusive: bool):
        if not exclusive:
            return None
        api = self._sd.query_hostapis(self._sd.query_devices(device)["hostapi"])["name"]
        if "WASAPI" not in api:
            raise DeviceError("exclusive mode is only available for WASAPI devices", code="SC_DEVICE_FORMAT")
        return self._sd.WasapiSettings(exclusive=True)

    def open_input(self, device, samplerate, channels, blocksize, callback, on_finished, exclusive=False):
        sd = self._sd
        counter = {"n": 0}

        def cb(indata, frames, time_info, status):
            flags = set()
            if status.input_overflow:
                flags.add("input_overflow")
            callback(indata, counter["n"], flags)
            counter["n"] += frames

        try:
            return sd.InputStream(device=device, samplerate=samplerate, channels=channels, dtype="float32",
                                  blocksize=blocksize, callback=cb, finished_callback=lambda: on_finished(None),
                                  extra_settings=self._extra(device, exclusive), latency="high")
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(f"cannot open input device {device}: {exc}") from exc

    def open_output(self, device, samplerate, channels, blocksize, fill, on_finished):
        sd = self._sd

        def cb(outdata, frames, time_info, status):
            outdata[:] = fill(frames).reshape(frames, -1)[:, :channels]

        try:
            return sd.OutputStream(device=device, samplerate=samplerate, channels=channels, dtype="float32",
                                   blocksize=blocksize, callback=cb, finished_callback=lambda: on_finished(None))
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(f"cannot open output device {device}: {exc}") from exc


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------


@dataclass
class SimWorld:
    """Physical toy model for the demo scenario "home studio".

    Equipment: ``pc`` (fan with a 39 Hz shaft rate; blade-pass at 117 Hz plus
    harmonics, transmitted structurally through the desk), ``hvac`` (broadband
    rumble, airborne), ``input`` ("connected"/"terminated": a terminated
    input still shows 50 Hz chain hum when ``chain_hum`` is set).
    ``pc_isolated`` True models isolation pads that cut the structural path by 18 dB.
    ``contact_mounted`` False models a contact pickup resting on foam (airborne
    pickup only), which the airborne-control procedure exploits.
    Channel 0 is the microphone, channel 1 (if present) a contact pickup on
    the desk, channel 2 (if present) a second microphone near the HVAC vent.
    """

    state: dict[str, str] = field(default_factory=lambda: {"pc": "on", "hvac": "on", "input": "connected"})
    pc_isolated: bool = False
    chain_hum: bool = False
    seed: int = 1234
    mic_position: str = "P1"
    contact_mounted: bool = True

    def render(self, fs: float, channels: int, n: int, start: int) -> np.ndarray:
        dur = n / fs
        s = self.state
        seed = self.seed + start // max(n, 1)
        t0 = start / fs
        t = t0 + np.arange(n) / fs
        out = np.zeros((n, channels))
        mic = signals.white_noise(2e-4, dur, fs, seed)  # converter + room noise floor
        contact = signals.white_noise(1e-4, dur, fs, seed + 1)
        if s.get("input") == "terminated":
            mic = signals.white_noise(3e-5, dur, fs, seed)
        else:
            dist_gain = {"P1": 1.0, "P2": 0.5, "P3": 0.25}.get(self.mic_position, 1.0)
            if s.get("pc") == "on":
                fan = sum(a * np.sin(2 * np.pi * k * 117.0 * t + k) for k, a in ((1, 1.0), (2, 0.35), (3, 0.15)))
                fan += 0.05 * np.sin(2 * np.pi * 39.0 * t)
                struct = 0.03 * fan * (10 ** (-18 / 20) if self.pc_isolated else 1.0)
                contact += struct * 4.0 if self.contact_mounted else 0.0
                contact += 0.0008 * fan  # airborne sound reaching the contact pickup either way
                mic += struct * 0.5 * dist_gain + 0.004 * fan * dist_gain  # desk radiation + direct airborne
            if s.get("hvac") == "on":
                rumble = signals.band_noise(0.01, 25, 180, dur, fs, seed + 7)
                mic += rumble * dist_gain
                contact += 0.1 * rumble  # airborne excitation of the contact sensor (ADV-003)
        if self.chain_hum:
            mic += sum(a * np.sin(2 * np.pi * k * 50.0 * t) for k, a in ((1, 0.003), (3, 0.001), (5, 0.0005)))
        out[:, 0] = mic
        if channels > 1:
            out[:, 1] = contact
        if channels > 2:
            out[:, 2] = signals.band_noise(0.02, 25, 180, dur, fs, seed + 7) if s.get("hvac") == "on" else \
                signals.white_noise(2e-4, dur, fs, seed + 3)
        return np.clip(out, -1.0, 1.0).astype(np.float32)


class _SimStream:
    def __init__(self, world: SimWorld, fs, channels, blocksize, callback, on_finished, speed: float,
                 max_frames: int | None, fail_after_frames: int | None):
        self.world, self.fs, self.ch, self.bs = world, fs, channels, blocksize
        self.cb, self.on_finished, self.speed = callback, on_finished, speed
        self.max_frames, self.fail_after = max_frames, fail_after_frames
        self._stop = threading.Event()
        self._thr: threading.Thread | None = None

    def start(self):
        self._thr = threading.Thread(target=self._run, name="sim-audio", daemon=True)
        self._thr.start()

    def _run(self):
        pos = 0
        t_start = time.monotonic()
        err = None
        while not self._stop.is_set():
            if self.fail_after is not None and pos >= self.fail_after:
                err = "simulated device disconnect"
                break
            if self.max_frames is not None and pos >= self.max_frames:
                break
            block = self.world.render(self.fs, self.ch, self.bs, pos)
            self.cb(block, pos, set())
            pos += self.bs
            if self.speed > 0:
                lag = pos / (self.fs * self.speed) - (time.monotonic() - t_start)
                if lag > 0:
                    time.sleep(lag)
        self.on_finished(err)

    def stop(self):
        self._stop.set()
        if self._thr and self._thr is not threading.current_thread():
            self._thr.join(timeout=5)

    def close(self):
        self.stop()


class _NullOut:
    def __init__(self, fill, bs, fs, on_finished):
        self.fill, self.bs, self.fs, self.on_finished = fill, bs, fs, on_finished
        self._stop = threading.Event()
        self.rendered: list[np.ndarray] = []

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            self.rendered.append(self.fill(self.bs))
            time.sleep(self.bs / self.fs)
        self.on_finished(None)

    def stop(self):
        self._stop.set()

    def close(self):
        self.stop()


class SimulatedBackend:
    name = "simulated"

    def __init__(self, world: SimWorld | None = None, speed: float = 1.0, fail_after_frames: int | None = None):
        """``speed``: 1.0 = real time; 20.0 = twenty times faster (tests, demo). The
        speed is bounded so the producer cannot overrun the bounded capture queue."""
        self.world = world or SimWorld()
        self.speed = speed
        self.fail_after_frames = fail_after_frames
        self.last_output: _NullOut | None = None

    def list_devices(self):
        return [DeviceDescriptor(0, "SonicClue simulator (3 in / 2 out)", "simulated", 3, 2, 48000.0, "simulated")]

    def check_input(self, device, samplerate, channels):
        if device != 0 or not 1 <= channels <= 3 or not 8000 <= samplerate <= 192000:
            raise DeviceError("simulator supports device 0, 1-3 channels, 8-192 kHz", code="SC_DEVICE_FORMAT")

    def open_input(self, device, samplerate, channels, blocksize, callback, on_finished, exclusive=False):
        self.check_input(device, samplerate, channels)
        return _SimStream(self.world, samplerate, channels, blocksize, callback, on_finished, self.speed, None,
                          self.fail_after_frames)

    def open_output(self, device, samplerate, channels, blocksize, fill, on_finished):
        self.last_output = _NullOut(fill, blocksize, samplerate, on_finished)
        return self.last_output
