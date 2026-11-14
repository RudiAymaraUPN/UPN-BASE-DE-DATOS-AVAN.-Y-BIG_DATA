/* =====================================================================================
   01_crear_dwclinica.sql  -  Data mart dimensional DWClinica (SQL Server)
   Esquemas: dw (dimensiones y hechos) | seg (mapa de anonimizacion) | etl (bitacora y rechazos) | rpt (reporteria, ver 03_crear_reporteria.sql)
   Ejecutar en SSMS conectado a FALCON-X\SQLEXPRESS. Es re-ejecutable: recrea la base desde cero.
   ===================================================================================== */
BEGIN TRANSACTION;
USE master;
GO
IF DB_ID('DWClinica') IS NOT NULL
BEGIN
    ALTER DATABASE DWClinica SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE DWClinica;
END
GO
CREATE DATABASE DWClinica;
GO
USE DWClinica;
GO
CREATE SCHEMA dw;  
GO
CREATE SCHEMA seg; 
GO
CREATE SCHEMA etl; 
GO

/* ------------------------------- DIMENSIONES ------------------------------- */
CREATE TABLE dw.DimFecha (
    fecha_key INT NOT NULL CONSTRAINT PK_DimFecha PRIMARY KEY,            -- AAAAMMDD
    fecha DATE NOT NULL, anio SMALLINT NOT NULL, trimestre TINYINT NOT NULL, mes TINYINT NOT NULL,
    nombre_mes NVARCHAR(12) NOT NULL, anio_mes CHAR(7) NOT NULL, semana_iso TINYINT NOT NULL,
    dia_semana NVARCHAR(10) NOT NULL, es_feriado BIT NOT NULL, descripcion_feriado NVARCHAR(60) NULL);
CREATE TABLE dw.DimPaciente (
    paciente_key INT NOT NULL CONSTRAINT PK_DimPaciente PRIMARY KEY,
    sexo NVARCHAR(10) NOT NULL, grupo_etario_actual NVARCHAR(25) NOT NULL, distrito NVARCHAR(60) NOT NULL);   -- sin DNI, nombre, telefono, correo ni direccion
CREATE TABLE dw.DimEspecialidad (
    especialidad_key INT NOT NULL CONSTRAINT PK_DimEspecialidad PRIMARY KEY,
    especialidad NVARCHAR(80) NOT NULL, duracion_cita_min SMALLINT NOT NULL);                                   -- duracion: parametro del DW (la base no la guarda)
CREATE TABLE dw.DimPersonal (
    personal_key INT NOT NULL CONSTRAINT PK_DimPersonal PRIMARY KEY,
    profesional NVARCHAR(150) NOT NULL, cargo NVARCHAR(60) NULL, especialidad_principal NVARCHAR(80) NOT NULL, nro_colegiatura NVARCHAR(30) NULL);
CREATE TABLE dw.DimEstadoCita (
    estado_key INT NOT NULL CONSTRAINT PK_DimEstadoCita PRIMARY KEY,
    estado NVARCHAR(20) NOT NULL, cuenta_para_inasistencia BIT NOT NULL);
CREATE TABLE dw.DimDiagnostico (
    diagnostico_key INT NOT NULL CONSTRAINT PK_DimDiagnostico PRIMARY KEY,                                   -- -1 No codificado, 0 Sin atencion
    diagnostico NVARCHAR(150) NOT NULL CONSTRAINT UQ_DimDiagnostico UNIQUE);
CREATE TABLE dw.DimFarmaco (
    farmaco_key INT NOT NULL CONSTRAINT PK_DimFarmaco PRIMARY KEY,
    farmaco NVARCHAR(150) NOT NULL, presentacion NVARCHAR(80) NULL, precio_vigente DECIMAL(10,2) NOT NULL, stock_minimo INT NOT NULL);
