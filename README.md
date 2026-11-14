# BI Clínica – ETL y scripts de base de datos (Grupo 13)

Solución de Business Intelligence para una clínica privada: base transaccional **BDClinica** (SQL Server, esquema `clinica`), ETL en Python y data mart **DWClinica** para reportería con **Power BI**.

## Estructura del repositorio

```
├── database/
│   ├── bdclinica/            Scripts de la base transaccional (ejecutar en SSMS, en orden)
│   │   ├── 01_crear_bdclinica.sql        crea BDClinica y las 15 tablas (esquema clinica)
│   │   ├── 02_crear_esquema_etl.sql      tablas de control de la carga diaria (etl.CargaDiaria, etl.RechazoDiario)
│   │   ├── 03_conteo_tablas.sql          conteo de filas por tabla (verificación)
│   │   └── 04_limpiar_datos.sql          vacía las tablas para repetir la carga inicial (solo pruebas)
│   └── dwclinica/            Scripts del data mart
│       ├── 01_crear_dwclinica.sql        crea DWClinica: esquemas dw, seg y etl, roles e índices
│       ├── 02_vistas_kpi.sql             vistas de los 7 indicadores
│       ├── 03_crear_reporteria.sql       esquema rpt: tablas de reportería para Power BI
│       └── 04_validacion_cuadre.sql      pruebas de cuadre BDClinica vs DWClinica
├── etl/                      Código Python (paquete)
│   ├── config.py                         lector del .env y rutas relativas a la raíz
│   ├── carga_inicial.py                  CSV → BDClinica (una sola vez)
│   ├── carga_diaria.py                   CSV nuevos del programa de la clínica → BDClinica (batch diario)
│   └── datamart.py                       BDClinica + Excel + CSV → DWClinica (dw.* y rpt.*)
├── scripts/                  Orquestación: ejecutar_diario.sh (cron), ejecutar_diario.bat (Windows), ejecutar_mensual.sh
├── data/                     Datos sintéticos de ejemplo
│   ├── inicial/              15 CSV de la carga inicial (3 383 filas)
│   ├── entrada_diaria/       CSV TABLA_AAAAMMDD.csv que deja el programa de la clínica
│   ├── fuentes/              Excel de inventario, Excel de metas y CSV de feriados
│   └── procesados/ rechazos/ salida_pruebas/    resultados de ejecución (no se versionan)
├── tools/                    Generadores de datos de prueba y tablero estático opcional
├── docs/                     Diagramas y capturas de referencia
├── .env.example              plantilla de configuración (copiar a .env; el .env NO se sube)
└── requirements.txt
```

## Puesta en marcha

Requisitos: SQL Server (probado con 2025 Express), SSMS, Python 3 con `py -m pip install -r requirements.txt` y *ODBC Driver 18 for SQL Server*. Los comandos se ejecutan **desde la raíz del repositorio y desde la terminal** (el botón ▶ de VS Code falla con rutas con espacios).

1. **Configuración:** copiar `.env.example` como `.env` y completar servidor y `DW_SAL_HASH` (sal secreta del hash del DNI).
2. **Base transaccional (SSMS):** `database/bdclinica/01_crear_bdclinica.sql` y luego `02_crear_esquema_etl.sql`.
3. **Carga inicial:** `py -m etl.carga_inicial` (usa `data/inicial`). Verificar con `03_conteo_tablas.sql` (15 tablas, 3 383 filas). Para repetirla: `04_limpiar_datos.sql` o `--recargar`.
4. **Data mart (SSMS):** `database/dwclinica/01_crear_dwclinica.sql`, `02_vistas_kpi.sql`, `03_crear_reporteria.sql`. *(El 01 recrea la base desde cero.)*
5. **Primera carga del data mart:** `py -m etl.datamart` (todos los módulos). Verificar con `04_validacion_cuadre.sql` (14 pruebas en OK).
6. **Carga diaria:** el programa de la clínica deja `TABLA_AAAAMMDD.csv` en `data/entrada_diaria`; `py -m etl.carga_diaria` valida y carga solo lo nuevo (reprocesar no duplica). El resumen queda en `etl.CargaDiaria` y los rechazos con su motivo en `etl.RechazoDiario`.

## ETL y frecuencia

| Proceso | Comando | Frecuencia |
|---|---|---|
| Carga inicial CSV → BDClinica | `py -m etl.carga_inicial` | Una vez |
| **ETL 1** CSV diarios → BDClinica | `py -m etl.carga_diaria` | **Diaria** |
| **ETL 2** BDClinica → DWClinica | `py -m etl.datamart --modulos transaccional` | **Diaria** (después del ETL 1) |
| Inventario físico de farmacia | `py -m etl.datamart --modulos inventario` | Mensual |
| Metas / feriados | `py -m etl.datamart --modulos metas` / `feriados` | Anual |

Programación diaria (23:30): `scripts/ejecutar_diario.sh` con cron (`30 23 * * * /ruta/scripts/ejecutar_diario.sh`; `DRY_RUN=1` solo imprime los comandos) o `scripts/ejecutar_diario.bat` con el Programador de tareas de Windows.

## Reportería con Power BI

El ETL **no genera archivos** para el informe: carga tablas en DWClinica y Power BI se conecta a esa base (SQL Server → Importar o DirectQuery, base `DWClinica`).

| Objeto | Contenido |
|---|---|
| `dw.*` | Modelo dimensional: 6 hechos (`FactCita`, `FactCapacidad`, `FactPrescripcion`, `FactFacturacionLinea`, `FactInventarioLote`, `FactMeta`) y 11 dimensiones |
| `rpt.KpiMensual` | Los 7 indicadores por mes con su meta |
| `rpt.KpiMensualEspecialidad` | Inasistencia y espera por mes y especialidad |
| `rpt.CalidadDatos`, `rpt.PruebasCuadre` | Resultado del perfilamiento y de las 14 pruebas, por carga |
| `rpt.vw_UltimaCarga`, `rpt.vw_CalidadDatos_Ultima`, `rpt.vw_PruebasCuadre_Ultima`, `rpt.vw_Rechazos_Ultima` | Vistas de la última carga |
| `etl.BitacoraCarga`, `etl.RechazoCarga` | Bitácora y rechazos del ETL |

`seg.MapaPaciente` (relación entre el paciente anonimizado y el DNI) **no** se expone a Power BI: el rol `rol_bi_lector` solo lee `dw` y `rpt`.

## Prueba sin servidor

`py -m etl.carga_inicial --solo-validar`, `py -m etl.carga_diaria --solo-validar --referencia data/inicial` y `py -m etl.datamart --origen csv --destino csv` (escribe en `data/salida_pruebas`, que no se versiona) ejecutan extracción, transformación y validación sin SQL Server.

## Qué se versiona

Se suben: `database/`, `etl/`, `scripts/`, `tools/`, `docs/`, `data/` de ejemplo (sintéticos), `.env.example`. **No** se suben: `.env`, `logs/`, `data/procesados`, `data/rechazos`, `data/salida_pruebas` (ver `.gitignore`). Los datos son sintéticos; no contienen personas reales.
