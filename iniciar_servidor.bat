@echo off
setlocal
cd /d "%~dp0"
if exist release\ContadoresServidorAtualizado.exe (
  "%~dp0release\ContadoresServidorAtualizado.exe"
  pause
  exit /b 0
)
if exist release\ContadoresServidor.exe (
  "%~dp0release\ContadoresServidor.exe"
  pause
  exit /b 0
)
if not exist .venv-servidor\Scripts\python.exe (
  echo Servidor nao encontrado. Copie a pasta completa ou execute build_windows.bat.
  pause
  exit /b 1
)
.venv-servidor\Scripts\python.exe server.py
pause
