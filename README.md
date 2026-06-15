# PDF Diff Studio

PDF Diff Studio is a portable desktop app for comparing two PDF files on Windows and macOS.

It lets you attach two PDFs, compares their extracted page text, and shows:

- A page-by-page change summary.
- Side-by-side highlighted text differences.
- A visual page comparison with changed pixels highlighted separately on each PDF.

## Run from source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pdfdiffstudio
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pdfdiffstudio
```

## Build a portable executable

PyInstaller builds for the operating system it is running on. Build the Windows executable on Windows, and the macOS app bundle on macOS.

Published builds are created by GitHub Actions when a version tag such as `v0.1.0` is pushed. The Windows `.exe` and macOS `.app` zip are attached to the GitHub Release.

Windows:

```powershell
.\scripts\build_windows.ps1
```

Output:

```text
dist\PDFDiffStudio.exe
```

macOS:

```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

Output:

```text
dist/PDFDiffStudio.app
```

The generated file can be zipped and shared. The recipient does not need to install Python or the project dependencies.

## Notes

- Text comparison uses extracted PDF text, so scanned PDFs without OCR will show little or no text difference.
- Visual comparison renders the selected page side by side: changed regions are marked red on the first PDF and green on the second PDF. This catches layout/image changes that text extraction may miss without stacking both pages into one overlay.
- macOS may show a Gatekeeper warning for unsigned local builds. Signing and notarization can be added later if the app will be distributed outside a trusted team.
