# -*- coding: utf-8 -*-
r"""
Genera las fuentes complementarias del informe a partir de los CSV de BDClinica (datos sinteticos, semilla fija):
  F2  Inventario_Fisico_Farmacia_2025-2026.xlsx   (12 hojas, una por corte mensual NOV-25 .. OCT-26, con errores tipicos de digitacion)
  F3  Metas_Indicadores_Gerencia_2026.xlsx        (7 indicadores x 12 meses)
  F4  feriados_peru_2025_2026.csv                 (feriados nacionales)
Uso:  python tools/generar_fuentes_bi.py --csv data/inicial --salida data/fuentes
"""
import argparse, os, random
import pandas as pd

MESES = ["NOV-25", "DIC-25", "ENE-26", "FEB-26", "MAR-26", "ABR-26", "MAY-26", "JUN-26", "JUL-26", "AGO-26", "SET-26", "OCT-26"]
CORTES = pd.date_range("2025-11-30", periods=12, freq="ME")
FERIADOS = [("2025-12-08", "Inmaculada Concepcion"), ("2025-12-09", "Batalla de Ayacucho"), ("2025-12-25", "Navidad"),
            ("2026-01-01", "Anio Nuevo"), ("2026-04-02", "Jueves Santo"), ("2026-04-03", "Viernes Santo"), ("2026-05-01", "Dia del Trabajo"),
            ("2026-06-07", "Batalla de Arica y Dia de la Bandera"), ("2026-06-29", "San Pedro y San Pablo"), ("2026-07-23", "Dia de la Fuerza Aerea del Peru"),
            ("2026-07-28", "Fiestas Patrias"), ("2026-07-29", "Fiestas Patrias"), ("2026-08-06", "Batalla de Junin"),
            ("2026-08-30", "Santa Rosa de Lima"), ("2026-10-08", "Combate de Angamos"), ("2026-10-31", "Dia de las Iglesias Evangelicas"),
            ("2026-11-01", "Todos los Santos"), ("2026-12-08", "Inmaculada Concepcion"), ("2026-12-09", "Batalla de Ayacucho"), ("2026-12-25", "Navidad")]