CREATE TABLE dw.DimLote (
    lote_key INT NOT NULL CONSTRAINT PK_DimLote PRIMARY KEY,
    nro_lote NVARCHAR(40) NOT NULL, fec_lote DATE NOT NULL, fec_vencimiento DATE NOT NULL,
    farmaco_key INT NOT NULL CONSTRAINT FK_DimLote_Farmaco REFERENCES dw.DimFarmaco(farmaco_key));           -- copo de nieve controlado
CREATE TABLE dw.DimServicio (
    servicio_key INT NOT NULL CONSTRAINT PK_DimServicio PRIMARY KEY, servicio NVARCHAR(150) NOT NULL, precio_vigente DECIMAL(10,2) NOT NULL);
CREATE TABLE dw.DimMetodoPago (
    metodo_key INT NOT NULL CONSTRAINT PK_DimMetodoPago PRIMARY KEY, metodo_pago NVARCHAR(20) NOT NULL, tipo NVARCHAR(20) NOT NULL);
CREATE TABLE dw.DimIndicador (
    indicador_key INT NOT NULL CONSTRAINT PK_DimIndicador PRIMARY KEY,
    indicador NVARCHAR(80) NOT NULL, unidad NVARCHAR(30) NOT NULL, sentido NVARCHAR(20) NOT NULL, area_responsable NVARCHAR(60) NOT NULL);

/* --------------------------------- HECHOS --------------------------------- */
CREATE TABLE dw.FactCita (                     -- grano: una cita (cualquier estado); su atencion 1:0..1 va en la misma fila
    id_cita INT NOT NULL CONSTRAINT PK_FactCita PRIMARY KEY,
    fecha_key INT NOT NULL CONSTRAINT FK_FCita_Fecha REFERENCES dw.DimFecha(fecha_key),
    paciente_key INT NOT NULL CONSTRAINT FK_FCita_Paciente REFERENCES dw.DimPaciente(paciente_key),
    personal_key INT NOT NULL CONSTRAINT FK_FCita_Personal REFERENCES dw.DimPersonal(personal_key),
    especialidad_key INT NOT NULL CONSTRAINT FK_FCita_Especialidad REFERENCES dw.DimEspecialidad(especialidad_key),
    estado_key INT NOT NULL CONSTRAINT FK_FCita_Estado REFERENCES dw.DimEstadoCita(estado_key),
    diagnostico_key INT NOT NULL CONSTRAINT FK_FCita_Diagnostico REFERENCES dw.DimDiagnostico(diagnostico_key),
    cantidad_cita TINYINT NOT NULL, flag_atendida BIT NOT NULL, flag_no_asistida BIT NOT NULL, flag_cancelada BIT NOT NULL,
    flag_sin_cierre BIT NOT NULL, flag_pendiente BIT NOT NULL, minutos_programados SMALLINT NOT NULL,
    minutos_espera INT NULL, flag_espera_valida BIT NOT NULL,
    CONSTRAINT CK_FCita_flags CHECK (CAST(flag_atendida AS INT)+flag_no_asistida+flag_cancelada+flag_sin_cierre+flag_pendiente = 1));
CREATE TABLE dw.FactCapacidad (                -- grano: un turno de un profesional en una fecha no feriada
    fecha_key INT NOT NULL CONSTRAINT FK_FCap_Fecha REFERENCES dw.DimFecha(fecha_key),
    id_horario INT NOT NULL,
    personal_key INT NOT NULL CONSTRAINT FK_FCap_Personal REFERENCES dw.DimPersonal(personal_key),
    especialidad_key INT NOT NULL CONSTRAINT FK_FCap_Especialidad REFERENCES dw.DimEspecialidad(especialidad_key),
    turnos_programados TINYINT NOT NULL, minutos_disponibles INT NOT NULL, cupos_disponibles INT NOT NULL,
    CONSTRAINT PK_FactCapacidad PRIMARY KEY (fecha_key, id_horario));
