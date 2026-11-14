/* =====================================================================================
   03_crear_reporteria.sql  -  Esquema rpt de DWClinica: tablas de reporteria para Power BI
   Orden: 01_crear_dwclinica.sql -> 02_vistas_kpi.sql -> este script.
   Power BI se conecta a DWClinica (Importar o DirectQuery) y usa:
     dw.*   modelo dimensional (hechos y dimensiones)   para analisis libre
     rpt.*  indicadores, calidad y pruebas YA calculados por el ETL (una fila por mes / por carga)
   El ETL (python -m etl.datamart) llena rpt.* en la misma transaccion que dw.*; no se generan archivos.
   ===================================================================================== */
BEGIN TRANSACTION;
USE DWClinica;
GO
/* ---------- Precondiciones: si algo falta, el script se detiene aqui y NO crea nada en otra base ---------- */
IF DB_NAME() <> 'DWClinica'
   OR OBJECT_ID('etl.BitacoraCarga') IS NULL
   OR OBJECT_ID('dw.vw_kpi_resumen') IS NULL
   OR OBJECT_ID('dw.vw_kpi2_kpi4_capacidad') IS NULL
   OR OBJECT_ID('dw.vw_kpi5_ingresos') IS NULL
   OR OBJECT_ID('dw.vw_kpi_citas') IS NULL
BEGIN
    RAISERROR('NO SE CREO rpt. Verifique: (1) la base activa es DWClinica, (2) se ejecuto 01_crear_dwclinica.sql, (3) se ejecuto 02_vistas_kpi.sql. Ejecute este script DESPUES de 01 y 02, y no vuelva a ejecutar 01 despues (borra la base).', 16, 1);
    SET NOEXEC ON;
END
GO
IF SCHEMA_ID('rpt') IS NULL EXEC('CREATE SCHEMA rpt');
GO

/* ---------- KPI mensuales (se reconstruyen completos en cada carga desde dw.vw_kpi_*) ---------- */
IF OBJECT_ID('rpt.KpiMensual') IS NULL
CREATE TABLE rpt.KpiMensual (
    anio_mes             CHAR(7)       NOT NULL CONSTRAINT PK_rpt_KpiMensual PRIMARY KEY,
    atendidas            INT           NOT NULL,
    no_asistidas         INT           NOT NULL,
    inasistencia_pct     DECIMAL(6,2)  NULL,      -- KPI 1
    ocupacion_pct        DECIMAL(6,2)  NULL,      -- KPI 2
    espera_prom_min      DECIMAL(6,2)  NULL,      -- KPI 3
    atenciones_por_turno DECIMAL(8,3)  NULL,      -- KPI 4
    ingresos             DECIMAL(12,2) NULL,      -- KPI 5
    meta_ingresos        DECIMAL(12,2) NULL,
    cumplimiento_pct     DECIMAL(6,2)  NULL,
    valor_en_riesgo      DECIMAL(12,2) NULL,      -- KPI 6 (solo meses con corte de inventario)
    farmacos_bajo_minimo INT           NULL,      -- KPI 7 (solo meses con corte de inventario)
    turnos_programados   INT           NULL,
    cupos_disponibles    INT           NULL,
    comprobantes         INT           NULL,
    ticket_promedio      DECIMAL(10,2) NULL,
    id_carga             VARCHAR(25)   NOT NULL,
    actualizado_en       DATETIME2     NOT NULL CONSTRAINT DF_rpt_KpiMensual_act DEFAULT SYSDATETIME());
GO
IF OBJECT_ID('rpt.KpiMensualEspecialidad') IS NULL
CREATE TABLE rpt.KpiMensualEspecialidad (
    anio_mes         CHAR(7)       NOT NULL,
    especialidad     NVARCHAR(80)  NOT NULL,
    atendidas        INT           NOT NULL,
    no_asistidas     INT           NOT NULL,
    inasistencia_pct DECIMAL(6,2)  NULL,
    espera_prom_min  DECIMAL(6,2)  NULL,
    id_carga         VARCHAR(25)   NOT NULL,
    actualizado_en   DATETIME2     NOT NULL CONSTRAINT DF_rpt_KpiEsp_act DEFAULT SYSDATETIME(),
    CONSTRAINT PK_rpt_KpiMensualEspecialidad PRIMARY KEY (anio_mes, especialidad));
GO

/* ---------- Calidad de datos y pruebas de cuadre (historial: una tanda por carga) ---------- */
IF OBJECT_ID('rpt.CalidadDatos') IS NULL
CREATE TABLE rpt.CalidadDatos (
    id_calidad  INT IDENTITY(1,1) CONSTRAINT PK_rpt_CalidadDatos PRIMARY KEY,
    id_carga    VARCHAR(25)   NOT NULL CONSTRAINT FK_rpt_Calidad_Bitacora REFERENCES etl.BitacoraCarga(id_carga),
    fuente      VARCHAR(4)    NOT NULL, tabla NVARCHAR(40) NOT NULL, problema NVARCHAR(200) NOT NULL,
    registros   INT NOT NULL, total INT NOT NULL, pct DECIMAL(6,2) NOT NULL, tratamiento NVARCHAR(250) NOT NULL);
