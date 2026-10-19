# Compras, proveedores y recepción de mercancía

**Alcance implementado:** ciclo inicial de compra de productos de inventario, desde proveedor y borrador hasta recepción parcial o completa. Las solicitudes permiten comparar cantidades y precios por renglón, adjudicar una necesidad completa o repartirla entre proveedores y conservar el saldo pendiente. Es código propio del ERP; no copia implementación de Odoo.

## Solicitud y comparación de ofertas

Compras puede crear una solicitud interna para varios productos activos de inventario, indicar ubicación y fecha deseadas, y enviar RFQ por correo a un proveedor activo con dirección registrada. El correo enumera los saldos pendientes y aclara que no constituye una orden ni autoriza la entrega. Cada intento, destinatario y resultado se conserva en el historial; si SMTP devuelve un resultado incierto, la pantalla recomienda revisar el correo antes de reenviar. Las respuestas siguen capturándose manualmente. Una oferta puede incluir uno o más renglones y una cantidad cotizada por renglón, que no excede la necesidad original. El ERP muestra cantidades, precio unitario, subtotal y total cotizado en MXN, además de impuestos/flete declarados, vigencia y entrega. Compras puede seleccionar cantidades de varias ofertas para una misma necesidad; el servidor impide exceder la cantidad solicitada ni la cantidad que cada proveedor cotizó. Si la oferta elegida tiene un precio unitario mayor que otra oferta vigente con cantidad disponible para ese producto, Compras debe explicar la decisión con al menos 10 caracteres. La justificación queda ligada al renglón de la orden y no se puede cambiar después de adjudicar. Cada adjudicación crea órdenes borrador agrupadas por proveedor y enlaza cada renglón a la solicitud y oferta de origen. El restante permanece abierto para futuras cotizaciones y adjudicaciones. Las ofertas, decisiones, actor, fecha y eventos se conservan; los precios recibidos no se editan. Compras debe revisar y confirmar cada orden por separado.

## Flujo

1. Compras registra el proveedor y puede capturar un plazo habitual de entrega de 0 a 365 días. También registra condiciones vigentes por producto: código del proveedor, costo unitario en MXN, mínimo opcional, plazo específico y fecha de revisión. La pareja proveedor-producto de una ficha es inmutable; para cambiarla se archiva esa ficha y se crea otra. La interfaz permite archivar y reactivar con motivo. Solo hay una condición actual por pareja; el alta y cada cambio generan una revisión inmutable con los valores completos, usuario, fecha y motivo. Al editar se requiere un motivo de 10 caracteres como mínimo; las órdenes anteriores conservan sus propios costos.
2. Al crear una orden, la pantalla propone el costo vigente de la pareja proveedor-producto. Se puede ajustar en el borrador. La fecha esperada usa el mayor plazo aplicable de sus productos; si un producto no tiene plazo propio, utiliza el general del proveedor. La fecha puede editarse manualmente.
3. Compras crea una orden con productos activos de inventario, cantidades, costo unitario estimado y ubicación prevista por renglón. El mínimo de compra se muestra como condición de referencia y no bloquea cantidades menores.
4. La orden se guarda como borrador `draft`. Se puede editar mientras siga en ese estado.
5. Un usuario con permiso de confirmación cambia el estado a `ordered` y se registra el actor y la fecha. Cambios posteriores al catálogo no reescriben órdenes existentes.
6. Almacén registra una o varias recepciones con la cantidad que llegó; la mercancía se recibe en la ubicación prevista del renglón. Cada renglón crea un movimiento de entrada inmutable, ligado a la orden por el folio y relacionado directamente con el renglón de recepción. Para órdenes antiguas que no tenían destino, la primera recepción fija la ubicación para el resto pendiente.
7. El sistema calcula la cantidad pendiente por renglón y el estado de la orden: `partial` o `received`. No permite recibir por arriba de lo solicitado ni generar existencias negativas.
8. Una clave de idempotencia permite reintentar una misma recepción sin duplicar existencias; reutilizarla con otra orden o cantidades se rechaza.
9. Después de recibir unidades, Contabilidad puede registrar una factura de proveedor con folio, fecha, vencimiento opcional, cantidad, precio unitario e impuesto declarado por concepto. El vencimiento se captura según las condiciones reales del proveedor; no se presupone un plazo. El control coteja orden, recepción y factura, impide facturar unidades que todavía no se recibieron y evita repetir un mismo folio por proveedor. La diferencia entre el precio acordado y el capturado queda visible para revisión.
10. Los pagos aplicados se pueden revertir con permiso `purchasing.reverse_supplierpayment`, confirmación explícita y motivo de al menos 10 caracteres. La reversa conserva el pago y sus aplicaciones, cambia su estado a `reversed` para reabrir el saldo del proveedor y registra actor, fecha y motivo. Si existe una póliza automática contabilizada, también crea y contabiliza su reversa en el periodo abierto; si la póliza de origen aún está en borrador, Contabilidad debe resolverla primero. Si no se configuró póliza automática, la reversa del saldo de proveedor queda registrada sin fingir una salida o devolución bancaria.
11. El reporte de antigüedad reconstruye los saldos de facturas registradas y pagos aplicados hasta la fecha de corte, incluso si el saldo aparece pagado actualmente; excluye pagos revertidos y conserva pagos que estaban aplicados al corte aunque hoy estén revertidos. Usa la fecha de registro y de aplicación del pago en el ERP; no reconstruye cancelaciones históricas de facturas.
12. El estado de cuenta por proveedor lista facturas registradas y pagos que permanecían aplicados hasta el corte, consolida cada pago en una línea aunque cubra varias facturas y calcula el saldo acumulado. Una reversa aparece como movimiento separado que vuelve a cargar el saldo; es un auxiliar interno y no equivale a la conciliación del banco.
13. Contabilidad puede adjuntar el XML CFDI 4.0 a una factura; el sistema coteja RFC de emisor y receptor, UUID, folio, fecha, subtotal, impuestos trasladados y total antes de guardar el archivo en almacenamiento privado.

