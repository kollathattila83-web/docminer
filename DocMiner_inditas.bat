@echo off
rem DocMiner inditasa: dupla kattintas. Elinditja a Dockert (ha kell), a DocMinert,
rem es megnyitja a DocMaster feluletet a bongeszoben.
setlocal
cd /d "%~dp0"
title DocMiner
echo.
echo  DocMiner inditasa...
echo.
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo  Letrehoztam a .env fajlt a mintabol, probamodban indul.
)

docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
echo  Docker Desktop inditasa, ez 1-2 perc is lehet...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a tries=0
:wait_docker
timeout /t 5 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
set /a tries+=1
if %tries% lss 60 goto wait_docker
echo.
echo  HIBA: a Docker 5 perc alatt sem indult el.
echo  Inditsd el kezzel a Docker Desktopot, majd probald ujra.
pause
exit /b 1

:docker_ok
echo  A Docker fut. A DocMiner inditasa (az elso alkalom tobb perc)...
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo  HIBA: nem sikerult elinditani. A fenti uzenetet kuldd el Claude-nak.
  pause
  exit /b 1
)

echo  Varakozas a feluletre...
set /a tries=0
:wait_ui
curl -s -o nul http://localhost:8501
if not errorlevel 1 goto ui_ok
set /a tries+=1
if %tries% geq 60 goto ui_ok
timeout /t 2 /nobreak >nul
goto wait_ui

:ui_ok
start "" http://localhost:8501
echo.
echo  Kesz! A DocMaster megnyilt a bongeszoben: http://localhost:8501
echo  Ezt az ablakot bezarhatod, a DocMiner a hatterben fut tovabb.
echo  Leallitas: DocMiner_leallitas.bat
timeout /t 15 >nul
