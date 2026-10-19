# Registro de cambios

Los cambios funcionales y de seguridad se registrarán aquí para cada versión publicada. El proyecto todavía está en desarrollo y no ha publicado una versión estable.

## Sin publicar

### Añadido

- El análisis de Inventario Odoo 19 ahora describe ajustes físicos, conteo asignado, aplicación con motivo, series por renglón y auditoría; contrasta esas funciones con el conteo y revisión serial que ya tiene Redmagna y enumera las brechas restantes.
- Conteo físico en pantalla y API para productos por cantidad y serie: fija saldo y estado inicial al iniciar, captura cantidades o identificadores, exige revisión por otra persona y aplica diferencias como movimientos ligados al conteo solo si no hubo movimientos concurrentes.
- Pagos 2.0 rechaza preparar un complemento cuando una factura relacionada tiene una nota de crédito aplicada; la fórmula actual no modela con seguridad su efecto en saldo e impuestos.
- El análisis funcional de Odoo 19 incorpora ESG: origen contable y manual de datos, factores, alcances y gases, desplazamientos, métricas sociales e iniciativas; registra los límites de privacidad y deja su disponibilidad/licencia sin clasificar cuando la evidencia del módulo no alcanza.
- Al devolver materiales o ajustar existencias, Almacén debe registrar un motivo; la API, el modelo y la pantalla bloquean movimientos sin ese dato para conservar una bitácora explicable.
- Las entradas manuales de existencias exigen una referencia de origen; las recepciones de órdenes de compra conservan su folio y la pantalla pide una remisión u otro respaldo para entradas directas.
- Los traspasos entre ubicaciones requieren motivo; la API, el modelo y el formulario bloquean la confirmación si falta.
- Los movimientos de inventario manuales usan una clave idempotente y una huella de la solicitud: un reintento idéntico devuelve el movimiento previo y no vuelve a modificar existencias.
- La matriz funcional de Odoo 19 precisa Blog, Foro, eLearning y Chat en vivo con referencias oficiales, incluyendo el límite de evidencia sobre aprobación editorial y los requisitos de configuración GeoIP on-premise.
- El análisis funcional añade Nómina mexicana como ciclo independiente con módulos oficiales documentados, controles de datos laborales y separación entre horas de servicio, recibos, pólizas y CFDI; su licencia y compatibilidad con FEL quedan sin verificar.
- El inventario admite códigos de barras únicos para productos y ubicaciones; en traspasos, cada lectura agrega una unidad a entradas, recepciones de compra con una sola línea pendiente para el producto, ajustes, entregas/devoluciones a órdenes o líneas de traspaso; se pueden escanear ubicaciones y se conservan las validaciones y captura manual de series.
- El análisis de Odoo 19 añade el ciclo de Código de barras: recepción, entrega, traspaso, conteo asignado, procesamiento por lotes y lectura GS1; diferencia manifiestos Community comprobados de la aplicación operativa cuya licencia queda sin clasificar y contrasta las brechas actuales de Redmagna.
- Contabilidad puede enviar manualmente al correo registrado del cliente el XML de un CFDI timbrado y el PDF disponible mediante un permiso independiente; la bitácora registra el resultado y la interfaz advierte que un intento incierto debe revisarse antes de repetirlo.
- Acuerdos marco de compra en la pantalla de Compras, API y Django Admin: borrador con proveedor, vigencia, precios y límite opcional por producto; activación con renglones inmutables, generación de órdenes borrador dentro de vigencia, control concurrente de cantidades comprometidas y liberación de saldo al cancelar una orden.
- Compras permite registrar cantidades cotizadas por renglón y adjudicar cantidades parciales entre proveedores; conserva la solicitud/oferta de origen, saldo pendiente, eventos y órdenes borrador separadas, y exige justificar una elección de mayor precio cuando hay una oferta más barata vigente.
- El análisis de compras Odoo 19 separa licitaciones con adjudicación parcial por renglón de acuerdos marco, documenta los controles de vigencia/saldo y enumera decisiones pendientes para Redmagna.
- El análisis de Ventas Odoo 19 distingue listas comerciales de precio de la hoja privada de costos de Redmagna y documenta que las reglas de precio por cliente, cantidad y vigencia requieren una decisión independiente antes de automatizarse.
- El análisis Odoo 19 detalla Automatización de marketing y Marketing social: audiencias, workflow, prueba y parada, cuentas OAuth, publicación programada, conversión de comentarios y límites de licencias/proveedores.
- El análisis Odoo 19 incorpora los ciclos de WhatsApp Business y agentes de IA, la conexión con Meta/OpenAI/Gemini, los riesgos de credenciales y datos, y los límites de edición/licencia observados.
- El mapa funcional de Odoo 19 ahora refleja las fichas detalladas de eCommerce, eLearning, Blog, Foro y Live Chat, y separa sus módulos Community de pagos, transporte y servicios externos.
- La pantalla de automatización contable permite configurar también pólizas borrador para notas de crédito, con diario y cuentas de ventas validadas igual que las facturas.
- Las reglas de automatización contable conservan versiones inmutables con cuentas, diario, estado, responsable y fecha; la interfaz muestra los cambios recientes junto a cada regla.
- Administración explica el efecto de la política de descuentos y registra en auditoría cada cambio de umbral o activación, junto con el usuario que lo realizó.
- Las cuentas por pagar verifican localmente el sello digital del emisor del CFDI de proveedor contra su certificado incrustado; guardan el resultado y su fecha, sin presentar esto como validación de confianza SAT ni consulta del UUID.
- El análisis Odoo 19 documenta To-do y Phone como tareas personales y llamadas ligadas a CRM/soporte, con dependencias de telefonía externa, controles de acceso y licencias sin clasificar donde falta evidencia del manifiesto.
- Importación masiva de proveedores por CSV con vista previa, validación de campos, omisión de RFC o correo duplicados y confirmación antes de crear; los datos existentes nunca se actualizan desde la importación.
- El mapa de Odoo 19 documenta hojas de cálculo y tableros, permisos por origen, colaboración, snapshots y límites de licencia entre el motor abierto y las integraciones empresariales.
- La orden de trabajo muestra por producto las cantidades requeridas, entregadas, devueltas, reservadas y pendientes; el avance operativo no presenta costos ni implica una valuación contable.
- El historial reciente de materiales en cada orden incluye fecha, ubicación, responsable y números de serie cuando corresponden.
- Los movimientos completos de entrega y devolución de materiales de una orden de trabajo se pueden descargar en CSV seguro, sin datos de costo.
- La ficha de equipo por serie muestra la orden de compra, proveedor, renglón y fecha de recepción de origen cuando existe una recepción vinculada; no agrega ni expone una valoración monetaria.
- El listado de equipos por serie ahora permite buscar por serie, producto, estado, cliente, ubicación, orden de compra y proveedor; pagina el resultado para que equipos después de los primeros 100 también estén disponibles en la pantalla.
- Cuentas por cobrar y pagar permiten exportar a CSV la antigüedad al corte (incluye importes, cobros y notas de crédito aplicables) y los estados de cuenta por cliente/proveedor con cargos, abonos y saldo acumulado. Las descargas usan el escape seguro existente para celdas interpretables como fórmulas.

