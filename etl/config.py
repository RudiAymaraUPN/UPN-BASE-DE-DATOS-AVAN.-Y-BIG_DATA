# -*- coding: utf-8 -*-
"""Configuracion comun de los ETL: lector del .env (sin librerias externas) y rutas relativas a la raiz del repositorio."""
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # carpeta que contiene etl/, database/, data/ ...


def cargar_env(ruta=None):
    """Lee KEY=VALOR del .env de la raiz del repositorio. Las variables ya definidas en el sistema tienen prioridad.
    El .env contiene claves y rutas locales: esta en .gitignore y NUNCA se sube al repositorio (usar .env.example como plantilla)."""
    ruta = ruta or os.path.join(RAIZ, ".env")
    if not os.path.isfile(ruta):
        return
    with open(ruta, encoding="utf-8-sig") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = (x.strip() for x in linea.split("=", 1))
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            os.environ.setdefault(k, v)


def ruta(variable, defecto):
    """Ruta configurada en el .env (absoluta o relativa a la raiz del repo) o, si no existe, la ruta por defecto dentro del repo."""
    valor = os.environ.get(variable) or defecto
    return valor if os.path.isabs(valor) else os.path.join(RAIZ, valor)


def carpeta_logs():
    d = os.path.join(RAIZ, "logs")
    os.makedirs(d, exist_ok=True)
    return d
