# CFDI de recepción de pagos 2.0

El esquema `Pagos20.xsd` y `catalogos/Pagos/catPagos.xsd` se descargaron del portal oficial del SAT el 18 de octubre de 2026 y se conservaron con rutas de importación relativas para validación sin conexión:

- [Esquema Pagos 2.0](https://www.sat.gob.mx/sitio_internet/cfd/Pagos/Pagos20.xsd)
- [Catálogo de pagos](https://www.sat.gob.mx/sitio_internet/cfd/catalogos/Pagos/catPagos.xsd)
- [Documentación oficial de recepción de pagos](https://wwwmat.sat.gob.mx/consultas/92764/comprobante-de-recepcion-de-pagos)

Se cambiaron las ubicaciones de importación del XSD a rutas relativas locales para validar sin conexión. `cfdi40-pagos20.xsd` importa en un solo conjunto el XSD CFDI 4.0 y el XSD Pagos 2.0; el esquema CFDI exige declarar los elementos de complementos que aparecen dentro de `cfdi:Complemento`.

La aplicación valida el CFDI completo con ambos esquemas y conserva una cadena original SAT local que ya incluye el XSLT de Pagos 2.0. La validación XSD estructural no sustituye la revisión fiscal, la matriz de errores SAT, la validación del PAC ni la comprobación de vigencia del CSD.
