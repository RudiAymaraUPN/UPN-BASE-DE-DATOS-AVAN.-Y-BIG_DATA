/* =====================================================================================
   04_validacion_cuadre.sql  -  Pruebas de cuadre BDClinica (clinica.*) vs DWClinica (dw.*), dentro del servidor
   Todas deben salir en OK (P10 depende del Excel de inventario: se contrasta con etl.BitacoraCarga / RechazoCarga).
   ===================================================================================== */
SET NOCOUNT ON;
SELECT p.prueba, p.descripcion, p.fuente, p.data_mart,
       CASE WHEN p.fuente = p.data_mart THEN 'OK' ELSE 'ERROR' END AS resultado
FROM (
  SELECT 'P01' AS prueba, 'N.° de citas' AS descripcion, (SELECT COUNT(*) FROM BDClinica.clinica.CITAS) + 0.0 AS fuente, (SELECT COUNT(*) FROM DWClinica.dw.FactCita) + 0.0 AS data_mart
  UNION ALL SELECT 'P02', 'Citas atendidas', (SELECT COUNT(*) FROM BDClinica.clinica.CITAS WHERE estado = 'Atendida'), (SELECT SUM(CAST(flag_atendida AS INT)) FROM DWClinica.dw.FactCita)
  UNION ALL SELECT 'P03', 'Citas no asistidas', (SELECT COUNT(*) FROM BDClinica.clinica.CITAS WHERE estado = 'No asistio'), (SELECT SUM(CAST(flag_no_asistida AS INT)) FROM DWClinica.dw.FactCita)
  UNION ALL SELECT 'P04', 'Atenciones registradas', (SELECT COUNT(*) FROM BDClinica.clinica.ATENCIONES), (SELECT COUNT(*) FROM DWClinica.dw.FactCita WHERE diagnostico_key <> 0)
  UNION ALL SELECT 'P05', 'Lineas de receta', (SELECT COUNT(*) FROM BDClinica.clinica.DETALLE_RECETA), (SELECT COUNT(*) FROM DWClinica.dw.FactPrescripcion)
  UNION ALL SELECT 'P06', 'Unidades prescritas', (SELECT SUM(cantidad) FROM BDClinica.clinica.DETALLE_RECETA), (SELECT SUM(cantidad_prescrita) FROM DWClinica.dw.FactPrescripcion)
  UNION ALL SELECT 'P07', 'Lineas de comprobante', (SELECT COUNT(*) FROM BDClinica.clinica.DETALLE_FACTURACION), (SELECT COUNT(*) FROM DWClinica.dw.FactFacturacionLinea)
  UNION ALL SELECT 'P08', 'Ingresos (S/) suma de lineas', (SELECT SUM(subtotal) FROM BDClinica.clinica.DETALLE_FACTURACION), (SELECT SUM(monto) FROM DWClinica.dw.FactFacturacionLinea)
  UNION ALL SELECT 'P09', 'N.° de comprobantes con lineas', (SELECT COUNT(DISTINCT id_factura) FROM BDClinica.clinica.DETALLE_FACTURACION), (SELECT COUNT(DISTINCT id_factura) FROM DWClinica.dw.FactFacturacionLinea)
  UNION ALL SELECT 'P11', 'Columnas identificatorias en DimPaciente', 0,
         (SELECT COUNT(*) FROM DWClinica.sys.columns WHERE object_id = OBJECT_ID('DWClinica.dw.DimPaciente') AND name IN ('dni','nombres','apellidos','telefono','correo','direccion','fecha_nacimiento'))
  UNION ALL SELECT 'P12', 'Claves foraneas huerfanas (cita-paciente)', 0, (SELECT COUNT(*) FROM DWClinica.dw.FactCita c WHERE NOT EXISTS (SELECT 1 FROM DWClinica.dw.DimPaciente p WHERE p.paciente_key = c.paciente_key))
  UNION ALL SELECT 'P13', 'Citas duplicadas en FactCita', 0, (SELECT COUNT(*) - COUNT(DISTINCT id_cita) FROM DWClinica.dw.FactCita)
  UNION ALL SELECT 'P14', 'Atenciones con espera valida + excluidas = atenciones',
         (SELECT COUNT(*) FROM BDClinica.clinica.ATENCIONES),
         (SELECT SUM(CAST(flag_espera_valida AS INT)) FROM DWClinica.dw.FactCita) + (SELECT COUNT(*) FROM DWClinica.dw.FactCita WHERE flag_espera_valida = 0 AND diagnostico_key <> 0)
) p ORDER BY p.prueba;
-- Las FK garantizan los demas huerfanos: cualquier clave inexistente habria hecho fallar la carga.
GO
