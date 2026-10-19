"""SOAP transport for FEL Premium stamping and reference queries.

The caller must provide a reviewed, signed, locally validated CFDI. This
module does not prepare invoice data or infer SAT catalog classifications.
"""

from dataclasses import dataclass
import base64
import binascii
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, pkcs12
from django.conf import settings

from billing.fiscal.cfdi40 import CFDISigningError, _certificate_number
from billing.fiscal.cfdi_payment20 import require_valid_payment_cfdi_xml
from billing.fiscal.validator import CFDIValidationError, require_valid_cfdi_xml


SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SERVICE_NS = "http://tempuri.org/"
SOAP_ACTION = "http://tempuri.org/IWSCFDI33/TimbrarCFDI"
QUERY_SOAP_ACTION = "http://tempuri.org/IWSCFDI33/ConsultarTimbrePorReferencia"
ENDPOINTS = {
    "test": "https://app.fel.mx/WSTimbrado33Test/WSCFDI33.svc",
    "production": "https://www.fel.mx/WSTimbrado33/WSCFDI33.svc",
}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class _NoRedirectHandler(HTTPRedirectHandler):
    """Never forward SOAP credentials or CFDI payloads to a redirect target."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


_FEL_OPENER = build_opener(_NoRedirectHandler)


class FELConfigurationError(RuntimeError):
    """FEL credentials or environment are missing or unsafe."""


class FELTransportError(RuntimeError):
    """The SOAP request did not produce a usable FEL response."""


class FELValidationError(ValueError):
    """The CFDI is not structurally valid and must not be sent to FEL."""


@dataclass(frozen=True)
class FELStampResult:
    succeeded: bool
    response_code: str
    message: str
    xml_content: str
    cfdi_uuid: str
    stamped_at: str
    pdf_base64: str


@dataclass(frozen=True)
class FELQueryResult:
    succeeded: bool
    response_code: str
    message: str
    xml_content: str
    cfdi_uuid: str
    stamped_at: str
    status: str
    pdf_base64: str = ""


@dataclass(frozen=True)
class FELCancellationResult:
    response_code: str
    message: str
    receipt_xml: str
    status: str


@dataclass(frozen=True)
class FELCancellationRequest:
    endpoint: str
    action: str
    envelope: bytes


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _first_text(element, name):
    if element is None:
        return ""
    for child in element.iter():
        if _local_name(child.tag) == name:
            return child.text or ""
    return ""


def _build_envelope(username, password, cfdi_xml, reference):
    envelope = ET.Element(ET.QName(SOAP_NS, "Envelope"))
    body = ET.SubElement(envelope, ET.QName(SOAP_NS, "Body"))
    operation = ET.SubElement(body, ET.QName(SERVICE_NS, "TimbrarCFDI"))
    for name, value in (
        ("usuario", username),
        ("password", password),
        ("cadenaXML", cfdi_xml),
        ("referencia", reference),
    ):
        ET.SubElement(operation, ET.QName(SERVICE_NS, name)).text = value
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def _build_query_envelope(username, password, reference):
    envelope = ET.Element(ET.QName(SOAP_NS, "Envelope"))
    body = ET.SubElement(envelope, ET.QName(SOAP_NS, "Body"))
    operation = ET.SubElement(body, ET.QName(SERVICE_NS, "ConsultarTimbrePorReferencia"))
    for name, value in (("usuario", username), ("password", password), ("referencia", reference)):
        ET.SubElement(operation, ET.QName(SERVICE_NS, name)).text = value
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def _build_query_uuid_envelope(username, password, cfdi_uuid):
    envelope = ET.Element(ET.QName(SOAP_NS, "Envelope"))
    body = ET.SubElement(envelope, ET.QName(SOAP_NS, "Body"))
    operation = ET.SubElement(body, ET.QName(SERVICE_NS, "ConsultarComplementoTimbre"))
    for name, value in (("usuario", username), ("password", password), ("UUID", cfdi_uuid)):
        ET.SubElement(operation, ET.QName(SERVICE_NS, name)).text = value
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def _build_cancel_envelope(username, password, issuer_rfc, detail, pfx_base64, pfx_password):
    envelope = ET.Element(ET.QName(SOAP_NS, "Envelope"))
    body = ET.SubElement(envelope, ET.QName(SOAP_NS, "Body"))
    operation = ET.SubElement(body, ET.QName(SERVICE_NS, "CancelarCFDI"))
    for name, value in (("usuario", username), ("password", password), ("rFCEmisor", issuer_rfc)):
        ET.SubElement(operation, ET.QName(SERVICE_NS, name)).text = value
    items = ET.SubElement(operation, ET.QName(SERVICE_NS, "listaCFDI"))
    item = ET.SubElement(items, ET.QName(SERVICE_NS, "DetalleCFDICancelacion"))
    for name, value in detail.items():
        ET.SubElement(item, ET.QName(SERVICE_NS, name)).text = str(value)
    ET.SubElement(operation, ET.QName(SERVICE_NS, "clavePrivada_Base64")).text = pfx_base64
    ET.SubElement(operation, ET.QName(SERVICE_NS, "passwordClavePrivada")).text = pfx_password
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def _require_cancellation_certificate_matches_xml(pfx_base64, pfx_password, root):
    """Ensure the cancellation PFX contains the exact CSD that sealed this CFDI."""
    if len(pfx_base64) > 1_000_000:
        raise FELConfigurationError("El PFX de cancelación excede el tamaño permitido.")
    certificate_text = root.attrib.get("Certificado", "")
    if not certificate_text or len(certificate_text) > 350_000:
        raise FELConfigurationError("El CFDI no contiene un certificado CSD válido para cotejar la cancelación.")
    try:
        pfx_data = base64.b64decode("".join(pfx_base64.split()), validate=True)
        private_key, pfx_certificate, _ = pkcs12.load_key_and_certificates(pfx_data, pfx_password.encode("utf-8"))
        certificate_data = base64.b64decode("".join(certificate_text.split()), validate=True)
        cfdi_certificate = x509.load_der_x509_certificate(certificate_data)
    except (binascii.Error, ValueError, TypeError, UnicodeEncodeError, UnsupportedAlgorithm):
        raise FELConfigurationError("El PFX o el certificado del CFDI no se pudo validar localmente.") from None

    if private_key is None or pfx_certificate is None:
        raise FELConfigurationError("El PFX de cancelación debe contener la llave privada y el certificado CSD.")
    if pfx_certificate.public_bytes(Encoding.DER) != cfdi_certificate.public_bytes(Encoding.DER):
        raise FELConfigurationError("El certificado del PFX no coincide con el CSD que selló este CFDI.")
    key_public = private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    certificate_public = pfx_certificate.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if key_public != certificate_public:
        raise FELConfigurationError("La llave privada del PFX no corresponde al certificado CSD del CFDI.")
    try:
        pfx_certificate_number = _certificate_number(pfx_certificate)
    except CFDISigningError:
        raise FELConfigurationError("El certificado CSD del PFX no contiene un número SAT válido.") from None
    if pfx_certificate_number != root.attrib.get("NoCertificado", ""):
        raise FELConfigurationError("El número de certificado del PFX no coincide con el CFDI.")


def _send_soap(endpoint, action, envelope, timeout):
    request = Request(
        endpoint,
        data=envelope,
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{action}"'},
        method="POST",
    )
    try:
        with _FEL_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise FELTransportError(f"FEL respondió con HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise FELTransportError("No se pudo confirmar la respuesta de FEL.") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise FELTransportError("La respuesta de FEL excede el tamaño permitido.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise FELTransportError("FEL devolvió una respuesta SOAP que no se pudo interpretar.") from None

    fault = next((node for node in root.iter() if _local_name(node.tag) == "Fault"), None)
    if fault is not None:
        message = _first_text(fault, "faultstring") or "Fallo SOAP sin detalle."
        raise FELTransportError(f"FEL devolvió un fallo SOAP: {message[:300]}")
    return root


def _credentials_and_endpoint():
    environment = getattr(settings, "FEL_ENVIRONMENT", "test")
    if environment not in ENDPOINTS:
        raise FELConfigurationError("FEL_ENVIRONMENT debe ser 'test' o 'production'.")
    if environment == "production" and not getattr(settings, "FEL_ALLOW_PRODUCTION", False):
        raise FELConfigurationError("El timbrado productivo está deshabilitado en esta instalación.")

    username = getattr(settings, "FEL_TIMBRADO_USER", "")
    password = getattr(settings, "FEL_TIMBRADO_PASSWORD", "")
    if not username or not password:
        raise FELConfigurationError("Configura FEL_TIMBRADO_USER y FEL_TIMBRADO_PASSWORD en el entorno del servidor.")
    if not 12 <= len(username.strip()) <= 13:
        raise FELConfigurationError("El usuario de timbrado FEL debe tener entre 12 y 13 caracteres, según el manual de FEL Premium.")
    if len(password) < 6:
        raise FELConfigurationError("La contraseña del usuario de timbrado FEL debe tener al menos 6 caracteres, según el manual de FEL Premium.")
    return ENDPOINTS[environment], username.strip(), password


def validate_fel_configuration():
    """Fail before changing document state if endpoint or credentials are absent."""
    _credentials_and_endpoint()


def stamp_cfdi(cfdi_xml, reference, timeout=30):
    """Send a prebuilt CFDI XML to FEL and return only normalized response data.

    Credentials are read from process settings and never included in the
    returned result or error messages. Production is opt-in via two settings.
    """
    if not cfdi_xml or not cfdi_xml.lstrip().startswith("<"):
        raise FELConfigurationError("Se requiere el XML CFDI previamente generado.")
    if not reference or len(reference) < 4:
        raise FELConfigurationError("La referencia de FEL debe tener al menos cuatro caracteres.")
    try:
        xml_bytes = cfdi_xml if isinstance(cfdi_xml, bytes) else cfdi_xml.encode("utf-8")
        if b"http://www.sat.gob.mx/Pagos20" in xml_bytes:
            require_valid_payment_cfdi_xml(cfdi_xml)
        else:
            require_valid_cfdi_xml(cfdi_xml)
    except CFDIValidationError as error:
        raise FELValidationError(str(error)) from error
    endpoint, username, password = _credentials_and_endpoint()

    root = _send_soap(endpoint, SOAP_ACTION, _build_envelope(username, password, cfdi_xml, reference), timeout)

    result = next((node for node in root.iter() if _local_name(node.tag) == "TimbrarCFDIResult"), None)
    if result is None:
        raise FELTransportError("La respuesta de FEL no contiene TimbrarCFDIResult.")

    success = _first_text(result, "OperacionExitosa").strip().lower() == "true"
    timbre = next((node for node in result.iter() if _local_name(node.tag) == "Timbre"), None)
    return FELStampResult(
        succeeded=success,
        response_code=_first_text(result, "CodigoRespuesta"),
        message=(_first_text(result, "MensajeErrorDetallado") or _first_text(result, "MensajeError"))[:1000],
        xml_content=_first_text(result, "XMLResultado") if success else "",
        cfdi_uuid=_first_text(timbre, "UUID") if success else "",
        stamped_at=_first_text(timbre, "FechaTimbrado") if success else "",
        pdf_base64=_first_text(result, "PDFResultado") if success else "",
    )


def query_stamp_by_reference(reference, timeout=30):
    """Look up a previously submitted FEL reference without consuming a stamp."""
    endpoint, username, password = _credentials_and_endpoint()
    if not reference or len(reference) < 4:
        raise FELConfigurationError("La referencia FEL debe tener al menos cuatro caracteres.")
    root = _send_soap(
        endpoint, QUERY_SOAP_ACTION,
        _build_query_envelope(username, password, reference), timeout,
    )
    result = next((node for node in root.iter() if _local_name(node.tag) == "ConsultarTimbrePorReferenciaResult"), None)
    if result is None:
        raise FELTransportError("La respuesta de FEL no contiene ConsultarTimbrePorReferenciaResult.")

    success = _first_text(result, "OperacionExitosa").strip().lower() == "true"
    timbre = next((node for node in result.iter() if _local_name(node.tag) == "Timbre"), None)
    return FELQueryResult(
        succeeded=success,
        response_code=_first_text(result, "CodigoRespuesta"),
        message=(_first_text(result, "MensajeErrorDetallado") or _first_text(result, "MensajeError"))[:1000],
        xml_content=_first_text(result, "XMLResultado") if success else "",
        cfdi_uuid=_first_text(timbre, "UUID") if success else "",
        stamped_at=_first_text(timbre, "FechaTimbrado") if success else "",
        status=_first_text(timbre, "Estado") if success else "",
        pdf_base64=_first_text(result, "PDFResultado") if success else "",
    )


def query_cancellation_status(cfdi_uuid, timeout=30):
    """Read the current FEL/SAT state of a previously stamped CFDI by UUID."""
    if getattr(settings, "FEL_ENVIRONMENT", "test") != "production" or not getattr(settings, "FEL_ALLOW_PRODUCTION", False):
        raise FELConfigurationError("La consulta de cancelación requiere la conexión productiva configurada para consultar el UUID real.")
    endpoint, username, password = _credentials_and_endpoint()
    root = _send_soap(
        endpoint,
        "http://tempuri.org/IWSCFDI33/ConsultarComplementoTimbre",
        _build_query_uuid_envelope(username, password, str(cfdi_uuid).replace("-", "")),
        timeout,
    )
    result = next((node for node in root.iter() if _local_name(node.tag) == "ConsultarComplementoTimbreResult"), None)
    if result is None:
        raise FELTransportError("La respuesta de FEL no contiene ConsultarComplementoTimbreResult.")
    success = _first_text(result, "OperacionExitosa").strip().lower() == "true"
    timbre = next((node for node in result.iter() if _local_name(node.tag) == "Timbre"), None)
    return FELQueryResult(
        succeeded=success,
        response_code=_first_text(result, "CodigoRespuesta"),
        message=(_first_text(result, "MensajeErrorDetallado") or _first_text(result, "MensajeError"))[:1000],
        xml_content="",
        cfdi_uuid=_first_text(timbre, "UUID") if success else "",
        stamped_at=_first_text(timbre, "FechaTimbrado") if success else "",
        status=_first_text(timbre, "Estado") if success else "",
    )


def prepare_cancellation_request(document, reason, replacement_uuid=None):
    """Validate all local prerequisites and build the transient FEL request."""
    if not getattr(settings, "FEL_ALLOW_CANCELLATION", False):
        raise FELConfigurationError("La cancelación fiscal está deshabilitada; habilítala explícitamente al configurar el servidor.")
    if getattr(settings, "FEL_ENVIRONMENT", "test") != "production" or not getattr(settings, "FEL_ALLOW_PRODUCTION", False):
        raise FELConfigurationError("La cancelación de FEL llega al SAT y no cuenta con sandbox; configura producción y habilita FEL_ALLOW_PRODUCTION explícitamente.")
    endpoint, username, password = _credentials_and_endpoint()
    pfx_base64 = getattr(settings, "FEL_CANCEL_PFX_BASE64", "")
    pfx_password = getattr(settings, "FEL_CANCEL_PFX_PASSWORD", "")
    if not pfx_base64 or not pfx_password:
        raise FELConfigurationError("Configura FEL_CANCEL_PFX_BASE64 y FEL_CANCEL_PFX_PASSWORD como secretos del servidor.")
    if not document.cfdi_uuid or not document.xml_content:
        raise FELConfigurationError("El CFDI timbrado no contiene UUID y XML para sustentar la cancelación.")
    try:
        root = ET.fromstring(document.xml_content)
    except ET.ParseError:
        raise FELConfigurationError("No se pudo leer el XML timbrado conservado para la cancelación.") from None
    issuer_rfc = root.attrib.get("Rfc", "").strip().upper()
    recipient_rfc = document.recipient_rfc.strip().upper()
    total = root.attrib.get("Total", "")
    if not issuer_rfc or not recipient_rfc or not total:
        raise FELConfigurationError("El CFDI conservado no incluye RFC emisor, RFC receptor e importe total.")
    if issuer_rfc != getattr(settings, "CFDI_ISSUER_RFC", "").strip().upper():
        raise FELConfigurationError("El RFC emisor del XML no coincide con el emisor configurado.")
    _require_cancellation_certificate_matches_xml(pfx_base64, pfx_password, root)
    detail = {
        "FolioSustitucion": str(replacement_uuid or ""),
        "Motivo": reason,
        "RFCReceptor": recipient_rfc,
        "Total": total,
        "UUID": str(document.cfdi_uuid).upper(),
    }
    if reason != "01":
        detail.pop("FolioSustitucion")

    return FELCancellationRequest(endpoint, "http://tempuri.org/IWSCFDI33/CancelarCFDI", _build_cancel_envelope(username, password, issuer_rfc, detail, pfx_base64, pfx_password))


def cancel_cfdi(request, timeout=45):
    """Send one irreversible SAT cancellation request through FEL Premium."""
    root_response = _send_soap(request.endpoint, request.action, request.envelope, timeout)
    result = next((node for node in root_response.iter() if _local_name(node.tag) == "CancelarCFDIResult"), None)
    if result is None:
        raise FELTransportError("La respuesta de FEL no contiene CancelarCFDIResult.")
    detail_result = next((node for node in result.iter() if _local_name(node.tag) in {"DetalleCancelacion", "DetalleCancelacionResult"}), None)
    code = _first_text(detail_result or result, "CodigoResultado") or _first_text(result, "CodigoRespuesta")
    message = (_first_text(detail_result or result, "MensajeResultado") or _first_text(result, "MensajeErrorDetallado") or _first_text(result, "MensajeError"))[:1000]
    receipt = _first_text(result, "XMLAcuse")
    status = "cancelled" if code in {"201", "202", "CANC103", "CANC107", "CANC109", "CANC110", "CANC111"} else "pending" if code in {"", "CANC105", "CANC106"} else "rejected"
    return FELCancellationResult(code, message, receipt, status)
