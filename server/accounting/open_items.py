"""Read-only validation of a legacy open-items CSV before an opening import."""

import csv
from hashlib import sha256
import io
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from billing.models import CustomerInvoice
from purchasing.models import Supplier, SupplierBill
from sales.models import Customer

from .models import Account, JournalEntry, JournalLine, OpeningBalanceItem


CENT = Decimal("0.01")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
REQUIRED_HEADERS = {
    "tipo", "rfc", "folio_externo", "sistema_origen", "fecha_emision",
    "fecha_vencimiento", "moneda", "total_original", "pagado_previo", "saldo_abierto",
}
HEADER_ALIASES = {
    "tipo": {"tipo", "cuenta"},
    "rfc": {"rfc"},
    "folio_externo": {"folio_externo", "folio", "numero_externo", "referencia_externa"},
    "sistema_origen": {"sistema_origen", "sistema", "origen"},
    "fecha_emision": {"fecha_emision", "fecha_de_emision"},
    "fecha_vencimiento": {"fecha_vencimiento", "fecha_de_vencimiento", "vencimiento"},
    "moneda": {"moneda"},
    "total_original": {"total_original", "importe_original"},
    "pagado_previo": {"pagado_previo", "pagos_previos", "importe_pagado"},
    "saldo_abierto": {"saldo_abierto", "saldo_pendiente"},
}


