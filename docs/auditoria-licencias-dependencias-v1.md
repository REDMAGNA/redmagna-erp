# Auditoría inicial de licencias de dependencias

**Corte:** 16 de octubre de 2026  
**Alcance:** resolución para CPython 3.12 en Linux x86_64 y metadatos/licencias de los wheels seleccionados. Es un inventario técnico inicial, no un dictamen legal ni una auditoría completa de las imágenes Docker.

## Licencia del proyecto

El código propio de Redmagna se publica bajo **GNU AGPL-3.0-only**, como indica `LICENSE`. No se incorpora código, interfaz, imagen, marca ni traducción de Odoo. Las bibliotecas de terceros mantienen sus licencias y avisos propios; no se cambian a AGPL por aparecer en el mismo archivo de requisitos.

## Dependencias Python bloqueadas

`server/requirements.txt` conserva los rangos de las siete dependencias directas. Docker instala `server/requirements.lock`, que fija 15 paquetes, incluidos siete transitivos y `tzdata` condicional para Windows, y verifica hashes SHA-256 de los wheels. La resolución de versiones se realizó para CPython 3.12 y `manylinux_2_17_x86_64`; el lock contiene hashes de los wheels no retirados de esos releases y no permite compilar desde archivos fuente.

| Paquete bloqueado | Origen | Licencia declarada en metadata/aviso del wheel |
|---|---|---|
| `asgiref==3.12.1` | Django | BSD-3-Clause |
| `cffi==2.1.1` | cryptography | MIT-0 |
| `cryptography==46.0.7` | Directa | Apache-2.0 OR BSD-3-Clause |
| `Django==5.2.18` | Directa | BSD-3-Clause |
| `djangorestframework==3.18.3` | Directa | BSD-3-Clause |
| `gunicorn==23.0.0` | Directa | MIT |
| `lxml==6.1.3` | Directa | BSD-3-Clause; conservar también `LICENSES.txt` del wheel, que detalla excepciones y avisos de componentes incluidos. |
| `packaging==26.3` | Gunicorn | Apache-2.0 OR BSD-2-Clause |
| `psycopg==3.3.6` | Directa | LGPL-3.0-only |
| `psycopg-binary==3.3.6` | Extra `binary` de Psycopg | LGPL-3.0-only |
| `pycparser==3.11` | cffi | BSD-3-Clause |
| `sqlparse==0.6.0` | Django | BSD-3-Clause |
| `typing-extensions==4.16.0` | Psycopg | PSF-2.0 |
| `tzdata==2026.5` | Compatibilidad de zona horaria para Windows | Apache-2.0; en el lock se instala solo en Windows. |
| `whitenoise==6.12.0` | Directa | MIT |

Se inspeccionaron `METADATA` y archivos `licenses/` dentro de los wheels resueltos. PyPI publica, por release, metadatos y hashes del archivo; también se pueden revisar las fichas de [Django](https://pypi.org/project/Django/), [Django REST framework](https://pypi.org/project/djangorestframework/), [Psycopg](https://pypi.org/project/psycopg/), [psycopg-binary](https://pypi.org/project/psycopg-binary/), [Gunicorn](https://pypi.org/project/gunicorn/), [WhiteNoise](https://pypi.org/project/whitenoise/), [lxml](https://pypi.org/project/lxml/) y [cryptography](https://pypi.org/project/cryptography/). La tabla refleja los paquetes elegidos en este lock; una actualización de versiones exige volver a revisar sus avisos.

## SBOM y pendientes de distribución

El [SBOM CycloneDX 1.6 de Python para CPython 3.12/Linux x86_64](sbom-python-cp312-linux-x86_64.cdx.json) enumera 14 componentes bloqueados para runtime, sus licencias revisadas y el SHA-256 de cada wheel. Se genera con `tools/build-python-sbom.py` desde `work/lock-wheels`, que debe corresponder a `server/requirements.lock`. El SBOM cubre las siete dependencias directas y sus componentes runtime resueltos para esa plataforma; no inventaría el contenido de las imágenes ni los avisos nativos incluidos dentro de algunas ruedas.

### Imágenes base fijadas

El 17 de octubre de 2026 se consultaron las etiquetas oficiales multi-arquitectura en Docker Hub y se fijaron sus digest de índice para que el registro seleccione la plataforma compatible sin cambiar silenciosamente el contenido:

| Servicio | Referencia fijada | Alcance |
|---|---|---|
| Aplicación | `python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` | Etiquetas coincidentes: `3.12-slim`, `3.12-slim-trixie`, `3.12.15-slim`, `3.12.15-slim-trixie`; índice multi-arquitectura. |
| Base de datos | `postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea` | Etiquetas coincidentes: `16-alpine`, `16-alpine3.24`, `16.15-alpine`, `16.15-alpine3.24`; índice multi-arquitectura. |

Para actualizar una base, revisar de nuevo la etiqueta oficial, su digest de índice, arquitecturas, avisos y notas de versión; cambiar en conjunto el Dockerfile/Compose y esta tabla, y reconstruir y desplegar la imagen resultante. El pin fija contenido, no mantiene automáticamente las correcciones futuras.

Antes de distribuir una imagen o publicar un release faltan:

1. Generar y revisar el SBOM del artefacto Docker, incluyendo dependencias de sistema y contenido de las imágenes base.
2. Registrar licencias y avisos del contenido del sistema operativo que contiene cada digest de imagen base.
3. Confirmar los avisos de copyright/licencia que quedan dentro de cada imagen final, incluidos los componentes nativos de `psycopg-binary`, `lxml` y `cryptography`.
4. Repetir la auditoría cuando cambien requisitos, versiones bloqueadas, arquitectura, digest de imagen base o artefactos distribuidos.

El paquete `source.zip` contiene el lock, la lista de requisitos y el SBOM de las ruedas Python, no las bibliotecas instaladas. Docker conserva los avisos de licencia de cada wheel en `site-packages`; todavía falta generar y revisar un SBOM de la imagen completa. Por eso este documento no afirma que la cadena completa de distribución ya esté auditada para publicación pública.
