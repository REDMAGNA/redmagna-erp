# Inventario funcional inicial de Odoo para el ERP abierto de REDMAGNA

**Corte:** 19 de octubre de 2026
**Estado:** mapa de cobertura basado en el índice oficial de aplicaciones de Odoo 19. Incluye las familias y aplicaciones listadas oficialmente, pero no equivale a una especificación funcional completa ni a una clasificación de edición/licencia.

## Método

Se toma como referencia el comportamiento que Odoo documenta públicamente: propósito del módulo, registros que maneja, cambios de estado, reglas, informes y conexiones con otras áreas. La implementación será propia. No se copiarán código, imágenes, textos de interfaz o marcas de Odoo; cualquier consulta a código público se limitará a componentes con licencia compatible y sus avisos se conservarán.

La disponibilidad por edición se clasifica por módulo a partir de manifiestos oficiales y documentación de despliegue. La ficha de reservas de Odoo 19 documenta las variantes al confirmar y antes de la fecha programada; para Redmagna se implementó primero reserva manual por orden de trabajo, cuya decisión y limitaciones quedan registradas en [inventario Redmagna](inventario-redmagna-v1.md). La revisión actual confirma quince módulos Community de Odoo 19, pero deja expresamente sin clasificar muchas extensiones y funciones compuestas. El índice de aplicaciones confirma nombres y agrupaciones, no disponibilidad comercial ni dependencias de cada función.

## Mapa por familia

| Familia | Registros y ciclo que hay que documentar | Conexiones principales | Prioridad para REDMAGNA |
|---|---|---|---|
| Plataforma y administración | Usuarios, grupos, permisos, compañías, preferencias, secuencias, actividades, mensajes, adjuntos, importación y auditoría. Definir alta, cambio, desactivación y retención. | Todas las áreas | Base |
| Contactos y CRM | Empresas, personas, prospectos, oportunidades, actividades, equipos, etapas y motivos de pérdida. Medir conversión y seguimiento. | Ventas, soporte, campañas | Alta |
| Ventas | Productos/servicios, listas de precio, cotizaciones, versiones, envío, aprobación, orden y cancelación; descuentos, impuestos y términos. | CRM, proyecto, inventario, facturación | Alta |
| Proyecto y servicio de campo | Proyectos, tareas/órdenes de trabajo, responsables, agenda, horas, partes, materiales, formularios, evidencia y cierre. | Ventas, empleados, inventario, facturación | Alta |
| Compras e inventario | Proveedores, solicitudes, órdenes, recepciones, ubicaciones, existencias, lotes/series, reservas, entregas, devoluciones y ajustes. | Ventas, proyectos, contabilidad | Alta |
| Contabilidad y facturación | Clientes/proveedores, facturas, notas de crédito, diarios, cuentas, impuestos, pagos, conciliaciones, periodos e informes. Registrar borrador, contabilización, pago parcial/total, reversa y cancelación según aplique. | Ventas, compras, bancos, FEL | Alta |
| México y FEL | Datos fiscales, configuración CFDI/PAC, solicitud de timbrado, respuesta, UUID, XML/PDF, errores, cancelación y sustitución. | Facturación, clientes, contabilidad | Alta; proveedor confirmado: FEL Premium; falta validar API, cuenta y credenciales |
| Punto de venta y comercio electrónico | Catálogo publicado, carrito/orden, cobro, entrega, devolución, caja y sesión. | Inventario, ventas, pagos, facturación | Después del núcleo |
| Suscripciones y servicios recurrentes | Plan, contrato, periodicidad, renovación, pausa, cancelación y facturación recurrente. | Ventas, contabilidad, soporte | Después del núcleo |
| Fabricación y calidad | Lista de materiales, orden de producción, operaciones, consumos, terminados, inspecciones y no conformidades. | Inventario, compras, mantenimiento, contabilidad | No prioritario para Redmagna |
| Mantenimiento y activos | Activos/equipos, solicitudes preventivas/correctivas, agenda, refacciones, costos e historial. | Inventario, compras, empleados | Extensión posible para equipos instalados |
| Gastos, empleados y tiempo | Empleados, gastos, aprobaciones, anticipos, horas, ausencias y reembolsos. Nómina local requiere análisis fiscal separado. | Proyectos, contabilidad, compras | Captura, aprobación, póliza y registro/reversa auditada de reembolsos implementados inicialmente; el pago bancario ocurre fuera del ERP; nómina requiere análisis fiscal separado |
| Soporte, conocimiento y comunicación | Tickets, equipos, etapas, SLA, prioridad, asignación, base de conocimiento, encuesta y cierre. | CRM, ventas, servicio de campo | Alta para soporte técnico; tickets, SLA con horario semanal opcional y recepción IMAP acotada ya están implementados parcialmente; faltan calendario de feriados, bandeja de entrada transversal, Help Center y encuestas |
| Sitio web, marketing y eventos | Páginas, formularios, campañas, listas, automatizaciones, eventos, registros y métricas. | CRM, ventas, contactos | Opcional |
| Documentos, firma y herramientas colaborativas | Archivos, etiquetas, acceso, versión, firma, aprobación y actividad. | Cotizaciones, compras, contabilidad, RR. HH. | Después del núcleo |

