"""Build and sign the supported CFDI 4.0 income-document subset."""

import base64
import re
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from lxml import etree

from .validator import require_valid_cfdi_xml


CFDI_NS = "http://www.sat.gob.mx/cfd/4"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
CFDI = f"{{{CFDI_NS}}}"
CHAIN_XSLT = Path(__file__).with_name("sat") / "4" / "cadenaoriginal_4_0" / "cadenaoriginal_4_0.xslt"
MAX_CERT_BYTES = 256 * 1024


class CFDISigningError(ValueError):
    """The local CSD is missing, invalid, or does not match the CFDI issuer."""


def _secret_file(path_setting, setting_name):
    path = Path(getattr(settings, setting_name, ""))
    if not str(path) or not path.is_file():
        raise CFDISigningError(f"No se encontró el archivo protegido configurado para {path_setting}.")
    data = path.read_bytes()
    if not data or len(data) > MAX_CERT_BYTES:
        raise CFDISigningError(f"El archivo configurado para {path_setting} está vacío o excede el tamaño permitido.")
    return data


def _load_certificate(data):
    try:
        return x509.load_der_x509_certificate(data)
    except ValueError:
        try:
            return x509.load_pem_x509_certificate(data)
        except ValueError as error:
            raise CFDISigningError("El certificado CSD no se pudo leer como DER o PEM.") from error


def _load_private_key(data, password):
    for loader in (serialization.load_der_private_key, serialization.load_pem_private_key):
        try:
            return loader(data, password=password)
        except (ValueError, TypeError):
            continue
    raise CFDISigningError("La llave privada CSD no se pudo abrir; verifica el archivo y su contraseña protegida.")


