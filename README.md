# PlateBridge

**[Download PlateBridge for Windows](https://github.com/redheadeddude-eng/PlateBridge/raw/refs/heads/main/downloads/PlateBridge.msi)**

[Watch the MakerWorld to Flash Studio demo on YouTube](https://www.youtube.com/shorts/sej65b7uRx8)

PlateBridge is a free Windows app for converting MakerWorld 3MF files into editable Flash Studio projects for the Flashforge AD5X, Adventurer 5M Pro, and Creator 5.

![PlateBridge showing a saved Creator 5 project](PlateBridge-working.jpg)

## Install and convert a project

1. Install 64-bit Python 3.14 from [python.org](https://www.python.org/downloads/windows/) with Tcl/Tk enabled. Open **PlateBridge.msi**, then launch **PlateBridge for Flashforge** from Start.
2. Drop the original MakerWorld 3MF into PlateBridge and select your printer.
3. Click **Save project**. The new 3MF sits next to the original with the printer name added.
4. Click **Open in Flash Studio**, check the plates and filament assignments, and slice.

PlateBridge carries over settings such as layer height, infill, supports and filament colors. Machine-specific settings come from the selected printer profile. The installer includes fallback profiles for all three supported printers.

[Download the demo video](PlateBridge-demo.mp4)

## Run from the published source on Windows

Download and extract the [source ZIP](https://github.com/redheadeddude-eng/PlateBridge/archive/refs/heads/main.zip). Install Python 3.14 for Windows with Tcl/Tk from [python.org](https://www.python.org/downloads/windows/). Open the extracted `app` folder and double-click **Open PlateBridge.pyw**. To see startup errors in a terminal, run `python app/PlateBridge.py` from the repository folder.

The current MSI installs the published Python files for your Windows account. It uses your separately installed Python runtime. If Defender blocks an older PlateBridge-Setup.exe, leave it quarantined.

## Build the Windows installer

With WiX 5 on PATH, run `.\build\package.ps1` from the checkout. The resulting MSI is written to `dist`. The MSI contains no custom actions.
