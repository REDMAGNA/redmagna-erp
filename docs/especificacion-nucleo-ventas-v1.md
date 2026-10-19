# REDMAGNA ERP: especificación inicial del núcleo de ventas

**Estado:** diseño de primera iteración. No es todavía un sistema contable ni una integración fiscal.

## Modelo de operación

```text
Cliente → Cotización borrador → Enviada → Aprobada → Orden de venta → Orden de trabajo
                         ↘ Cancelada                  ↘ trabajo/cierre en curso
```

La aprobación produce dos registros distintos: la orden comercial conserva el compromiso aceptado y la orden de trabajo permite planear la ejecución. El cambio y sus registros asociados se guardan en una transacción para no dejar una cotización aprobada sin orden.

Las salidas y devoluciones de materiales pueden registrarse desde la orden de trabajo y se vinculan a ella en la bitácora de inventario. El catálogo de almacén no contiene precios ni costos. Cada cotización puede tener una hoja interna de costos separada y protegida por permisos; la hoja no se incluye en la propuesta ni en el enlace público de aceptación.

## Hoja interna de costos por cotización

Ventas y Gerencia pueden registrar equipo, materiales, mano de obra, traslados, subcontratación y otros costos, con cantidad y costo unitario MXN. Los costos opcionales se mantienen aparte de la base obligatoria. La hoja compara costos y subtotales de venta base y opcionales antes de IVA, estima utilidad y margen bruto para ambos grupos por separado, y opcionalmente calcula subtotales sugeridos para un margen objetivo mediante `costo ÷ (1 − margen)`. El objetivo no tiene valor predeterminado; un margen de 100% no se admite.

El resultado es una referencia para preparar la cotización, no una decisión de precio automática: guardar o modificar costos nunca altera sus conceptos, descuentos, impuestos ni precio de venta. Al enviar la cotización, el costeo queda de solo lectura; crear una revisión copia la hoja como punto de partida independiente para el nuevo borrador. No incluye costos indirectos asignados, costo laboral calculado desde nómina, tipos de cambio ni valuación de inventario.

La API autenticada `GET/PUT /api/quotes/{id}/cost-sheet/` usa permisos separados `sales.view_quotecostsheet` y `sales.change_quotecostsheet`. Ventas y Gerencia reciben acceso inicial; los usuarios sin permiso de costeo no reciben importes internos en la API ordinaria de cotizaciones.

La pantalla permite descargar la hoja vigente o la captura actual como CSV compatible con Excel, con costos y resumen de margen base/opcional. El archivo no contiene fórmulas ejecutables ni datos fiscales del cliente; las celdas de texto se exportan como texto para evitar que una descripción se interprete como fórmula.

## Autorización de descuentos excepcionales

La política de descuentos se configura por empresa desde Django Admin. Se instala desactivada y con límite de 0%; Gerencia debe habilitarla y definir el porcentaje máximo antes de que tenga efecto. Cuando cualquier concepto de una cotización enviada excede el límite, el enlace público y la aprobación interna quedan bloqueados hasta que una persona con permiso `sales.approve_quote` autorice el descuento. La interfaz de cotizaciones muestra el mayor descuento solicitado y el límite vigente para la revisión de Gerencia. Esta autorización queda separada de la aceptación de la cotización.

La autorización registra quién aprobó, cuándo, el límite aplicado, el descuento máximo y una huella de los conceptos comerciales revisados. Un cambio en cualquier concepto invalida la autorización para la nueva versión del contenido. La bitácora de autorizaciones es de solo lectura. El sistema no define un umbral comercial para Redmagna; debe decidirlo Gerencia antes de activar la política.

