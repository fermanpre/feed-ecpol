# Feed RSS de las publicaciones de Jorge Galindo (EsadeEcPol)

La página de perfil <https://www.esade.edu/ecpol/es/perfil/jorge-galindo/> no ofrece feed.
Este repositorio lo genera cada día con un script de Python y lo publica en GitHub Pages,
de forma gratuita, para poder suscribirse desde Feedly.

## Puesta en marcha (una sola vez)

1. Crear en GitHub un repositorio **público** (por ejemplo, `feed-ecpol`) y subir estos ficheros:
   `generar_feed.py`, `requirements.txt`, `README.md` y `.github/workflows/feed.yml`.
   Ojo: la carpeta `.github` empieza por punto; si se sube desde la web, hay que arrastrarla entera.
2. En **Settings → Actions → General → Workflow permissions**, marcar **Read and write permissions**.
3. En la pestaña **Actions**, abrir «Actualizar feed» y pulsar **Run workflow**. Debe terminar en verde
   y crear `feed.xml` en el repositorio.
4. En **Settings → Pages**, elegir **Deploy from a branch**, rama `main`, carpeta `/ (root)`.
5. A los pocos minutos, el feed estará en `https://<usuario>.github.io/<repositorio>/feed.xml`.
6. En Feedly: **+ Add content**, pegar esa URL y seguir.

## Comportamiento

- Se actualiza cada día (05:17 UTC) y se puede lanzar a mano.
- Incluye las 50 publicaciones más recientes del perfil: título, enlace, autores, fecha, resumen completo y enlace al PDF.
- `cache.json` guarda lo ya descargado de cada publicación para no repetir peticiones; las de los últimos 30 días se revisan cada día.
- Si la página cambia de estructura o Esade bloquea la petición, el workflow falla y GitHub avisa por correo.

## Probarlo en local

    python generar_feed.py feed.xml

## Otra web

Para otra página, cambiar `URL_PERFIL`, los títulos del feed y la lógica de `AnalizadorTarjetas`
(es lo único específico de esta web).

Feed no oficial, solo para uso personal. Los contenidos son de Esade.
