@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv-servidor
if errorlevel 1 goto erro
.venv-servidor\Scripts\python.exe -m pip install --upgrade pip
.venv-servidor\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto erro
echo.
echo Componentes do servidor instalados. Execute iniciar_servidor.bat.
pause
exit /b 0
:erro
echo.
echo Falha na instalacao. Instale Python 3.10 ou superior e tente novamente.
pause
exit /b 1
