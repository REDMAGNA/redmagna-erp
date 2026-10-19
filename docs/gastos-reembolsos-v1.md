# Gastos y reembolsos — análisis funcional inicial para Redmagna

**Estado:** primera versión de servidor/API e interfaz implementada, incluido registro del pago efectivo y póliza borrador de salida; la validación en entorno Django/PostgreSQL sigue pendiente.  
**Base:** documentación oficial de Odoo 19. Las reglas de Redmagna, cuentas contables y tratamiento fiscal siguen pendientes de aprobación.

## Qué cubre Odoo

Odoo permite capturar gastos manualmente o crear registros desde recibos cargados, arrastrados o enviados por correo. Cada gasto incluye descripción, categoría, importe, fecha, empleado y quién lo pagó (el empleado o la empresa); puede adjuntar el comprobante y asociarse a una orden de venta para refacturación. Las categorías determinan precio fijo o costo real, cuenta contable y si se puede refacturar.

El empleado envía uno o más gastos dentro de un reporte. Una persona con permiso de gerente aprueba o rechaza el reporte; después, Contabilidad puede publicar los gastos aprobados en un diario. El reembolso se tramita aparte: Odoo documenta reembolso por caja, cheque, depósito directo o nómina. Si el gasto se asocia a una orden de venta, el asiento publicado lo deja disponible para facturar al cliente. También hay análisis por empleado y categoría, tarjetas de gastos conectadas y digitalización de recibos mediante servicios adicionales.

El flujo separa tres hechos: el gasto incurrido, su aprobación y registro contable, y el reembolso efectivo. Una fotografía del recibo no prueba que la empresa haya pagado ni que un impuesto sea acreditable.

## Flujo propuesto para la primera versión de Redmagna

1. **Catálogo:** Contabilidad crea categorías con descripción, cuenta de gasto, política de comprobante y estado. Las cuentas vienen del catálogo validado por el contador.
2. **Captura:** la persona autenticada crea un borrador en MXN con descripción, fecha, categoría, total pagado, quién pagó (persona o empresa), referencia de proveedor opcional y nota. El usuario autenticado es el responsable inicial; no se crea nómina ni expediente laboral en esta etapa.
3. **Comprobante:** se adjunta imagen o PDF privado con validación de tipo y tamaño, y descarga con permiso. No se digitaliza ni extrae información automáticamente.
4. **Reporte:** la persona agrupa sus gastos borrador, envía el reporte y congela los renglones mientras esperan aprobación. Se conservan autor y fecha.
5. **Aprobación:** Gerencia revisa importes, fechas, categoría y comprobantes. Puede aprobar o rechazar con motivo; el rechazo conserva el historial y permite corregir el reporte. Quien captura no aprueba su propio reporte.
6. **Registro contable:** Contabilidad puede generar una póliza borrador balanceada para reportes aprobados, usando cuentas configuradas. Se distingue el gasto pagado por la persona (pasivo pendiente) del pagado directamente por la empresa (cuenta de fondos). No se contabiliza automáticamente.
7. **Reembolso:** después de que Contabilidad contabilice la póliza de gasto, Contabilidad registra la transferencia, cheque o entrega de efectivo ya ocurrida, con fecha, referencia y confirmación. El servidor limita el importe al saldo de gastos pagados por la persona y admite parcialidades. Cada registro crea una póliza de salida en borrador contra el pasivo del empleado y la cuenta bancaria/caja configurada; Contabilidad la revisa, contabiliza y concilia con el estado de cuenta. Un reintento con la misma clave no duplica el pago. La reversa requiere confirmar que el pago se devolvió/canceló y genera una póliza inversa contabilizada; antes de revertir el gasto original deben revertirse sus pagos activos.
8. **Cierre e informes:** gastos, pagos y pólizas conservan autor y fecha; las correcciones financieras usan reversas. Los informes muestran importe reembolsable, pagado y saldo pendiente.

## Entidades candidatas

| Entidad | Datos y responsabilidad |
|---|---|
| ExpenseCategory | Nombre, referencia opcional, cuenta de gasto, comprobante requerido y estado. Solo Contabilidad la administra. |
| Expense | Responsable, categoría, fecha, descripción, importe bruto, MXN, quién pagó, proveedor/referencia opcionales, nota y estado. |
| ExpenseReceipt | Archivo privado, nombre, tipo, tamaño, huella SHA-256, autor y fecha. Inmutable tras enviar el reporte. |
| ExpenseReport | Responsable, periodo opcional, estado, total calculado, envío, aprobación/rechazo con autor, fecha y motivo. |
| ExpenseEvent | Bitácora inmutable de cambios de estado y acciones de gasto, reporte y reembolso. |
| ExpenseReimbursement | Persona beneficiaria vía reporte, importe parcial, método, fecha, referencia, clave idempotente, póliza de salida y actor; la reversa registra motivo, responsable, fecha y póliza inversa. |

La refacturación a clientes, empleados formales, nómina, tarjetas corporativas, OCR y moneda extranjera quedan como extensiones. Ligar un gasto a un cliente no crea un cargo comercial sin revisión de Ventas.

## Estados y permisos iniciales

