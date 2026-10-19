"""Build and validate the supported CFDI 4.0 / Pagos 2.0 receipt subset."""

import base64
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.utils import timezone
from lxml import etree

from .cfdi40 import (
    CFDI,
    CFDI_NS,
    XSI_NS,
    _cadena_transform,
    _decimal,
    _load_csd,
)
from .validator import CFDIValidationError, MAX_CFDI_BYTES


PAGOS_NS = "http://www.sat.gob.mx/Pagos20"
PAGOS = f"{{{PAGOS_NS}}}"
PAYMENT_CFDI_SCHEMA_PATH = Path(__file__).with_name("sat") / "Pagos" / "cfdi40-pagos20.xsd"
SAT_SCHEMA_LOCATION = (
    f"{CFDI_NS} http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd "
    f"{PAGOS_NS} http://www.sat.gob.mx/sitio_internet/cfd/Pagos/Pagos20.xsd"
)
IVA_TOTALS = {
    ("002", "Tasa", "0.160000"): ("TotalTrasladosBaseIVA16", "TotalTrasladosImpuestoIVA16"),
    ("002", "Tasa", "0.080000"): ("TotalTrasladosBaseIVA8", "TotalTrasladosImpuestoIVA8"),
    ("002", "Tasa", "0.000000"): ("TotalTrasladosBaseIVA0", "TotalTrasladosImpuestoIVA0"),
    ("002", "Exento", ""): ("TotalTrasladosBaseIVAExento", ""),
}


class PaymentCFDIError(ValueError):
    """The payment snapshot cannot be represented in the supported SAT subset."""


@lru_cache(maxsize=1)
def _payment_cfdi_schema():
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    return etree.XMLSchema(etree.parse(str(PAYMENT_CFDI_SCHEMA_PATH), parser))


def require_valid_payment_cfdi_xml(xml_content):
    """Validate the CFDI 4.0 envelope and its Pagos 2.0 subtree offline."""
    if isinstance(xml_content, str):
        data = xml_content.encode("utf-8")
    elif isinstance(xml_content, bytes):
        data = xml_content
    else:
        raise CFDIValidationError("El CFDI de pago debe recibirse como texto XML o bytes.")
    if not data or len(data) > MAX_CFDI_BYTES:
        raise CFDIValidationError("El CFDI de pago está vacío o excede el tamaño permitido.")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(data, parser)
    except (etree.XMLSyntaxError, TypeError, ValueError) as error:
        raise CFDIValidationError("El CFDI de pago no se pudo interpretar como XML.") from error
    if root.tag != f"{CFDI}Comprobante" or root.get("Version") != "4.0":
        raise CFDIValidationError("Se requiere un elemento cfdi:Comprobante en versión 4.0.")
    complements = root.findall(f"{CFDI}Complemento/{PAGOS}Pagos")
    if len(complements) != 1:
        raise CFDIValidationError("El CFDI debe contener exactamente un complemento Pagos 2.0.")
    schema = _payment_cfdi_schema()
    if schema.validate(root):
        return []
    details = "; ".join(error.message[:300] for error in list(schema.error_log)[-12:])
    raise CFDIValidationError(f"El CFDI 4.0 con Pagos 2.0 no cumple los XSD oficiales SAT: {details}")


def _payment_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise PaymentCFDIError("El snapshot no contiene una fecha de pago válida.") from error
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return timezone.localtime(parsed).replace(tzinfo=None).isoformat(timespec="seconds")


def _as_decimal(value):
    try:
        return Decimal(str(value))
    except Exception as error:
        raise PaymentCFDIError("El snapshot o el XML del complemento contiene un importe inválido.") from error