### Corregido

- La pantalla FEL muestra el estado y código de la última consulta de cancelación, incluyendo si el UUID devuelto coincide con el comprobante; deja visible la evidencia cuando la solicitud permanece pendiente o fue rechazada.
- La consulta de cancelación FEL solo marca un CFDI cancelado cuando la respuesta confirma tanto el UUID exacto como el estado cancelado; una respuesta exitosa pero incompleta o para otro UUID conserva el estado pendiente y deja evidencia en la bitácora.
- Los auxiliares identifican por separado facturas, cobros/pagos, reversas, notas de crédito y saldos previos de apertura en pantalla, impresión y exportación CSV.
- El análisis funcional de Odoo 19 incorpora fichas de Studio y el ciclo de instalación, actualización y retiro de aplicaciones/módulos, con controles de migración, dependencia y eliminación de registros.
- El mapa funcional de Odoo 19 documenta IoT y modo sin conexión por separado: dispositivos de red local, restricciones del modo general y sincronización limitada de Punto de Venta; se aclara que la caché no valida movimientos fiscales o financieros.
- El análisis de Odoo amplía ajustes generales: distingue usuarios, sesiones, idiomas, empresa y modo técnico; documenta correo SMTP/IMAP, autenticación SPF/DKIM/DMARC y el alcance actual del ERP Redmagna.
- El mapa de productividad distingue la limpieza/archivo Community de la estandarización/fusión Enterprise; especifica controles para no fusionar automáticamente clientes fiscales, inventario o registros contables.
- El análisis de productividad documenta reuniones, disponibilidad, recurrencias y sincronización de Google/Outlook, y distingue el calendario general de la agenda operativa y las citas públicas de Redmagna.
- El análisis de productividad cubre Discuss, chatter, seguidores, preferencias de notificación y actividades, y los separa de notas privadas y eventos de auditoría; revisa la licencia `LGPL-3` del módulo Community `mail`.
- Se documenta el diseño pendiente de valuación de inventario y costo por orden, separando movimientos físicos, costo de adquisición, submayor monetario y pólizas sujetas a reglas aprobadas por el contador.