def _certificate_number(certificate):
    raw = certificate.serial_number.to_bytes(max(1, (certificate.serial_number.bit_length() + 7) // 8), "big")
    try:
        number = raw.decode("ascii").strip("\x00 ")
    except UnicodeDecodeError:
        number = str(certificate.serial_number).zfill(20)
    if not re.fullmatch(r"\d{20}", number):
        raise CFDISigningError("El certificado CSD no contiene un número de certificado SAT de 20 dígitos reconocible.")
    return number


def _load_csd(issuer_rfc):
    certificate_data = _secret_file("CFDI_CSD_CERT_PATH", "CFDI_CSD_CERT_PATH")
    key_data = _secret_file("CFDI_CSD_KEY_PATH", "CFDI_CSD_KEY_PATH")
    password_path = Path(getattr(settings, "CFDI_CSD_PASSWORD_FILE", ""))
    if not str(password_path) or not password_path.is_file():
        raise CFDISigningError("No se encontró el archivo protegido de contraseña del CSD.")
    password = password_path.read_bytes().rstrip(b"\r\n")
    if not password:
        raise CFDISigningError("El archivo protegido de contraseña del CSD está vacío.")
    certificate = _load_certificate(certificate_data)
    private_key = _load_private_key(key_data, password)
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
        raise CFDISigningError("El CSD debe contener una llave RSA de al menos 2048 bits.")
    if private_key.public_key().public_numbers() != certificate.public_key().public_numbers():
        raise CFDISigningError("La llave privada CSD no corresponde al certificado configurado.")
    now = timezone.now()
    if now < certificate.not_valid_before_utc or now > certificate.not_valid_after_utc:
        raise CFDISigningError("El certificado CSD está fuera de su periodo de vigencia.")
    serial_values = certificate.subject.get_attributes_for_oid(x509.NameOID.SERIAL_NUMBER)
    if serial_values and issuer_rfc.upper() not in serial_values[0].value.upper():
        raise CFDISigningError("El RFC configurado para el emisor no coincide con el RFC del certificado CSD.")
    der_certificate = certificate.public_bytes(serialization.Encoding.DER)
    return certificate, private_key, _certificate_number(certificate), der_certificate


@lru_cache(maxsize=1)
def _cadena_transform():
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    stylesheet = etree.parse(str(CHAIN_XSLT), parser)
    return etree.XSLT(stylesheet)


def _decimal(value, places=2):
    number = Decimal(str(value))
    return f"{number:.{places}f}"


def _build_unsigned(snapshot, certificate_number, certificate_data):
    document_type = snapshot.get("document_type")
    if document_type not in {"I", "E"} or snapshot.get("cfdi_version") != "4.0":
        raise CFDISigningError("La generación inicial solo admite CFDI 4.0 de ingreso o egreso.")
    if snapshot.get("exportation") == "02":
        raise CFDISigningError("La clave de exportación 02 requiere el Complemento de Comercio Exterior; no se generó el XML.")
    issuer, recipient = snapshot.get("issuer", {}), snapshot.get("recipient", {})
    required = [issuer.get("rfc"), issuer.get("legal_name"), issuer.get("fiscal_regime"), snapshot.get("place_of_issue_postal_code"), recipient.get("rfc"), recipient.get("legal_name"), recipient.get("fiscal_regime"), recipient.get("fiscal_postal_code"), recipient.get("cfdi_use")]
    if not all(required):
        raise CFDISigningError("El snapshot no contiene todos los datos fiscales obligatorios de emisor y receptor.")
    if document_type == "E" and not (snapshot.get("related_cfdi_uuid") and snapshot.get("relation_type")):
        raise CFDISigningError("El CFDI de egreso requiere tipo de relación y UUID del ingreso relacionado.")
    now_local = timezone.localtime(timezone.now())
    issue_date = datetime.fromisoformat(snapshot.get("issue_date", "")).date()
    if issue_date != now_local.date():
        raise CFDISigningError("La fecha de la factura debe ser la fecha local de hoy para generar un CFDI nuevo.")
    timestamp = now_local.strftime("%Y-%m-%dT%H:%M:%S")
    root = etree.Element(CFDI + "Comprobante", nsmap={"cfdi": CFDI_NS, "xsi": XSI_NS})
    root.set("Version", "4.0")
    root.set("Fecha", timestamp)
    root.set("Sello", "")
    root.set("NoCertificado", certificate_number)
    root.set("Certificado", base64.b64encode(certificate_data).decode("ascii"))
    root.set("SubTotal", _decimal(snapshot["subtotal"]))
    discount_total = Decimal(snapshot.get("discount_total", "0.00"))
    if discount_total > 0:
        root.set("Descuento", _decimal(discount_total))
    root.set("Moneda", snapshot.get("currency", "MXN"))
    root.set("Total", _decimal(snapshot["total"]))
    root.set("TipoDeComprobante", document_type)
    root.set("Exportacion", snapshot["exportation"])
    root.set("MetodoPago", snapshot["payment_method"])
    root.set("LugarExpedicion", snapshot["place_of_issue_postal_code"])
    root.set(f"{{{XSI_NS}}}schemaLocation", f"{CFDI_NS} http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd")
    if snapshot.get("payment_method") == "PUE":
        root.set("FormaPago", snapshot["payment_form"])
    if document_type == "E":
        related = etree.SubElement(root, CFDI + "CfdiRelacionados", TipoRelacion=snapshot["relation_type"])
        etree.SubElement(related, CFDI + "CfdiRelacionado", UUID=snapshot["related_cfdi_uuid"])
    issuer_node = etree.SubElement(root, CFDI + "Emisor")
    issuer_node.set("Rfc", issuer["rfc"])
    issuer_node.set("Nombre", issuer["legal_name"])
    issuer_node.set("RegimenFiscal", issuer["fiscal_regime"])
    receiver = etree.SubElement(root, CFDI + "Receptor")
    receiver.set("Rfc", recipient["rfc"])
    receiver.set("Nombre", recipient["legal_name"])
    receiver.set("DomicilioFiscalReceptor", recipient["fiscal_postal_code"])
    receiver.set("RegimenFiscalReceptor", recipient["fiscal_regime"])
    receiver.set("UsoCFDI", recipient["cfdi_use"])
    concepts_node = etree.SubElement(root, CFDI + "Conceptos")
    tax_groups = {}
    for item in snapshot["concepts"]:
        concept = etree.SubElement(concepts_node, CFDI + "Concepto")
        concept.set("ClaveProdServ", item["product_service_key"])
        if item.get("catalog_product_sku"):
            concept.set("NoIdentificacion", item["catalog_product_sku"][:100])
        concept.set("Cantidad", item["quantity"])
        concept.set("ClaveUnidad", item["unit_key"])
        concept.set("Descripcion", item["description"][:1000])
        concept.set("ValorUnitario", _decimal(item["unit_price"]))
        concept.set("Importe", _decimal(item["amount"]))
        discount = Decimal(item.get("discount", "0.00"))
        if discount > 0:
            concept.set("Descuento", _decimal(discount))
        concept.set("ObjetoImp", item["tax_object"])
        if item["tax_object"] == "02":
            tax_rate = Decimal(item["vat_rate_percent"])
            tax_factor = item.get("tax_factor", "Tasa")
            if tax_factor == "Exento" and tax_rate != 0:
                raise CFDISigningError("Un concepto exento no puede tener una tasa de IVA distinta de cero.")
            transfers = etree.SubElement(etree.SubElement(concept, CFDI + "Impuestos"), CFDI + "Traslados")
            transfer = etree.SubElement(transfers, CFDI + "Traslado")
            tax_base = Decimal(item.get("tax_base", str(Decimal(item["amount"]) - discount)))
            transfer.set("Base", _decimal(tax_base))
            transfer.set("Impuesto", "002")
            transfer.set("TipoFactor", tax_factor)
            if tax_factor == "Tasa":
                rate = (tax_rate / Decimal("100")).quantize(Decimal("0.000001"))
                transfer.set("TasaOCuota", f"{rate:.6f}")
                transfer.set("Importe", _decimal(item["vat_amount"]))
                key = f"002|Tasa|{rate:.6f}"
                prior = tax_groups.get(key, Decimal("0.00"))
                tax_groups[key] = prior + Decimal(item["vat_amount"])
            elif tax_factor != "Exento":
                raise CFDISigningError("Solo se admiten IVA trasladado tipo Tasa o Exento.")
    if tax_groups:
        taxes_node = etree.SubElement(root, CFDI + "Impuestos")
        taxes_node.set("TotalImpuestosTrasladados", _decimal(sum(tax_groups.values(), Decimal("0.00"))))
        transfers = etree.SubElement(taxes_node, CFDI + "Traslados")
        for key, amount in sorted(tax_groups.items()):
            tax, factor, rate = key.split("|")
            transfer = etree.SubElement(transfers, CFDI + "Traslado")
            transfer.set("Base", _decimal(sum(Decimal(item.get("tax_base", str(Decimal(item["amount"]) - Decimal(item.get("discount", "0.00"))))) for item in snapshot["concepts"] if item["tax_object"] == "02" and item.get("tax_factor", "Tasa") == factor and (Decimal(item["vat_rate_percent"]) / Decimal("100")).quantize(Decimal("0.000001")) == Decimal(rate))))
            transfer.set("Impuesto", tax)
            transfer.set("TipoFactor", factor)
            transfer.set("TasaOCuota", rate)
            transfer.set("Importe", _decimal(amount))
    return root


def build_signed_income_cfdi(snapshot):
    """Generate an offline-signed CFDI request using the mounted SAT CSD files."""
    issuer_rfc = snapshot.get("issuer", {}).get("rfc", "")
    certificate, private_key, certificate_number, certificate_data = _load_csd(issuer_rfc)
    root = _build_unsigned(snapshot, certificate_number, certificate_data)
    try:
        cadena = str(_cadena_transform()(root)).encode("utf-8")
        sello = private_key.sign(cadena, padding.PKCS1v15(), hashes.SHA256())
    except etree.XSLTError as error:
        raise CFDISigningError("No se pudo producir la cadena original con el XSLT oficial local del SAT.") from error
    root.set("Sello", base64.b64encode(sello).decode("ascii"))
    xml_content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False).decode("utf-8")
    require_valid_cfdi_xml(xml_content)
    return xml_content


def build_signed_credit_note_cfdi(snapshot):
    """Generate an offline-signed CFDI 4.0 egreso using the mounted SAT CSD."""
    if snapshot.get("document_type") != "E":
        raise CFDISigningError("El snapshot no corresponde a un CFDI de egreso.")
    return build_signed_income_cfdi(snapshot)