Gasto: borrador → enviado en reporte → aprobado → contabilizado; también puede rechazarse y corregirse en borrador.  
Reporte: borrador → enviado → aprobado o rechazado → contabilizado.  
Reembolso: pago realizado registrado → revertido con motivo, confirmación y póliza inversa.

| Rol | Acceso propuesto |
|---|---|
| Solicitante | Crear y ver sus borradores; corregir rechazados; enviar reportes y consultar el resultado. |
| Gerencia | Revisar reportes pendientes; aprobar o rechazar con motivo; no editar importes. |
| Contabilidad | Administrar categorías, preparar y contabilizar pólizas, registrar reembolsos, reversar con motivo e informar/exportar. |

La matriz final debe respetar separación de funciones en Redmagna. Contabilidad registra y revierte reembolsos; las consultas de API filtran por responsable y ocultar botones no sustituye permisos de servidor.

## Límites fiscales y decisiones pendientes

- Guardar el total declarado y adjuntar el CFDI o recibo, sin calcular IVA acreditable ni deducibilidad.
- El XML CFDI podría ligarse después al gasto y cotejarse; el proceso de CFDI de proveedor actual no basta para aprobar un gasto de empleado.
- Acordar con el contador categorías, comprobantes, cuentas, anticipos, gastos pagados con caja/corporativo y diferencias entre recibo y reembolso.
- Acordar quién aprueba cuando no exista una persona distinta del solicitante.
- No incluir nómina, retenciones, deducciones laborales, IVA ni viáticos con tarifa fija sin política local aprobada.
- La primera versión se limita a MXN; el pago registrado representa un desembolso confirmado por el usuario, y su póliza de salida debe revisarse/contabilizarse y conciliarse con el banco en el flujo bancario ya existente. No inicia transferencias ni mueve dinero. Los comprobantes se validan por extensión, firma de archivo y tamaño; aún no se calcula hash SHA-256. La póliza usa el total declarado y no separa IVA.

## Diferencias frente a Odoo y prioridad

| Función Odoo | Decisión inicial Redmagna |
|---|---|
| Captura manual, carga/arrastre/correo y OCR | Captura manual y archivo privado; correo y OCR se posponen. |
| Aprobación y publicación | Reporte agrupado, aprobación de Gerencia y póliza borrador revisada por Contabilidad. |
| Reembolso por caja, cheque, depósito o nómina | Transferencia/caja registrada por separado; nómina fuera del primer alcance. |
| Refacturación a ventas | Posterior a definir reglas comerciales y fiscales. |
| Tarjetas conectadas | Fuera del alcance hasta elegir proveedor y revisar costos y datos. |
| Análisis por empleado/categoría | Filtros internos por fecha, responsable, categoría y estado. |

## Estado técnico de esta entrega

- API bajo `/api/expenses/`: categorías, gastos, comprobantes privados, reportes, configuración y reembolsos con reversa auditada.
- Ciclo disponible: crear gasto → adjuntar archivo → agrupar/enviar reporte → aprobar/rechazar → preparar y contabilizar póliza de gasto → registrar pago ya realizado → contabilizar y conciliar póliza de salida; la reversa crea una póliza inversa contabilizada.
- Comprobantes JPG, PNG, WEBP y PDF de hasta 10 MB; las consultas se limitan al propietario salvo permisos de consulta global.
- La bitácora conserva el envío, aprobación, rechazo y creación de póliza. La migración está en `server/expenses/migrations/0001_initial.py`.
- La interfaz permite capturar gastos, adjuntar/descargar comprobantes, crear y enviar reportes, revisar y rechazar/aprobar, corregir reportes rechazados y preparar pólizas borrador. Contabilidad administra categorías y la configuración de cuentas.
- La API incluye `POST /api/expenses/reports/{id}/reimburse/` y `POST /api/expenses/reports/{id}/reimbursements/{reimbursement_id}/reverse/`. La transferencia o entrega real debe ocurrir fuera del ERP; luego Contabilidad revisa la póliza borrador y empata la salida en conciliación bancaria. Pendiente: validar la migración en un entorno Django/PostgreSQL, hash de comprobantes y OCR.

El bloque está integrado en la navegación de Gastos. La configuración contable selecciona diarios separados para el registro de gasto y para reembolsos.

## Referencias oficiales

- [Aplicación Gastos Odoo 19](https://www.odoo.com/documentation/19.0/applications/finance/expenses.html)
- [Registrar gastos y adjuntar recibos](https://www.odoo.com/documentation/19.0/applications/finance/expenses/log_expenses.html)
- [Categorías de gasto y cuentas](https://www.odoo.com/documentation/19.0/applications/finance/expenses/expense_categories.html)
- [Enviar y aprobar reportes](https://www.odoo.com/documentation/19.0/es_419/applications/finance/expenses/submit_expenses.html), [aprobar y rechazar](https://www.odoo.com/documentation/19.0/es_419/applications/finance/expenses/approve_expenses.html)
- [Publicar pólizas de gasto](https://www.odoo.com/documentation/19.0/es/applications/finance/expenses/post_expenses.html)
- [Reembolsos](https://www.odoo.com/documentation/19.0/applications/finance/expenses/reimburse.html)
- [Refacturar gastos a clientes](https://www.odoo.com/documentation/19.0/applications/finance/expenses/reinvoice_expenses.html)