### Corregido

- La guía de Synology distingue la dirección donde Compose publica el puerto del NAS de la interfaz interna donde Gunicorn escucha; documenta el uso de `127.0.0.1` detrás del proxy DSM.
- El preflight de Synology valida antes del arranque la coherencia entre proxy HTTPS, cookies seguras, redirección SSL, HSTS y captación pública de prospectos.
- El preflight comprueba formato de credenciales FEL productivas y requisitos para habilitar cancelaciones antes de iniciar contenedores, sin mostrar los valores secretos.
- El transporte SOAP de FEL ya no sigue redirecciones HTTP: evita reenviar credenciales y XML fiscal fuera de los endpoints configurados.
- La cancelación FEL verifica localmente que el PFX contenga el certificado exacto que selló el CFDI y que su llave privada corresponda, antes de transmitir el PFX al servicio.
- El registro de timbrados FEL compara el XML completo contra la solicitud firmada, exige un solo TFD con sello CFDI coincidente y guarda la fecha SAT de `FechaTimbrado`.
- La consulta de cancelación FEL solo cierra un CFDI cuando la operación es exitosa y el estado es exactamente `Cancelado`; los valores distintos o ambiguos quedan pendientes.
- La bitácora de reparaciones registra los estados de custodia antes y después de recibir o devolver el equipo, y presenta esas transiciones con etiquetas propias en español.
- Los límites mínimos decimales de cantidades, horas y reembolsos usan `Decimal`, evitando comparaciones flotantes y advertencias en la verificación de Django.
- Los respaldos PostgreSQL/medios usan un identificador por ejecución para evitar colisiones; si falla la publicación de cualquiera de los archivos, se retiran también los finales parciales. El paquete ahora exige las dos migraciones recientes de soporte.
- Inventario registra explícitamente el `basename` de las reglas de reabastecimiento; se corrigieron importaciones y nombres de campos de pagos a proveedor y recibos IMAP que impedían cargar rutas/modelos de Django. La migración renombra columnas IMAP conservando su contenido.

### Añadido

