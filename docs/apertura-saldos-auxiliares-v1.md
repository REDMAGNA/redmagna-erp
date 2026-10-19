# Apertura de cuentas por cobrar y pagar

**Estado:** están disponibles la conciliación, la vista previa, la preparación persistente del lote y una revisión de dos personas. Publicar crea registros auxiliares operativos de CxC/CxP sin generar una póliza individual ni reconocer impuestos o ingresos; la póliza general de balanza sigue siendo un flujo separado.

## Propósito

Permitir iniciar Redmagna ERP en una fecha de corte conservando el mayor contable y los auxiliares de CxC/CxP sin volver a reconocer ventas, compras, IVA o movimientos de banco ya registrados en el sistema anterior.

La apertura se compone de dos entregas relacionadas, pero distintas:

1. **Balanza inicial:** una póliza de mayor cuadrada a la fecha acordada, incluidos los saldos de las cuentas de control de clientes y proveedores. Usa el flujo actual `import-opening-balances`; requiere revisión y contabilización de Contabilidad.
2. **Partidas abiertas:** facturas individualizadas que explican exactamente los saldos de esas cuentas de control. La carga auxiliar no genera otra póliza, ingreso, gasto, impuesto, cobro ni pago.

La suma de saldos abiertos de clientes debe igualar el saldo deudor importado en la cuenta de control CxC; la suma de proveedores debe igualar el saldo acreedor de la cuenta CxP, conforme a la naturaleza del catálogo de Redmagna. Si no coinciden al centavo, se rechaza la publicación completa y se informa la diferencia por cuenta.

## Datos que necesita conservar cada documento

La unidad de carga es una factura, no un saldo agregado por RFC. La previsualización deberá cotejar cliente/proveedor por RFC, número externo, fechas y moneda MXN, evitando duplicar partidas ya cargadas o documentos internos.

| Dato | Cuentas por cobrar | Cuentas por pagar |
|---|---|---|
| Parte relacionada | Cliente activo, RFC y contacto si existe | Proveedor activo, RFC y contacto si existe |
| Identidad documental | Serie/folio externo y referencia de sistema origen | Serie/folio externo y referencia de sistema origen |
| Fechas y moneda | Emisión, vencimiento y fecha de corte; MXN | Emisión, vencimiento y fecha de corte; MXN |
| Importes | Total original, pagado antes del corte y saldo abierto; la resta debe cuadrar | Total original, pagado antes del corte y saldo abierto; la resta debe cuadrar |
| Evidencia fiscal | UUID CFDI 4.0, tipo de comprobante y XML si está disponible | UUID, XML CFDI 4.0 disponible y folio del proveedor |
| Impuestos | Renglones originales, tasa/objeto y base/importe por impuesto | Base e impuestos trasladados/retenciones según XML y cuenta por pagar |
| Historial previo | Parcialidades anteriores, importes y desglose de impuestos pagados | Pagos previos, notas de crédito, saldo y sus referencias externas |

Los importes `total original`, `pagado antes del corte` y `saldo abierto` son snapshots independientes y deben cumplir `original − pagado = saldo`. No se deben reconstruir pagos históricos como nuevos cobros/pagos bancarios, porque eso duplicaría fondos y pólizas.

## Complementos de pago para CFDI anteriores

Una factura con saldo abierto no es suficiente para emitir un complemento Pagos 2.0 correcto. Para el siguiente pago se necesita el UUID del CFDI origen, el saldo inmediatamente anterior, el número de parcialidad que continúa, la moneda y el cálculo del impuesto pagado por cada grupo de la factura. Si hubo pagos previos, también se necesita suficiente detalle de sus asignaciones fiscales para no volver a distribuir el IVA ya pagado.

Por eso, cada factura cargada debe clasificarse antes de publicar:

- **CFDI vinculado y habilitado para complemento:** UUID y datos fiscales revisados; líneas y pagos previos suficientes para reproducir saldos, parcialidad e impuestos.
- **Solo saldo operativo:** se puede consultar y cobrar en el auxiliar con autorización contable, pero el sistema no puede emitir Pagos 2.0 para ese documento hasta completar su historia fiscal.
- **Pendiente de revisión:** RFC, UUID, XML, impuestos o importes no conciliados; se conserva en la previsualización con errores y no entra al saldo operativo.

No se debe generar un UUID sustituto, un CFDI artificial ni tratar el saldo abierto como si fuera el total de la factura original. Los CFDI históricos no se vuelven a timbrar por importarlos.

