/* =====================================================================================
   02_crear_esquema_etl.sql  -  Control de la carga diaria en BDClinica (esquema etl)
   Ejecutar despues de 01_crear_bdclinica.sql y antes de la primera carga diaria (python -m etl.carga_diaria).
   ===================================================================================== */
USE BDClinica;
GO
IF SCHEMA_ID('etl') IS NULL EXEC('CREATE SCHEMA etl');
GO
IF OBJECT_ID('etl.CargaDiaria') IS NULL
CREATE TABLE etl.CargaDiaria (                      -- una fila por tabla y por fecha de lote
    id_control    INT IDENTITY(1,1) CONSTRAINT PK_CargaDiaria PRIMARY KEY,
    fecha_lote    CHAR(8)      NOT NULL,            -- AAAAMMDD del nombre del CSV
    tabla         VARCHAR(30)  NOT NULL,
    leidas        INT NOT NULL, insertadas INT NOT NULL, ya_existentes INT NOT NULL, rechazadas INT NOT NULL,
    procesado     DATETIME2    NOT NULL CONSTRAINT DF_CargaDiaria_proc DEFAULT SYSDATETIME());
GO
IF OBJECT_ID('etl.RechazoDiario') IS NULL
CREATE TABLE etl.RechazoDiario (                    -- filas del CSV que no pasaron la validacion, con su motivo
    id_rechazo    INT IDENTITY(1,1) CONSTRAINT PK_RechazoDiario PRIMARY KEY,
    fecha_lote    CHAR(8)      NOT NULL,
    tabla         VARCHAR(30)  NOT NULL,
    clave         NVARCHAR(100) NULL,               -- llave primaria del registro rechazado
    motivo        NVARCHAR(500) NOT NULL,
    procesado     DATETIME2    NOT NULL CONSTRAINT DF_RechazoDiario_proc DEFAULT SYSDATETIME());
GO
