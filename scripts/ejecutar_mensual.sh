#!/bin/bash
# Carga mensual del inventario fisico de farmacia (Excel de data/fuentes) -> DWClinica. Las metas y feriados son anuales:
#   python -m etl.datamart --modulos metas      /      python -m etl.datamart --modulos feriados
cd "$(dirname "$0")/.." || exit 1
"${PYTHON:-python3}" -m etl.datamart --origen sqlserver --destino sqlserver --modulos inventario
