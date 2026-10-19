# Importación inicial de clientes

La pantalla **Clientes → Importar CSV** permite revisar y crear clientes desde un archivo delimitado por coma, punto y coma o tabulador. El archivo debe usar UTF-8 y puede contener hasta 1,000 filas y 5 MB. La vista previa se procesa en memoria y no conserva el archivo en el servidor.

## Columnas

`name` o `Nombre` es obligatoria. Las demás son opcionales:

| Campo | Encabezados reconocidos |
|---|---|
| Nombre comercial | `name`, `nombre`, `customer`, `contact` |
| Razón social | `legal_name`, `razon_social`, `company_name`, `nombre_fiscal` |
| RFC | `rfc`, `tax_id`, `vat` |
| Correo | `email`, `correo`, `e_mail` |
| Teléfono | `phone`, `telefono`, `telephone`, `mobile` |
| Régimen fiscal | `fiscal_regime`, `regimen_fiscal`, `tax_regime` |
| Código postal fiscal | `fiscal_postal_code`, `codigo_postal_fiscal`, `zip`, `zip_code`, `postal_code` |

Los nombres de encabezado no distinguen mayúsculas, acentos ni espacios. Si el CSV tiene dos columnas equivalentes para el mismo campo, la importación se detiene para evitar elegir una silenciosamente.

## Revisión y creación

La vista previa marca cada fila como lista, posible duplicado o error de validación. El botón de importación crea únicamente filas listas y muestra cuántos registros se crearon, omitieron o requieren corrección. Las filas duplicadas no actualizan al cliente existente: se comparan RFC normalizado, o nombre y correo cuando hay correo. Si la importación se repite, los clientes creados en el intento anterior se detectan como duplicados.

La función requiere permisos para consultar y agregar clientes. No importa contactos adicionales, sitios de servicio, cotizaciones ni oportunidades; tampoco valida que los datos fiscales correspondan a la operación o que el RFC esté vigente ante el SAT. Revisa la información con el cliente antes de facturar.
