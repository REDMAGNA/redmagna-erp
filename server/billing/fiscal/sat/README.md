# Recursos CFDI 4.0 del SAT

Estos XSD son los esquemas técnicos publicados por el SAT para validar la estructura CFDI 4.0. Se conservan junto con el ERP para validar sin depender de una descarga en cada emisión.

Archivos de origen:

- `4/cfdv40.xsd` — `http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd`
- `4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt` y sus 33 XSLT auxiliares — `http://www.sat.gob.mx/sitio_internet/cfd/4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt`
- `catalogos/catCFDI.xsd` — `http://www.sat.gob.mx/sitio_internet/cfd/catalogos/catCFDI.xsd`
- `tipoDatos/tdCFDI/tdCFDI.xsd` — `http://www.sat.gob.mx/sitio_internet/cfd/tipoDatos/tdCFDI/tdCFDI.xsd`

Descargados del dominio oficial del SAT el 16 de octubre de 2026. Las rutas de importación del XSD raíz apuntan a las copias locales y las inclusiones XSLT son locales para que la validación y la cadena original no usen la red. Los hashes SHA-256 del conjunto se fijan en `SHA256SUMS.txt`; `python tools/verify_sat_resources.py` detecta cambios o archivos faltantes y el empaquetado Synology lo ejecuta antes de crear el archivo. Tras descargar y revisar manualmente una actualización desde el SAT, `python tools/verify_sat_resources.py --refresh` actualiza los hashes. Esto detecta cambios accidentales, no autentica por sí solo una fuente ni reemplaza la validación fiscal contra los casos y matriz vigentes.

El SAT marca `Exportacion` como atributo requerido en CFDI 4.0. `catalogos/catCFDI.xsd` enumera valores de UsoCFDI, régimen, exportación, forma de pago, ClaveProdServ y unidad; la preparación valida que las claves existan en el esquema empaquetado y el XSD CFDI 4.0 valida de nuevo el XML generado. Una clave existente no garantiza que sea semánticamente adecuada para la operación ni que se cumplan todas las reglas cruzadas de la matriz SAT. La clave `02` puede exigir el Complemento de Comercio Exterior, que todavía no genera este ERP y por ello se rechaza durante la generación. La validación XSD no sustituye la comprobación de vigencia/revocación del certificado ni la aceptación del PAC.
