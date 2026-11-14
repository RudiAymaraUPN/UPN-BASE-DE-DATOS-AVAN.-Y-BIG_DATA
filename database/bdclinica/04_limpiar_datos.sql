/* =====================================================================================
   04_limpiar_datos.sql  -  Vacia las tablas de BDClinica para volver a hacer la carga inicial.  SOLO PARA DESARROLLO / PRUEBAS.
   No usa TRUNCATE (no se permite con claves foraneas): borra de hijos a padres y reinicia los contadores IDENTITY.
   ===================================================================================== */
USE BDClinica;
GO
SET XACT_ABORT ON;
BEGIN TRAN;
DELETE FROM clinica.DETALLE_FACTURACION;
DELETE FROM clinica.FACTURACION;
DELETE FROM clinica.DETALLE_RECETA;
DELETE FROM clinica.RECETAS;
DELETE FROM clinica.ATENCIONES;
DELETE FROM clinica.CITAS;
DELETE FROM clinica.LOTES_FARMACOS;
DELETE FROM clinica.FARMACOS;
DELETE FROM clinica.SERVICIOS;
DELETE FROM clinica.PERSONAL_ESPECIALIDAD;
DELETE FROM clinica.HORARIOS_PERSONAL;
DELETE FROM clinica.PERSONAL;
DELETE FROM clinica.PACIENTES;
DELETE FROM clinica.ESPECIALIDADES;
DELETE FROM clinica.CARGOS;
DBCC CHECKIDENT ('clinica.CARGOS', RESEED, 0);
DBCC CHECKIDENT ('clinica.ESPECIALIDADES', RESEED, 0);
DBCC CHECKIDENT ('clinica.PACIENTES', RESEED, 0);
DBCC CHECKIDENT ('clinica.PERSONAL', RESEED, 0);
DBCC CHECKIDENT ('clinica.HORARIOS_PERSONAL', RESEED, 0);
DBCC CHECKIDENT ('clinica.SERVICIOS', RESEED, 0);
DBCC CHECKIDENT ('clinica.FARMACOS', RESEED, 0);
DBCC CHECKIDENT ('clinica.LOTES_FARMACOS', RESEED, 0);
DBCC CHECKIDENT ('clinica.CITAS', RESEED, 0);
DBCC CHECKIDENT ('clinica.ATENCIONES', RESEED, 0);
DBCC CHECKIDENT ('clinica.RECETAS', RESEED, 0);
DBCC CHECKIDENT ('clinica.DETALLE_RECETA', RESEED, 0);
DBCC CHECKIDENT ('clinica.FACTURACION', RESEED, 0);
DBCC CHECKIDENT ('clinica.DETALLE_FACTURACION', RESEED, 0);
COMMIT;
GO