def _transfer_values(parent, suffix):
    containers = parent.findall(f"{PAGOS}Impuestos{suffix}")
    if len(containers) > 1:
        raise PaymentCFDIError("El complemento contiene nodos de impuestos duplicados.")
    if not containers:
        return {}
    container = containers[0]
    if container.find(f"{PAGOS}Retenciones{suffix}") is not None:
        raise PaymentCFDIError("El complemento timbrado contiene retenciones fuera del snapshot preparado.")
    transfer_groups = container.findall(f"{PAGOS}Traslados{suffix}")
    if len(transfer_groups) > 1:
        raise PaymentCFDIError("El complemento contiene grupos de traslados duplicados.")
    if not transfer_groups:
        return {}
    values = {}
    for node in transfer_groups[0].findall(f"{PAGOS}Traslado{suffix}"):
        factor = node.get(f"TipoFactor{suffix}", "")
        rate = _as_decimal(node.get(f"TasaOCuota{suffix}")) if factor == "Tasa" else None
        key = (node.get(f"Impuesto{suffix}", ""), factor, rate)
        if key in values:
            raise PaymentCFDIError("El complemento repite un grupo de impuestos.")
        values[key] = {
            "base": _as_decimal(node.get(f"Base{suffix}")),
            "amount": _as_decimal(node.get(f"Importe{suffix}", "0")),
        }
    return values


def _snapshot_tax_values(taxes, base_key, amount_key):
    values = {}
    for tax in taxes:
        factor = tax.get("factor", "")
        rate = _as_decimal(tax["rate"]) if factor == "Tasa" else None
        key = (tax.get("tax_code", ""), factor, rate)
        if key in values:
            raise PaymentCFDIError("El snapshot repite un grupo de impuestos.")
        values[key] = {
            "base": _as_decimal(tax[base_key]),
            "amount": _as_decimal(tax[amount_key]),
        }
    return values


def _require_equal(actual, expected, message):
    if actual != expected:
        raise PaymentCFDIError(message)