CREATE TABLE dw.FactPrescripcion (             -- grano: un farmaco prescrito dentro de una receta
    id_detalle_receta INT NOT NULL CONSTRAINT PK_FactPrescripcion PRIMARY KEY, id_receta INT NOT NULL,
    fecha_key INT NOT NULL CONSTRAINT FK_FPre_Fecha REFERENCES dw.DimFecha(fecha_key),
    paciente_key INT NOT NULL CONSTRAINT FK_FPre_Paciente REFERENCES dw.DimPaciente(paciente_key),
    personal_key INT NOT NULL CONSTRAINT FK_FPre_Personal REFERENCES dw.DimPersonal(personal_key),
    especialidad_key INT NOT NULL CONSTRAINT FK_FPre_Especialidad REFERENCES dw.DimEspecialidad(especialidad_key),
    diagnostico_key INT NOT NULL CONSTRAINT FK_FPre_Diagnostico REFERENCES dw.DimDiagnostico(diagnostico_key),
    farmaco_key INT NOT NULL CONSTRAINT FK_FPre_Farmaco REFERENCES dw.DimFarmaco(farmaco_key),
    cantidad_prescrita INT NOT NULL);
CREATE TABLE dw.FactFacturacionLinea (         -- grano: una linea de comprobante (servicio o farmaco); id_factura degenerada
    id_detalle_factura INT NOT NULL CONSTRAINT PK_FactFacturacionLinea PRIMARY KEY, id_factura INT NOT NULL,
    fecha_key INT NOT NULL CONSTRAINT FK_FFac_Fecha REFERENCES dw.DimFecha(fecha_key),
    paciente_key INT NOT NULL CONSTRAINT FK_FFac_Paciente REFERENCES dw.DimPaciente(paciente_key),
    servicio_key INT NOT NULL CONSTRAINT FK_FFac_Servicio REFERENCES dw.DimServicio(servicio_key),
    farmaco_key INT NOT NULL CONSTRAINT FK_FFac_Farmaco REFERENCES dw.DimFarmaco(farmaco_key),
    metodo_key INT NOT NULL CONSTRAINT FK_FFac_Metodo REFERENCES dw.DimMetodoPago(metodo_key),
    cantidad INT NOT NULL, precio_unitario DECIMAL(10,2) NOT NULL, monto DECIMAL(12,2) NOT NULL,
    CONSTRAINT CK_FFac_monto CHECK (monto = ROUND(cantidad * precio_unitario, 2)));
CREATE TABLE dw.FactInventarioLote (           -- grano: un lote en una fecha de corte mensual (instantanea periodica)
    fecha_corte_key INT NOT NULL CONSTRAINT FK_FInv_Fecha REFERENCES dw.DimFecha(fecha_key),
    lote_key INT NOT NULL CONSTRAINT FK_FInv_Lote REFERENCES dw.DimLote(lote_key),
    farmaco_key INT NOT NULL CONSTRAINT FK_FInv_Farmaco REFERENCES dw.DimFarmaco(farmaco_key),
    stock_fisico INT NOT NULL, valor_stock DECIMAL(12,2) NOT NULL, dias_para_vencer INT NOT NULL, estado_vencimiento NVARCHAR(20) NOT NULL,
    CONSTRAINT PK_FactInventarioLote PRIMARY KEY (fecha_corte_key, lote_key));
CREATE TABLE dw.FactMeta (                     -- grano: la meta mensual de un indicador
    indicador_key INT NOT NULL CONSTRAINT FK_FMeta_Indicador REFERENCES dw.DimIndicador(indicador_key),
    anio_mes CHAR(7) NOT NULL, valor_meta DECIMAL(12,2) NOT NULL,
    CONSTRAINT PK_FactMeta PRIMARY KEY (indicador_key, anio_mes));

