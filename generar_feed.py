"""Genera un feed RSS 2.0 (feed.xml) a partir de la página de perfil de EsadeEcPol.

Sin dependencias externas: solo la biblioteca estándar de Python.
Uso: python generar_feed.py [ruta_de_salida]
"""

import sys
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from xml.sax.saxutils import escape

URL_PERFIL = "https://www.esade.edu/ecpol/es/perfil/jorge-galindo/"
TITULO_FEED = "EsadeEcPol: publicaciones de Jorge Galindo"
DESCRIPCION_FEED = "Feed no oficial generado a partir de la página de perfil de Jorge Galindo en EsadeEcPol."
MAXIMO_ENTRADAS = 50

# Esade bloquea a los clientes sin cabecera de navegador (responde 403).
CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}

# La página mezcla abreviaturas en español e inglés («Abr», «Oct»).
MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5,
    "jun": 6, "jul": 7, "ago": 8, "aug": 8, "sep": 9, "set": 9, "oct": 10,
    "nov": 11, "dic": 12, "dec": 12,
}


class AnalizadorTarjetas(HTMLParser):
    """Recorre el HTML y recoge una entrada por cada tarjeta de publicación."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entradas = []
        self.entrada_actual = None
        self.dentro_del_archivo = False
        self.profundidad_archivo = 0
        self.campo_actual = None
        self.profundidad_campo = 0

    def handle_starttag(self, etiqueta, atributos):
        atributos = dict(atributos)
        clases = (atributos.get("class") or "").split()

        if etiqueta == "div" and atributos.get("id") == "ecpolArchive":
            self.dentro_del_archivo = True
            self.profundidad_archivo = 1
            return
        if not self.dentro_del_archivo:
            return

        if etiqueta == "div":
            self.profundidad_archivo += 1
            if "col-lg-4" in clases:
                self.entrada_actual = {
                    "titulo": "", "enlace": "", "autores": "",
                    "fecha": "", "extracto": "",
                }
                self.entradas.append(self.entrada_actual)
            elif self.entrada_actual is not None and "text-secondary" in clases:
                self._empezar_campo("autores")
            elif self.entrada_actual is not None and "text-muted" in clases and "semismall" in clases:
                self._empezar_campo("extracto")
        elif self.entrada_actual is not None:
            if etiqueta == "a" and "mt-4" in clases and not self.entrada_actual["enlace"]:
                self.entrada_actual["enlace"] = atributos.get("href", "")
            elif etiqueta == "strong":
                self._empezar_campo("titulo")
            elif etiqueta == "span" and "semismall" in clases and "text-muted" not in clases:
                self._empezar_campo("fecha")

    def _empezar_campo(self, nombre):
        self.campo_actual = nombre
        self.profundidad_campo = 1

    def handle_endtag(self, etiqueta):
        if not self.dentro_del_archivo:
            return
        if etiqueta == "div":
            self.profundidad_archivo -= 1
            if self.profundidad_archivo <= 0:
                self.dentro_del_archivo = False
                self.entrada_actual = None
        if self.campo_actual and etiqueta in ("div", "strong", "span"):
            self.profundidad_campo -= 1
            if self.profundidad_campo <= 0:
                self.campo_actual = None

    def handle_data(self, texto):
        if self.campo_actual and self.entrada_actual is not None:
            self.entrada_actual[self.campo_actual] += texto


def descargar_pagina(url):
    peticion = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        return respuesta.read().decode("utf-8")


def convertir_fecha(texto_fecha):
    """«23 Oct, 2026» -> datetime con zona horaria UTC (mediodía, por no tener hora)."""
    partes = texto_fecha.replace(",", " ").split()
    if len(partes) != 3:
        raise ValueError(f"Fecha con formato inesperado: {texto_fecha!r}")
    dia, mes_texto, anio = partes
    mes = MESES[mes_texto.lower()[:3]]
    return datetime(int(anio), mes, int(dia), 12, 0, tzinfo=timezone.utc)


def limpiar(texto):
    return " ".join(texto.split())


def construir_feed(entradas):
    ahora = format_datetime(datetime.now(timezone.utc))
    lineas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        f"<title>{escape(TITULO_FEED)}</title>",
        f"<link>{escape(URL_PERFIL)}</link>",
        f"<description>{escape(DESCRIPCION_FEED)}</description>",
        "<language>es</language>",
        f"<lastBuildDate>{ahora}</lastBuildDate>",
    ]
    for entrada in entradas:
        fecha = convertir_fecha(limpiar(entrada["fecha"]))
        descripcion = limpiar(entrada["extracto"])
        autores = limpiar(entrada["autores"])
        if autores:
            descripcion = f"{autores}. {descripcion}"
        lineas += [
            "<item>",
            f"<title>{escape(limpiar(entrada['titulo']))}</title>",
            f"<link>{escape(entrada['enlace'])}</link>",
            f'<guid isPermaLink="true">{escape(entrada["enlace"])}</guid>',
            f"<pubDate>{format_datetime(fecha)}</pubDate>",
            f"<description>{escape(descripcion)}</description>",
            "</item>",
        ]
    lineas += ["</channel>", "</rss>"]
    return "\n".join(lineas) + "\n"


def main():
    ruta_salida = sys.argv[1] if len(sys.argv) > 1 else "feed.xml"

    html = descargar_pagina(URL_PERFIL)
    analizador = AnalizadorTarjetas()
    analizador.feed(html)

    entradas = [
        entrada for entrada in analizador.entradas
        if entrada["titulo"].strip() and entrada["enlace"] and entrada["fecha"].strip()
    ]
    if not entradas:
        # Que el workflow falle en alto si cambia el HTML o Esade bloquea la petición.
        raise SystemExit("ERROR: no se ha extraído ninguna publicación; revisar la estructura de la página.")

    entradas = entradas[:MAXIMO_ENTRADAS]
    with open(ruta_salida, "w", encoding="utf-8", newline="\n") as fichero:
        fichero.write(construir_feed(entradas))
    print(f"{len(entradas)} publicaciones escritas en {ruta_salida}")


if __name__ == "__main__":
    main()
