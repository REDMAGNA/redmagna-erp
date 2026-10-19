from decimal import Decimal, ROUND_HALF_UP, localcontext
from xml.etree import ElementTree


SIX_PLACES = Decimal("0.000001")
TWO_PLACES = Decimal("0.01")
SUPPORTED_VAT_RATES = {Decimal("0"), Decimal("0.08"), Decimal("0.16")}


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _children(element, name):
    return [child for child in list(element) if _tag(child) == name]


def _six(value):
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def _decimal_attribute(element, name, required=True):
    value = element.attrib.get(name)
    if value in (None, ""):
        if required:
            raise ValueError(f"El CFDI timbrado no contiene el atributo {name}.")
        return Decimal("0")
    try:
        return Decimal(value)
    except Exception as error:
        raise ValueError(f"El CFDI timbrado contiene un importe inválido en {name}.") from error


def issued_invoice_tax_basis(xml_content, cfdi_uuid, expected_total):
    """Read the stamped CFDI's narrow IVA subset used by the first payment workflow."""
    if not xml_content or len(xml_content) > 5_000_000:
        raise ValueError("El XML timbrado está vacío o excede el tamaño permitido para lectura.")
    upper_xml = xml_content.upper()
    if "<!DOCTYPE" in upper_xml or "<!ENTITY" in upper_xml:
        raise ValueError("El XML timbrado contiene declaraciones externas no permitidas.")
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError as error:
        raise ValueError("No se pudo leer el XML del CFDI timbrado relacionado.") from error
    if _tag(root) != "Comprobante" or root.attrib.get("Version") != "4.0" or root.attrib.get("TipoDeComprobante") != "I":
        raise ValueError("El documento relacionado no contiene un CFDI 4.0 timbrado.")
    if root.attrib.get("Moneda") != "MXN":
        raise ValueError("El cálculo inicial del complemento admite únicamente CFDI relacionados en MXN.")
    if _decimal_attribute(root, "Total") != expected_total:
        raise ValueError("El total del CFDI timbrado no coincide con la factura interna; requiere revisión manual.")

    timbre = next((element for element in root.iter() if _tag(element) == "TimbreFiscalDigital"), None)
    if not timbre or timbre.attrib.get("UUID", "").upper() != str(cfdi_uuid).upper():
        raise ValueError("El UUID del CFDI timbrado no coincide con el documento relacionado.")
    concepts_node = next((element for element in root.iter() if _tag(element) == "Conceptos"), None)
    concepts = _children(concepts_node, "Concepto") if concepts_node is not None else []
    if not concepts:
        raise ValueError("El CFDI timbrado no contiene conceptos que permitan calcular impuestos del pago.")

    tax_objects = set()
    groups = {}
    for concept in concepts:
        tax_object = concept.attrib.get("ObjetoImp")
        if tax_object not in {"01", "02"}:
            raise ValueError("El CFDI contiene un objeto de impuesto fuera del subconjunto inicial del complemento.")
        tax_objects.add(tax_object)
        impuestos = next(iter(_children(concept, "Impuestos")), None)
        retenciones = _children(impuestos, "Retenciones") if impuestos is not None else []
        if retenciones:
            raise ValueError("El CFDI contiene retenciones; el cálculo inicial del complemento no las admite.")
        if tax_object == "01":
            if impuestos is not None:
                raise ValueError("El CFDI marca un concepto como no objeto y además contiene impuestos.")
            continue
        if impuestos is None:
            raise ValueError("El CFDI marca un concepto como objeto de impuesto, pero no detalla sus impuestos.")
        for transfers in _children(impuestos, "Traslados"):
            for transfer in _children(transfers, "Traslado"):
                tax_code = transfer.attrib.get("Impuesto")
                factor = transfer.attrib.get("TipoFactor")
                if tax_code != "002" or factor not in {"Tasa", "Exento"}:
                    raise ValueError("El CFDI contiene impuestos o factores fuera del subconjunto inicial (IVA por tasa o exento).")
                rate = _decimal_attribute(transfer, "TasaOCuota", required=factor == "Tasa") if factor == "Tasa" else Decimal("0")
                if factor == "Tasa" and rate not in SUPPORTED_VAT_RATES:
                    raise ValueError("El CFDI contiene una tasa de IVA no soportada por el cálculo inicial del complemento.")
                base = _decimal_attribute(transfer, "Base")
                amount = _decimal_attribute(transfer, "Importe", required=False)
                if base < 0 or amount < 0:
                    raise ValueError("El CFDI contiene una base o importe de impuesto negativo.")
                key = (tax_code, factor, rate)
                group = groups.setdefault(key, {"tax_code": tax_code, "factor": factor, "rate": rate, "base": Decimal("0"), "amount": Decimal("0")})
                group["base"] += base
                group["amount"] += amount
    if len(tax_objects) > 1:
        raise ValueError("El CFDI mezcla conceptos objeto y no objeto; requiere validación fiscal antes de calcular el complemento.")
    if "02" in tax_objects and not groups:
        raise ValueError("El CFDI objeto de impuesto no contiene traslados compatibles para el cálculo.")
    for group in groups.values():
        if group["factor"] == "Tasa":
            expected_amount = (group["base"] * group["rate"]).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            if abs(expected_amount - group["amount"]) > TWO_PLACES:
                raise ValueError("El IVA del CFDI no coincide con la base y tasa agrupadas; requiere revisión manual.")
    return {
        "tax_object": next(iter(tax_objects)),
        "taxes": [
            {
                "tax_code": group["tax_code"],
                "factor": group["factor"],
                "rate": format(group["rate"], ".6f") if group["factor"] == "Tasa" else "",
                "base_total": str(_six(group["base"])),
                "amount_total": str(_six(group["amount"])),
            }
            for key, group in sorted(groups.items(), key=lambda item: item[0])
        ],
    }


