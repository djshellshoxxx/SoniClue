"""SonicClue: affordable sound and vibration cause investigation.

Package layout and dependency direction (enforced by tests/test_contracts_architecture.py):

    gui, cli  ->  app  ->  {acquisition, storage, reporting, procedures, stimulus,
                            diagnostics, compare, sync, sensors, qualification}
                       ->  dsp  ->  domain

`domain` and `dsp` never import from GUI, device, storage or orchestration code.
"""

__version__ = "0.1.0"
try:  # written by packaging/build.py for release builds (git SHA + UTC time); absent in source checkouts
    from ._build import BUILD_ID  # type: ignore[import-not-found]
except ImportError:
    BUILD_ID = "dev"
