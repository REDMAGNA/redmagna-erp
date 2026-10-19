# Soporte técnico inicial

**Estado:** módulo de tickets vinculado con clientes, órdenes de trabajo y equipos serializados instalados. El equipo puede enviar al correo registrado del cliente un enlace HTTPS firmado y temporal para consultar el ticket y responder desde el portal. El personal puede marcar cada respuesta como compartida; los mensajes externos y las notas internas se guardan por separado. Las políticas SLA se configuran por prioridad desde Django Admin; cada ticket conserva objetivo, calendario semanal y zona horaria como snapshot.

## Flujo

```text
Solicitud → ticket nuevo → atención / espera del cliente
                          → resuelto → cerrado
                          ↘ cancelado
```

Un caso puede reabrirse desde Resuelto o Cerrado a En atención. Cancelado es terminal. Cada transición conserva actor, fecha y estado anterior/nuevo en una bitácora no editable. Las notas internas y los mensajes compartidos son inmutables y quedan ligados al ticket; una respuesta del cliente reanuda un ticket en espera, y una respuesta pública del personal lo deja en espera del cliente.

## Datos y reglas

- Folio `RM-SOP-AAAA-00001`, secuencial por año.
- Cliente activo requerido; la orden de trabajo es opcional y debe pertenecer al mismo cliente.
- Un ticket puede referenciar un equipo instalado del cliente; la ficha conserva número de serie, orden origen, fecha de instalación y fin de garantía si se capturó. El endpoint de activos solo muestra las unidades instaladas que pertenezcan al cliente consultado.
- Si el ticket está vinculado a un equipo con fecha de garantía, la interfaz indica si esa fecha registrada seguía vigente al abrirse el ticket o ya había vencido. Si no hay fecha, muestra que se desconoce; esto es una referencia temporal y no confirma cobertura contractual, causal del daño ni aceptación de la garantía.
- Asunto, descripción, prioridad (baja, normal, alta, urgente) y canal (teléfono, correo, web o interno).
- Responsable opcional; la lista de responsables incluye solo usuarios activos.
- Las notas no se pueden agregar a tickets cerrados o cancelados. Reabre el ticket para continuar el seguimiento.
- Los tickets y sus notas no se eliminan desde el API.
- El enlace del portal vence en 30 días, queda invalidado al emitir otro enlace para ese ticket y deja de funcionar si cambia el correo del cliente o se archiva su ficha. Su acceso es de portador: comparte la URL solo con el contacto autorizado del cliente.
- El portal muestra folio, asunto, descripción, estado, fecha de actualización y mensajes marcados como compartidos. No muestra notas internas, asignación, historial interno, números de serie, documentos ni información contable.
- Para responder se requiere el correo registrado del cliente. Solo se aceptan respuestas en tickets nuevos, en atención o en espera del cliente; no se reciben respuestas en casos resueltos, cerrados o cancelados. La identidad externa queda como cliente en la bitácora, sin atribuirla a un usuario interno.
- Una respuesta del personal es privada por omisión. Compartirla requiere `support.publish_supportticketmessage` y confirmación en la pantalla; una nota interna no aparece en el portal.
- Las políticas SLA son opcionales y se configuran en Django Admin, una por prioridad, con minutos objetivo de primera respuesta y resolución. No hay valores precargados: hasta que Redmagna defina sus objetivos, los tickets mostrarán “Sin objetivo configurado”. Un calendario vacío conserva minutos corridos. Para usar horas hábiles, se configura `weekly_schedule` como JSON de día local (`0` lunes a `6` domingo) y pares ordenados `[inicio, fin]` en formato `HH:MM`, más una zona IANA; por ejemplo, lunes a viernes de 09:00–13:00 y 14:00–18:00 en `America/Mexico_City`. No admite intervalos traslapados ni feriados/excepciones. La resolución se pausa mientras el ticket espera respuesta del cliente y solo descuenta intervalos laborables cuando hay calendario. El ticket conserva su snapshot y los cambios de prioridad quedan en bitácora. La primera respuesta cuenta cuando personal autorizado comparte una respuesta; las respuestas del cliente no cumplen ese indicador. Editar una política no cambia tickets existentes.
- Cada respuesta del portal crea un aviso en bandeja de salida para el responsable activo o, si no lo hay, para quien registró el ticket. Se envía en el siguiente ciclo de hasta cinco minutos; si SMTP falla, se reintenta con espera creciente hasta cinco intentos. El resultado queda visible en la conversación interna y en la bitácora; si no hay correo para ningún destinatario, queda registrado como omitido. La entrega es de mejor esfuerzo y puede repetirse si el servidor acepta el correo pero la conexión se pierde antes de confirmar.
- Se puede habilitar aparte la lectura del buzón de soporte por IMAP sobre TLS. El proceso abre el buzón en modo de solo lectura, procesa folios antiguos primero y registra UID/UIDVALIDITY para no duplicar respuestas. Solo agrega texto plano de hasta 4,000 caracteres si el asunto contiene el folio, el remitente coincide con el correo actual del cliente y el servidor declara `dmarc=pass` en un encabezado `Authentication-Results` de un `authserv-id` configurado. Ese identificador debe ser el del proveedor que elimina o reemplaza encabezados recibidos de Internet; no se debe confiar en un valor escrito por el remitente. Los mensajes automáticos, folios desconocidos, respuestas fuera de estado y autenticaciones fallidas se registran como ignorados o rechazados. No se guardan cuerpos MIME originales ni se aceptan adjuntos.
- La recepción se habilita solo al usar el perfil Compose `email-inbound` y configurar `SUPPORT_IMAP_HOST`, `SUPPORT_IMAP_PORT`, `SUPPORT_IMAP_USERNAME`, `SUPPORT_IMAP_PASSWORD`, `SUPPORT_IMAP_MAILBOX` y `SUPPORT_IMAP_AUTH_SERV_ID`. Sin host configurado, el comando se desactiva sin conectar. Los secretos van en `.env` local y no en el repositorio.