## Acuerdos marco

Compras registra en la pantalla de Compras, API o Django Admin un acuerdo borrador con proveedor, referencia única para ese proveedor, fechas de vigencia y productos. Cada producto puede aparecer una vez; guarda un precio fijo en MXN y un límite opcional acumulado. Al activar, quedan inmutables los términos y renglones. Solo un acuerdo activo dentro de su vigencia puede generar órdenes; cada pedido queda como borrador con referencia al acuerdo, copia del precio, producto y cantidad, y ubicación de recepción por línea. Las órdenes borrador reservan saldo para que la misma cantidad no se comprometa dos veces; cancelar una orden libera sus cantidades. El servidor bloquea el acuerdo durante la validación, valida el límite por transacción y rechaza órdenes concurrentes que lo excedan. Cerrar un acuerdo impide nuevas órdenes y no cambia las órdenes ya emitidas. No hay ajuste de precios, renovaciones automáticas, moneda extranjera ni conversión automática desde RFQ.

## API

- `GET/POST /api/purchasing/suppliers/`
- `GET/POST /api/purchasing/supplier-products/` (también acepta `?supplier=<id>`)
- `PATCH /api/purchasing/supplier-products/{id}/`
- `GET/POST /api/purchasing/orders/`
- `GET/POST /api/purchasing/framework-agreements/` (un renglón por producto; `line_inputs` incluye `product`, `unit_cost`, `quantity_limit?` y `description?`)
- `PATCH /api/purchasing/framework-agreements/{id}/` (solo borradores)
- `POST /api/purchasing/framework-agreements/{id}/activate/` y `/close/`
- `POST /api/purchasing/framework-agreements/{id}/create-order/` con `lines: [{framework_line, expected_location, quantity}]`, `expected_date?` y `notes?`; devuelve una orden en borrador ligada al acuerdo.
- `GET/POST /api/purchasing/sourcing/`
- `POST /api/purchasing/sourcing/{id}/send-rfq/` con `supplier` y `confirm_send: true` (usa SMTP; registra intento y resultado en el historial).
- `GET/POST /api/purchasing/sourcing/{id}/offers/`
- `POST /api/purchasing/sourcing/{id}/award/` con `offer` y `reason?` para compatibilidad con la adjudicación completa de una sola oferta; `reason` se exige si se elige una oferta más cara.
- `POST /api/purchasing/sourcing/{id}/award-lines/` con `allocations: [{offer, sourcing_line, quantity, reason?}]` para distribuir cantidades por producto; crea órdenes borrador por proveedor y deja el saldo no adjudicado disponible. `reason` es obligatorio (mínimo 10 caracteres) cuando existe una oferta vigente más barata y disponible para el producto.
- `POST /api/purchasing/orders/{id}/confirm/`
- `POST /api/purchasing/orders/{id}/cancel/`
- `POST /api/purchasing/orders/{id}/receive/`
- `GET /api/purchasing/receipts/`
- `GET /api/purchasing/supplier-bills/`
- `POST /api/purchasing/supplier-bills/{id}/attach-cfdi/` (multipart, campo `xml_file`)
- `GET /api/purchasing/supplier-bills/{id}/cfdi-xml/` (descarga autenticada)
- `GET /api/purchasing/supplier-bills/payables-aging/?as_of=AAAA-MM-DD`
- `GET /api/purchasing/supplier-bills/supplier-statement/?supplier_id=<id>&as_of=AAAA-MM-DD`
- `POST /api/purchasing/orders/{id}/register-bill/`
- `GET/POST /api/purchasing/supplier-payments/`
- `POST /api/purchasing/supplier-payments/{id}/post/`
- `POST /api/purchasing/supplier-payments/{id}/reverse/` con `reason` y `confirm_irreversible: true`.