- Política de descuentos excepcionales configurable y desactivada por defecto: Gerencia puede fijar un límite, ve en cada pendiente el descuento solicitado y el máximo vigente, autoriza cotizaciones enviadas y consulta una bitácora inmutable; tanto la aceptación del cliente como la aprobación interna bloquean descuentos pendientes.
- El análisis de Odoo documenta rutas Community 19.0 no encontradas para `sale_renting`, `planning` y `knowledge`; mantiene sus licencias y edición sin clasificar, sin deducir Enterprise a partir de un 404.
- Hoja interna de costos por cotización con renglones por categoría, costos base/opcionales, utilidad y margen bruto estimados por separado, ventas sugeridas por margen objetivo y descarga CSV compatible con Excel; permisos separados, historial de cambios en bitácora y bloqueo al enviar. No modifica ni expone los precios internos en la cotización del cliente.
- Los cálculos de vista previa y CSV de costos usan centavos y cantidades escaladas con redondeo decimal half-up, igual que el backend, evitando diferencias de centavos por punto flotante.
- Los respaldos DSM incluyen hashes SHA-256 pareados para base y medios; la tarea valida que ambos archivos sean legibles, y la restauración comprueba integridad y pertenencia al mismo respaldo antes de cargar la base de prueba. Los respaldos anteriores siguen aceptándose con aviso.
- El análisis funcional de Odoo 19 amplía las secciones independientes y la matriz con Alquiler, Planeación de servicio y Conocimiento; detalla custodia/devolución y depósitos, turnos y publicación, y artículos con alcance interno/público. La licencia de estos módulos sigue pendiente de revisar con manifiestos exactos.
- El análisis de Odoo 19 profundiza el ciclo del expediente laboral, contratación y evaluaciones; documenta privacidad por participante y confirma manifiestos Community para Empleados/Reclutamiento, dejando Appraisals sin clasificar donde no se encontró manifiesto público de la rama 19.0.
- El análisis funcional de Odoo 19 completa fichas de Tiempo libre y Asistencias, separando saldo/solicitud y marcación/revisión; documenta los manifiestos Community consultados y deja fuera cualquier regla de nómina o cumplimiento laboral mexicano no validada.
- El análisis de Odoo 19 incorpora aprobaciones genéricas y reglas de aprobación de acciones como capacidades distintas, con controles de segregación de funciones y licencia sin clasificar para los módulos no presentes en el repositorio Community consultado.
- El análisis funcional de Odoo 19 amplía Manufactura, Calidad, PLM y Flota, separando el registro de vehículos, los kits de venta, la producción, inspecciones y cambios de ingeniería.
- El análisis funcional de Odoo 19 amplía documentos y firma electrónica, con flujos de acceso/archivo y solicitud/constancia, límites de validez para México y estado de licencia sin inferir desde una ruta Community ausente.
- El análisis funcional de Odoo 19 completa las fichas de eLearning, Blog, Foro y Live Chat, con ciclos, dependencias, licencia base y criterios de prioridad y privacidad para Redmagna.
- Recordatorios optativos y auditados de cobranza por correo para facturas abiertas con saldo: aviso próximo al vencimiento y aviso vencido, SMTP con reintentos limitados, deduplicación por factura/etapa, omisión trazable de contactos sin correo y reencolado administrativo con actor/fecha. La activación permanece deshabilitada por defecto.
- La pantalla de Facturación muestra si los recordatorios de una factura están pendientes, enviados, agotados o se omitieron por falta de correo; la API precarga los registros para evitar consultas por fila.