def allocate_payment_taxes(tax_basis, prior_taxes, paid_amount, previous_balance):
    prior_by_key = {
        (item["tax_code"], item["factor"], item.get("rate", "")): item
        for item in prior_taxes
    }
    with localcontext() as context:
        context.prec = 28
        fraction = paid_amount / previous_balance
        result = []
        for tax in tax_basis["taxes"]:
            key = (tax["tax_code"], tax["factor"], tax.get("rate", ""))
            previous = prior_by_key.get(key, {})
            remaining_base = Decimal(tax["base_total"]) - Decimal(previous.get("base_paid", "0"))
            if remaining_base < 0:
                raise ValueError("Los impuestos pagados anteriormente exceden la base del CFDI relacionado.")
            base_paid = _six(remaining_base * fraction)
            if tax["factor"] == "Tasa":
                amount_paid = _six(base_paid * Decimal(tax["rate"]))
            else:
                amount_paid = Decimal("0.000000")
            result.append({
                "tax_code": tax["tax_code"],
                "factor": tax["factor"],
                "rate": tax.get("rate", ""),
                "base_paid": str(base_paid),
                "amount_paid": str(amount_paid),
            })
        return result


def summarize_payment_taxes(related_documents):
    groups = {}
    for document in related_documents:
        for tax in document.get("taxes", []):
            key = (tax["tax_code"], tax["factor"], tax.get("rate", ""))
            group = groups.setdefault(key, {"tax_code": tax["tax_code"], "factor": tax["factor"], "rate": tax.get("rate", ""), "base": Decimal("0"), "amount": Decimal("0")})
            group["base"] += Decimal(tax["base_paid"])
            group["amount"] += Decimal(tax["amount_paid"])
    return [
        {"tax_code": group["tax_code"], "factor": group["factor"], "rate": group["rate"], "base": str(_six(group["base"])), "amount": str(_six(group["amount"]))}
        for key, group in sorted(groups.items(), key=lambda item: item[0])
    ]
