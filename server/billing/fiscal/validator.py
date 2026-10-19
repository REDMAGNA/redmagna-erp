"""Offline structural validation against the SAT CFDI 4.0 XSD."""

from functools import lru_cache
from pathlib import Path

from lxml import etree


SAT_SCHEMA_PATH = Path(__file__).with_name("sat") / "4" / "cfdv40.xsd"
MAX_CFDI_BYTES = 5 * 1024 * 1024
CFDI_NAMESPACE = "http://www.sat.gob.mx/cfd/4"


class CFDIValidationError(ValueError):
    """The XML is malformed or fails the bundled SAT structural schema."""


@lru_cache(maxsize=1)
def _schema():
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    schema_document = etree.parse(str(SAT_SCHEMA_PATH), parser)
    return etree.XMLSchema(schema_document)


def validate_cfdi_xml(xml_content):
    """Return SAT XSD errors for one CFDI 4.0 XML; never fetches schemas remotely."""
    if isinstance(xml_content, str):
        data = xml_content.encode("utf-8")
    elif isinstance(xml_content, bytes):
        data = xml_content
    else:
        raise CFDIValidationError("El CFDI debe recibirse como texto XML o bytes.")
    if not data or len(data) > MAX_CFDI_BYTES:
        raise CFDIValidationError("El XML CFDI está vacío o excede el tamaño permitido.")

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    try:
        document = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as error:
        raise CFDIValidationError(f"El XML CFDI no está bien formado (línea {error.lineno}).") from None
    if document.tag != f"{{{CFDI_NAMESPACE}}}Comprobante" or document.get("Version") != "4.0":
        raise CFDIValidationError("Se requiere un elemento cfdi:Comprobante en versión 4.0.")

    schema = _schema()
    if schema.validate(document):
        return []
    return [
        {"line": error.line, "message": error.message[:500]}
        for error in list(schema.error_log)[-20:]
    ]


def require_valid_cfdi_xml(xml_content):
    errors = validate_cfdi_xml(xml_content)
    if errors:
        details = "; ".join(f"línea {error['line']}: {error['message']}" for error in errors)
        raise CFDIValidationError(f"El XML no cumple el XSD CFDI 4.0 del SAT: {details}")
    return xml_content
