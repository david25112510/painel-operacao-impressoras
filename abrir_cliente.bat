@echo off
setlocal
cd /d "%~dp0"
if exist release\ContadoresClienteAtualizado.exe (
  start "" "%~dp0release\ContadoresClienteAtualizado.exe"
  exit /b 0
)
if exist release\ContadoresClienteCorrigido.exe (
  start "" "%~dp0release\ContadoresClienteCorrigido.exe"
  exit /b 0
)
if exist release\ContadoresCliente.exe (
  start "" "%~dp0release\ContadoresCliente.exe"
  exit /b 0
)
if not exist .venv-cliente\Scripts\python.exe (
  echo Cliente nao encontrado. Copie a pasta completa ou execute build_windows.bat.
  pause
  exit /b 1
)
.venv-cliente\Scripts\python.exe client.py
if errorlevel 1 pause