def validate_payment_cfdi_snapshot(root, snapshot):
    """Require a returned/timbrado Pagos 2.0 document to match the reviewed snapshot."""
    issuer = root.find(f"{CFDI}Emisor")
    recipient = root.find(f"{CFDI}Receptor")
    payments = root.findall(f"{CFDI}Complemento/{PAGOS}Pagos")
    expected_issuer = snapshot.get("issuer", {})
    expected_recipient = snapshot.get("recipient", {})
    _require_equal(root.get("TipoDeComprobante"), "P", "El XML timbrado no conserva el tipo CFDI Pago.")
    _require_equal(root.get("Moneda"), "XXX", "El CFDI tipo Pago debe conservar Moneda XXX.")
    _require_equal(_as_decimal(root.get("Total", "-1")), Decimal("0"), "El CFDI tipo Pago debe conservar total cero.")
    _require_equal(root.get("LugarExpedicion"), expected_issuer.get("postal_code"), "El código postal del emisor cambió en el CFDI tipo Pago.")
    if issuer is None or recipient is None:
        raise PaymentCFDIError("El CFDI tipo Pago no conserva emisor y receptor.")
    for actual, expected, message in (
        (issuer.get("Rfc"), expected_issuer.get("rfc"), "El RFC emisor cambió en el CFDI tipo Pago."),
        (issuer.get("Nombre"), expected_issuer.get("legal_name"), "La razón social del emisor cambió en el CFDI tipo Pago."),
        (issuer.get("RegimenFiscal"), expected_issuer.get("fiscal_regime"), "El régimen del emisor cambió en el CFDI tipo Pago."),
        (recipient.get("Rfc"), expected_recipient.get("rfc"), "El RFC receptor cambió en el CFDI tipo Pago."),
        (recipient.get("Nombre"), expected_recipient.get("legal_name"), "La razón social del receptor cambió en el CFDI tipo Pago."),
        (recipient.get("DomicilioFiscalReceptor"), expected_recipient.get("fiscal_postal_code"), "El código postal fiscal del receptor cambió en el CFDI tipo Pago."),
        (recipient.get("RegimenFiscalReceptor"), expected_recipient.get("fiscal_regime"), "El régimen del receptor cambió en el CFDI tipo Pago."),
        (recipient.get("UsoCFDI"), "CP01", "El uso CFDI del recibo de pago debe ser CP01."),
    ):
        _require_equal(actual, expected, message)

    if len(payments) != 1 or payments[0].get("Version") != "2.0":
        raise PaymentCFDIError("El CFDI debe conservar un solo complemento Pagos 2.0.")
    pagos = payments[0]
    total_nodes = pagos.findall(f"{PAGOS}Totales")
    payment_nodes = pagos.findall(f"{PAGOS}Pago")
    if len(total_nodes) != 1 or len(payment_nodes) != 1:
        raise PaymentCFDIError("El complemento debe conservar un nodo de Totales y un nodo Pago.")
    total_node, payment = total_nodes[0], payment_nodes[0]
    try:
        expected_date = _payment_timestamp(snapshot["payment_date"])
        expected_amount = _as_decimal(snapshot["payment_amount"])
        _require_equal(payment.get("FechaPago"), expected_date, "La fecha de pago del XML timbrado cambió respecto al snapshot revisado.")
        _require_equal(payment.get("FormaDePagoP"), snapshot.get("payment_form"), "La forma de pago del XML timbrado no coincide con el snapshot revisado.")
        _require_equal(payment.get("MonedaP"), snapshot.get("currency"), "La moneda del XML timbrado no coincide con el snapshot revisado.")
        _require_equal(_as_decimal(payment.get("Monto", "-1")), expected_amount, "El importe del Pago timbrado no coincide con el snapshot revisado.")

        related = snapshot.get("related_documents", [])
        related_nodes = payment.findall(f"{PAGOS}DoctoRelacionado")
        expected_by_uuid = {str(item.get("cfdi_uuid", "")).upper(): item for item in related}
        actual_by_uuid = {str(node.get("IdDocumento", "")).upper(): node for node in related_nodes}
        if not expected_by_uuid or len(expected_by_uuid) != len(related) or len(actual_by_uuid) != len(related_nodes) or set(actual_by_uuid) != set(expected_by_uuid):
            raise PaymentCFDIError("Los CFDI relacionados del XML timbrado no coinciden con el snapshot preparado.")

        for cfdi_uuid, expected in expected_by_uuid.items():
            node = actual_by_uuid[cfdi_uuid]
            for actual, value, message in (
                (node.get("MonedaDR"), expected.get("currency"), "La moneda del documento relacionado cambió."),
                (node.get("NumParcialidad"), str(expected.get("installment_number")), "El número de parcialidad cambió."),
                (node.get("ObjetoImpDR"), expected.get("tax_object"), "El objeto de impuesto del documento relacionado cambió."),
            ):
                _require_equal(actual, value, message)
            for attribute, key in (("ImpSaldoAnt", "previous_balance"), ("ImpPagado", "amount_paid"), ("ImpSaldoInsoluto", "remaining_balance")):
                _require_equal(_as_decimal(node.get(attribute, "-1")), _as_decimal(expected[key]), "Los saldos o el importe pagado del documento relacionado cambiaron.")
            actual_taxes = _transfer_values(node, "DR")
            expected_taxes = _snapshot_tax_values(expected.get("taxes", []), "base_paid", "amount_paid")
            _require_equal(actual_taxes, expected_taxes, "El desglose de impuestos del documento relacionado cambió respecto al snapshot revisado.")

        expected_summary = snapshot.get("taxes_summary", [])
        _require_equal(_transfer_values(payment, "P"), _snapshot_tax_values(expected_summary, "base", "amount"), "El desglose de impuestos del pago cambió respecto al snapshot revisado.")
        expected_totals = {"MontoTotalPagos": expected_amount}
        for tax in expected_summary:
            key = (tax.get("tax_code"), tax.get("factor"), tax.get("rate", ""))
            fields = IVA_TOTALS.get(key)
            if not fields:
                raise PaymentCFDIError("El snapshot contiene un impuesto fuera del subconjunto Pagos admitido.")
            base_field, amount_field = fields
            expected_totals[base_field] = expected_totals.get(base_field, Decimal("0")) + _as_decimal(tax["base"])
            if amount_field:
                expected_totals[amount_field] = expected_totals.get(amount_field, Decimal("0")) + _as_decimal(tax["amount"])
        _require_equal(set(total_node.attrib), set(expected_totals), "Los totales fiscales del complemento no coinciden con el snapshot revisado.")
        for name, expected in expected_totals.items():
            _require_equal(_as_decimal(total_node.get(name)), expected, "Los totales fiscales del complemento no coinciden con el snapshot revisado.")
    except KeyError as error:
        raise PaymentCFDIError("El snapshot de Pagos no conserva todos los datos necesarios para cotejar el XML timbrado.") from error


