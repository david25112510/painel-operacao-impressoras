@echo off
netsh advfirewall firewall add rule name="Contadores de Impressoras - painel central" dir=in action=allow protocol=TCP localport=8765 profile=private
if errorlevel 1 (
  echo Execute este arquivo como administrador do Windows.
  pause
  exit /b 1
)
echo A porta TCP 8765 foi liberada para a rede privada do Windows.
pause
