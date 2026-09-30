@echo off
rem Armar post: arrastrar la carpeta del casamiento sobre este archivo.
rem
rem   - Las fotos tienen que estar ya reveladas y exportadas a JPEG.
rem   - Si adentro hay una carpeta "novios" con 3 o 4 fotos de ellos, los reconoce.
rem   - Al terminar abre post.jpg, que muestra el carrusel completo.
rem   - Para cambiar algo: escribir en cambios.txt (misma carpeta que post.jpg) y volver a arrastrar.
rem   - Mas comodo todavia: la pagina, que se abre con  python curator/interfaz.py

chcp 65001 >nul
if "%~1"=="" (
  echo Arrastra la carpeta del casamiento sobre este archivo.
  pause
  exit /b 1
)

set "ALBUM=%~1"
set "NOVIOS="
if exist "%ALBUM%\novios\" set NOVIOS=--novios "%ALBUM%\novios"

python "%~dp0curate.py" "%ALBUM%" %NOVIOS%
if errorlevel 1 (
  echo.
  echo Algo fallo. El detalle esta arriba.
  pause
  exit /b 1
)

rem %~nx1 y no %~n1: una carpeta "boda.2026" perderia el ".2026" como si fuera extension
start "" "%~dp0salida\%~nx1\post.jpg"
echo.
echo Listo. Las slides estan en: %~dp0salida\%~nx1\slides
pause
