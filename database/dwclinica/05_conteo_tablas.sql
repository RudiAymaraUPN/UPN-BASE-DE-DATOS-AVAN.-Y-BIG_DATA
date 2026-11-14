/* 05_conteo_tablas.sql - conteo de filas por tabla de DWClinica (verificacion despues de la carga del data mart) */
USE DWClinica;
GO

SELECT * FROM (
SELECT 'DIMENSION' AS tipo, 'dw.DimFecha' AS tabla, COUNT(1) AS filas FROM dw.DimFecha
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimPaciente' AS tabla, COUNT(1) AS filas FROM dw.DimPaciente
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimEspecialidad' AS tabla, COUNT(1) AS filas FROM dw.DimEspecialidad
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimPersonal' AS tabla, COUNT(1) AS filas FROM dw.DimPersonal
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimEstadoCita' AS tabla, COUNT(1) AS filas FROM dw.DimEstadoCita
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimDiagnostico' AS tabla, COUNT(1) AS filas FROM dw.DimDiagnostico
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimFarmaco' AS tabla, COUNT(1) AS filas FROM dw.DimFarmaco
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimLote' AS tabla, COUNT(1) AS filas FROM dw.DimLote
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimServicio' AS tabla, COUNT(1) AS filas FROM dw.DimServicio
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimMetodoPago' AS tabla, COUNT(1) AS filas FROM dw.DimMetodoPago
UNION ALL
SELECT 'DIMENSION' AS tipo, 'dw.DimIndicador' AS tabla, COUNT(1) AS filas FROM dw.DimIndicador
UNION ALL
SELECT 'HECHO' AS tipo, 'dw.FactCita' AS tabla, COUNT(1) AS filas FROM dw.FactCita
UNION ALL
SELECT 'HECHO' AS tipo, 'dw.FactCapacidad' AS tabla, COUNT(1) AS filas FROM dw.FactCapacidad
UNION ALL
SELECT 'HECHO' AS tipo, 'dw.FactPrescripcion' AS tabla, COUNT(1) AS filas FROM dw.FactPrescripcion
UNION ALL
SELECT 'HECHO' AS tipo, 'dw.FactFacturacionLinea' AS tabla, COUNT(1) AS filas FROM dw.FactFacturacionLinea
UNION ALL
SELECT 'HECHO' AS tipo, 'dw.FactInventarioLote' AS tabla, COUNT(1) AS filas FROM dw.FactInventarioLote
UNION ALL
SELECT 'HECHO' AS tipo, 'dw.FactMeta' AS tabla, COUNT(1) AS filas FROM dw.FactMeta
UNION ALL
SELECT 'SEGURIDAD' AS tipo, 'seg.MapaPaciente' AS tabla, COUNT(1) AS filas FROM seg.MapaPaciente
UNION ALL
SELECT 'CONTROL' AS tipo, 'etl.BitacoraCarga' AS tabla, COUNT(1) AS filas FROM etl.BitacoraCarga
UNION ALL
SELECT 'CONTROL' AS tipo, 'etl.RechazoCarga' AS tabla, COUNT(1) AS filas FROM etl.RechazoCarga
UNION ALL
SELECT 'REPORTERIA' AS tipo, 'rpt.KpiMensual' AS tabla, COUNT(1) AS filas FROM rpt.KpiMensual
UNION ALL
SELECT 'REPORTERIA' AS tipo, 'rpt.KpiMensualEspecialidad' AS tabla, COUNT(1) AS filas FROM rpt.KpiMensualEspecialidad
UNION ALL
SELECT 'REPORTERIA' AS tipo, 'rpt.CalidadDatos' AS tabla, COUNT(1) AS filas FROM rpt.CalidadDatos
UNION ALL
SELECT 'REPORTERIA' AS tipo, 'rpt.PruebasCuadre' AS tabla, COUNT(1) AS filas FROM rpt.PruebasCuadre
) AS c
ORDER BY CASE tipo WHEN 'DIMENSION' THEN 1 WHEN 'HECHO' THEN 2 WHEN 'SEGURIDAD' THEN 3 WHEN 'CONTROL' THEN 4 ELSE 5 END, tabla;
GO

/* Total de filas cargadas en el modelo dimensional (dw): debe coincidir con 'filas_cargadas' de etl.BitacoraCarga + seg */
SELECT SUM(p.rows) AS total_filas_dw
FROM sys.partitions p JOIN sys.tables t ON t.object_id = p.object_id
WHERE SCHEMA_NAME(t.schema_id) = 'dw' AND p.index_id IN (0,1);
GO
