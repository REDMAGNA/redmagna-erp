# Diseño inicial: contabilidad, facturación y CFDI/FEL para REDMAGNA

## Hallazgo de integración FEL (documentación pública)

El manual público de **FEL Premium / Facturar en Línea** describe un Web Service SOAP con WSDL de pruebas (`https://app.fel.mx/WSTimbrado33Test/WSCFDI33.svc?WSDL`) y productivo (`https://www.fel.mx/WSTimbrado33/WSCFDI33.svc?WSDL`). Para `TimbrarCFDI` documenta usuario de timbrado y contraseña, XML CFDI 4.0 y una referencia única; la respuesta incluye XML timbrado, UUID, fecha y sellos. El manual indica que el usuario de timbrado puede ser distinto del usuario del portal y que timbrar en productivo consume timbres. Describe cancelación como otra operación; la cancelación no cuenta con ambiente de pruebas y requiere datos del emisor, UUID, motivo y certificado/clave privada para la solicitud.

Redmagna confirmó que su proveedor es **Facturar en Línea (FEL Premium)**. La cuenta técnica, el WSDL vigente para esa cuenta y las credenciales de sandbox siguen pendientes de validación. La configuración predeterminada usa el WSDL de pruebas; el WSDL productivo requiere habilitar explícitamente `FEL_ALLOW_PRODUCTION`. El envío asigna una referencia idempotente y guarda eventos mínimos sin credenciales; los fallos de transporte permanecen en revisión y se consultan por referencia antes de otra acción. Falta validar el flujo con la cuenta de Redmagna y el contador.