- Las órdenes de trabajo exponen el total comercial aceptado con IVA y muestran pendiente de facturar, facturas internas, borradores y saldo de CxC; la vista separa estos importes de costos/márgenes y aclara que la factura interna no confirma el timbrado CFDI.
- Conciliación de auxiliares CxC/CxP contra cuentas de control del mayor al corte, con diferencia explícita y exportación CSV desde Contabilidad; prepara los controles para cargar saldos abiertos sin duplicar pólizas.
- Vista previa de CSV para saldos abiertos: coteja RFC activos, duplicados, fechas, MXN, aritmética original/pagado/saldo y totales contra cuentas de control; no guarda partidas ni genera pólizas.
- Lotes persistentes de saldos CxC/CxP con huella del CSV, reservas de folios externos e idempotencia; Contabilidad prepara y una persona distinta puede revisar partidas, descargar el detalle CSV y publicar como saldo operativo o rechazar con nota. La publicación no genera pólizas ni habilita Pagos 2.0 sin historia fiscal.
- La lista de lotes carga solo sus resúmenes; las partidas y sus vínculos se consultan bajo demanda al abrir el detalle.
- Docker excluye `work/`, `node_modules/` y `outputs/` del contexto de construcción; el Dockerfile solo necesita las carpetas que copia explícitamente.
- La guía Synology incluye una comprobación previa de solo lectura para rutas persistentes, secretos, GID de datos y sintaxis Compose; no inicia servicios ni revela valores de `.env`.