def _build_unsigned_payment(snapshot):
    if snapshot.get("cfdi_version") != "4.0" or snapshot.get("document_type") != "P" or snapshot.get("complement_version") != "2.0":
        raise PaymentCFDIError("La generación disponible requiere CFDI 4.0 con complemento Pagos 2.0.")
    issuer, recipient = snapshot.get("issuer", {}), snapshot.get("recipient", {})
    required = (
        issuer.get("rfc"), issuer.get("legal_name"), issuer.get("fiscal_regime"), issuer.get("postal_code"),
        recipient.get("rfc"), recipient.get("legal_name"), recipient.get("fiscal_regime"), recipient.get("fiscal_postal_code"),
        snapshot.get("payment_form"), snapshot.get("payment_amount"), snapshot.get("payment_date"),
    )
    related = snapshot.get("related_documents")
    if not all(required) or not isinstance(related, list) or not related:
        raise PaymentCFDIError("El snapshot no conserva todos los datos fiscales del pago y las facturas relacionadas.")
    if snapshot.get("currency") != "MXN" or any(item.get("currency") != "MXN" for item in related):
        raise PaymentCFDIError("La generación inicial de Pagos 2.0 solo admite cobros y CFDI relacionados en MXN.")
    if Decimal(snapshot["payment_amount"]) <= 0:
        raise PaymentCFDIError("El importe del pago debe ser mayor que cero.")
    if Decimal(snapshot["payment_amount"]) != sum((Decimal(item["amount_paid"]) for item in related), Decimal("0.00")):
        raise PaymentCFDIError("La suma pagada de los documentos relacionados no coincide con el importe del cobro.")

    _, private_key, certificate_number, certificate_data = _load_csd(issuer["rfc"])
    now_local = timezone.localtime(timezone.now())
    root = etree.Element(CFDI + "Comprobante", nsmap={"cfdi": CFDI_NS, "xsi": XSI_NS, "pago20": PAGOS_NS})
    for name, value in (
        ("Version", "4.0"),
        ("Fecha", now_local.strftime("%Y-%m-%dT%H:%M:%S")),
        ("Sello", ""),
        ("NoCertificado", certificate_number),
        ("Certificado", base64.b64encode(certificate_data).decode("ascii")),
        ("SubTotal", "0"),
        ("Moneda", "XXX"),
        ("Total", "0"),
        ("TipoDeComprobante", "P"),
        ("Exportacion", "01"),
        ("LugarExpedicion", issuer["postal_code"]),
    ):
        root.set(name, value)
    root.set(f"{{{XSI_NS}}}schemaLocation", SAT_SCHEMA_LOCATION)

    issuer_node = etree.SubElement(root, CFDI + "Emisor")
    for name, value in (("Rfc", issuer["rfc"]), ("Nombre", issuer["legal_name"]), ("RegimenFiscal", issuer["fiscal_regime"])):
        issuer_node.set(name, value)
    receiver = etree.SubElement(root, CFDI + "Receptor")
    for name, value in (
        ("Rfc", recipient["rfc"]),
        ("Nombre", recipient["legal_name"]),
        ("DomicilioFiscalReceptor", recipient["fiscal_postal_code"]),
        ("RegimenFiscalReceptor", recipient["fiscal_regime"]),
        ("UsoCFDI", "CP01"),
    ):
        receiver.set(name, value)
    concepts = etree.SubElement(root, CFDI + "Conceptos")
    concept = etree.SubElement(concepts, CFDI + "Concepto")
    for name, value in (("ClaveProdServ", "84111506"), ("Cantidad", "1"), ("ClaveUnidad", "ACT"), ("Descripcion", "Pago"), ("ValorUnitario", "0"), ("Importe", "0"), ("ObjetoImp", "01")):
        concept.set(name, value)

    complemento = etree.SubElement(root, CFDI + "Complemento")
    pagos = etree.SubElement(complemento, PAGOS + "Pagos", Version="2.0")
    summary = snapshot.get("taxes_summary", [])
    totals = {"MontoTotalPagos": _decimal(snapshot["payment_amount"])}
    for tax in summary:
        key = (tax["tax_code"], tax["factor"], tax.get("rate", ""))
        fields = IVA_TOTALS.get(key)
        if not fields:
            raise PaymentCFDIError("La retención o tasa de impuesto sale del subconjunto de IVA 0, 8, 16 o exento configurado.")
        base_field, tax_field = fields
        totals[base_field] = _decimal(Decimal(totals.get(base_field, "0")) + Decimal(tax["base"]))
        if tax_field:
            totals[tax_field] = _decimal(Decimal(totals.get(tax_field, "0")) + Decimal(tax["amount"]))
    total_node = etree.SubElement(pagos, PAGOS + "Totales")
    for name, value in totals.items():
        total_node.set(name, value)

    payment = etree.SubElement(pagos, PAGOS + "Pago")
    payment.set("FechaPago", _payment_timestamp(snapshot["payment_date"]))
    payment.set("FormaDePagoP", snapshot["payment_form"])
    payment.set("MonedaP", "MXN")
    payment.set("Monto", _decimal(snapshot["payment_amount"]))
    for document in related:
        node = etree.SubElement(payment, PAGOS + "DoctoRelacionado")
        for name, value in (
            ("IdDocumento", document["cfdi_uuid"]),
            ("MonedaDR", "MXN"),
            ("NumParcialidad", str(document["installment_number"])),
            ("ImpSaldoAnt", _decimal(document["previous_balance"])),
            ("ImpPagado", _decimal(document["amount_paid"])),
            ("ImpSaldoInsoluto", _decimal(document["remaining_balance"])),
            ("ObjetoImpDR", document["tax_object"]),
        ):
            node.set(name, value)
        taxes = document.get("taxes", [])
        if taxes:
            taxes_node = etree.SubElement(node, PAGOS + "ImpuestosDR")
            transfers = etree.SubElement(taxes_node, PAGOS + "TrasladosDR")
            for tax in taxes:
                transfer = etree.SubElement(transfers, PAGOS + "TrasladoDR")
                transfer.set("BaseDR", tax["base_paid"])
                transfer.set("ImpuestoDR", tax["tax_code"])
                transfer.set("TipoFactorDR", tax["factor"])
                if tax["factor"] == "Tasa":
                    transfer.set("TasaOCuotaDR", tax["rate"])
                    transfer.set("ImporteDR", tax["amount_paid"])

    if summary:
        taxes_node = etree.SubElement(payment, PAGOS + "ImpuestosP")
        transfers = etree.SubElement(taxes_node, PAGOS + "TrasladosP")
        for tax in summary:
            transfer = etree.SubElement(transfers, PAGOS + "TrasladoP")
            transfer.set("BaseP", tax["base"])
            transfer.set("ImpuestoP", tax["tax_code"])
            transfer.set("TipoFactorP", tax["factor"])
            if tax["factor"] == "Tasa":
                transfer.set("TasaOCuotaP", tax["rate"])
                transfer.set("ImporteP", tax["amount"])
    return root, private_key


def build_signed_payment_cfdi(snapshot):
    """Generate a CSD-signed CFDI 4.0 payment receipt without calling a PAC."""
    root, private_key = _build_unsigned_payment(snapshot)
    try:
        cadena = str(_cadena_transform()(root)).encode("utf-8")
        sello = private_key.sign(cadena, padding.PKCS1v15(), hashes.SHA256())
    except etree.XSLTError as error:
        raise PaymentCFDIError("No se pudo producir la cadena original de Pagos 2.0 con el XSLT local del SAT.") from error
    except Exception as error:
        raise PaymentCFDIError("No se pudo firmar el complemento de pago con el CSD configurado.") from error
    root.set("Sello", base64.b64encode(sello).decode("ascii"))
    xml_content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False).decode("utf-8")
    require_valid_payment_cfdi_xml(xml_content)
    return xml_content