## Catálogo oficial de aplicaciones y estado del análisis

El índice de Odoo 19 agrupa aplicaciones en estas familias. Esta tabla registra el universo visible para evitar que el plan se limite a las áreas ya priorizadas. Las descripciones son un mapa de temas, no una afirmación de equivalencia, completitud ni disponibilidad Community. CRM, ventas, Website, contabilidad, inventario, compras y servicios tienen análisis funcional parcial en [el documento detallado](analisis-funcional-odoo-v19.md); las demás siguen en inventario inicial y requieren fichas por flujo.

| Familia oficial | Aplicaciones que aparecen en el índice | Relevancia inicial para Redmagna | Estado de ingeniería funcional |
|---|---|---|---|
| Esenciales | Etapas; actividades; informes; búsqueda, filtros y agrupación; editor de texto; contactos; importar y exportar; compras dentro de la aplicación (IAP); atajos; campos de propiedad; catálogo de productos. | Alta para contactos, actividades, búsqueda/importación y catálogo; baja para funciones de compra IAP. | Contactos, actividades e informes tienen cobertura parcial. Faltan permisos y comportamiento por registro en cada aplicación transversal. |
| Finanzas | Contabilidad y facturación; gastos; pagos en línea; localizaciones fiscales; ESG. | Alta para contabilidad, facturación, México y FEL; gastos útiles para viáticos; pagos en línea no prioritarios para B2B inicial; ESG de prioridad baja, sujeto a fuentes de factores y controles de privacidad. | Contabilidad/FEL tienen diseño propio. Gastos ya tiene servidor e interfaz inicial para captura, reportes, aprobación y póliza borrador; el análisis del flujo Odoo está en la sección 8 del análisis detallado. Falta validar runtime; el registro de reembolso pagado ya genera una póliza de salida. Pagos en línea tienen ficha funcional parcial, sin implementación; ESG cuenta con ficha funcional parcial en la sección 54; licencia/composición y aplicabilidad de fuentes mexicanas siguen sin clasificar. |
| Ventas | CRM; ventas; punto de venta; suscripciones; alquiler. | Alta para CRM y ventas B2B; POS, suscripciones y alquiler dependen del modelo comercial futuro. | CRM, cotizaciones, alquiler, POS y suscripciones tienen análisis parcial en el documento detallado. Suscripciones cubre plan, ciclo de factura, renovación, venta adicional, cierre, fallos de pago e informes MRR/ARR; su licencia sigue sin verificarse. |
| Sitios web | Website; eCommerce; eLearning; foro; blog; chat en vivo. | Website y formularios pueden captar solicitudes B2B; tienda solo si Redmagna decide vender en línea; eLearning y blog pueden apoyar capacitación y documentación; foro y chat requieren moderación/operación diaria. | Ciclos, objetos, controles y prioridad están descritos en secciones 9, 12 y 19–22 del análisis detallado. Se verificaron los manifiestos Community `website_sale`, `website_slides`, `website_blog`, `website_forum` e `im_livechat` por separado; conectores de pago/transporte, servicios de contenido y funciones adicionales requieren clasificación independiente. |
| Cadena de suministro | Inventario; fabricación; compras; código de barras; calidad; mantenimiento; PLM; reparaciones. | Alta para inventario, compras, reparación y mantenimiento de equipos instalados; fabricación/PLM/calidad industrial son posteriores. | Inventario y compras parcialmente desglosados; hay reserva manual de material por orden y cantidades aceptadas como requerimientos, pronóstico fechado por ubicación y reservas por serie. Código de barras cuenta con análisis de ciclo en la sección 53 y el ERP ya almacena códigos únicos de producto/ubicación y admite escaneo en entradas, recepciones de compra no ambiguas, ajustes, entregas/devoluciones y traspasos; faltan conteos asignados, empaques y preparación por lote. Faltan rutas de abastecimiento, devoluciones completas, reparación y mantenimiento preventivo. Compras ya registra solicitudes, compara ofertas y envía RFQ por SMTP; captura las respuestas manualmente. Las condiciones proveedor-producto conservan revisiones inmutables. La adjudicación parcial por producto/cantidad y los acuerdos marco con límite opcional están implementados; faltan aprobaciones por importe y abastecimiento automático de la demanda completa. |
| Recursos humanos | Asistencias; empleados; evaluaciones; recepción/frontdesk; flotilla; nómina; tiempo libre; reclutamiento; referidos; comedor. | Horas y empleados vinculados a operaciones podrían ser útiles; nómina mexicana, flotilla y control de personal requieren definición local y legal. | Empleados, asistencia y ausencias cuentan con fichas funcionales en el análisis detallado; nómina mexicana sigue fuera de alcance y no se deben iniciar cálculos laborales sin reglas aprobadas por especialistas mexicanos. |
| Marketing | Email marketing; SMS; automatización de marketing; social; eventos; tarjetas de marketing; encuestas. | El correo/SMS transaccional existente no equivale a campañas masivas; las automatizaciones y publicaciones requieren consentimiento, aprobación, control editorial y cuentas de proveedor. | Email/SMS: sección 13; eventos: 15; encuestas: 16; automatización: 51; social: 52. Community `mass_mailing`, `mass_mailing_sms`, `sms`, `mass_mailing_crm` y `event` tienen manifiestos revisados; rutas Community de `marketing_automation` y `social` no aparecen, por lo que su edición/licencia queda sin clasificar. Encuestas y proveedores IAP aún requieren revisión específica. |
| Servicios | Proyecto; hojas de horas; planificación; servicio de campo; Helpdesk. | Alta para las instalaciones y soporte técnico de Redmagna. | Proyecto, tickets y servicio de campo tienen cobertura parcial. Tickets ya incorpora SLA medibles por prioridad con calendario semanal opcional y recepción IMAP limitada a respuestas verificadas; faltan feriados/excepciones y bandeja transversal. El análisis distingue la agenda semanal implementada de turnos Gantt/publicados y auto-planificación de Odoo; quedan rutas, reglas completas de horarios/ausencias/roles, recurrencias y plantillas de visita. |
| Productividad | Documentos; firma; hojas de cálculo; tableros; conocimiento; calendario; citas; Discuss; limpieza de datos; WhatsApp; telefonía; tareas por hacer; IA. | Documentos, calendario, citas y tareas pueden apoyar ventas/operaciones; WhatsApp exige cuenta y API de Meta; IA depende del modelo/proveedor externo y requiere política de datos y costos. | Citas: 14; limpieza de datos: 44; calendario: 45; Discuss: 46; hojas/tableros: 47; To-do/Phone: 48; WhatsApp: 49; IA: 50. WhatsApp figura como Enterprise en la documentación; las rutas de manifiesto Community de WhatsApp y AI no están presentes y la edición/licencia de AI queda sin clasificar. Revisar permisos, retención, API y proveedores. `calendar` y `mail` Community declaran `LGPL-3`; `o-spreadsheet` publica LGPLv3; no extrapolar estas licencias a sus integraciones o módulos adicionales. |
| Studio | Campos y widgets; vistas; modelos, módulos y aplicaciones; automatizaciones; informes PDF; reglas de aprobación. | Configuración flexible puede ser útil, pero no sustituye reglas versionadas ni controles de cambios del ERP abierto. | Ficha funcional añadida en la sección 38 del [análisis detallado](analisis-funcional-odoo-v19.md). La licencia/edición por función sigue sin clasificarse. No se planea construir un clon de Studio en el núcleo inicial. |
| Ajustes generales | Aplicaciones y módulos; usuarios; compañías; IoT; correo; integraciones; modo desarrollador; modo sin conexión. | Alta para usuarios, correo e integraciones; una compañía en Redmagna. IoT y offline dependen de despliegue, red y dispositivos. | Ciclos de instalación/módulos: sección 39; IoT: 40; desconexión: 41; usuarios, preferencias y compañía: 42; correo entrante/saliente: 43. Faltan panel general de preferencias, perfil editable de empresa y bandeja transversal de correo. |