- Primera etapa de expedientes de reparación separada en su propia aplicación Django; enlaza un ticket con activo serializado instalado, captura diagnóstico y autorización humana, registra transiciones auditadas y evita cargos o movimientos de inventario automáticos.
- El análisis Odoo 19 añade los ciclos de Reparaciones y Mantenimiento: distingue devoluciones y reparación de equipos del cliente de mantenimiento preventivo/correctivo de activos propios, documenta estados, piezas, garantías, métricas y dependencias Community `LGPL-3`.
- El servicio periódico de CRM marca cotizaciones enviadas como vencidas después de su fecha límite y registra el cambio en la bitácora; la aceptación sigue comprobando la vigencia dentro de su transacción.
- Diseño de apertura para CxC/CxP que separa la póliza de balanza de los auxiliares, exige cuadrar las cuentas de control y conserva el historial de CFDI/parcialidades necesario para no emitir complementos Pagos 2.0 incompletos.
- SLA de soporte admite calendario semanal y zona horaria IANA configurables por prioridad; cada ticket congela esa regla, calcula vencimientos en horas laborables y pausa la resolución por espera del cliente solo dentro de los intervalos definidos. Los calendarios vacíos conservan minutos corridos.
- El análisis Odoo 19 añade Encuestas: preguntas y condiciones, acceso por enlace/invitación, intentos, puntuación, certificación, sesiones en vivo y reportes; verifica `survey` como Community `LGPL-3` y define privacidad, versión publicada y uso posterior al servicio para Redmagna.
- La aceptación de un CFDI de Pagos 2.0 timbrado coteja contra el snapshot revisado emisor, receptor, fecha, forma e importe, parcialidades, saldos, impuestos por documento y pago, y totales del complemento; si FEL devuelve datos distintos, el recibo permanece enviado para investigación y no se registra como timbrado.
- El análisis Odoo 19 añade el ciclo de Eventos: publicación, boletos y registro, preguntas, comunicaciones, agenda, check-in y controles de cobro/cancelación; distingue el manifiesto Community base de sus integraciones opcionales.
- El análisis Odoo 19 añade el ciclo de Citas: tipos, disponibilidad de usuarios/recursos, capacidad, confirmación, preguntas, cancelación y creación opcional de oportunidades; distingue una reserva pública de una orden de trabajo y deja su licencia sin clasificar hasta revisar el manifiesto.
- El análisis funcional Odoo 19 añade la sección de Marketing: listas, consentimiento y bajas, segmentación, correos/SMS, automatizaciones, métricas y dependencias externas; verifica manifiestos Community LGPL-3 donde hay evidencia y deja sin clasificar los módulos ausentes.
- Los XSD/XSLT SAT de CFDI 4.0 y Pagos 2.0 quedan fijados por SHA-256; el empaquetado Synology detiene la generación si un esquema cambia o desaparece sin actualizar y revisar el manifiesto.
- Nuevo perfil **Técnicos**: cada técnico solo consulta sus órdenes asignadas; puede completar checklist, registrar horas y evidencia, avanzar el trabajo y guardar su nota de cierre. No puede asignar ni reprogramar órdenes ni consultar reportes globales de horas.
- Operaciones y Gerencia pueden consultar y exportar a CSV horas registradas por servicio y persona, filtradas por fechas; el reporte deja claro que no calcula nómina ni costo laboral.
- Contabilidad puede descargar en CSV la balanza de comprobación, el libro mayor consultado y los estados financieros; los archivos incluyen los movimientos y totales del periodo seleccionado.
- Los contenedores de respaldo y restauración ahora fijan el mismo digest PostgreSQL que el servicio de base de datos; el respaldo prepara ambos archivos como temporales y los publica solo después de terminar la exportación de base y medios.
- El empaquetado AGPL y Synology ahora omite carpetas de secretos, certificados, llaves, contraseñas CSD y archivos `.env` locales; valida los archivos comprimidos para rechazar secretos si algún patrón de exclusión falla.
- Ficha de clientes con varios contactos comerciales, área/puesto, correo y teléfono; mantiene un principal activo, permite archivar/reactivar y no elimina ni cambia contactos de cliente.
- Ventas puede seleccionar el destinatario de cada cotización; nombre y correo quedan guardados en la propuesta, revisión, correo y validación de aceptación aunque la ficha cambie después.
- Plazo de pago predeterminado opcional en clientes, snapshot de días naturales por cotización y propuesta automática de vencimiento al crear la cuenta por cobrar desde la orden; las facturas conservan un solo vencimiento editable mientras están en borrador.
- Ruta pública de solicitud de cotización que crea oportunidades nuevas sin asignar un usuario ficticio, registra consentimiento, usa token temporal/campo trampa y aplica límite por correo. Desactivada por defecto; el arranque exige HTTPS y una URL del aviso de privacidad antes de habilitarla.
- La solicitud pública conserva parámetros UTM de origen, medio y campaña en la oportunidad; el reporte comercial ahora muestra conversión e ingreso ponderado por campaña.
- Administración puede filtrar y buscar oportunidades por canal/campaña, y consultar en modo de solo lectura la fecha del consentimiento de los prospectos web.
- Avisos opcionales de nuevos prospectos web mediante una cola durable, entrega SMTP con reintentos y consulta administrativa del resultado; la captura permanece guardada aunque el correo falle.
- Administración puede reencolar manualmente un aviso agotado después de corregir el SMTP, sin alterar la solicitud comercial y conservando el contador de reintentos manuales.
- La cancelación CFDI con motivo 01 ahora exige que el UUID sustituto pertenezca a un CFDI vigente ya timbrado en Redmagna; coteja proveedor, tipo, RFC emisor/receptor, moneda, UUID del Timbre Fiscal Digital y relación SAT tipo 04 al comprobante original antes de enviar la solicitud irreversible a FEL.
- La preparación de CFDI de ingreso mantiene el IVA al 8% deshabilitado por defecto; requiere la activación explícita `CFDI_ALLOW_BORDER_8_RATE=true` y bloquea la clave genérica 01010101, con advertencia documentada sobre las condiciones fronterizas que aún debe validar Contabilidad.
- La tasa fronteriza al 8% ahora exige además un producto enlazado cuya clave SAT fue marcada como revisada en Django Admin; si cambia `ClaveProdServ`, la marca se restablece. Ventas muestra el estado de revisión por producto y en la clasificación de cada CFDI.
- La revisión del 8% no puede marcarse en un producto si su `ClaveProdServ` no existe en el catálogo SAT local; la preparación de CFDI valida también la existencia de las claves SAT de producto/servicio y unidad antes de crear el snapshot.
- El 8% requiere que el código postal de expedición pertenezca a `CFDI_BORDER_8_REVIEWED_POSTAL_CODES`, una lista configurada por Contabilidad tras cotejar el catálogo SAT fronterizo.
- El análisis de Odoo 19 para México detalla el flujo público documentado de PUE/PPD, complementos tipo P, cancelación y sustitución; se corrigió la comparación para reflejar que Redmagna ya implementa cancelación FEL opt-in y dejar como brecha la creación guiada del reemplazo y su verificación operativa.