Cada concepto de cotización admite un descuento porcentual de 0 a 100; el precio unitario se conserva, el descuento se redondea a centavos por línea y la tasa de IVA puede variar por concepto; el IVA se calcula sobre el importe neto de cada renglón. La aceptación parcial vuelve a calcular el descuento sobre la cantidad aceptada; ese porcentaje y la tasa de IVA acompañan la línea a la factura interna y al snapshot CFDI; la clasificación SAT de objeto y factor se confirma después por concepto. La política opcional de autorización de descuentos ya está implementada y se instala apagada: antes de habilitarla, Gerencia debe definir el máximo y mantenerlo coherente con su regla comercial. Cada concepto de cotización puede vincularse opcionalmente a un artículo del catálogo. Equipo y material aceptan productos con existencias; instalación y servicio aceptan productos de servicio. La descripción y el precio siguen editables en la cotización; vincular un SKU no reemplaza la hoja comercial ni cambia el importe. Al aprobarse la cotización, los conceptos aprobados de equipo/material vinculados al catálogo se copian como requerimientos inmutables en la orden de trabajo con la cantidad aceptada. El enlace también se conserva al crear la factura interna y en el snapshot CFDI de revisión, junto al SKU, para identificar el artículo. El requerimiento todavía no reserva stock ni alimenta la sugerencia de compras hasta elegir ubicación y apartar el material.

El cliente puede guardar un plazo predeterminado opcional de hasta 3,650 días naturales. Al crear una cotización, se copia como snapshot editable mientras siga en borrador; si no hay plazo, permanece vacío. Al cambiar el cliente de un borrador, se propone el plazo predeterminado del nuevo cliente, que Ventas puede ajustar. Al facturar una orden aprobada, la cuenta por cobrar propone el vencimiento sumando esos días a su fecha de emisión. Contabilidad puede corregir el vencimiento mientras la factura está en borrador. Es un único vencimiento, sin calendario de parcialidades ni cálculo de pronto pago.

Ventas puede crear plantillas reutilizables con título, vigencia, notas, tasa predeterminada y tasa de IVA por concepto. Al elegir una plantilla, el formulario precarga los valores para una nueva cotización; al guardarla, los conceptos y precios quedan copiados en la cotización, de modo que cambios posteriores a la plantilla no alteran propuestas ya creadas. Las plantillas se archivan en lugar de eliminarse. Los conceptos opcionales se identifican en la plantilla o cotización, no se incluyen en el total base y se presentan aparte como importe estimado. Al aceptar por el enlace público, el cliente incluye o excluye cada concepto por su cantidad completa; la decisión se guarda en la línea aprobada y establece la cantidad máxima que se puede facturar. El endpoint de aprobación interna acepta `optional_line_ids`; si no se envía, se aprueban solo los conceptos obligatorios. La cotización pública puede imprimirse o guardarse como PDF desde el navegador antes o después de aceptarla; la impresión muestra las opciones seleccionadas y, si ya se aceptó, solo las cantidades aprobadas. Siguen pendientes las cantidades parciales y las plantillas PDF diseñadas para la marca.

Ventas puede escoger en una cotización un domicilio frecuente de `/api/customer-sites/`; nombre, domicilio y contacto quedan como snapshot en la propuesta que recibe el cliente. Al aprobarla, esos datos se copian a la orden de trabajo. Gerencia y Operaciones programan fecha/hora, asignan a una persona activa y anotan la ejecución. El sistema rechaza horarios que se traslapen con otra orden activa de la misma persona, serializando la asignación por usuario para evitar dos reservas concurrentes incompatibles. Todavía no calcula capacidad con jornada, ausencias, habilidades/roles ni traslados entre domicilios. Los sitios se pueden seleccionar o guardar desde una orden, y cada orden conserva su copia histórica aunque cambie el catálogo. Un sitio inactivo se conserva en el historial y no se ofrece para nuevas cotizaciones u órdenes. La ubicación y contacto de una orden pueden editarse mientras el trabajo está abierto; después de registrar la conformidad quedan congelados y el cambio se audita sin copiar datos personales a la bitácora. Operaciones agrega entradas inmutables de fecha, horas y trabajo realizado mientras la orden está en curso. La transición a terminada exige una nota de cierre; una orden terminada o cancelada es inmutable en esta primera iteración.

