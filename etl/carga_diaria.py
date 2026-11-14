# -*- coding: utf-8 -*-
r"""
ETL DIARIO (batch)  |  CSV nuevos del programa de la clinica  ->  SQL Server (BDClinica.clinica)

El programa de la clinica deja cada dia, en la carpeta de entrada, un CSV por tabla con los registros NUEVOS:
    PACIENTES_20261112.csv, CITAS_20261112.csv, ATENCIONES_20261112.csv, ...   (TABLA_AAAAMMDD.csv, mismas columnas que BDClinica)
Este ETL procesa en orden cada fecha pendiente (de la mas antigua a la mas nueva):
  1) EXTRACCION      lee los CSV de esa fecha
  2) TRANSFORMACION  valida fila por fila (tipos, obligatorios, dominios, reglas, UNIQUE, llaves foraneas contra la base y contra lo ya aceptado)
  3) CARGA           inserta solo lo nuevo, en UNA transaccion por fecha; lo que ya existe se omite (reproceso seguro / idempotente)
  4) CIERRE          mueve los CSV a procesados/AAAAMMDD/ y deja los rechazos con su motivo en rechazados/
Una fila invalida NO detiene el dia: se rechaza con su motivo (y sus hijos tambien, por la FK). Un error de base de datos si hace ROLLBACK del dia.

Uso (terminal en la RAIZ del repositorio):
    python -m etl.carga_diaria --solo-validar --referencia data/inicial   # prueba sin tocar la base
    python -m etl.carga_diaria                                            # procesa todas las fechas pendientes
    python -m etl.carga_diaria --fecha 20261113                           # solo una fecha
Resultado de cada fecha: filas en BDClinica + resumen en etl.CargaDiaria y rechazos con su motivo en etl.RechazoDiario (tablas, no archivos).
Configuracion en .env: DB_SERVER, DB_NAME, DB_SCHEMA, DB_USER, DB_PASSWORD, DIARIO_RUTA_ENTRADA, DIARIO_RUTA_PROCESADOS, DIARIO_RUTA_RECHAZADOS.
"""
import argparse, glob, os, re, shutil, sys, time, traceback
import pandas as pd

# Permite ejecutar el archivo directamente desde cualquier carpeta (py etl\carga_inicial.py o py .\carga_inicial.py)
import sys as _sys
from pathlib import Path as _Path
_raiz = str(_Path(__file__).resolve().parent.parent)
if _raiz not in _sys.path:
    _sys.path.insert(0, _raiz)

from etl import carga_inicial as base          # SPEC, DOMINIOS, REGLAS, FORMATOS y conexion de la carga inicial
from etl.config import cargar_env, carpeta_logs, ruta

cargar_env()
RUTA_ENTRADA = ruta("DIARIO_RUTA_ENTRADA", "data/entrada_diaria")
RUTA_PROC = ruta("DIARIO_RUTA_PROCESADOS", "data/procesados")
RUTA_RECH = ruta("DIARIO_RUTA_RECHAZADOS", "data/rechazos")      # solo para devolver el detalle al area que envio el CSV
LOG_FILE = None
ORDEN = base.ORDEN


def p(msg=""):
    print(msg)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(str(msg) + "\n")


