@echo off
REM Proceso batch diario (Programador de tareas de Windows).
REM 1) CSV del dia -> BDClinica   2) BDClinica -> DWClinica (dw.* y rpt.*) solo modulo transaccional
cd /d "%~dp0.."
py -m etl.carga_diaria
if errorlevel 1 (
  echo [ERROR] la carga diaria fallo; no se actualiza el data mart.
  exit /b 1
)
py -m etl.datamart --origen sqlserver --destino sqlserver --modulos transaccional
if errorlevel 1 exit /b 1
echo Proceso diario completo.