def _header(value):
    value = unicodedata.normalize("NFD", (value or "").strip().lower())
    value = "".join(character for character in value if unicodedata.category(character) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _amount(value):
    raw = (value or "").strip().replace("$", "").replace("MXN", "").replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[1]
        if len(tail) == 3:
            raise ValueError("separador ambiguo; usa 1234.00 o 1234,00 sin separador de miles")
        raw = raw.replace(",", ".")
    if raw.count(".") > 1 or ("." in raw and len(raw.rsplit(".", 1)[1]) > 2):
        raise ValueError("usa como máximo dos decimales y sin separadores de miles")
    try:
        amount = Decimal(raw).quantize(CENT)
    except (InvalidOperation, ValueError):
        raise ValueError("importe inválido") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("el importe debe ser un número finito no negativo")
    return amount


def _date(value, field):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise ValueError(f"{field} debe usar formato AAAA-MM-DD") from None


def _control_balance(account, as_of):
    totals = JournalLine.objects.filter(
        account=account,
        entry__state=JournalEntry.State.POSTED,
        entry__entry_date__lte=as_of,
    ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
    net = (totals["debit"] or Decimal("0.00")) - (totals["credit"] or Decimal("0.00"))
    return net if account.normal_balance == Account.BalanceSide.DEBIT else -net


def preview_open_items_csv(upload, as_of, receivables_account, payables_account):
    if upload.size > MAX_FILE_BYTES:
        raise ValueError("El CSV supera el límite de 2 MB.")
    raw_content = upload.read()
    try:
        text = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Guarda el CSV como UTF-8 para poder leer acentos y RFC correctamente.") from None
    csv_sha256 = sha256(raw_content).hexdigest()
    sample = text[:8192]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("El CSV necesita una fila de encabezados.")
    normalized_headers = [_header(name) for name in reader.fieldnames]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise ValueError("El CSV contiene encabezados repetidos o equivalentes; deja una sola columna por dato.")
    source_headers = dict(zip(normalized_headers, reader.fieldnames))
    mapping = {}
    for canonical, aliases in HEADER_ALIASES.items():
        matches = [source_headers[alias] for alias in aliases if alias in source_headers]
        if len(matches) > 1:
            raise ValueError(f"El CSV contiene más de una columna para {canonical}.")
        mapping[canonical] = matches[0] if matches else None
    missing = sorted(field for field in REQUIRED_HEADERS if mapping.get(field) is None)
    if missing:
        raise ValueError("Faltan columnas: " + ", ".join(missing))

    customer_rows = list(Customer.objects.filter(is_active=True).exclude(rfc=""))
    supplier_rows = list(Supplier.objects.filter(is_active=True).exclude(rfc=""))
    customers = {item.rfc.strip().upper(): item for item in customer_rows}
    suppliers = {item.rfc.strip().upper(): item for item in supplier_rows}
    if len(customers) != len(customer_rows):
        raise ValueError("El catálogo contiene clientes activos con RFC repetido; corrige el maestro antes de importar.")
    if len(suppliers) != len(supplier_rows):
        raise ValueError("El catálogo contiene proveedores activos con RFC repetido; corrige el maestro antes de importar.")
    customer_docs = {
        (rfc.strip().upper(), number.casefold())
        for rfc, number in CustomerInvoice.objects.filter(customer_id__in=[item.pk for item in customer_rows]).values_list("customer__rfc", "number")
    }
    supplier_docs = {
        (rfc.strip().upper(), number.casefold())
        for rfc, number in SupplierBill.objects.filter(supplier_id__in=[item.pk for item in supplier_rows]).values_list("supplier__rfc", "invoice_number")
    }
    reserved_external_items = {
        (direction, rfc.strip().upper(), source.casefold(), number.casefold())
        for direction, rfc, source, number in OpeningBalanceItem.objects.filter(is_reserved=True).values_list(
            "direction", "counterparty_rfc", "source_system", "external_number"
        )
    }
    duplicates = set()
    issues = []
    totals = {"cxc": Decimal("0.00"), "cxp": Decimal("0.00")}
    counts = {"cxc": 0, "cxp": 0}
    valid_rows = 0
    validated_items = []
    for row_number, raw_row in enumerate(reader, start=2):
        if row_number > MAX_ROWS + 1:
            raise ValueError(f"El CSV supera el límite de {MAX_ROWS} renglones.")
        if None in raw_row:
            issues.append({"row": row_number, "errors": ["el renglón tiene más columnas que el encabezado"]})
            continue
        row = {
            canonical: (raw_row.get(source_header) or "").strip()
            for canonical, source_header in mapping.items()
            if source_header is not None
        }
        errors = []
        direction = row.get("tipo", "").strip().casefold()
        direction = {"cxc": "cxc", "cx c": "cxc", "por_cobrar": "cxc", "cxp": "cxp", "cx p": "cxp", "por_pagar": "cxp"}.get(direction, direction)
        rfc = row.get("rfc", "").upper()
        folio = row.get("folio_externo", "")
        source_system = row.get("sistema_origen", "")
        issue_date = None
        due_date = None
        if direction not in totals:
            errors.append("tipo debe ser CxC o CxP")
        party_map = customers if direction == "cxc" else suppliers
        if not rfc or rfc not in party_map:
            errors.append("RFC sin coincidencia con un cliente o proveedor activo")
        if not folio:
            errors.append("falta folio_externo")
        if not source_system:
            errors.append("falta sistema_origen")
        currency = row.get("moneda", "").upper()
        if currency != "MXN":
            errors.append("moneda debe ser MXN")
        try:
            issue_date = _date(row.get("fecha_emision"), "fecha_emision")
            if issue_date > as_of:
                errors.append("fecha_emision no puede ser posterior al corte")
        except ValueError as error:
            errors.append(str(error))
        try:
            due_date = _date(row.get("fecha_vencimiento"), "fecha_vencimiento")
            if issue_date and due_date < issue_date:
                errors.append("fecha_vencimiento no puede ser anterior a fecha_emision")
        except ValueError as error:
            errors.append(str(error))
        parsed = {}
        for field in ("total_original", "pagado_previo", "saldo_abierto"):
            try:
                parsed[field] = _amount(row.get(field))
            except ValueError as error:
                errors.append(f"{field}: {error}")
        if len(parsed) == 3:
            if parsed["total_original"] <= 0:
                errors.append("total_original debe ser mayor que cero")
            if parsed["saldo_abierto"] <= 0:
                errors.append("saldo_abierto debe ser mayor que cero")
            if parsed["total_original"] - parsed["pagado_previo"] != parsed["saldo_abierto"]:
                errors.append("total_original menos pagado_previo debe ser igual a saldo_abierto")
        key = (direction, rfc, folio.casefold())
        if direction in totals and key in duplicates:
            errors.append("folio externo duplicado para el mismo RFC dentro del archivo")
        duplicates.add(key)
        if direction == "cxc" and (rfc, folio.casefold()) in customer_docs:
            errors.append("ya existe una factura interna con ese folio para el cliente")
        elif direction == "cxp" and (rfc, folio.casefold()) in supplier_docs:
            errors.append("ya existe una factura de proveedor con ese folio")
        if (direction, rfc, source_system.casefold(), folio.casefold()) in reserved_external_items:
            errors.append("el folio externo ya está reservado por otro lote de apertura publicado o pendiente")
        if errors:
            issues.append({"row": row_number, "errors": errors})
            continue
        totals[direction] += parsed["saldo_abierto"]
        counts[direction] += 1
        valid_rows += 1
        party = party_map[rfc]
        validated_items.append({
            "direction": direction,
            "counterparty_rfc": rfc,
            "counterparty_id": str(party.pk),
            "source_system": source_system,
            "external_number": folio,
            "issue_date": issue_date,
            "due_date": due_date,
            "currency": currency,
            "original_total": parsed["total_original"],
            "paid_before_cutoff": parsed["pagado_previo"],
            "open_balance": parsed["saldo_abierto"],
        })

    controls = []
    for direction, account, expected_category, expected_side in (
        ("cxc", receivables_account, Account.Category.ASSET, Account.BalanceSide.DEBIT),
        ("cxp", payables_account, Account.Category.LIABILITY, Account.BalanceSide.CREDIT),
    ):
        if account.category != expected_category or account.normal_balance != expected_side:
            raise ValueError(f"La cuenta {account.code} no tiene la clasificación/naturaleza esperada para {direction.upper()}.")
        ledger = _control_balance(account, as_of).quantize(CENT)
        total = totals[direction].quantize(CENT)
        controls.append({
            "direction": direction,
            "account_code": account.code,
            "account_name": account.name,
            "open_items_total": str(total),
            "control_balance": str(ledger),
            "difference": str((total - ledger).quantize(CENT)),
            "row_count": counts[direction],
        })
    ready = not issues and valid_rows > 0 and all(Decimal(item["difference"]) == 0 for item in controls)
    return {
        "as_of": as_of.isoformat(),
        "currency": "MXN",
        "valid_rows": valid_rows,
        "error_rows": len(issues),
        "ready_for_review": ready,
        "publication_enabled": False,
        "totals": controls,
        "issues": issues,
        "_csv_sha256": csv_sha256,
        "_validated_items": validated_items,
        "limitations": [
            "La vista previa no crea saldos ni pólizas.",
            "Las partidas se clasificarían como saldo operativo; todavía no se emiten complementos Pagos 2.0 para CFDI históricos.",
        ],
    }