### Perfil Técnicos

El grupo **Técnicos** restringe la lista de órdenes al usuario asignado. En una orden en curso, puede registrar horas, completar la lista de verificación, subir evidencia, capturar la conformidad del cliente y guardar la nota de cierre. No puede consultar el catálogo de sitios, reasignar personas, modificar agenda ni ver reportes globales de horas. La API aplica el mismo alcance de asignación en cada acción para impedir acceso directo a órdenes ajenas.

## Objetos

| Objeto | Propósito | Reglas de primera iteración |
|---|---|---|
| Cliente | Datos comerciales y fiscales básicos | Baja lógica con `is_active`; no se elimina si ya tiene cotizaciones |
| Contacto de cliente | Personas comerciales, área/puesto, correo y teléfono | Varios por cliente; uno principal activo como máximo; se archiva, no se elimina ni se mueve a otro cliente |
| Cotización | Propuesta con folio, vigencia, conceptos y estado | Folio `RM-año-secuencia`; solo borradores editables; enviar requiere conceptos; aprobación requiere enviada y vigente |
| Concepto de cotización | Equipo, material, instalación o servicio, cantidad, precio, descuento porcentual e IVA | Cantidad positiva; precio no negativo; descuento de 0 a 100; tasa de 0 a 100; vínculo opcional a producto compatible; IVA sobre importe neto; importes guardados y serializados con decimales |
| Orden de venta | Aceptación comercial derivada de una cotización | Una por cotización aprobada; registra si la confirmó personal interno o el cliente |
| Orden de trabajo | Ejecución del servicio | Se crea programada al aprobar venta; estados: programada, en curso, bloqueada, terminada o cancelada; permite agenda, responsable y notas de cierre |
| Evidencia de servicio | Fotos o documentos ligados a la orden | Solo JPG/PNG/WEBP/PDF de hasta 10 MB; almacenamiento privado persistente; autor, fecha, descripción y descarga con permisos; no se edita ni elimina |
| Bitácora de horas | Tiempo de ejecución por orden de trabajo | Entradas de 0.01 a 24 horas, autor y descripción; máximo 24 horas diarias por persona; solo inserción; se suman para mostrar esfuerzo total |
| Movimiento de materiales | Existencia entregada o devuelta en un trabajo | Solo productos controlables; cantidad positiva; movimiento inmutable; impide stock negativo; salida solo a orden programada o en curso |
| Requerimiento de material | Cantidad aprobada de una línea de equipo/material de cotización con producto de inventario | Se crea como snapshot inmutable al aprobar; excluye servicios, conceptos sin SKU y opciones no aceptadas |
| Evento de auditoría | Historial de acciones y transiciones | Solo inserción; actor, entidad, fecha, acción y estados anterior/nuevo |

## Transiciones

| Registro | Estado inicial | Acción | Estado resultante | Condiciones |
|---|---|---|---|---|
| Cotización | Borrador | Enviar | Enviada | Debe tener al menos un concepto y no estar vencida |
| Cotización | Enviada | Aprobar | Aprobada | Debe seguir vigente; crea orden de venta y orden de trabajo |
| Cotización | Borrador o enviada | Cancelar | Cancelada | Conserva el registro y genera auditoría |
| Orden de trabajo | Programada | Iniciar | En curso | Transición permitida |
| Orden de trabajo | En curso | Bloquear / terminar | Bloqueada / terminada | Terminar requiere nota de cierre |
| Orden de trabajo | Bloqueada | Reanudar / cancelar | En curso / cancelada | Transición permitida |
| Orden de trabajo | Terminada o cancelada | — | Terminal | No permite transición en esta versión |

## API inicial