GO
IF OBJECT_ID('rpt.PruebasCuadre') IS NULL
CREATE TABLE rpt.PruebasCuadre (
    id_prueba   INT IDENTITY(1,1) CONSTRAINT PK_rpt_PruebasCuadre PRIMARY KEY,
    id_carga    VARCHAR(25)   NOT NULL CONSTRAINT FK_rpt_Pruebas_Bitacora REFERENCES etl.BitacoraCarga(id_carga),
    prueba      VARCHAR(5)    NOT NULL, descripcion NVARCHAR(200) NOT NULL,
    fuente      NVARCHAR(30)  NULL, data_mart NVARCHAR(30) NULL,
    resultado   VARCHAR(10)   NOT NULL);
GO

/* ---------- Vistas de la ultima carga (lo que normalmente consume el informe) ---------- */
CREATE OR ALTER VIEW rpt.vw_UltimaCarga AS
SELECT TOP (1) id_carga, inicio, fin, modulos, filas_leidas, filas_cargadas, rechazos, advertencias, pruebas_ok, pruebas_total, estado
FROM etl.BitacoraCarga ORDER BY inicio DESC;
GO
CREATE OR ALTER VIEW rpt.vw_CalidadDatos_Ultima AS
SELECT c.* FROM rpt.CalidadDatos c WHERE c.id_carga = (SELECT id_carga FROM rpt.vw_UltimaCarga);
GO
CREATE OR ALTER VIEW rpt.vw_PruebasCuadre_Ultima AS
SELECT p.* FROM rpt.PruebasCuadre p WHERE p.id_carga = (SELECT id_carga FROM rpt.vw_UltimaCarga);
GO
CREATE OR ALTER VIEW rpt.vw_Rechazos_Ultima AS
SELECT r.* FROM etl.RechazoCarga r WHERE r.id_carga = (SELECT id_carga FROM rpt.vw_UltimaCarga);
GO

/* ---------- Procedimiento que recalcula los KPI (lo llama el ETL al final de cada carga) ---------- */
CREATE OR ALTER PROCEDURE rpt.usp_refrescar_kpi @id_carga VARCHAR(25) AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM rpt.KpiMensual;
    INSERT INTO rpt.KpiMensual (anio_mes, atendidas, no_asistidas, inasistencia_pct, ocupacion_pct, espera_prom_min, atenciones_por_turno, ingresos, meta_ingresos,
                                cumplimiento_pct, valor_en_riesgo, farmacos_bajo_minimo, turnos_programados, cupos_disponibles, comprobantes, ticket_promedio, id_carga)
    SELECT r.anio_mes, ISNULL(c.atendidas, 0), ISNULL(c.no_asistidas, 0), r.inasistencia_pct, r.ocupacion_pct, r.espera_prom_min, r.atenciones_por_turno, r.ingresos, r.meta_ingresos,
           r.cumplimiento_pct, r.valor_en_riesgo, r.farmacos_bajo_minimo, k.turnos, k.cupos, g.comprobantes, g.ticket_promedio, @id_carga
    FROM dw.vw_kpi_resumen r
    LEFT JOIN dw.vw_kpi2_kpi4_capacidad k ON k.anio_mes = r.anio_mes
    LEFT JOIN dw.vw_kpi5_ingresos g       ON g.anio_mes = r.anio_mes
    LEFT JOIN (SELECT f.anio_mes, SUM(CAST(ci.flag_atendida AS INT)) AS atendidas, SUM(CAST(ci.flag_no_asistida AS INT)) AS no_asistidas
               FROM dw.FactCita ci JOIN dw.DimFecha f ON f.fecha_key = ci.fecha_key GROUP BY f.anio_mes) c ON c.anio_mes = r.anio_mes;

    DELETE FROM rpt.KpiMensualEspecialidad;
    INSERT INTO rpt.KpiMensualEspecialidad (anio_mes, especialidad, atendidas, no_asistidas, inasistencia_pct, espera_prom_min, id_carga)
    SELECT anio_mes, especialidad, atendidas, no_asistidas, inasistencia_pct, espera_prom_min, @id_carga FROM dw.vw_kpi_citas;
END;
GO

/* ---------- Permisos: Power BI solo lee; el ETL escribe y ejecuta ---------- */
GRANT SELECT ON SCHEMA::rpt TO rol_bi_lector;
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON SCHEMA::rpt TO rol_etl_dw;
GO
SET NOEXEC OFF;
GO
/* ---------- Verificacion: deben salir 4 tablas, 4 vistas y 1 procedimiento ---------- */
SELECT name AS objeto_rpt, type_desc FROM sys.objects WHERE schema_id = SCHEMA_ID('rpt') AND type IN ('U','V','P') ORDER BY type_desc, name;
GO
COMMIT TRANSACTION;