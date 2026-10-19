"""Offline structural and payables checks for supplier CFDI 4.0 XML."""

import base64
import binascii
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from lxml import etree

from billing.fiscal.validator import CFDIValidationError, require_valid_cfdi_xml
from billing.fiscal.cfdi40 import CFDISigningError, _cadena_transform, _certificate_number, _load_certificate

from .models import SupplierBill, SupplierBillCFDI


CFDI_NS = "http://www.sat.gob.mx/cfd/4"
TFD_NS = "http://www.sat.gob.mx/TimbreFiscalDigital"
MAX_SUPPLIER_CFDI_BYTES = 5 * 1024 * 1024
CENT = Decimal("0.01")
MAX_EMBEDDED_CERT_BYTES = 256 * 1024


class SupplierCFDIValidationError(ValueError):
    """The supplier XML cannot be safely linked to the registered payable."""


def _money(value, label):
    try:
        amount = Decimal(value or "0").quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise SupplierCFDIValidationError(f"El CFDI contiene un importe inválido en {label}.") from None
    if not amount.is_finite():
        raise SupplierCFDIValidationError(f"El CFDI contiene un importe inválido en {label}.")
    return amount


def _normalize_invoice_number(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())


def _verify_issuer_seal(root, issuer_rfc):
    """Check the issuer RSA seal against the embedded CSD; this is not SAT trust validation."""
    certificate_text = root.get("Certificado", "")
    seal_text = root.get("Sello", "")
    if not certificate_text or not seal_text:
        raise SupplierCFDIValidationError("El CFDI no incluye el certificado y sello digital del emisor.")
    try:
        certificate_data = base64.b64decode(certificate_text, validate=True)
        seal = base64.b64decode(seal_text, validate=True)
        if not certificate_data or len(certificate_data) > MAX_EMBEDDED_CERT_BYTES:
            raise ValueError
        certificate = _load_certificate(certificate_data)
    except (ValueError, binascii.Error, CFDISigningError):
        raise SupplierCFDIValidationError("No se pudo leer el certificado o sello digital del emisor.") from None

    try:
        certificate_number = _certificate_number(certificate)
    except CFDISigningError:
        raise SupplierCFDIValidationError("El certificado incrustado no contiene un número SAT válido.") from None
    if root.get("NoCertificado", "") != certificate_number:
        raise SupplierCFDIValidationError("El número de certificado del CFDI no coincide con el certificado incrustado.")
    serial_values = certificate.subject.get_attributes_for_oid(x509.NameOID.SERIAL_NUMBER)
    certificate_rfcs = re.findall(
        r"(?<![A-Z0-9&Ñ])([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})(?![A-Z0-9])",
        serial_values[0].value.upper() if serial_values else "",
    )
    if issuer_rfc.upper() not in certificate_rfcs:
        raise SupplierCFDIValidationError("El RFC emisor no coincide con el RFC incluido en el certificado del CFDI.")
    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey) or not 1024 <= public_key.key_size <= 4096:
        raise SupplierCFDIValidationError("El certificado del CFDI no contiene una llave RSA válida.")

    try:
        issue_time = datetime.fromisoformat(root.get("Fecha", ""))
        if timezone.is_naive(issue_time):
            issue_time = timezone.make_aware(issue_time, timezone.get_current_timezone())
    except (ValueError, TypeError):
        raise SupplierCFDIValidationError("La fecha del CFDI no se pudo interpretar para verificar la vigencia del certificado.") from None
    if issue_time < certificate.not_valid_before_utc or issue_time > certificate.not_valid_after_utc:
        raise SupplierCFDIValidationError("El certificado del emisor estaba fuera de vigencia en la fecha del CFDI.")
    try:
        original_string = str(_cadena_transform()(root)).encode("utf-8")
    except etree.XSLTError:
        raise SupplierCFDIValidationError("No se pudo generar la cadena original con el XSLT SAT local.") from None
    try:
        public_key.verify(seal, original_string, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise SupplierCFDIValidationError("El sello digital del emisor no coincide con la cadena original del CFDI.") from None
    except (TypeError, ValueError):
        raise SupplierCFDIValidationError("No se pudo verificar criptográficamente el sello del emisor del CFDI.") from None


def inspect_supplier_cfdi(bill, xml_bytes):
    if not isinstance(xml_bytes, bytes) or not xml_bytes or len(xml_bytes) > MAX_SUPPLIER_CFDI_BYTES:
        raise SupplierCFDIValidationError("Adjunta un CFDI XML de hasta 5 MB.")
    if b"<!DOCTYPE" in xml_bytes.upper():
        raise SupplierCFDIValidationError("El XML no puede declarar un DTD.")
    try:
        require_valid_cfdi_xml(xml_bytes)
    except CFDIValidationError as error:
        raise SupplierCFDIValidationError(str(error)) from None

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as error:
        raise SupplierCFDIValidationError(f"El XML no está bien formado (línea {error.lineno}).") from None
    if root.getroottree().docinfo.doctype:
        raise SupplierCFDIValidationError("El XML no puede declarar un DTD.")
    if root.get("TipoDeComprobante") != "I":
        raise SupplierCFDIValidationError("La cuenta por pagar requiere un CFDI de ingreso tipo I.")
    if root.get("Moneda") != "MXN":
        raise SupplierCFDIValidationError("La cuenta por pagar de esta versión solo admite CFDI en MXN.")
    if _money(root.get("Descuento"), "Descuento") != 0:
        raise SupplierCFDIValidationError("El XML declara un descuento; regístralo y revisa la factura antes de adjuntarlo.")

    issuer = root.find(f"{{{CFDI_NS}}}Emisor")
    receiver = root.find(f"{{{CFDI_NS}}}Receptor")
    supplier_rfc = (bill.supplier.rfc or "").strip().upper()
    issuer_rfc = (issuer.get("Rfc", "") if issuer is not None else "").strip().upper()
    receiver_rfc = (receiver.get("Rfc", "") if receiver is not None else "").strip().upper()
    configured_rfc = (settings.CFDI_ISSUER_RFC or "").strip().upper()
    if not supplier_rfc:
        raise SupplierCFDIValidationError("Captura el RFC del proveedor antes de adjuntar su CFDI.")
    if issuer_rfc != supplier_rfc:
        raise SupplierCFDIValidationError("El RFC emisor del XML no coincide con el proveedor de la factura.")
    _verify_issuer_seal(root, issuer_rfc)
    if not configured_rfc:
        raise SupplierCFDIValidationError("Configura CFDI_ISSUER_RFC para cotejar el receptor del XML.")
    if receiver_rfc != configured_rfc:
        raise SupplierCFDIValidationError("El RFC receptor del XML no coincide con el RFC emisor de Redmagna configurado.")

    try:
        invoice_date = date.fromisoformat(root.get("Fecha", "")[:10])
    except ValueError:
        raise SupplierCFDIValidationError("La fecha del CFDI no es válida.") from None
    if invoice_date != bill.invoice_date:
        raise SupplierCFDIValidationError("La fecha del XML no coincide con la fecha de la factura registrada.")

    xml_folio = f"{root.get('Serie', '')}{root.get('Folio', '')}"
    if xml_folio and _normalize_invoice_number(xml_folio) != _normalize_invoice_number(bill.invoice_number):
        raise SupplierCFDIValidationError("La serie y folio del XML no coinciden con el folio capturado.")

    subtotal = _money(root.get("SubTotal"), "Subtotal")
    total = _money(root.get("Total"), "Total")
    cfdi_taxes = root.find(f"{{{CFDI_NS}}}Impuestos")
    tax_total = _money(cfdi_taxes.get("TotalImpuestosTrasladados") if cfdi_taxes is not None else None, "Impuestos trasladados")
    withholding = _money(cfdi_taxes.get("TotalImpuestosRetenidos") if cfdi_taxes is not None else None, "Impuestos retenidos")
    if withholding != 0:
        raise SupplierCFDIValidationError("La factura declara retenciones, que todavía no están soportadas en cuentas por pagar.")
    if subtotal != bill.subtotal or tax_total != bill.tax_total or total != bill.total:
        raise SupplierCFDIValidationError("Subtotal, impuestos o total del XML no coinciden con la factura capturada.")

    stamps = root.findall(f".//{{{TFD_NS}}}TimbreFiscalDigital")
    if len(stamps) != 1:
        raise SupplierCFDIValidationError("El CFDI debe incluir un solo Timbre Fiscal Digital.")
    stamp = stamps[0]
    required_stamp_fields = ("UUID", "FechaTimbrado", "SelloCFD", "NoCertificadoSAT", "SelloSAT")
    if any(not stamp.get(name, "").strip() for name in required_stamp_fields):
        raise SupplierCFDIValidationError("El Timbre Fiscal Digital no contiene todos los datos requeridos.")
    try:
        cfdi_uuid = uuid.UUID(stamp.get("UUID", ""))
    except (ValueError, AttributeError):
        raise SupplierCFDIValidationError("El UUID del Timbre Fiscal Digital no es válido.") from None
    if SupplierBillCFDI.objects.filter(cfdi_uuid=cfdi_uuid).exists():
        raise SupplierCFDIValidationError("Ese UUID ya está asociado a otra factura de proveedor.")

    return {
        "cfdi_uuid": cfdi_uuid,
        "sha256": sha256(xml_bytes).hexdigest(),
        "issuer_rfc": issuer_rfc,
        "receiver_rfc": receiver_rfc,
        "invoice_number": xml_folio,
        "invoice_date": invoice_date,
        "issuer_seal_verified": True,
        "issuer_seal_verified_at": timezone.now(),
        "subtotal": subtotal,
        "tax_total": tax_total,
        "total": total,
    }


@transaction.atomic
def attach_supplier_bill_cfdi(bill_id, uploaded_by, xml_file):
    bill = SupplierBill.objects.select_for_update().select_related("supplier").get(pk=bill_id)
    if SupplierBillCFDI.objects.filter(supplier_bill=bill).exists():
        raise ValidationError("Esta factura ya tiene un XML CFDI adjunto.")
    position = xml_file.tell() if hasattr(xml_file, "tell") else 0
    xml_bytes = xml_file.read(MAX_SUPPLIER_CFDI_BYTES + 1)
    if hasattr(xml_file, "seek"):
        xml_file.seek(position)
    metadata = inspect_supplier_cfdi(bill, xml_bytes)
    record = SupplierBillCFDI(
        supplier_bill=bill,
        uploaded_by=uploaded_by,
        xsd_validated_at=timezone.now(),
        **metadata,
    )
    record.xml_file.save(f"{metadata['cfdi_uuid']}.xml", ContentFile(xml_bytes), save=False)
    try:
        record.save(force_insert=True)
    except IntegrityError:
        record.xml_file.delete(save=False)
        raise ValidationError("El UUID ya se asoció a otra factura o este registro ya tiene un XML CFDI.") from None
    except Exception:
        record.xml_file.delete(save=False)
        raise
    return record