## API y permisos

- `GET/POST /api/support/tickets/`: consultar o registrar tickets.
- `PATCH /api/support/tickets/{id}/`: editar datos y responsable con permisos.
- `POST /api/support/tickets/{id}/transition/` con `status`: cambiar el estado según la transición permitida.
- `POST /api/support/tickets/{id}/add-note/` con `body` y, opcionalmente, `is_public: true`: agregar una nota interna o una respuesta compartida. Compartirla requiere `support.publish_supportticketmessage`.
- `GET /api/support/tickets/assignees/`: ver usuarios activos cuando el rol puede asignar.
- `GET /api/support/tickets/assets/?customer={id}`: consultar equipos instalados del cliente para vincularlos al ticket.
- `POST /api/repairs/cases/` con el UUID del ticket: abrir un expediente de reparación para un activo serializado instalado del mismo cliente; solo uno por ticket.
- `POST /api/support/tickets/{id}/send-portal-link/`: enviar un enlace HTTPS al correo registrado del cliente. Requiere `support.send_supportticket_portal_link`, `ERP_PUBLIC_URL` HTTPS y SMTP configurado; el destinatario y cada intento/resultado quedan en el historial.
- `sla_response_due_at`, `sla_resolution_due_at`, `sla_response_status` y `sla_resolution_status` aparecen como campos de solo lectura en cada ticket. Los estados posibles son `unconfigured`, `on_track`, `overdue`, `met`, `breached` y `not_applicable` (para tickets cancelados).
- `GET/POST /api/support/portal/{token}/`: consulta y respuesta pública con token firmado. El POST agrega un mensaje del cliente; nunca permite modificar el estado directamente ni leer notas internas.
- El servicio `send_support_ticket_notifications` procesa la bandeja interna y también puede ejecutarse manualmente desde el contenedor de la aplicación; Compose lo ejecuta en ciclos de cinco minutos cuando SMTP está configurado. `receive_support_emails` puede ejecutarse manualmente o con el perfil Compose opcional `email-inbound`, en ciclos de cinco minutos.

Ventas puede consultar, crear, agregar notas internas, compartir respuestas y enviar el enlace. Gerencia y Operaciones pueden también actualizar, asignar y cambiar estados. Administración conserva los permisos completos. La pantalla se habilita al conectar la API y oculta navegación y acciones según permisos.

## Límites y siguiente alcance

El expediente inicial de reparación permite registrar diagnóstico, trabajo propuesto, revisión manual de garantía, autorización con evidencia y avance hasta cierre; cada cambio queda auditado. No hay recepción física en taller, consumo de piezas, cotización o factura desde ese expediente. No hay lectura de adjuntos enviados por el cliente, calendario de feriados/excepciones, evaluación automática de cobertura contractual, encuestas ni automatización de visita. El indicador de fecha no determina cobertura ni bloquea soporte por vencimiento. Consulta [expedientes de reparación](reparaciones-v1.md). Redmagna debe confirmar los tiempos por prioridad, zona horaria y horario operativo antes de activar las políticas como compromiso con clientes.