- `POST /api/auth/token/`: obtiene token con usuario y contraseña.
- `/api/customers/`: lectura para usuarios autenticados; cambios solo por personal con acceso de administración.
- `/api/customer-contacts/?customer={uuid}&active=all`: lista contactos activos y archivados de un cliente. Personal con permisos de clientes puede agregar, editar, marcar un contacto principal, archivar o reactivar; los registros no se eliminan ni se cambian de cliente.
- `/api/quotes/`: consulta y alta de cotizaciones; admite `customer_contact`, que debe pertenecer al cliente y estar activo. Guarda nombre y correo destinatarios como snapshot, que no cambian si después se edita la ficha de contacto. Sin contacto elegido usa los datos del cliente. Las revisiones copian el contacto y snapshot. Las cotizaciones enviadas conservan inmutable su destinatario. También admite `customer_site` y snapshots del domicilio y contacto del servicio. `send-email` dirige el mensaje al correo guardado y el enlace de aceptación exige ese mismo correo; la aceptación registra nombre/fecha y crea orden de venta/trabajo en una transacción.
- `/api/quote-templates/`: lista, crea y edita plantillas activas; `is_active=false` las archiva sin borrar el historial. La creación exige entre 1 y 50 conceptos y valida la compatibilidad del producto con cada tipo. La interfaz permite precargar una plantilla al crear una cotización y guardar los valores actuales, incluidas las tasas de IVA por concepto, como nueva plantilla. `POST /api/quotes/` también admite `template` y puede crear el snapshot desde el servidor si no se envían líneas.
- `GET/POST /cotizaciones/aceptar/{token}/`: página pública con token firmado temporal; permite seleccionar conceptos opcionales, muestra la tasa de IVA por concepto, el total base y actualiza el total con opciones elegidas. El botón **Imprimir / guardar PDF** usa la impresión del navegador y conserva un resumen de selección; tras aceptar muestra e imprime solo los conceptos y cantidades aprobadas. Al aceptar, guarda en cada línea su cantidad aprobada (cero para opciones excluidas), registra el nombre/correo y crea los documentos comerciales derivados en una transacción; la aceptación comercial no es una firma electrónica certificada. La vista imprimible presenta una hoja comercial con cabecera configurable (`ERP_COMPANY_*`) y no inventa identidad fiscal.
- Cada elemento de `lines` acepta `catalog_product` opcional; equipo/material requiere artículo con existencias e instalación/servicio requiere un producto de tipo servicio. La cantidad, descripción y precio siguen capturándose por separado.
- `/api/work-orders/`: consulta de órdenes y `material_requirements` (snapshot de cantidades aceptadas de equipo/material con SKU); incluye `approved_total`, total aceptado con IVA según cantidades aprobadas y descuentos/tasas de cada renglón. La pantalla de proyecto cruza ese importe con las cantidades aún facturables y las facturas internas, sus borradores y saldos de CxC. Son importes comerciales/operativos: no representan costo, margen ni confirmación de timbrado CFDI. Cambio de estado con `transition`; agenda, asignación, domicilio del servicio, contacto del sitio y notas con `PATCH /{id}/schedule/`. El domicilio y teléfono de sitio no modifican la ficha fiscal del cliente y quedan congelados después de registrar la conformidad.
- `/api/checklist-templates/`: lista, crea y edita plantillas reutilizables de listas de verificación; no elimina registros, permite archivarlos con `is_active=false`. `POST /api/work-orders/{id}/checklist/apply-template/` copia sus puntos a una orden vacía. La copia es propia de la orden: cambios posteriores a la plantilla no cambian órdenes existentes. Operaciones puede además guardar una lista de una orden como una nueva plantilla.
- `/api/customer-sites/`: catálogo de domicilios por cliente; admite lista, detalle, creación y edición parcial, pero no eliminación. Puede filtrarse con `?customer={uuid}`. La edición del catálogo no altera las copias históricas en cotizaciones enviadas ni en órdenes de trabajo.
- `/api/work-orders/assignees/`: lista de usuarios activos disponible solo para Gerencia y Operaciones.
- `POST /api/work-orders/{id}/log-hours/`: Operaciones registra fecha, duración y descripción mientras la orden está en curso; la lista y el total de horas se incluyen en la respuesta de la orden.
- `GET /api/work-orders/hours-report/?date_from=AAAA-MM-DD&date_to=AAAA-MM-DD`: Gerencia y Operaciones consultan horas agrupadas por orden y persona; el periodo admite hasta un año. Es un reporte operativo, no una nómina ni un cálculo de costo laboral.
- `GET/PUT /api/quotes/{id}/cost-sheet/`: lectura y guardado de hoja interna de costos con categorías, cantidades, costos unitarios, opciones y margen objetivo; una hoja no puede editarse después de enviar su cotización. Los precios sugeridos no se aplican automáticamente.
- `POST /api/work-orders/{id}/customer-acceptance/`: captura una vez nombre del contacto del cliente, correo opcional, observaciones y confirmación del personal de que el cliente manifestó su conformidad. Requiere nota de cierre y checklist completo; devuelve el acuse inmutable con fecha y usuario capturador. Es un registro operativo, no una firma electrónica certificada, y no es requisito obligatorio para terminar la orden.
- `GET/POST /api/work-orders/{id}/evidence/`: consulta o carga archivos privados; el cuerpo de alta usa `multipart/form-data` con `file` y `description` opcional. `GET /api/work-orders/{id}/evidence/{evidence_id}/download/` entrega el archivo como descarga autenticada.
- `GET /admin/`: administración inicial de datos y usuarios.