## Flujo propuesto

1. Contabilidad registra la balanza general de apertura con el flujo de póliza actual y define fecha de corte y cuentas de control CxC/CxP.
2. Una persona con permiso prepara el CSV; el servidor valida RFC activos, moneda MXN, fechas, aritmética por documento, folios repetidos y total por cuenta de control. Preparar conserva la huella y los renglones en un lote pendiente, pero todavía no modifica auxiliares.
3. Una persona revisora distinta comprueba corte, cuentas y partidas. Puede rechazar con explicación o publicar el lote. La publicación es transaccional y crea facturas operativas abiertas sin pólizas individuales; el lote se hace inmutable.
4. El reporte posterior compara balanza y auxiliares por cuenta. Una corrección requiere rechazar antes de publicar o seguir un proceso de reversa autorizado; nunca se borra el historial.

Un lote debe ser idempotente: reintentar la misma carga no crea facturas adicionales. Si cambian los datos fuente, Administración debe generar una nueva versión de vista previa y explicar el cambio; no debe sobrescribir una apertura contabilizada.

## Decisiones necesarias antes de habilitarlo

- Fecha oficial de corte y si todas las partidas abiertas entran en MXN.
- Cuentas de control exactas aprobadas por el contador.
- Campos y formato exportable del sistema de origen para clientes, proveedores, facturas, notas de crédito, pagos y UUID CFDI.
- Qué porcentaje de facturas históricas tiene XML original y datos completos de parcialidades/impuestos.
- Tratamiento operativo de saldos sin UUID, documentos cancelados, disputas, anticipos y saldos a favor. Estos casos no se deben convertir silenciosamente en facturas abiertas normales.
- Quién prepara, quién revisa y quién contabiliza la apertura; la persona que carga no debe aprobarla por defecto.

## Vista previa disponible

En **Contabilidad → Conciliación de CxC y CxP → Vista previa de saldos abiertos**, la pantalla descarga una plantilla y envía el archivo a `POST /api/accounting/reports/open-items-preview/` como `multipart/form-data`: campos `file`, `as_of`, `receivables_account_code` y `payables_account_code`. Acepta hasta 2 MB y 5,000 renglones CSV UTF-8 con tipo, RFC, folio externo, sistema origen, emisión, vencimiento, moneda, total original, pagos previos y saldo abierto. Cada registro debe corresponder a un cliente/proveedor activo, estar en MXN, tener fechas e importes válidos y cumplir `total original − pagado previo = saldo abierto`. El preview detecta folios repetidos dentro del archivo y duplicados que ya existan en facturas internas o facturas de proveedor, y compara los saldos cargados con el mayor contabilizado al corte. Exige una cuenta de activo de naturaleza deudora para CxC y una de pasivo acreedora para CxP.

El resultado puede quedar listo para revisión cuando todos los renglones sean válidos y ambos totales coincidan con el mayor. El botón **Preparar para revisión** vuelve a validar y conserva los renglones en un lote con huella SHA-256; repetir la misma carga, fecha y cuentas devuelve el lote vigente en vez de duplicarlo. Una persona distinta puede abrir cada lote, revisar RFC, folios, sistema origen, fechas e importes de las partidas, descargar el CSV completo y publicarlo o rechazarlo con nota. La pantalla muestra las primeras 100 partidas y el archivo contiene el lote completo. Al publicarse se crean registros abiertos visibles en CxC/CxP, con la referencia del sistema anterior y el folio externo. Se conserva el lote y se bloquea la reutilización de esos folios mientras estén publicados.

La publicación no crea póliza, factura fiscal ni pago histórico. Los registros históricos actuales no incluyen UUID, desglose fiscal ni detalle de parcialidades previas; por eso quedan clasificados como saldos operativos y el servidor bloquea Pagos 2.0 para ellos. El revisor puede dar de alta el lote sin una nota de publicación; el rechazo sí requiere explicación.

## Límite actual

La vista previa no importa UUID, XML, desglose de impuestos, notas de crédito, pagos históricos ni parcialidades. Tampoco liga automáticamente el lote con la póliza general de balanza; Contabilidad debe verificar la conciliación por separado. Antes de habilitar Pagos 2.0 para documentos históricos se debe importar y revisar la evidencia fiscal y el historial de pagos. Consulta la [plantilla actual de saldos del mayor](plantilla-saldos-iniciales.csv) y el [diseño contable y FEL](diseno-contabilidad-cfdi-fel-v1.md).
