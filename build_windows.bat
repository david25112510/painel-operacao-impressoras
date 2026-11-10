@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv-build
if errorlevel 1 goto erro
.venv-build\Scripts\python.exe -m pip install --upgrade pip
.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto erro
if not exist release mkdir release
.venv-build\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --name ContadoresClienteAtualizado --distpath release --workpath work\cliente client.py
if errorlevel 1 goto erro
.venv-build\Scripts\pyinstaller.exe --noconfirm --clean --onefile --name ContadoresServidorAtualizado --distpath release --workpath work\servidor --collect-all pysnmp server.py
if errorlevel 1 goto erro
echo.
echo Executaveis criados na pasta release.
pause
exit /b 0
:erro
echo.
echo A compilacao falhou. Revise as mensagens acima.
pause
exit /b 1
