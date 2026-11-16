"""Locate frozen Linux PortAudio without requiring a host linker-cache entry."""


def _pyi_rthook():
    import ctypes.util
    import os
    import sys
    from pathlib import Path

    if not getattr(sys, "frozen", False) or not sys.platform.startswith("linux"):
        return
    alsa = Path(sys._MEIPASS) / "alsa"
    if (not os.environ.get("ALSA_CONFIG_PATH") and not os.environ.get("ALSA_CONFIG_DIR")
            and not Path("/usr/share/alsa/alsa.conf").is_file() and (alsa / "alsa.conf").is_file()):
        os.environ["ALSA_CONFIG_PATH"] = str(alsa / "alsa.conf")
        os.environ["ALSA_CONFIG_DIR"] = str(alsa)
    library = Path(sys._MEIPASS) / "libportaudio.so.2"
    if not library.is_file():
        return
    system_find = ctypes.util.find_library

    def find_library(name):
        if name == "portaudio":
            return str(library)
        return system_find(name)

    ctypes.util.find_library = find_library


_pyi_rthook()
del _pyi_rthook
