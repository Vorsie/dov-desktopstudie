@echo off
rem Junction van de pluginmap van het standaard-QGIS-profiel naar deze checkout, voor ontwikkeling:
rem QGIS laadt dan de code uit de repository (Plugin Reloader herlaadt na een wijziging).
rem Overschrijft niets: staat er al een map of junction, dan stopt het script en zegt dat.
setlocal
set "PLUGINS=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins"
set "TARGET=%PLUGINS%\desktopstudie"
set "SOURCE=%~dp0..\desktopstudie"
if exist "%TARGET%" (
  echo Bestaat al: %TARGET%
  echo Verwijder die map of junction eerst zelf; dit script overschrijft niets.
  exit /b 1
)
if not exist "%PLUGINS%" mkdir "%PLUGINS%"
mklink /J "%TARGET%" "%SOURCE%"
if errorlevel 1 (
  echo Junction maken mislukt.
  exit /b 1
)
echo Junction gemaakt: %TARGET% -^> %SOURCE%
endlocal
