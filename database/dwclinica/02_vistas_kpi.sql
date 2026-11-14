/* =====================================================================================
   02_vistas_kpi.sql  -  Vistas de los 7 indicadores (DWClinica). Misma logica que calcular_kpis() de etl/datamart.py
   ===================================================================================== */
USE DWClinica;
GO
CREATE OR ALTER VIEW dw.vw_kpi_citas AS               -- KPI 1 (inasistencia) y KPI 3 (espera) por mes y especialidad
SELECT f.anio_mes, e.especialidad,
       SUM(CAST(c.flag_atendida AS INT)) AS atendidas, SUM(CAST(c.flag_no_asistida AS INT)) AS no_asistidas,
       CAST(100.0 * SUM(CAST(c.flag_no_asistida AS INT)) / NULLIF(SUM(CAST(c.flag_atendida AS INT)) + SUM(CAST(c.flag_no_asistida AS INT)), 0) AS DECIMAL(6,2)) AS inasistencia_pct,
       CAST(AVG(CAST(c.minutos_espera AS FLOAT)) AS DECIMAL(6,2)) AS espera_prom_min
FROM dw.FactCita c JOIN dw.DimFecha f ON f.fecha_key = c.fecha_key JOIN dw.DimEspecialidad e ON e.especialidad_key = c.especialidad_key
GROUP BY f.anio_mes, e.especialidad;
GO
CREATE OR ALTER VIEW dw.vw_kpi2_kpi4_capacidad AS     -- KPI 2 (ocupacion) y KPI 4 (productividad). Se agregan por separado y recien se dividen (RN-17)
WITH cit AS (SELECT f.anio_mes, SUM(CAST(c.flag_atendida AS INT)) AS atendidas
             FROM dw.FactCita c JOIN dw.DimFecha f ON f.fecha_key = c.fecha_key GROUP BY f.anio_mes),
     cap AS (SELECT f.anio_mes, SUM(k.turnos_programados) AS turnos, SUM(k.cupos_disponibles) AS cupos
             FROM dw.FactCapacidad k JOIN dw.DimFecha f ON f.fecha_key = k.fecha_key GROUP BY f.anio_mes)
SELECT cap.anio_mes, cit.atendidas, cap.turnos, cap.cupos,
       CAST(100.0 * cit.atendidas / NULLIF(cap.cupos, 0) AS DECIMAL(6,2)) AS ocupacion_pct,
       CAST(1.0 * cit.atendidas / NULLIF(cap.turnos, 0) AS DECIMAL(8,3)) AS atenciones_por_turno
FROM cap LEFT JOIN cit ON cit.anio_mes = cap.anio_mes;
GO
CREATE OR ALTER VIEW dw.vw_kpi5_ingresos AS            -- KPI 5: ingresos de las lineas (RN-16) frente a la meta de gerencia
SELECT f.anio_mes, SUM(l.monto) AS ingresos, COUNT(DISTINCT l.id_factura) AS comprobantes,
       CAST(SUM(l.monto) / NULLIF(COUNT(DISTINCT l.id_factura), 0) AS DECIMAL(10,2)) AS ticket_promedio,
       MAX(m.valor_meta) AS meta, CAST(100.0 * SUM(l.monto) / NULLIF(MAX(m.valor_meta), 0) AS DECIMAL(6,2)) AS cumplimiento_pct
FROM dw.FactFacturacionLinea l JOIN dw.DimFecha f ON f.fecha_key = l.fecha_key
LEFT JOIN dw.FactMeta m ON m.anio_mes = f.anio_mes AND m.indicador_key = (SELECT indicador_key FROM dw.DimIndicador WHERE indicador = 'Ingresos totales')
GROUP BY f.anio_mes;
GO
CREATE OR ALTER VIEW dw.vw_kpi6_kpi7_farmacia AS       -- KPI 6 y 7 por corte. El stock es semiaditivo (RN-18): se suma dentro de un corte, nunca entre cortes
WITH riesgo AS (SELECT f.anio_mes, i.fecha_corte_key, SUM(CASE WHEN i.dias_para_vencer <= 90 THEN i.valor_stock ELSE 0 END) AS valor_en_riesgo
                FROM dw.FactInventarioLote i JOIN dw.DimFecha f ON f.fecha_key = i.fecha_corte_key GROUP BY f.anio_mes, i.fecha_corte_key),
     vig AS (SELECT i.fecha_corte_key, d.farmaco_key, d.stock_minimo, SUM(CASE WHEN i.dias_para_vencer >= 0 THEN i.stock_fisico ELSE 0 END) AS stock_vigente
             FROM dw.DimFarmaco d LEFT JOIN dw.FactInventarioLote i ON i.farmaco_key = d.farmaco_key
             WHERE d.farmaco_key > 0 AND i.fecha_corte_key IS NOT NULL GROUP BY i.fecha_corte_key, d.farmaco_key, d.stock_minimo)
SELECT r.anio_mes, r.fecha_corte_key, r.valor_en_riesgo,
       (SELECT COUNT(*) FROM dw.DimFarmaco x WHERE x.farmaco_key > 0 AND ISNULL((SELECT v.stock_vigente FROM vig v WHERE v.fecha_corte_key = r.fecha_corte_key AND v.farmaco_key = x.farmaco_key), 0) < x.stock_minimo) AS farmacos_bajo_minimo
FROM riesgo r;
GO
CREATE OR ALTER VIEW dw.vw_kpi_resumen AS              -- tablero: una fila por mes con los 7 indicadores y su meta
SELECT i.anio_mes, c.inasistencia_pct, c.espera_prom_min, k.ocupacion_pct, k.atenciones_por_turno, g.ingresos, g.meta AS meta_ingresos, g.cumplimiento_pct,
       f.valor_en_riesgo, f.farmacos_bajo_minimo
FROM (SELECT DISTINCT anio_mes FROM dw.DimFecha WHERE anio_mes BETWEEN '2025-11' AND '2026-12') i
LEFT JOIN (SELECT f2.anio_mes,
                  CAST(100.0 * SUM(CAST(c2.flag_no_asistida AS INT)) / NULLIF(SUM(CAST(c2.flag_atendida AS INT)) + SUM(CAST(c2.flag_no_asistida AS INT)), 0) AS DECIMAL(6,2)) AS inasistencia_pct,
                  CAST(AVG(CAST(c2.minutos_espera AS FLOAT)) AS DECIMAL(6,2)) AS espera_prom_min
           FROM dw.FactCita c2 JOIN dw.DimFecha f2 ON f2.fecha_key = c2.fecha_key GROUP BY f2.anio_mes) c ON c.anio_mes = i.anio_mes
LEFT JOIN dw.vw_kpi2_kpi4_capacidad k ON k.anio_mes = i.anio_mes
LEFT JOIN dw.vw_kpi5_ingresos g ON g.anio_mes = i.anio_mes
LEFT JOIN dw.vw_kpi6_kpi7_farmacia f ON f.anio_mes = i.anio_mes;
GO
