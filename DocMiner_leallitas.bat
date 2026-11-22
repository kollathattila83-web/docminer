@echo off
rem A DocMiner leallitasa. Az adatok (iratok, adatbazis) megmaradnak.
cd /d "%~dp0"
title DocMiner leallitasa
echo  DocMiner leallitasa...
docker compose stop
echo.
echo  Leallitva. Az iratok es az adatbazis megmaradtak.
timeout /t 5 >nul