Fuente técnica consultada: [Manual de API de timbrado FEL](https://www.facturarenlinea.com.mx/descargas/FLP_Manual_de_API_Timbrado.pdf). Este manual es específico de FEL Premium; validar su versión con el proveedor antes de implementarlo.

### Contraste del adaptador con el manual oficial

La revisión del manual público de API Timbrado 4.0 confirma que los endpoints SOAP de pruebas y producción que usa el adaptador coinciden con los publicados por FEL; `TimbrarCFDI` recibe credenciales, XML y referencia, y la referencia debe ser única. El usuario de timbrado publicado mide 12–13 caracteres y la contraseña al menos 6; el adaptador ahora valida esos requisitos antes de llamar al servicio y recorta espacios externos del usuario. El manual exige consultar `ConsultarTimbrePorReferencia` cuando el servicio no responde o tarda, para detectar un timbrado ya realizado y evitar duplicarlo; el flujo del ERP conserva la referencia y deja el resultado de transporte incierto en revisión, con consulta explícita, sin reintento automático. El manual advierte además que productivo consume timbres cuando la petición es exitosa y que una tasa alta de solicitudes erróneas puede generar cargos o bloqueo, por lo que la validación local y el ambiente de pruebas son necesarios antes de habilitar productivo.

No se pudo leer el WSDL directamente durante esta revisión. Por tanto, la documentación confirma las rutas y los nombres descritos por FEL, pero no permite certificar hoy la forma exacta de los mensajes SOAP, el contrato publicado actualmente por esos endpoints ni el WSDL habilitado para la cuenta de Redmagna. Tampoco se hicieron llamadas al servicio ni se usaron credenciales. El manual recomienda para cancelaciones un rango de hasta 200 UUID en una solicitud (y deja claro que no hay sandbox); el ERP prepara una cancelación individual y bloquea su envío salvo habilitación explícita en producción. La cancelación es irreversible, así que sigue pendiente validación con contador y proveedor. En la consulta del 18 de octubre de 2026, el manual oficial disponible en la URL pública consultada también recomienda esperar 24 horas desde la emisión antes de solicitar cancelación y señala que un resultado exitoso con código 201 puede consumir un timbre; el ERP conserva la confirmación de espera en la interfaz y solo manda un UUID por solicitud. El mismo manual especifica que el PFX debe corresponder al CSD con que se emitió el CFDI. Se añadió una validación local que abre el PFX, coteja su certificado DER exacto y número SAT con los atributos del CFDI, y verifica que la llave privada corresponda al certificado antes de enviar datos al SAT. Esto comprueba correspondencia del certificado; no valida vigencia, revocación ni el contrato WSDL.

Se añadió un transporte SOAP para `TimbrarCFDI` y `ConsultarTimbrePorReferencia`, basado en el manual público de FEL. El WSDL de pruebas documentado es `https://app.fel.mx/WSTimbrado33Test/WSCFDI33.svc?WSDL`; requiere confirmar su vigencia y los campos con la cuenta de Redmagna. El paquete incluye los XSD CFDI 4.0 y XSLT de cadena original publicados por el SAT. Para CFDI de ingreso tipo I, la pantalla/API generan un XML firmado localmente con el CSD montado fuera del código, y la acción explícita de envío llama a FEL usando referencia idempotente. Los resultados inciertos quedan en estado enviado y requieren consulta por referencia antes de cualquier acción posterior. La clave de exportación `02` se bloquea hasta implementar Comercio Exterior. El XSD no sustituye catálogos SAT, matriz de errores, revocación del certificado ni aceptación de FEL. El envío está implementado, pero falta validarlo con las credenciales sandbox y la cuenta de Redmagna.

**Fecha de revisión:** 18 de octubre de 2026
**Estado:** diseño funcional/técnico para discusión; proveedor confirmado por Redmagna como FEL Premium. La generación y el sellado local de CFDI 4.0 de ingreso y el envío FEL están implementados para el subconjunto descrito; no sustituyen la revisión del contador, la validación con credenciales de sandbox ni la comprobación del WSDL de la cuenta.

El backend contiene el primer libro de pólizas manuales (catálogo, diarios, borrador, validación de cargos/abonos, contabilización y reversa), submayores de clientes y proveedores para las operaciones que ya existen en el ERP y configuración de generación de pólizas. En **Contabilidad → Catálogo contable y diarios**, Contabilidad puede crear cuentas y diarios y activar o desactivar sus registros; no se permite desactivar una cuenta con subcuentas activas ni una cuenta o diario usado por una regla automática activa. La sección **Automatización de pólizas** permite a Contabilidad elegir diario y cuentas para cuatro eventos: factura/cobro de cliente y factura/pago de proveedor. La cuenta determina las imputaciones; al registrar cada evento se genera un borrador idempotente para revisión y nunca se contabiliza automáticamente. Un bloqueo transaccional en PostgreSQL serializa reintentos simultáneos del mismo origen antes de buscar o crear ese borrador. La factura CFDI no vuelve a generar ingresos para evitar duplicar el asiento de la factura interna. La reversa de un cobro se inicia desde su registro, conserva el historial y sus aplicaciones, reabre la cuenta por cobrar y crea una póliza inversa; el libro general bloquea la reversa directa de pólizas originadas por cobros. La conciliación importa estados bancarios por CSV; propone líneas ya contabilizadas de la misma cuenta e importe exactos y las ordena por referencia, texto y fecha. La sugerencia es heurística y Contabilidad confirma cada vínculo; el cierre exige saldo cuadrado y todos los movimientos vinculados, con usuario y fecha. La **Balanza de comprobación** puede importar una sola carga de cuentas de movimiento a la fecha de apertura y preparar una póliza general en borrador; exige cargos y abonos iguales, y Contabilidad debe revisarla y contabilizarla. No cambia saldos hasta contabilizarse. Las partidas abiertas de clientes/proveedores cuentan con conciliación contra las cuentas de control, vista previa CSV, lote persistente e idempotente, reserva de folios y revisión de dos personas. Publicar genera únicamente auxiliares operativos y conserva los saldos históricos reportados; no crea pólizas individuales. Los XML, UUID, detalle de impuestos y pagos previos del sistema anterior todavía no se importan, por lo que no se emiten complementos Pagos 2.0 con esos saldos hasta verificar su historia fiscal. Consulta el [diseño de apertura de auxiliares](apertura-saldos-auxiliares-v1.md), [Facturas internas, cobros y CFDI](facturas-cobros-cfdi-v1.md) y [saldos iniciales del mayor](plantilla-saldos-iniciales.csv).

La API expone `/api/accounting/accounts/`, `/api/accounting/journals/`, `/api/accounting/entries/`, `/api/accounting/posting-configurations/`, `/api/accounting/bank-statements/`, `/api/accounting/reports/trial-balance/`, `/api/accounting/reports/general-ledger/?account_code=1010` y `/api/accounting/reports/financial-statements/`. La pantalla de Contabilidad permite asignar diario y cuentas a reglas de generación de pólizas; se pueden activar solo después de recibir el plan aprobado del contador. Los eventos configurados generan borradores idempotentes que requieren contabilización manual. La factura CFDI no crea un segundo asiento de ingreso. La balanza toma solo pólizas contabilizadas y muestra saldos de apertura, cargos/abonos del periodo y saldos de cierre. El libro mayor devuelve el detalle ordenado por fecha y número de póliza de una cuenta, con su saldo de apertura, saldo acumulado y totales del periodo; también excluye borradores y mantiene visible el vínculo de las pólizas reversadas. El estado de resultados resume ingresos y gastos del periodo; el balance general muestra activos, pasivos y capital a la fecha final, más el resultado acumulado todavía no cerrado. Los reportes reciben `date_from` y `date_to` en formato ISO. Son internos y preliminares: requieren validar la clasificación del catálogo y el proceso de cierre con el contador; no sustituyen estados fiscales ni financieros dictaminados. El grupo Contabilidad puede crear y editar pólizas en borrador, contabilizarlas y revertirlas; los catálogos empiezan vacíos y su configuración no debe inventarse antes de recibir el plan de cuentas de Redmagna. Para conciliación importa cada estado CSV, revisa sugerencias por cuenta, importe, referencia y fecha, y confirma manualmente los vínculos. Si falta una póliza, Contabilidad puede preparar un borrador balanceado con la cuenta de contrapartida que elija; debe revisarlo y contabilizarlo antes de vincularlo. El flujo no crea asientos contabilizados automáticamente.

## Decisión principal de diseño

Separar cuatro hechos distintos para no perder historial ni mezclar responsabilidades:

1. **Venta y trabajo:** qué se vendió, qué se entregó, y cuál es el importe comercial a cobrar.
2. **Factura de cuentas por cobrar:** el documento interno que controla vencimiento, saldo y cobranza.
3. **CFDI:** el comprobante fiscal timbrado, cancelado o sustituido y su relación con otros comprobantes.
4. **Póliza:** el registro contable de doble partida con cargos y abonos.

Un CFDI no debe borrarse ni reemplazarse en el mismo registro. La factura interna, el CFDI original, una sustitución, el pago recibido y su póliza deben conservar sus relaciones y eventos.

## Flujo de negocio propuesto

```text
Orden de venta / trabajo ejecutado
  → preparar factura interna y sus conceptos
  → validar datos fiscales y política de pago
  → emitir/timbrar por adaptador FEL
  → conservar UUID, XML, respuesta y estado del comprobante
  → registrar póliza según política aprobada por el contador
  → registrar pagos y aplicarlos a una o varias facturas
  → generar complemento de pago cuando corresponda
  → conciliar el banco y registrar su efecto contable
```

Los pasos de timbrado y contabilización serán procesos relacionados, pero con estados separados. El contador debe confirmar cuándo se contabiliza la factura y cómo se registran impuestos, anticipos, diferencias y cancelaciones.

## Entidades recomendadas

| Entidad | Campos/relaciones clave | Regla de integridad |
|---|---|---|
| `CustomerInvoice` | Cliente, orden/entrega de origen, conceptos, moneda, fechas de emisión/vencimiento, saldo, estado interno | Conserva el importe y el origen comercial; las correcciones se hacen con otro documento relacionado |
| `CustomerInvoiceLine` | Descripción, cantidad, unidad, producto/servicio, clave SAT, descuentos e impuestos configurados | Guardar cantidades y decimales exactos usados para el documento; no inferir el tratamiento fiscal solo del tipo de servicio |
| `FiscalDocument` | Tipo/versión CFDI, emisor/receptor como snapshot, UUID, serie/folio, sello/timbre, XML, PDF, proveedor y factura relacionada | Un comprobante emitido es inmutable; sustitución/cancelación agrega otro documento y eventos |
| `FiscalEvent` | Solicitud/respuesta de timbrado, consulta o cancelación, fecha, código, estado anterior/nuevo, idempotencia y referencia FEL | Bitácora append-only; no guardar contraseñas ni llaves privadas en la bitácora |
| `Payment` | Fecha, importe, moneda, referencia bancaria, método operativo, depósito/cuenta y estado de conciliación | No exceder el disponible del pago ni duplicar aplicaciones |
| `PaymentAllocation` | Pago, factura, importe aplicado y fecha | La suma aplicada no puede exceder el pago ni el saldo exigible según política |
| `PaymentComplement` | Documento de pago CFDI, pagos relacionados, UUID(s), archivos y eventos de timbrado | Es distinto del registro interno de cobro; relaciona comprobantes según los catálogos y reglas vigentes |
| `Account` | Código, nombre, tipo, moneda opcional, cuenta padre, activa y permite conciliación | El catálogo se configura desde el catálogo aprobado por Redmagna y su contador |
| `JournalEntry` / `JournalLine` | Fecha contable, diario, origen, estado, cuenta, contacto, referencia, cargo y abono | Al contabilizar debe balancear; entradas contabilizadas no se editan ni eliminan, se corrigen con reversa y nueva póliza |
| `BankStatementLine` / conciliación | Cuenta, fecha, referencia, importe y movimientos emparejados | Conciliar no equivale a recibir el pago ni a contabilizar una factura; conservar el vínculo de la conciliación |

## Estados independientes

### Factura interna y cuenta por cobrar

`borrador → lista_para_revisión → abierta → parcialmente_pagada → pagada`

Puede tener vencimiento, disputa o saldo incobrable como atributos/estados de cobranza. La cancelación comercial no altera por sí sola el estado fiscal ni borra una póliza.

### CFDI y proveedor

`preparado → envío_pendiente → timbrado | rechazado`

Para cancelación: `timbrado → cancelación_solicitada → cancelado | cancelación_rechazada`. La respuesta puede ser asíncrona. Una falla de red con resultado incierto debe consultarse antes de reintentar para evitar emitir duplicados.

Guardar cada respuesta del PAC, incluyendo errores, folio de solicitud, UUID si existe y marcas de tiempo. Operar con idempotencia y una acción de consulta de estado; nunca asumir que el timeout significa que el PAC no timbró.

### Pólizas

`borrador → contabilizada → reversada`

Al contabilizar, validar cargos = abonos en moneda de la póliza y registrar quién, cuándo y con qué regla generó cada línea. No modificar una póliza contabilizada: crear asiento reverso y, cuando corresponda, el nuevo asiento.

## Datos fiscales que deben capturarse como snapshot

El SAT indica para CFDI 4.0 datos obligatorios del receptor como RFC, nombre/razón social, régimen fiscal y código postal del domicilio fiscal; también describe el objeto del impuesto y otros datos del formato. Al emitir, copiar los datos utilizados al documento fiscal histórico, aunque posteriormente cambie la ficha del cliente. ([Formato Anexo 20](https://wwwmat.sat.gob.mx/cs/Satellite?c=ConsultaInfo&childpagename=SatTyR%2FConsultaInfo%2FSAT_LandingConsultaInformacion&cid=1462228635025&packedargs=d%3DTouch&pagename=TySWrapper))

La pantalla de preparación debería incluir, de acuerdo con la guía/catalogación que valide el contador: uso CFDI, régimen y domicilio fiscal del receptor, exportación, método y forma de pago, moneda/tipo de cambio, clave de producto/servicio, unidad, objeto del impuesto, tasas/retenciones, descuentos, impuestos trasladados y relacionados. Las claves y reglas deberán guardarse con su versión/fecha de vigencia; no se deben congelar catálogos fiscales en el código.

La factura interna puede existir antes del timbrado. La emisión debe registrar una copia exacta del XML timbrado y su UUID, no reconstruir el comprobante a partir de la ficha actual del cliente.

## Cobros y complementos de pago

Registrar el cobro real, su referencia y su aplicación por separado del CFDI tipo Pago. El SAT documenta un complemento de pagos para parcialidades o pagos diferidos y mantiene una guía y documentación técnica; la política del sistema debe determinar, con asesoría contable vigente, cuándo emitirlo y qué pagos asociar. ([Complemento de pagos SAT](https://wwwmat.sat.gob.mx/consultas/92764/comprobante-de-recepcion-de-pagos), [material y guías de factura SAT](https://www.sat.gob.mx/minisitio/Factura/emite_materialdeayudaparafactura.htm))

El SAT distingue método de pago (momento de liquidación) de forma de pago (medio utilizado), con claves que deben provenir del catálogo vigente. No representar ambos con un solo campo. ([Infografía SAT sobre forma y método de pago](https://www.sat.gob.mx/minisitio/Factura/documentos/infografias/formaspagometodopagos.pdf))

## Cancelación y sustitución CFDI

Guardar motivo de cancelación, UUID que sustituye cuando aplique, solicitud, estado de aceptación y respuesta del PAC/SAT. Las claves publicadas por el SAT incluyen `01` errores con relación, `02` errores sin relación, `03` operación no realizada y `04` operación nominativa relacionada en factura global. Para sustitución con motivo `01`, el SAT pide informar el folio fiscal que sustituye; la respuesta de cancelación puede depender de aceptación o consulta posterior. ([Esquema de cancelación SAT](https://wwwmatnp.sat.gob.mx/consultas/91447/nuevo-esquema-de-cancelacion))

Implementar las reglas como catálogos/configuración versionada y actualizar su fuente antes de una liberación fiscal; no codificar los plazos de aceptación como una constante permanente.

## Adaptador FEL

Redmagna confirmó **Facturar en Línea (FEL Premium)** como proveedor. El manual público describe `TimbrarCFDI` con XML CFDI 4.0 y referencia única. También indica que, ante falta de respuesta, se debe consultar el timbre por referencia para confirmar el resultado y evitar duplicados; la consulta devuelve XML/UUID y no consume otro timbre. El ERP ya dispone de una consulta explícita para documentos enviados: usa el `provider_request_id` guardado como referencia, registra la consulta y adopta el UUID/XML si FEL confirma el timbre. Una respuesta negativa o incierta no habilita un reenvío automático. El transporte SOAP no sigue redirecciones HTTP para evitar reenviar credenciales o XML fiscal a destinos distintos de los endpoints configurados. Se agregó la solicitud de cancelación con motivo SAT, UUID sustituto, PFX del CSD y confirmación explícita; está desactivada por defecto. El manual de FEL advierte que no hay sandbox para cancelación y que la operación es irreversible. Antes de usarla quedan por validar con Redmagna el WSDL vigente, credenciales, códigos de respuesta y aceptación del receptor. El manual es una guía pública, no prueba de acceso a la cuenta ni del comportamiento del endpoint actual. ([Manual de API Timbrado FEL Premium](https://www.facturarenlinea.com.mx/descargas/FLP_Manual_de_API_Timbrado.pdf))

Una persona con permiso independiente de envío de copias fiscales puede enviar manualmente por correo una copia del CFDI timbrado al correo guardado en la ficha del cliente. El XML siempre se adjunta; el PDF se incluye si FEL lo devolvió y sigue disponible. Cada intento confirmado o incierto queda en la bitácora del CFDI. Una falla de respuesta SMTP puede ocurrir después de aceptar el mensaje; por ello no hay reintento automático y la pantalla pide revisar la bitácora antes de volver a enviarlo. Esta acción no timbra ni cancela el CFDI y no cambia su estado contable.

Implementación propuesta:

```text
ERP → interfaz FiscalProvider
       ├── validar(payload) → errores legibles
       ├── timbrar(idempotency_key, payload) → respuesta normalizada + archivos
       ├── consultar(identificador) → estado actual
       ├── solicitar_cancelacion(uuid, motivo, uuid_sustituto?)
       └── descargar_documentos(uuid) → XML/PDF
```

Guardar secretos fuera de la base de datos y del repositorio, usando variables secretas o el almacén seguro disponible. Redactar credenciales de logs. Cifrar respaldos y restringir acceso a XML/PDF y datos fiscales.

## Reglas contables aún pendientes de Redmagna

No inicializar pólizas productivas ni saldos fiscales hasta recibir y validar con el contador:

1. Catálogo de cuentas, diarios, periodo fiscal y códigos de impuestos.
2. Cuentas por cobrar/ingresos/IVA trasladado e IVA pendiente de cobro, según aplique al régimen y política contable.
3. Reconocimiento de ingresos, anticipos, costos de material/equipo, inventario, instalación y soporte.
4. Política para pagos parciales, diferencias, comisiones, notas de crédito, devoluciones y cancelaciones fiscales.
5. Tratamiento de redondeo, moneda, tipo de cambio y fecha contable.
6. Estados de cuenta bancarios y método de importación/conciliación.

## Fuentes revisadas

- [SAT: Anexo 20, formato y datos CFDI](https://wwwmat.sat.gob.mx/cs/Satellite?c=ConsultaInfo&childpagename=SatTyR%2FConsultaInfo%2FSAT_LandingConsultaInformacion&cid=1462228635025&packedargs=d%3DTouch&pagename=TySWrapper)
- [SAT: guías de llenado de CFDI y complementos](https://www.sat.gob.mx/minisitio/Factura/emite_materialdeayudaparafactura.htm)
- [SAT: complemento de recepción de pagos](https://wwwmat.sat.gob.mx/consultas/92764/comprobante-de-recepcion-de-pagos)
- [SAT: cancelación de facturas](https://wwwmatnp.sat.gob.mx/consultas/91447/nuevo-esquema-de-cancelacion)
- [SAT: diferencia entre forma y método de pago](https://www.sat.gob.mx/minisitio/Factura/documentos/infografias/formaspagometodopagos.pdf)