def log(msg):
    p(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ---------------------------------------------------------------- EXTRACCION
def fechas_pendientes(solo=None):
    fechas = set()
    for ruta in glob.glob(os.path.join(RUTA_ENTRADA, "*_????????.csv")):
        m = re.fullmatch(r"(.+)_(\d{8})\.csv", os.path.basename(ruta))
        if m and m.group(1) in base.SPEC:
            fechas.add(m.group(2))
    return sorted(fechas) if not solo else [f for f in sorted(fechas) if f == solo]


def extraer(fecha):
    crudos = {}
    for t in ORDEN:
        ruta = os.path.join(RUTA_ENTRADA, f"{t}_{fecha}.csv")
        if os.path.isfile(ruta):
            df = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8-sig").apply(lambda s: s.str.strip())
            crudos[t] = df.where(df != "", None)
            log(f"EXTRACCION  {t:24s} {len(df):5d} filas")
    return crudos


# ---------------------------------------------------------------- ESTADO ACTUAL DE LA BASE
def _claves_de(df, cols):
    return set(map(tuple, df[cols].dropna().astype(int).values.tolist())) if all(df[c].dtype.kind in "iuf" or True for c in cols) else set()


def estado_desde_csv(carpeta):
    """Modo --solo-validar: la 'base' son los CSV de la carga inicial."""
    est = {}
    for t in ORDEN:
        df = pd.read_csv(os.path.join(carpeta, f"{t}.csv"), dtype=str, keep_default_na=False, encoding="utf-8-sig")
        est[t] = _estado(t, df)
    return est


def _estado(t, df):
    spec = base.SPEC[t]
    return {"pk": set(map(tuple, df[spec["pk"]].astype(int).values.tolist())),
            "uk": {u: set(df[u].dropna().astype(str)) for u in spec["uk"]}}


def estado_desde_bd(cur):
    est = {}
    for t in ORDEN:
        spec = base.SPEC[t]
        cols = list(dict.fromkeys(spec["pk"] + spec["uk"]))
        df = pd.DataFrame.from_records(cur.execute(f"SELECT {', '.join(cols)} FROM {base.SCHEMA}.{t}").fetchall(), columns=cols)
        est[t] = _estado(t, df)
    return est


# ---------------------------------------------------------------- TRANSFORMACION (fila por fila)
def validar(t, crudo, est, aceptadas):
    """Devuelve (nuevas, ya_existentes, rechazadas). `rechazadas` lleva la columna motivo."""
    spec, df = base.SPEC[t], crudo.copy()
    ahora = pd.Timestamp.now().floor("s")
    motivos = pd.Series([[] for _ in range(len(df))], index=df.index)
    def marca(mask, texto):
        for i in df.index[mask.fillna(False)]:
            motivos[i].append(texto)
    faltan = [c for c, _ in spec["cols"] if c not in df.columns and c != "created_at"]
    if faltan:
        return df.iloc[0:0], df.iloc[0:0], df.assign(motivo=f"archivo sin columnas {faltan}")
    if "created_at" not in df.columns:
        df["created_at"] = None
    df = df[[c for c, _ in spec["cols"]]]
    for c, tipo in spec["cols"]:                                                  # tipos
        s, vacio = df[c], df[c].isna()
        conv = pd.to_numeric(s, errors="coerce") if tipo in ("int", "dec") else (pd.to_datetime(s, format=base.FORMATOS[tipo], errors="coerce") if tipo in base.FORMATOS else s)
        marca(conv.isna() & ~vacio, f"{c}: formato invalido")
        df[c] = conv
    df["created_at"] = df["created_at"].fillna(ahora)                              # igual que DEFAULT GETDATE()
    for c, _ in spec["cols"]:                                                      # obligatorios
        if c not in spec["nullable"]:
            marca(df[c].isna(), f"{c}: obligatorio vacio")
    for (tt, c), valores in base.DOMINIOS.items():                                  # dominios
        if tt == t:
            marca(df[c].notna() & ~df[c].isin(valores), f"{c}: fuera de dominio")
    for desc, f in base.REGLAS.get(t, []):                                          # reglas = CHECK de la base
        try:
            marca(f(df), f"regla incumplida [{desc}]")
        except Exception:
            pass
    ints = [c for c, tipo in spec["cols"] if tipo == "int"]
    for c in ints:
        if c in df: df[c] = df[c].astype("Int64")
    pkcols = spec["pk"]
    marca(df.duplicated(pkcols, keep="first"), "PK repetida dentro del archivo")
    clave = df[pkcols].apply(lambda r: tuple(int(x) if pd.notna(x) else -1 for x in r), axis=1)
    existe = clave.isin(est[t]["pk"])
    for u in spec["uk"]:                                                            # UNIQUE (dni, nombre, id_cita ...)
        val = df[u].astype(str)
        marca(~existe & df[u].notna() & val.isin(est[t]["uk"][u]), f"{u}: valor ya usado por otro registro (UNIQUE)")
        marca(df[u].notna() & df.duplicated(u, keep="first"), f"{u}: repetido dentro del archivo (UNIQUE)")
    for col, ref, refcol in spec["fks"]:                                            # FK contra la base y contra lo aceptado hoy
        vals = df[col].dropna().astype(int)
        ok = vals.map(lambda v: (v,) in est[ref]["pk"]) if refcol == base.SPEC[ref]["pk"][0] and len(base.SPEC[ref]["pk"]) == 1 else pd.Series(True, index=vals.index)
        marca(df[col].notna() & ~ok.reindex(df.index, fill_value=True), f"{col}: no existe en {ref}")
    mal = motivos.map(len) > 0
    nuevas = df[~mal & ~existe]
    return nuevas, df[~mal & existe], df[mal].assign(motivo=motivos[mal].map("; ".join)), clave[~mal & ~existe].tolist()


# ---------------------------------------------------------------- CARGA
def cargar_dia(cur, resultados):
    for t in ORDEN:
        if t not in resultados or not len(resultados[t][0]):
            continue
        spec, df = base.SPEC[t], resultados[t][0]
        cols = spec["cols"]
        filas = [tuple(base._a_python(v, tipo) for v, (_, tipo) in zip(f, cols)) for f in df.itertuples(index=False, name=None)]
        sql = f"INSERT INTO {base.SCHEMA}.{t} ({', '.join(c for c, _ in cols)}) VALUES ({', '.join('?' * len(cols))})"
        cur.fast_executemany = not any(tipo == "time" for _, tipo in cols)
        if spec["identity"]:
            cur.execute(f"SET IDENTITY_INSERT {base.SCHEMA}.{t} ON")
        cur.executemany(sql, filas)
        if spec["identity"]:
            cur.execute(f"SET IDENTITY_INSERT {base.SCHEMA}.{t} OFF")


def registrar_control(cur, resumen, resultados):
    """Guarda en BDClinica (esquema etl) el resumen de la fecha y los rechazos con su motivo; va en la MISMA transaccion que la carga."""
    ahora = pd.Timestamp.now().floor("s").to_pydatetime()
    cur.executemany("INSERT INTO etl.CargaDiaria (fecha_lote, tabla, leidas, insertadas, ya_existentes, rechazadas, procesado) VALUES (?,?,?,?,?,?,?)",
                    [(r["fecha_lote"], r["tabla"], int(r["leidas"]), int(r["insertadas"]), int(r["ya_existentes"]), int(r["rechazadas"]), ahora) for r in resumen])
    fecha = resumen[0]["fecha_lote"] if resumen else None
    filas = []
    for t, (_, _, rech) in resultados.items():
        for reg in rech.to_dict("records"):
            clave = "|".join(str(reg.get(c)) for c in base.SPEC[t]["pk"])
            filas.append((fecha, t, clave[:100], str(reg["motivo"])[:500], ahora))
    if filas:
        cur.executemany("INSERT INTO etl.RechazoDiario (fecha_lote, tabla, clave, motivo, procesado) VALUES (?,?,?,?,?)", filas)


def procesar_fecha(fecha, est, conn, solo_validar):
    log(f"=== FECHA DE LOTE {fecha} ===")
    crudos = extraer(fecha)
    resultados, resumen = {}, []
    for t in ORDEN:                                                                 # padres primero: lo aceptado queda visible para los hijos
        if t not in crudos:
            continue
        res = validar(t, crudos[t], est, None)
        if len(res) == 3:                                                           # archivo con columnas faltantes
            nuevas, existentes, rech = res; claves = []
        else:
            nuevas, existentes, rech, claves = res
        resultados[t] = (nuevas, existentes, rech)
        est[t]["pk"].update(claves)
        for u in base.SPEC[t]["uk"]:
            est[t]["uk"][u].update(nuevas[u].dropna().astype(str))
        resumen.append(dict(fecha_lote=fecha, tabla=t, leidas=len(crudos[t]), insertadas=len(nuevas), ya_existentes=len(existentes), rechazadas=len(rech)))
        log(f"VALIDACION  {t:24s} leidas={len(crudos[t]):4d} nuevas={len(nuevas):4d} ya_existentes={len(existentes):3d} rechazadas={len(rech):3d}")
    if not solo_validar and conn is not None:
        cur = conn.cursor()
        try:
            cargar_dia(cur, resultados)
            registrar_control(cur, resumen, resultados)
            conn.commit()
            log(f"COMMIT OK   {sum(r['insertadas'] for r in resumen)} filas nuevas en BDClinica")
        except Exception:
            conn.rollback(); log("ERROR: ROLLBACK de la fecha; los CSV quedan en la entrada para reintentar."); raise
    cierre(fecha, resultados, resumen, solo_validar)
    return resumen


def cierre(fecha, resultados, resumen, solo_validar):
    if solo_validar:
        return
    dest = os.path.join(RUTA_PROC, fecha); os.makedirs(dest, exist_ok=True)
    rdir = RUTA_RECH; os.makedirs(rdir, exist_ok=True)
    for t, (_, _, rech) in resultados.items():
        if len(rech):
            rech.to_csv(os.path.join(rdir, f"{t}_{fecha}_rechazos.csv"), index=False, encoding="utf-8-sig")
        shutil.move(os.path.join(RUTA_ENTRADA, f"{t}_{fecha}.csv"), os.path.join(dest, f"{t}_{fecha}.csv"))


def main():
    global LOG_FILE, RUTA_ENTRADA
    ap = argparse.ArgumentParser(description="ETL diario CSV -> BDClinica")
    ap.add_argument("--entrada", default=RUTA_ENTRADA); ap.add_argument("--fecha", help="AAAAMMDD: procesa solo esa fecha")
    ap.add_argument("--solo-validar", action="store_true", help="no toca la base; requiere --referencia (CSV de la carga inicial)")
    ap.add_argument("--referencia", help="carpeta con los CSV de BDClinica (solo para --solo-validar)")
    ap.add_argument("--server", default=base.SERVER); ap.add_argument("--database", default=base.DATABASE)
    a = ap.parse_args()
    RUTA_ENTRADA = a.entrada; base.SERVER, base.DATABASE = a.server, a.database
    LOG_FILE = os.path.join(carpeta_logs(), f"etl_diario_{time.strftime('%Y%m%d_%H%M%S')}.log")
    conn = None
    try:
        if not os.path.isdir(RUTA_ENTRADA):
            raise FileNotFoundError(f"No existe la carpeta de entrada: {RUTA_ENTRADA}")
        fechas = fechas_pendientes(a.fecha)
        log(f"INICIO  entrada={RUTA_ENTRADA}  fechas pendientes={fechas or 'ninguna'}  modo={'SOLO_VALIDAR' if a.solo_validar else 'CARGA'}")
        if not fechas:
            log("Nada que procesar."); return
        if a.solo_validar:
            if not a.referencia: raise ValueError("--solo-validar necesita --referencia (carpeta con los CSV de la carga inicial).")
            est = estado_desde_csv(a.referencia)
        else:
            if not (base.SERVER and base.DATABASE): raise ValueError("Falta DB_SERVER / DB_NAME en el .env (o --server / --database).")
            conn = base.conectar(); est = estado_desde_bd(conn.cursor())
        total = []
        for f in fechas:
            total += procesar_fecha(f, est, conn, a.solo_validar)
        r = pd.DataFrame(total)
        p("\n" + "=" * 70 + f"\n{'RESUMEN':26s}{'leidas':>8s}{'nuevas':>8s}{'ya_exist':>9s}{'rechaz.':>9s}\n" + "=" * 70)
        for t, g in r.groupby("tabla", sort=False):
            p(f"{t:26s}{g.leidas.sum():8d}{g.insertadas.sum():8d}{g.ya_existentes.sum():9d}{g.rechazadas.sum():9d}")
        p("=" * 70)
        log(f"FIN OK  fechas={len(fechas)}  nuevas={r.insertadas.sum()}  rechazadas={r.rechazadas.sum()}  (log: {LOG_FILE})")
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        p(f"\n*** ETL DIARIO DETENIDO ***\n{e}\n(detalle tecnico en {LOG_FILE})")
        sys.exit(1)
    finally:
        if conn: conn.close()


if __name__ == "__main__":
    main()