- El análisis funcional de Odoo 19 documenta Website de página y publicación a formulario CRM, SEO, UTM y analítica; verifica el manifiesto Community `LGPL-3` y distingue servicios externos y funciones no implementadas en Redmagna.

- Las reservas por cantidad o serie y las salidas de almacén quedan limitadas en servidor a los productos, ubicaciones y cantidades de material aprobados en la orden de trabajo; los productos serializados requieren cantidades enteras.

- La hoja imprimible de cotización muestra una cabecera comercial configurable por instalación (nombre, razón social, RFC y contacto) sin fijar datos fiscales de ejemplo.

- El registro de CFDI emitidos valida el XML con el XSD local y coteja RFC, UUID del timbre, moneda, subtotal y total contra el documento interno; para notas de crédito también compara UUID y tipo de relación.

- Los contenedores web, recordatorios CRM y recepción IMAP montan una raíz de solo lectura y un `/tmp` temporal, manteniendo escritura persistente en medios y datos de PostgreSQL.

- Conciliación bancaria permite preparar, desde un movimiento sin póliza, un asiento balanceado en borrador con diario y contrapartida seleccionados por Contabilidad; requiere contabilización manual antes de vincularlo y protege la fecha, cuenta, importe y dirección de su línea bancaria.

- El registro contable de CFDI emitidos incluye egresos tipo E junto a ingresos tipo I, vincula UUID relacionados y presenta separados sus importes e impuestos desde los XML guardados.

- Flujo interno de notas de crédito en borrador y aplicadas, ligadas a renglones de factura; limita el total a cantidades y saldo pendientes, refleja abonos en antigüedad/estado de cuenta y permite póliza contable borrador configurada. Primer flujo de CFDI 4.0 tipo E para notas ligadas a un ingreso timbrado, XML firmado local y envío expreso por FEL Premium; requiere selección contable de uso CFDI y forma de pago. CFDI E para escenarios ampliados, devoluciones físicas y reembolsos siguen fuera del alcance actual. Las notas aplicadas pueden revertirse con motivo y recuperan el saldo, con póliza inversa cuando la original ya se contabilizó.

