# Third-party notices

Pluto Scanner is distributed under the MIT License (see `LICENSE`).
The portable Windows build contains third-party components with their own
licenses. This file is a notice, not a replacement for the full license texts.

## Bundled native libraries

| Component | License | Source |
| --- | --- | --- |
| libiio / libiio1 | LGPL-2.1-or-later | https://github.com/analogdevicesinc/libiio |
| libusb-1.0 | LGPL-2.1-or-later | https://github.com/libusb/libusb |
| libserialport | LGPL-3.0-or-later | https://github.com/sigrokproject/libserialport |
| libxml2 | MIT | https://gitlab.gnome.org/GNOME/libxml2 |
| zstd | BSD-3-Clause | https://github.com/facebook/zstd |
| PortAudio (via sounddevice) | MIT | https://www.portaudio.com/ |

The libiio, libusb and libserialport DLLs are loaded dynamically, so they can
be replaced with a compatible build of the same library.

## Python packages

| Package | License | Source |
| --- | --- | --- |
| Python | PSF-2.0 | https://www.python.org/ |
| PySide6 / Qt for Python | LGPL-3.0-only (or GPL/commercial) | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| numpy | BSD-3-Clause | https://numpy.org/ |
| scipy | BSD-3-Clause | https://scipy.org/ |
| pyqtgraph | MIT | https://www.pyqtgraph.org/ |
| sounddevice | MIT | https://python-sounddevice.readthedocs.io/ |
| pyadi-iio | ADI BSD | https://github.com/analogdevicesinc/pyadi-iio |
| pylibiio | LGPL-2.1-or-later | https://github.com/analogdevicesinc/libiio |
| PyInstaller (bootloader) | GPL-2.0-or-later with special exception | https://pyinstaller.org/ |

The PyInstaller exception explicitly allows building and distributing
non-free applications with PyInstaller.

## Notes

- Full license texts are available from the upstream projects and from the
  installed Python packages in this repository's virtual environment.
- If you redistribute the portable build, keep this notice and the MIT
  `LICENSE` file next to `PlutoScanner.exe`.