METAS = [  # indicador, unidad, sentido, area, meta mensual (lista de 12 o valor)
    ("Tasa de inasistencia", "%", "Menor es mejor", "Admision", 10),
    ("Tasa de ocupacion de horarios", "%", "Mayor es mejor", "Direccion medica", 75),
    ("Tiempo promedio de espera", "min", "Menor es mejor", "Direccion medica", 20),
    ("Productividad medica", "atenciones por turno", "Mayor es mejor", "Direccion medica", 8),
    ("Ingresos totales", "S/", "Mayor es mejor", "Gerencia general", [3200, 3400, 3000, 3000, 3400, 3500, 3500, 3400, 3500, 3600, 3600, 3700]),
    ("Valor de stock en riesgo de vencimiento", "S/", "Menor es mejor", "Jefatura de farmacia", 1500),
    ("Farmacos bajo stock minimo", "farmacos", "Menor es mejor", "Jefatura de farmacia", 3),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="carpeta con los 15 CSV de BDClinica")
    ap.add_argument("--salida", default="data/fuentes")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)
    rd = lambda n: pd.read_csv(os.path.join(a.csv, n + ".csv"), encoding="utf-8-sig")
    lotes, farm = rd("LOTES_FARMACOS"), rd("FARMACOS")
    lotes["fec_lote"] = pd.to_datetime(lotes.fec_lote); lotes["fec_vencimiento"] = pd.to_datetime(lotes.fec_vencimiento)
    lotes = lotes.merge(farm[["id_farmaco", "nombre_farmaco", "presentacion"]], on="id_farmaco")
    rnd = random.Random(2026)

    # ---------------- F2: inventario fisico (12 hojas) ----------------
    hojas = {}
    for i, (nom, corte) in enumerate(zip(MESES, CORTES)):
        filas = []
        for r in lotes[lotes.fec_lote <= corte].itertuples():
            stock = max(0, round(r.stock * (1 + 0.03 * (11 - i)) + rnd.randint(-5, 5)))
            filas.append(dict(corte=corte, prod=f"{r.nombre_farmaco} {r.presentacion}", lote=r.nro_lote, venc=r.fec_vencimiento, stock=stock, r=r))
        df = pd.DataFrame([{"FECHA CORTE": f["corte"], "ALMACEN": "Farmacia central", "CODIGO": f"F{f['r'].id_farmaco:04d}", "PRODUCTO": f["prod"],
                            "PRESENTACION": f["r"].presentacion, "N° LOTE": f["lote"], "F. VENCIMIENTO": f["venc"], "STOCK FÍSICO": f["stock"],
                            "RESPONSABLE": rnd.choice(["Q.F. Rojas", "Q.F. Vega", "Q.F. Salas"])} for f in filas])
        # --- ensuciar como hace una digitacion a mano ---
        n = len(df)
        for col in ["FECHA CORTE", "F. VENCIMIENTO"]:
            df[col] = df[col].astype(object)
        for idx in rnd.sample(range(n), max(1, n // 2)):                        # fechas como texto dd/mm/aaaa
            df.at[idx, "FECHA CORTE"] = df.at[idx, "FECHA CORTE"].strftime("%d/%m/%Y")
        for idx in rnd.sample(range(n), int(n * 0.7)):
            df.at[idx, "F. VENCIMIENTO"] = df.at[idx, "F. VENCIMIENTO"].strftime("%d/%m/%Y")
        for idx in rnd.sample(range(n), max(1, n // 14)):                       # producto con mayusculas / espacios
            df.at[idx, "PRODUCTO"] = "  " + df.at[idx, "PRODUCTO"].upper() + " "
        for idx in rnd.sample(range(n), max(1, n // 14)):                       # lote en minusculas o con guion
            v = df.at[idx, "N° LOTE"]; df.at[idx, "N° LOTE"] = v.lower() if rnd.random() < .5 else v[:2] + "-" + v[2:]
        df["STOCK FÍSICO"] = df["STOCK FÍSICO"].astype(object)
        for idx in rnd.sample(range(n), max(1, n // 80)):                       # stock con texto
            df.at[idx, "STOCK FÍSICO"] = f"{df.at[idx, 'STOCK FÍSICO']} und"
        for idx in rnd.sample(range(n), max(1, n // 80)):
            df.at[idx, "STOCK FÍSICO"] = None                                   # vacio
        for idx in rnd.sample(range(n), max(1, n // 250)):
            df.at[idx, "STOCK FÍSICO"] = -abs(rnd.randint(1, 9))                # negativo
        for k in range(max(1, n // 60)):                                        # lote que no existe en BD (muestra medica)
            df.loc[len(df)] = [CORTES[i], "Farmacia central", "F9999", "Muestra medica", "Caja", f"MM{rnd.randint(1000, 9999)}", CORTES[i] + pd.Timedelta(days=400), rnd.randint(1, 20), "Q.F. Rojas"]
        dup = df.sample(max(1, n // 60), random_state=i)                        # filas duplicadas exactas
        df = pd.concat([df, dup], ignore_index=True)
        hojas[nom] = df
    with pd.ExcelWriter(os.path.join(a.salida, "Inventario_Fisico_Farmacia_2025-2026.xlsx")) as xw:
        for nom, df in hojas.items():
            df.to_excel(xw, sheet_name=nom, index=False)
    print("F2 inventario:", sum(len(d) for d in hojas.values()), "filas en", len(hojas), "hojas")

    # ---------------- F3: metas ----------------
    filas = []
    for ind, uni, sen, area, meta in METAS:
        for k, c in enumerate(CORTES):
            filas.append({"INDICADOR": ind, "PERIODO": c.strftime("%Y-%m"), "META": meta[k] if isinstance(meta, list) else meta, "UNIDAD": uni, "SENTIDO": sen, "AREA": area})
    pd.DataFrame(filas).to_excel(os.path.join(a.salida, "Metas_Indicadores_Gerencia_2026.xlsx"), sheet_name="Metas", index=False)
    print("F3 metas:", len(filas), "filas")

    # ---------------- F4: feriados ----------------
    pd.DataFrame(FERIADOS, columns=["fecha", "descripcion"]).assign(tipo="Nacional").to_csv(
        os.path.join(a.salida, "feriados_peru_2025_2026.csv"), index=False, encoding="utf-8")
    print("F4 feriados:", len(FERIADOS), "filas")


if __name__ == "__main__":
    main()
