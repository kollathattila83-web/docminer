@echo off
rem A legujabb kod letoltese es a DocMiner ujrainditasa. Az adatok megmaradnak.
setlocal
cd /d "%~dp0"
title DocMiner frissitese
echo  Legujabb valtozat letoltese...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo  HIBA: a letoltes nem sikerult. A fenti uzenetet kuldd el Claude-nak.
  pause
  exit /b 1
)
call "%~dp0DocMiner_inditas.bat"
