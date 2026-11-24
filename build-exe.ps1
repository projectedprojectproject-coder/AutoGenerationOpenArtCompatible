# Rebuilds "Shorts Maker.exe" from tools/shorts_gui.py.
# Run this after editing shorts_gui.py / shorts_common.py and re-launch the exe to pick up changes.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
Set-Location $PSScriptRoot
uv run --with pyinstaller pyinstaller --onefile --windowed --name "Shorts Maker" --clean `
  --paths tools --hidden-import win_encoding --hidden-import shorts_common `
  --distpath . --workpath build_pyinstaller --specpath build_pyinstaller `
  tools/shorts_gui.py
Write-Output "`nBuilt: $PSScriptRoot\Shorts Maker.exe"
