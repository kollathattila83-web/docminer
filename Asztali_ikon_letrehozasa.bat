@echo off
rem Egyszer kell futtatni: "DocMiner" ikont tesz az asztalra, ami a DocMiner_inditas.bat-ot inditja.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'DocMiner.lnk')); $s.TargetPath='%~dp0DocMiner_inditas.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,21'; $s.Description='DocMiner inditasa'; $s.Save()"
if errorlevel 1 (
  echo  HIBA: nem sikerult az ikont letrehozni.
  pause
  exit /b 1
)
echo  Kesz: az asztalon van egy DocMiner ikon. Dupla kattintassal indul.
timeout /t 8 >nul
