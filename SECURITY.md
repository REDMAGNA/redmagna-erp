# Política de seguridad

## Versiones con soporte

El ERP está en desarrollo y todavía no tiene releases públicos. Mientras no se publique una versión estable, la rama de desarrollo es la única línea que recibe correcciones; no se promete soporte de seguridad para paquetes ZIP o imágenes anteriores.

## Cómo reportar una vulnerabilidad

No publiques detalles de una vulnerabilidad en un issue, foro o comentario público. Cuando el proyecto esté alojado en GitHub, utiliza **Report a vulnerability** en la pestaña **Security** para abrir un aviso privado. Si esa opción no está habilitada, contacta en privado a la persona mantenedora indicada en el perfil del repositorio y pide un canal seguro; no adjuntes secretos, llaves privadas, contraseñas, XML reales de clientes ni datos personales.

Incluye, si puedes hacerlo sin exponer datos sensibles:

- Componente y versión afectados.
- Pasos para reproducir el problema en un entorno de prueba.
- Impacto observado y condiciones necesarias para explotarlo.
- Una forma segura de contactarte para coordinar la corrección.

La persona mantenedora confirmará la recepción por el mismo canal cuando sea posible, analizará el reporte y coordinará una corrección y su divulgación contigo. No hay un plazo de respuesta garantizado mientras el proyecto siga sin un equipo de mantenimiento formal.

## Despliegues propios

Las instalaciones deben restringir el acceso al NAS, mantener DSM, Container Manager y las imágenes actualizados, usar contraseñas únicas y proteger los secretos y respaldos. No compartas públicamente archivos `.env`, credenciales FEL, certificados o llaves CSD, XML fiscales, bases de datos ni archivos de medios. Consulta la [guía de Synology](docs/guia-synology-ds720-redmagna-erp.md) antes de exponer el servicio fuera de la red local.