## Permisos iniciales

| Grupo | Acceso previsto |
|---|---|
| Administración | Todos los permisos del módulo inicial; normalmente conviene asignarlo a la cuenta administradora, que también es superusuario |
| Ventas | Consultar y mantener clientes y borradores, marcar cotizaciones enviadas, mandar el resumen y enlace al correo registrado, y consultar órdenes resultantes |
| Gerencia | Consultar cotizaciones/órdenes, aprobar manualmente o cancelar cotizaciones enviadas y programar/asignar órdenes |
| Operaciones | Consultar clientes y órdenes; programar/asignar órdenes, registrar horas y moverlas según el flujo permitido |
| Contabilidad | Consulta de clientes, cotizaciones, órdenes de venta y trabajo; no contabiliza ni emite CFDI en esta versión |
| Almacén | Consulta de órdenes y registro de entradas, entregas, devoluciones y ajustes de existencias |

Los grupos se crean al iniciar el servicio. Las cuentas se asignan desde la administración. La matriz todavía requiere validación con el equipo y habrá que añadir permisos de datos (por ejemplo, acceso de técnicos solo a sus órdenes asignadas) antes de uso amplio. La conformidad de servicio es captura manual por personal de Redmagna y no autentica por sí misma la identidad del cliente.

## Decisiones que requieren revisión del negocio

1. Si la cotización aprobada crea siempre una orden de trabajo o si algunos productos deben convertirse solo en entrega.
2. Cómo se asignan folios si se anulan cotizaciones y si se reinicia por ejercicio fiscal.
3. Qué campos fiscales se deben pedir del receptor antes del CFDI y cuáles valida FEL.
4. Qué máximo comercial fijará Gerencia antes de habilitar la política de descuentos; también confirmar cómo representar tasa cero, exento y retenciones.
5. Qué permisos necesita cada rol (ventas, operaciones, contabilidad y administrador) y qué acciones requieren aprobación.
6. Qué datos y evidencias debe contener el cierre de una instalación o visita de soporte.

## Fuera de alcance de esta iteración

CFDI/timbrado, pólizas, catálogo contable, pagos, conciliación bancaria, impuestos de declaración, notas de crédito y cancelación fiscal. No se deben inferir esos comportamientos a partir del cálculo de IVA de una cotización. Contabilidad y el proveedor FEL deben confirmar sus reglas antes de implementar esos registros.
