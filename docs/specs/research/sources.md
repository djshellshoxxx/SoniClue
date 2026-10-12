# Research source register

Accessed 2026-10-12 unless noted.

| ID | Source | Used for |
|---|---|---|
| SRC-01 | Open Sound Meter releases: https://opensoundmeter.com/releases (desktop versions GPL-3.0) | licence classification, feature comparison |
| SRC-02 | Open Sound Meter repository: https://github.com/psmokotnin/osm | feature comparison |
| SRC-03 | Friture on PyPI: https://pypi.org/project/friture/ (GPL) | licence classification |
| SRC-04 | Friture contributing page: https://friture.org/contributing.html (GPLv3+) | licence classification |
| SRC-05 | Friture audio backend source: https://github.com/tlecomte/friture/blob/master/friture/audiobackend.py (sounddevice + rtmixer) | callback design alternative (RISK-004) |
| SRC-06 | Free audio analyzer comparison (SonaVyx "AI diagnostics" claim): https://sonavyx.com/en/compare/free-audio-analyzer-tools | competitive claim check |
| SRC-07 | SciPy `signal.welch` / `csd` / `coherence` documentation and source (`np.conjugate(result_x) * result_y` orientation checked in installed scipy 1.17.1 source) | INV-005 cross-spectrum orientation |
| SRC-08 | IEC 61260-1:2014 octave-band and fractional-octave-band filters (base-10 midband definition) | band centres |
| SRC-09 | ISO 1683:2015 preferred reference values for acoustical and vibratory levels | dB references |
| SRC-10 | Bendat & Piersol, *Random Data: Analysis and Measurement Procedures* (coherence bias, estimator variance) | ADV-009, uncertainty model |
| SRC-11 | Heinzel, Rüdiger, Schilling (2002), *Spectrum and spectral density estimation by the DFT* (window ENBW/coherent gain) | INV-004 |
| SRC-12 | python-sounddevice documentation (WasapiSettings, InputStream callback status flags) | acquisition backend |
| SRC-13 | Steinberg ASIO SDK licensing terms | DEC-003a |
| SRC-14 | Qt for Python (PySide6) licensing: LGPLv3 / commercial | DEC-009, licence inventory |
