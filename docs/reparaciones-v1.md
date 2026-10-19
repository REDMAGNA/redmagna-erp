# Expedientes iniciales de reparación

**Estado:** flujo operativo integrado con Soporte. Registra diagnóstico, propuesta de trabajo, revisión manual de garantía, autorización y avance de un servicio correctivo sobre un equipo serializado instalado de un cliente; la custodia física opcional de equipos recibidos en taller se registra aparte.

## Flujo

```text
Ticket con equipo instalado → Expediente → Diagnóstico → Espera autorización
                                      → Autorizado → En reparación → Listo → Cerrado
                                      ↘ No reparable → Cerrado

Custodia física opcional: No recibido → Recibido en Redmagna → Devuelto al cliente
```

Un ticket admite como máximo un expediente. El equipo y cliente se copian de su vínculo al ticket y quedan protegidos contra cambios; el reporte inicial conserva una copia de la descripción del ticket. El expediente se conserva aunque el ticket cambie de estado. Solo se puede abrir desde un ticket no cancelado que referencie un número de serie instalado que pertenezca a ese cliente.

## Reglas de control

- El diagnóstico y trabajo propuesto se guardan antes de pedir autorización.
- La transición a **Autorizado** exige evidencia de autorización de al menos 10 caracteres y conserva el usuario y fecha que la registran. El ERP no autentica al contacto ni sustituye una firma. Cerrar, marcar no reparable o cancelar requiere una nota de al menos 10 caracteres.
- El fin de garantía registrado en el activo se muestra como referencia. El usuario registra una revisión manual: pendiente, cubierta, sin cobertura confirmada o no determinada; el sistema no decide cobertura por fecha.
- Cada edición relevante y transición conserva actor, fecha, etapa anterior/nueva y campos modificados en una bitácora no editable.
- La custodia es un eje separado del estado del diagnóstico: recepción y devolución requieren una descripción de condición/accesorios de al menos 10 caracteres, y quedan con responsable, fecha y transición explícita de custodia en un evento inmutable. Un expediente cerrado no puede conservar el equipo en custodia; se exige marcarlo listo, no reparable o cancelado antes de registrar devolución. Los expedientes de atención en sitio pueden permanecer como “No recibido físicamente”.
- Gerencia y Operaciones pueden consultar, crear y mantener expedientes según sus permisos de soporte. El cliente solo ve lo que se comparte desde el portal del ticket; el expediente no se expone en el portal. El perfil Técnicos no recibe permiso global para ver expedientes de todos los clientes; primero hay que definir un alcance por orden asignada.
- La recepción física es un control de custodia, no recepción de almacén: no modifica el estado del activo instalado, saldos ni movimientos de inventario. El flujo aún no reserva ni consume repuestos, crea cotizaciones/facturas/CFDI/pólizas ni cobra. La custodia no es un acuse firmado por el cliente ni acredita quién entregó el equipo. Diagnóstico y presupuesto adicional siguen requiriendo revisión y autorización por los procesos comerciales vigentes.

## API

- `GET/POST /api/repairs/cases/`: consultar expedientes o crear uno con `{"ticket": "<uuid>"}`. La creación requiere `repairs.add_repaircase`.
- `GET /api/repairs/cases/?ticket=<uuid>`: filtrar por ticket.
- `PATCH /api/repairs/cases/{id}/`: guardar `diagnosis`, `proposed_work` y `warranty_review`; requiere `repairs.change_repaircase`.
- `POST /api/repairs/cases/{id}/transition/`: avanzar `status`; requiere `repairs.transition_repaircase`. Al autorizar, enviar además `authorization_record`; para cerrar, marcar no reparable o cancelar, incluir `note`.
- `POST /api/repairs/cases/{id}/custody/`: registrar `{"action":"receive|return","condition":"..."}`; requiere `repairs.transition_repaircase`. La recepción exige un expediente activo; la devolución exige custodia previa y estado listo, no reparable o cancelado. La acción guarda responsable, fecha, observación y evento inmutable.

La base mantiene las tablas aisladas en la aplicación `repairs`; el expediente enlaza ticket, cliente y activo serializado para conservar el historial. La etapa y la custodia son controles operativos, no movimientos de inventario ni contabilización. Los equipos existentes se inicializan como “No recibido físicamente”; no se infiere custodia para expedientes históricos.

## Siguiente alcance

Antes de manejar equipos devueltos a taller en operación, validar con Redmagna el formato de inspección física, identidad/acuse de quien entrega y recibe, fotos/adjuntos, condiciones de rechazo y autorización de salida. La primera custodia solo documenta la condición en texto y no prueba firmas. Antes de reservar piezas, enlazar el consumo al inventario con cantidad real, serie y autorización; antes de cobrar, crear una cotización revisada por el cliente y continuar por la factura/CFDI y contabilidad existentes. También quedan por validar SLA de diagnóstico y presupuestos con Redmagna.