/* ----------------------- INDICES DE APOYO AL TABLERO ----------------------- */
CREATE INDEX IX_FCita_fecha ON dw.FactCita(fecha_key) INCLUDE (especialidad_key, flag_atendida, flag_no_asistida, minutos_espera);
CREATE INDEX IX_FCita_esp   ON dw.FactCita(especialidad_key, fecha_key);
CREATE INDEX IX_FCap_fecha  ON dw.FactCapacidad(fecha_key) INCLUDE (especialidad_key, turnos_programados, cupos_disponibles);
CREATE INDEX IX_FPre_farm   ON dw.FactPrescripcion(farmaco_key, fecha_key);
CREATE INDEX IX_FFac_fecha  ON dw.FactFacturacionLinea(fecha_key) INCLUDE (monto, id_factura);
CREATE INDEX IX_FInv_corte  ON dw.FactInventarioLote(fecha_corte_key) INCLUDE (farmaco_key, stock_fisico, valor_stock, dias_para_vencer);
CREATE INDEX IX_DimFecha_am ON dw.DimFecha(anio_mes);

/* --------------------- SEGURIDAD: MAPA DE ANONIMIZACION -------------------- */
CREATE TABLE seg.MapaPaciente (
    paciente_key INT NOT NULL CONSTRAINT PK_MapaPaciente PRIMARY KEY CONSTRAINT FK_Mapa_Paciente REFERENCES dw.DimPaciente(paciente_key),
    id_paciente_origen INT NOT NULL CONSTRAINT UQ_Mapa_origen UNIQUE,
    dni_hash CHAR(64) NOT NULL);                                                                              -- SHA-256(sal + DNI); la sal vive en el .env del ETL

/* ----------------------- CONTROL: BITACORA Y RECHAZOS ---------------------- */
CREATE TABLE etl.BitacoraCarga (
    id_carga VARCHAR(25) NOT NULL CONSTRAINT PK_BitacoraCarga PRIMARY KEY,
    inicio DATETIME2 NOT NULL, fin DATETIME2 NULL, modulos VARCHAR(80) NOT NULL,
    filas_leidas INT NOT NULL, filas_cargadas INT NOT NULL, rechazos INT NOT NULL, advertencias INT NOT NULL,
    pruebas_ok TINYINT NOT NULL, pruebas_total TINYINT NOT NULL, estado VARCHAR(12) NOT NULL);
CREATE TABLE etl.RechazoCarga (
    id_rechazo INT IDENTITY(1,1) CONSTRAINT PK_RechazoCarga PRIMARY KEY,
    id_carga VARCHAR(25) NOT NULL CONSTRAINT FK_Rechazo_Bitacora REFERENCES etl.BitacoraCarga(id_carga),
    fuente CHAR(2) NOT NULL, tabla NVARCHAR(40) NOT NULL, clave_origen NVARCHAR(60) NOT NULL, motivo NVARCHAR(200) NOT NULL,
    nivel VARCHAR(12) NOT NULL CONSTRAINT CK_Rechazo_nivel CHECK (nivel IN ('RECHAZO','ADVERTENCIA')));

/* ------------------------------- ROLES ------------------------------------ */
CREATE ROLE rol_etl_dw;  CREATE ROLE rol_bi_lector;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dw  TO rol_etl_dw;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::seg TO rol_etl_dw;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::etl TO rol_etl_dw;
GRANT SELECT ON SCHEMA::dw TO rol_bi_lector;
DENY  SELECT ON SCHEMA::seg TO rol_bi_lector;                         -- el tablero nunca ve el mapa de pacientes
GO

COMMIT TRANSACTION;
/* ------------------------------ VERIFICACION ------------------------------ */
SELECT (SELECT COUNT(*) FROM sys.tables WHERE schema_id = SCHEMA_ID('dw'))  AS tablas_dw,
       (SELECT COUNT(*) FROM sys.foreign_keys WHERE SCHEMA_NAME(schema_id) = 'dw') AS fk_dw,
       (SELECT COUNT(*) FROM sys.check_constraints WHERE SCHEMA_NAME(schema_id) = 'dw') AS check_dw;