Las agrupaciones anteriores están confirmadas en el [índice oficial de aplicaciones de Odoo 19](https://www.odoo.com/documentation/19.0/applications.html). La página presenta por separado, entre otras, las familias de [esenciales](https://www.odoo.com/documentation/19.0/applications/essentials.html), [finanzas](https://www.odoo.com/documentation/19.0/applications/finance.html), [sitios web](https://www.odoo.com/documentation/19.0/applications/websites.html), [cadena de suministro](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp.html), [recursos humanos](https://www.odoo.com/documentation/19.0/applications/hr.html), [marketing](https://www.odoo.com/documentation/19.0/applications/marketing.html), [servicios](https://www.odoo.com/documentation/19.0/applications/services.html), [productividad](https://www.odoo.com/documentation/19.0/applications/productivity.html), [Studio](https://www.odoo.com/documentation/19.0/applications/studio.html) y [ajustes generales](https://www.odoo.com/documentation/19.0/applications/general.html). El índice puede cambiar entre revisiones; se registró este corte el 18 de octubre de 2026.

## Flujos que deben desglosarse antes de programar

1. **Cotización a cobro:** oportunidad → cotización → envío y seguimiento → aceptación → orden → trabajo/entrega → factura → timbrado FEL → cobro parcial o total → conciliación → póliza.
2. **Compra a pago:** solicitud interna → aprobación → orden de compra → recepción → factura del proveedor → pago → conciliación → póliza.
3. **Instalación o soporte:** solicitud/ticket → diagnóstico → asignación → agenda → materiales y horas → evidencia → aceptación del cliente → factura o cargo contra contrato.
4. **Inventario:** recepción → disponibilidad/reserva → salida a técnico o proyecto → devolución/merma → costeo y efecto contable.
5. **Correcciones fiscales:** factura timbrada → solicitud de cancelación/sustitución → respuesta del PAC/SAT → conservar XML, UUID, relación y bitácora; nunca borrar el registro previo.

## Ficha que se completará para cada aplicación

- Objetivo y usuarios/roles.
- Entidades, campos clave, relaciones y restricciones.
- Estados y transiciones, incluyendo quién puede hacerlas.
- Reglas de cálculo, impuestos, redondeo, fechas y numeración.
- Documentos de origen y efectos en otros módulos.
- Informes y métricas.
- Funciones Community, Enterprise, tercero o servicio externo.
- Integración técnica, permisos, secretos, errores y reintentos.
- Casos de prueba derivados del flujo y criterio de aceptación.
- Licencia de código y dependencias si se estudia o reutiliza una implementación pública.

## Orden de análisis y construcción sugerido

1. Base, contactos y permisos.
2. Ventas, cotizaciones, productos/servicios y aprobación.
3. Órdenes de trabajo, horas, materiales e inventario básico.
4. Facturación, contabilidad mexicana y FEL Premium, con aprobación del contador y acceso técnico de pruebas confirmado.
5. Compras, pagos, conciliación, importación de hojas de cálculo y reportes.
6. Soporte, mantenimiento y las extensiones que Redmagna use realmente.
7. Módulos generales opcionales, cada uno separado y con sus dependencias declaradas.

## Fuentes oficiales iniciales

- [Índice general de aplicaciones de Odoo 19](https://www.odoo.com/documentation/19.0/applications.html)
- [Aplicaciones y módulos: dependencias y administración](https://www.odoo.com/documentation/19.0/applications/general/apps_modules.html)
- [Cotizaciones de venta](https://www.odoo.com/documentation/19.0/applications/sales/sales/sales_quotations/create_quotations.html)
- [Facturas de cliente y estados](https://www.odoo.com/documentation/19.0/applications/finance/accounting/customer_invoices/overview.html)
- [Servicios: proyecto, planificación, campo y soporte](https://www.odoo.com/documentation/19.0/applications/services.html)
- [Licencias de Odoo](https://www.odoo.com/documentation/19.0/ro/legal/licenses.html)
- [Licencia GNU AGPLv3 elegida para este proyecto](https://www.gnu.org/licenses/agpl-3.0.html)

## Siguiente trabajo

La ampliación funcional está en el [análisis detallado de Odoo 19](analisis-funcional-odoo-v19.md), que cubre parcialmente ciclos de CRM, ventas, compras, inventario, servicio de campo, soporte, contabilidad, gastos y suscripciones. La ficha de suscripciones documenta planes, factura recurrente, renovación, venta adicional, cierre, cobro fallido e informes MRR/ARR; para Redmagna queda como extensión condicionada a confirmar contratos de soporte o monitoreo. El módulo inicial de gastos en Redmagna ya tiene servidor e interfaz para captura, reportes, aprobación y póliza borrador; el ERP registra el pago ya efectuado y genera la póliza de salida; ejecutar la transferencia continúa fuera del sistema. El catálogo de este documento cubre las familias publicadas en el índice oficial; la siguiente revisión debe completar fichas por aplicación y verificar disponibilidad/licencia por módulo, dependencia y función compuesta. El flujo de Redmagna está en la [especificación del núcleo de ventas](especificacion-nucleo-ventas-v1.md); el [inventario básico](inventario-redmagna-v1.md) ya cubre entradas, salidas, devoluciones, ajustes y reservas iniciales. Compras ya cuenta con registro interno de solicitudes, comparación de ofertas, envío auditado de RFQ por SMTP, revisiones inmutables de condiciones proveedor-producto, adjudicación parcial y acuerdos marco con límites de cantidad y órdenes borrador relacionadas. Las respuestas de RFQ siguen capturándose manualmente; faltan reglas de aprobación por importe y abastecimiento automático por demanda. Falta levantar y validar el servicio en Docker, revisar permisos por persona y acordar reglas contables y fiscales con el contador y FEL.
