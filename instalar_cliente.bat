@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv-cliente
if errorlevel 1 goto erro
.venv-cliente\Scripts\python.exe -m pip install --upgrade pip
.venv-cliente\Scripts\python.exe -m pip install -r requirements-client.txt
if errorlevel 1 goto erro
echo.
echo Componentes do programa instalados. Execute abrir_cliente.bat.
pause
exit /b 0
:erro
echo.
echo Falha na instalacao. Instale Python 3.10 ou superior e tente novamente.
pause
exit /b 1