- ERP modular original para clientes, CRM, cotizaciones, ventas, órdenes de trabajo, compras, inventario, cuentas por cobrar y pagar, contabilidad y soporte.
- Preparación local de CFDI 4.0 y recepción de Pagos 2.0 con integración FEL Premium configurable.
- El catálogo de productos puede guardar claves SAT de producto/servicio y unidad; los CFDI las sugieren y siguen requiriendo revisión manual.
- La pantalla de inventario incluye el catálogo de productos y servicios con edición sujeta a permisos, también para mantener sus claves SAT.
- Los productos permiten mantener valores predeterminados de objeto de impuesto y factor de IVA; la preparación del CFDI los sugiere por concepto y vuelve a exigir revisión.
- Importación inicial de clientes por CSV con vista previa, validación por fila, omisión de duplicados y creación explícita sin actualizar registros existentes.
- Importación inicial de productos y servicios por CSV, con validación de claves SAT y SKU y sin modificar existencias, precios ni productos previos.
- Diseño de brecha para anticipos y cobros no aplicados: distingue el recibo operativo del anticipo fiscal, mapea las rutas CFDI SAT documentadas y deja las decisiones contables/fiscales pendientes antes de automatizar.
- Reintentos de creación de revisiones de cotización recorren toda la cadena y devuelven la versión más reciente, sin regresar a una revisión que ya fue reemplazada.
- La pantalla abre cada nueva revisión en modo edición y permite reabrir borradores; Gerencia recibe el permiso `sales.change_quote` para completar este flujo.
- La API y la lista de cotizaciones muestran el folio de origen de cada revisión para seguir su historial comercial.
- Las cotizaciones admiten tasas de IVA por concepto en el formulario, las plantillas conservan esa configuración y el PDF, la aceptación pública y el correo muestran la tasa aplicada por renglón.
- Las cotizaciones y plantillas conservan y calculan IVA por concepto; la propuesta PDF muestra la tasa aplicada a cada renglón.
- Políticas SLA de soporte configurables por prioridad, objetivos históricos en cada ticket, pausa durante espera del cliente e indicadores de primera respuesta y resolución.
- Recepción IMAP opcional de respuestas a tickets, con deduplicación UID, validación DMARC del proveedor, verificación del folio y correo registrado, sin guardar el mensaje MIME ni adjuntos.
- Despliegue Compose para Synology DS720+, persistencia de datos y medios, respaldos y restauración de prueba documentada.
- Análisis funcional de Odoo 19 para orientar la cobertura por aplicaciones sin reutilizar su código, marca ni interfaz.
- Comparación funcional ampliada de gestión documental, solicitudes de firma y soporte con SLA; enlaces corregidos a la documentación oficial de Odoo 19. La licencia de cada app sigue pendiente donde no hay manifiesto comprobado.
- El análisis de Odoo 19 amplía el mapa de Calendar y Discuss, y verifica sus manifiestos Community LGPL-3 junto con sus dependencias declaradas.
- El análisis funcional de Odoo 19 agrega una ficha de alquiler de equipos: disponibilidad por periodo, custodia por serie, recogida/devolución, depósitos, cargos tardíos y límites para Redmagna.
- El análisis funcional de Odoo 19 agrega el ciclo de gastos: comprobantes, categorías, aprobación, póliza, reembolso y refacturación ligada a ventas, con límites del módulo Redmagna.
- El análisis funcional de Odoo 19 agrega el ciclo de eCommerce: catálogo y precios, acceso B2B, checkout, proveedor de pago, entrega, factura y devolución, con dependencias y licencia del módulo base verificadas.
- El análisis funcional de Odoo 19 agrega el flujo de Punto de Venta: sesión de caja, cobros, cierre, diferencias, devoluciones, impuestos y operación offline, con dependencias Community identificadas.
- El análisis funcional de Odoo 19 agrega el ciclo de Suscripciones: planes y facturación recurrente, renovaciones, ventas adicionales, cierres, cobros fallidos e informes MRR/ARR; la licencia del módulo quedó sin verificar tras revisar la ruta Community.
- La primera ruta implementada de CFDI tipo E se limita a notas ligadas a un solo ingreso timbrado; reembolsos, devoluciones de inventario y otros escenarios fiscales siguen separados o pendientes de política contable.
- La guía del DS720+ incorpora las advertencias de DSM 7.4.1 y los pasos de activación del perfil opcional de recepción de soporte por IMAP.
- Política inicial de reporte responsable de vulnerabilidades.
- SBOM CycloneDX 1.6 reproducible para las ruedas Python bloqueadas en CPython 3.12/Linux x86_64.
- Digest multi-arquitectura fijados para las imágenes oficiales Python y PostgreSQL, con procedimiento documentado para actualizarlos.

### Pendiente antes de un release público

- Ejecutar y documentar la validación de migraciones y del flujo completo en un entorno Django/PostgreSQL compatible.
- Validar FEL con la cuenta de Redmagna y un CFDI controlado.
- Desplegar en el DS720+ y verificar respaldos y restauración en el NAS.
- Completar SBOM de imágenes Docker y revisar avisos de dependencias nativas e imágenes base.
- Publicar el repositorio y habilitar un canal privado de reporte de vulnerabilidades.