Para crear una orden se envían `supplier`, `order_date`, `expected_date`, `notes` y una lista `line_inputs` con `product`, `quantity`, `unit_cost` y `description`. Para recibir, se envía una clave UUID `idempotency_key`, una nota y `lines`, cada una con `purchase_order_line`, `location` y `quantity`.

`SupplierSerializer` expone `lead_time_days` como valor opcional entero de 0 a 365. `SupplierProductSerializer` guarda una condición actual única por producto y proveedor y devuelve `history` con todas sus revisiones. Al crear se registra la revisión inicial; al cambiar cualquier término o archivar se exige `history_reason`. Compras administra estos datos con permisos separados; la ficha maestra de administración es de solo lectura y las revisiones no se editan ni borran. El frontend propone el costo y la fecha esperada en borradores; la cantidad mínima es informativa. La API de órdenes sigue aceptando `expected_date` y `unit_cost` explícitos.

Para registrar una factura se envía `invoice_number`, `invoice_date`, `due_date` opcional y `lines`, cada una con el concepto `purchase_order_line`, `quantity`, `unit_cost` y el `tax_amount` declarado. El folio se normaliza a mayúsculas y es único por proveedor. El registro y sus conceptos quedan inmutables para preservar la bitácora. Las facturas existentes y las que no tienen vencimiento explícito aparecen en el grupo **Sin vencimiento**.

Para capturar un pago se envía proveedor, importe MXN, método, fecha `paid_at` y `applications` con factura e importe asignado. El pago empieza en borrador; `POST /{id}/post/` requiere que la suma aplicada coincida con el total y no exceda los saldos de las facturas. Se permiten pagos parciales y una aplicación puede distribuirse entre varias facturas del mismo proveedor por API. El saldo abierto de cada factura se calcula restando solo aplicaciones de pagos aplicados. Si el pago se aplicó por error o se reembolsó, `POST /{id}/reverse/` pide motivo y confirmación; el pago original y sus aplicaciones permanecen en el historial y sus facturas reabren el saldo. Cuando existe una póliza automática contabilizada, el servicio contabiliza una póliza inversa en un periodo abierto y enlaza ambos movimientos; si la póliza automática sigue en borrador, no deja revertir hasta que Contabilidad la resuelva.

## Controles y permisos

- Grupo **Compras**: proveedores, condiciones de precio y plazo por producto, alta y edición de borradores, confirmar o cancelar órdenes y consultar recepciones. También puede crear/editar/activar/cerrar acuerdos marco y generar órdenes desde acuerdos activos.
- Grupo **Almacén**: consultar órdenes y registrar recepciones.
- **Contabilidad**: consulta de proveedores, órdenes y recepciones; registro y consulta de facturas de proveedor.
- **Contabilidad** también prepara pagos, edita borradores, los aplica y puede revertirlos con motivo; **Gerencia** puede consultar los pagos.
- **Contabilidad** adjunta XML a facturas; quienes tienen permiso de consulta de facturas pueden descargar el XML privado.
- **Gerencia**: consulta de proveedores, órdenes, recepciones, precios de referencia y facturas. El acceso a la ficha de costos usa permiso separado `purchasing.view_supplierproduct`; Almacén no lo recibe.
- **Compras**: crea solicitudes, registra ofertas y adjudica renglones o cantidades entre proveedores para crear órdenes borrador; **Gerencia** puede consultar solicitudes, ofertas, cantidades adjudicadas y órdenes resultantes.
- Proveedores se archivan; no se borran físicamente.
- Órdenes solicitadas no se editan. Las líneas recibidas quedan ligadas al historial de existencias.
- Una orden con mercancía recibida no se puede cancelar como si la operación no hubiera ocurrido.

## Pendiente

La revisión del XML valida su estructura local con el XSD CFDI 4.0 incluido, coteja datos seleccionados con la cuenta por pagar y verifica criptográficamente el sello del emisor contra el certificado incrustado, incluido el RFC, número y vigencia del certificado en la fecha del CFDI. Este control local no establece confianza de la cadena del certificado emitido por SAT, no valida criptográficamente el sello SAT del timbre ni consulta el estado del UUID en SAT/FEL. No determina IVA acreditable. Descuentos, retenciones y moneda distinta de MXN requieren soporte. Si hay reglas activas, se generan pólizas borrador según las cuentas configuradas por Contabilidad; requieren revisión y contabilización manual. Todavía no hay pagos no aplicados, devoluciones al proveedor, órdenes de servicio, recepción automática de respuestas de RFQ, reposición automática ni costeo contable del inventario. Los acuerdos marco están implementados con precios fijos en MXN, vigencia y límite opcional por producto; la pantalla administra su ciclo y genera pedidos borrador que reservan saldo. Los costos de compra se guardan como referencia comercial, no como costo promedio. El pago capturado no equivale a una salida bancaria conciliada. La migración 0018 agrega los acuerdos marco y debe aplicarse y validarse en PostgreSQL antes de usarse con compras reales.
