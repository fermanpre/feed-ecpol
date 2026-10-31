"""Genera un feed RSS 2.0 (feed.xml) a partir de la página de perfil de EsadeEcPol.

Sin dependencias externas: solo la biblioteca estándar de Python.
Para cada publicación descarga además su página y mete en el feed el resumen completo
(bloque «contentText») y el enlace al PDF. Lo ya descargado se guarda en cache.json.
Uso: python generar_feed.py [ruta_de_salida]
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from xml.sax.saxutils import escape

URL_PERFIL = "https://www.esade.edu/ecpol/es/perfil/jorge-galindo/"
TITULO_FEED = "EsadeEcPol: publicaciones de Jorge Galindo"
DESCRIPCION_FEED = "Feed no oficial generado a partir de la página de perfil de Jorge Galindo en EsadeEcPol."
MAXIMO_ENTRADAS = 50
RUTA_CACHE = "cache.json"
PAUSA_ENTRE_PETICIONES = 1.0   # segundos, para no cargar el servidor de Esade
DIAS_PARA_REVISAR = 30         # las publicaciones recientes se vuelven a descargar por si Esade las corrige
ETIQUETAS_PERMITIDAS = {
    "p", "ul", "ol", "li", "strong", "b", "em", "i", "br", "blockquote",
    "h2", "h3", "h4", "h5", "h6", "a",
}

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


class AnalizadorCuerpo(HTMLParser):
    """Extrae, con etiquetas simples, el contenido del bloque «contentText» de una publicación."""

    def __init__(self, url_base):
        super().__init__(convert_charrefs=True)
        self.url_base = url_base
        self.dentro_del_bloque = False
        self.profundidad = 0
        self.fragmentos = []

    def handle_starttag(self, etiqueta, atributos):
        atributos = dict(atributos)
        clases = (atributos.get("class") or "").split()
        if not self.dentro_del_bloque:
            if etiqueta == "div" and "contentText" in clases:
                self.dentro_del_bloque = True
                self.profundidad = 1
            return
        if etiqueta == "div":
            self.profundidad += 1
        elif etiqueta in ETIQUETAS_PERMITIDAS:
            if etiqueta == "a" and atributos.get("href"):
                enlace = urllib.parse.urljoin(self.url_base, atributos["href"])
                self.fragmentos.append(f'<a href="{escape(enlace, {chr(34): "&quot;"})}">')
            elif etiqueta == "br":
                self.fragmentos.append("<br/>")
            else:
                self.fragmentos.append(f"<{etiqueta}>")

    def handle_endtag(self, etiqueta):
        if not self.dentro_del_bloque:
            return
        if etiqueta == "div":
            self.profundidad -= 1
            if self.profundidad <= 0:
                self.dentro_del_bloque = False
        elif etiqueta in ETIQUETAS_PERMITIDAS and etiqueta != "br":
            self.fragmentos.append(f"</{etiqueta}>")

    def handle_data(self, texto):
        if self.dentro_del_bloque:
            self.fragmentos.append(escape(texto))


def extraer_publicacion(html, url_publicacion):
    """Devuelve el resumen completo (HTML simple) y el enlace al PDF, si lo hay."""
    analizador = AnalizadorCuerpo(url_publicacion)
    analizador.feed(html)
    cuerpo = "".join(analizador.fragmentos).strip()

    enlace_pdf = ""
    posicion_adjuntos = html.find("contentAttachment")
    if posicion_adjuntos >= 0:
        coincidencia = re.search(r'href="([^"]+\.pdf)"', html[posicion_adjuntos:], re.IGNORECASE)
        if coincidencia:
            enlace_pdf = urllib.parse.urljoin(url_publicacion, coincidencia.group(1))
    return {"cuerpo": cuerpo, "pdf": enlace_pdf}


def cargar_cache():
    if not os.path.exists(RUTA_CACHE):
        return {}
    with open(RUTA_CACHE, encoding="utf-8") as fichero:
        return json.load(fichero)


def guardar_cache(cache):
    with open(RUTA_CACHE, "w", encoding="utf-8", newline="\n") as fichero:
        json.dump(cache, fichero, ensure_ascii=False, indent=1, sort_keys=True)
        fichero.write("\n")


def completar_con_publicaciones(entradas):
    """Añade a cada entrada el resumen completo y el PDF, descargando solo lo que falta."""
    cache = cargar_cache()
    ahora = datetime.now(timezone.utc)
    descargadas = 0
    fallidas = 0

    for entrada in entradas:
        url = entrada["enlace"]
        antiguedad = ahora - convertir_fecha(limpiar(entrada["fecha"]))
        es_reciente = antiguedad.days <= DIAS_PARA_REVISAR
        if url not in cache or es_reciente:
            try:
                html = descargar_pagina(url)
                cache[url] = extraer_publicacion(html, url)
                descargadas += 1
            except Exception as error:
                # Si falla una publicación, el feed sigue saliendo con el extracto.
                fallidas += 1
                print(f"AVISO: no se pudo descargar {url}: {error}")
            time.sleep(PAUSA_ENTRE_PETICIONES)
        entrada["cuerpo"] = cache.get(url, {}).get("cuerpo", "")
        entrada["pdf"] = cache.get(url, {}).get("pdf", "")

    guardar_cache(cache)
    print(f"Páginas descargadas: {descargadas} | fallidas: {fallidas} | en caché: {len(cache)}")


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
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
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
        contenido = entrada.get("cuerpo", "")
        if contenido:
            if entrada.get("pdf"):
                contenido += (
                    f'<p><strong>Artículo completo (PDF):</strong> '
                    f'<a href="{escape(entrada["pdf"])}">{escape(entrada["pdf"])}</a></p>'
                )
            contenido_xml = f"<content:encoded><![CDATA[{contenido.replace(']]>', ']]&gt;')}]]></content:encoded>"
        else:
            contenido_xml = ""
        lineas += [
            "<item>",
            f"<title>{escape(limpiar(entrada['titulo']))}</title>",
            f"<link>{escape(entrada['enlace'])}</link>",
            f'<guid isPermaLink="true">{escape(entrada["enlace"])}</guid>',
            f"<pubDate>{format_datetime(fecha)}</pubDate>",
            f"<description>{escape(descripcion)}</description>",
        ]
        if contenido_xml:
            lineas.append(contenido_xml)
        lineas.append("</item>")
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
    completar_con_publicaciones(entradas)
    with open(ruta_salida, "w", encoding="utf-8", newline="\n") as fichero:
        fichero.write(construir_feed(entradas))
    print(f"{len(entradas)} publicaciones escritas en {ruta_salida}")


if __name__ == "__main__":
    main()
