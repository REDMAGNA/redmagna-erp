# Importación del catálogo de productos y servicios

En **Inventario → Catálogo de productos y servicios → Importar CSV** se puede cargar el catálogo inicial antes de registrar compras, ventas o existencias. La vista previa no crea registros ni conserva el archivo. La carga acepta CSV UTF-8 delimitado por coma, punto y coma o tabulador, de hasta 5 MB y 1,000 filas.

## Columnas admitidas

`SKU` y `Nombre` son obligatorias. Las demás son opcionales. Los encabezados ignoran mayúsculas, acentos y espacios.

| Campo | Encabezados reconocidos |
|---|---|
| SKU | `sku`, `codigo`, `code`, `default_code`, `internal_reference`, `product_code` |
| Nombre | `name`, `nombre`, `product`, `producto` |
| Descripción | `description`, `descripcion`, `sales_description` |
| Tipo | `kind`, `type`, `tipo`, `product_type` |
| Unidad comercial | `unit`, `unidad`, `unit_of_measure`, `uom` |
| Seguimiento | `tracking_policy`, `tracking`, `seguimiento` |
| Clave SAT producto/servicio | `sat_product_service_key`, `clave_prodserv`, `clave_sat_prodserv`, `clave_producto_servicio` |
| Clave SAT unidad | `sat_unit_key`, `clave_unidad_sat`, `clave_unidad` |
| Objeto de impuesto sugerido | `sat_tax_object`, `objeto_impuesto`, `objeto_imp` |
| Factor de IVA sugerido | `sat_tax_factor`, `factor_iva`, `tipo_factor` |

El tipo acepta producto/stockable o servicio. El seguimiento admite cantidad o serie; los valores `lot`, `by_lots` y `none` se representan como seguimiento por cantidad porque este catálogo no maneja lotes. El objeto fiscal admite `01`/`02` o “No objeto”/“Sí objeto”; el factor admite `Tasa` o `Exento`. Las claves SAT de producto/servicio y unidad se validan con los catálogos locales incluidos.

## Vista previa y alcance

Cada fila queda marcada como lista, SKU existente o error. Solo se crean filas válidas después de confirmar; los SKU existentes se omiten y no se actualizan. Repetir la carga no duplica los SKU ya creados. La importación no carga precios, costos, niveles de existencias, ubicaciones, reglas de reabastecimiento ni series individuales. Las claves y sugerencias fiscales se deben revisar con Contabilidad antes de usarlas en CFDI.
