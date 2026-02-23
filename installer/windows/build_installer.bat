@echo off
setlocal

set "ROOT=%~dp0..\.."
pushd "%ROOT%" || goto :error

if not defined PYTHON set "PYTHON=python"

if not exist "migrate\inputs" mkdir "migrate\inputs"
if not exist "migrate\output" mkdir "migrate\output"
if not exist "migrate\inputs\.gitkeep" type nul > "migrate\inputs\.gitkeep"
if not exist "migrate\output\.gitkeep" type nul > "migrate\output\.gitkeep"

if /I "%1"=="--skip-pyinstaller" goto :build_installer

echo [1/2] Building one-dir package with PyInstaller...
%PYTHON% -m PyInstaller -y ln2_inventory.spec
if errorlevel 1 goto :error

:build_installer
echo [2/2] Building Setup.exe with Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do (
    set "ISCC=%%~fI"
    goto :found_iscc
  )
)

:found_iscc

if not exist "%ISCC%" (
  echo ERROR: ISCC.exe not found.
  echo Install Inno Setup 6 or run ISCC manually.
  goto :error
)

"%ISCC%" installer\windows\LN2InventoryAgent.iss
if errorlevel 1 goto :error

echo Done. Installer output is under dist\installer\
popd
exit /b 0

:error
popd
exit /b 1
