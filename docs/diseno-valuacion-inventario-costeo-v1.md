# Diseño propuesto: valuación de inventario y costo real por orden

**Estado:** propuesta funcional; no implementada. El costo de inventario, el margen real por orden y las pólizas de valuación quedan pendientes de política aprobada por Contabilidad.

## Alcance actual comprobado

Redmagna ya registra productos, ubicaciones, saldos, movimientos físicos inmutables, reservas y números de serie. Compras captura costo unitario por renglón de orden y conserva facturas de proveedor ligadas a cantidades recibidas. La hoja comercial de cálculo mantiene costos estimados fuera de la cotización; el catálogo de inventario no contiene un costo contable. Por eso hoy no se puede calcular el valor monetario de existencias ni el costo real de equipos/materiales consumidos por orden. Consulta [inventario básico](inventario-redmagna-v1.md) y [contabilidad y FEL](diseno-contabilidad-cfdi-fel-v1.md).

## Referencia funcional de Odoo 19

Odoo distingue el **método de costeo** de la **valuación contable**. Para costeo documenta Precio estándar, costo promedio ponderado (AVCO) y FIFO/PEPS, que pueden configurarse globalmente o por categoría; estrategias de surtido como FEFO o LIFO no cambian por sí solas el método de valuación. El inventario calcula valores con movimientos físicos y capas remanentes; la contabilidad mantiene su propio importe y reporta diferencias.

También separa valuación periódica al cierre de valuación perpetua. En Odoo 19 la opción perpetua afecta la cuenta de inventario a nivel de factura, y el asiento de cierre sincroniza diferencias entre inventario físico y contabilidad; este comportamiento cambió con respecto a versiones anteriores. La guía señala que el reconocimiento de costo puede depender del estándar contable y del momento de factura/entrega. Son referencias funcionales de Odoo, no reglas que se deban copiar o aplicar automáticamente a Redmagna. ([métodos y comparación](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/inventory_valuation/inventory_valuation_config.html), [efecto de movimientos](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/inventory_valuation/operations_valuation.html), [valuación contable y configuración Odoo 19](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/inventory_valuation.html))

## Diseño de datos para Redmagna

Mantener el libro físico actual como fuente de cantidades y añadir un submayor de costo independiente, append-only:

| Registro propuesto | Datos y vínculo | Regla |
|---|---|---|
| `InventoryCostPolicy` | Versión, categoría/producto, costeo, moneda, vigencia y aprobaciones | Solo cambia por versión; no reescribe movimientos ya costeados. Sin valor inicial hasta autorización de Contabilidad. |
| `InventoryValuationLayer` | Movimiento, recepción, renglón de orden/factura, producto, ubicación, serie opcional, cantidad, valor MXN, costo unitario y fecha contable | Las capas de entrada conservan origen e importes exactos; la suma de cantidades/valores remanentes explica el inventario a la fecha. |
| `InventoryCostAllocation` | Capa(s) de salida, movimiento de entrega/consumo, orden de trabajo y cantidad consumida | Inmutable; no asigna unidades dos veces ni rebasa la cantidad entregada. Para FIFO consume las capas más antiguas; para serie ligada a compra, conserva el costo específico de esa unidad si Contabilidad lo aprueba. |
| `InventoryCostAdjustment` | Motivo, movimiento relacionado, diferencia, actor y aprobación | Corrige con ajuste vinculado y póliza inversa/ajuste cuando aplique; nunca edita o borra la capa original. |
| `LandedCostAllocation` (fase posterior) | Cargo de transporte/importación/seguro y regla de reparto entre recepciones | No forma parte de la primera versión; requiere CFDI/cuenta, base de prorrateo y validación fiscal/contable. |

Los valores de costo se guardan sin el IVA acreditable declarado en la factura del proveedor, hasta que Contabilidad defina el tratamiento de impuestos, descuentos, bonificaciones, fletes, moneda extranjera y diferencias entre orden, recepción y CFDI. El XML revisado estructuralmente no demuestra por sí solo que cada importe sea costo capitalizable.

## Eventos y efectos

1. **Recepción parcial:** crear capa solo por la cantidad recibida. La cantidad y el costo acordado de la orden son el costo provisional; el lote identifica que puede requerir conciliación posterior con factura.
2. **Factura de proveedor:** conciliar sus renglones con recepción y orden. Registrar la diferencia entre costo facturado y costo provisional sin alterar de forma silenciosa ventas, cotizaciones ni historial. La asignación a existencias restantes, consumos ya instalados o cuenta de diferencia requiere una política aprobada.
3. **Entrega a orden de trabajo:** crear asignaciones desde la capa de salida y sumar su costo real al consumo de la orden. Para equipos serializados, ligar el costo a la misma unidad que se instala; para material por cantidad, usar la regla de costeo autorizada.
4. **Devolución al almacén:** revertir la asignación original cuando sea posible, manteniendo vínculo y valor; si ya no existe la capa o difiere el estado del equipo, registrar excepción para revisión.
5. **Devolución a proveedor, merma y ajuste:** cantidades, costo y contrapartida se proponen en borrador con motivo, autorización y vínculo al movimiento físico. No registrar póliza contabilizada automáticamente.
6. **Reportes:** inventario físico y monetario por ubicación/serie a una fecha; capas abiertas y diferencias con facturas; costo estimado de la hoja comercial frente al costo real aplicado por orden. Etiquetar los reportes como operativos hasta conciliar con el mayor.

Las cuentas se añadirían a reglas configurables de póliza solo después de recibir el catálogo de Redmagna y la política del contador. No debe duplicarse el costo al contabilizar simultáneamente una factura de proveedor y una entrega física, ni crear un segundo ingreso/costo desde el CFDI.

## Decisiones que faltan

Contabilidad y Redmagna deben determinar antes de implementar:

1. Si equipo serializado y consumibles tendrán el mismo método; elegir costo específico, PEPS, promedio o estándar por tipo/categoría.
2. Si la contabilidad reconocerá costo de inventario periódicamente o con valuación perpetua, y qué eventos generan pólizas borrador.
3. Cómo tratar diferencias entre orden, recepción y CFDI, fletes, devoluciones, garantías, bonificaciones, mermas y material instalado parcialmente.
4. Si inventario de demostración, consignación, garantías o propiedad de cliente pertenece al inventario valuado de Redmagna.
5. Qué método de carga inicial conservará cantidades, costos y capas por serie, y cómo cuadrar el saldo contra la cuenta de control.

No crear capas monetarias ni pólizas contables para inventario existente hasta aprobar estos puntos y un corte de apertura verificable.

## Secuencia de implementación propuesta

1. Aprobar política, catálogo de cuentas y ejemplos reales de Redmagna con el contador.
2. Añadir submayor inmutable y costo por serie, con migración de esquema sin inventar saldos.
3. Costear recepciones y aplicar costos a órdenes de trabajo con trazabilidad completa y reportes de diferencias.
4. Incorporar costo promedio/PEPS para artículos por cantidad si la operación lo requiere.
5. Activar pólizas en borrador y conciliación del inventario solo después de validar ejemplos de recepción, entrega, devolución, factura tardía, merma y cierre.

## Referencias

- [Guía de valuación de inventario de Odoo 19](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/inventory_valuation.html)
- [Métodos de costo y periodicidad de valuación](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/inventory_valuation/inventory_valuation_config.html)
- [Valuación contable de inventario](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/inventory_valuation.html)
