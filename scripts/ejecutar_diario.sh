#!/bin/bash
# Proceso batch diario (cron). 1) CSV del dia -> BDClinica   2) BDClinica -> DWClinica (dw.* y rpt.*) solo modulo transaccional.
# Prueba sin ejecutar nada real:  DRY_RUN=1 scripts/ejecutar_diario.sh
# cron (23:30):  30 23 * * * /ruta/clinica-bi/scripts/ejecutar_diario.sh >> /ruta/clinica-bi/logs/cron.log 2>&1
cd "$(dirname "$0")/.." || exit 1
PYTHON="${PYTHON:-python3}"
mkdir -p logs
run() { if [ "${DRY_RUN:-0}" = "1" ]; then echo "[SIMULACION] $*"; else "$@"; fi; }
echo "=== $(date '+%F %T') inicio del proceso diario ==="
run "$PYTHON" -m etl.carga_diaria || { echo "[ERROR] carga diaria fallo; no se actualiza el data mart."; exit 1; }
run "$PYTHON" -m etl.datamart --origen sqlserver --destino sqlserver --modulos transaccional || exit 1
echo "=== $(date '+%F %T') proceso diario completo ==="
