"""Build a portable Synology package and its matching AGPL source archive."""

from pathlib import Path
import argparse
import re
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", "work", "__pycache__", "secrets"}
SENSITIVE_SUFFIXES = {".cer", ".crt", ".key", ".pem", ".p12", ".pfx"}
REQUIRED_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "docker-compose.yml",
    ".dockerignore",
    "server/accounting/open_items.py",
    "server/accounting/opening_balance_services.py",
    "server/accounting/migrations/0009_openingbalancebatch_openingbalanceitem.py",
    "server/accounting/migrations/0010_remove_openingbalanceitem_accounting_opening_external_item_uniq_and_more.py",
    "server/accounting/migrations/0011_openingbalancebatch_accounting_opening_batch_idempotent_uniq.py",
    "server/accounting/migrations/0012_remove_openingbalanceitem_accounting_opening_external_item_uniq_and_more.py",
    "server/accounting/migrations/0013_postingconfigurationevent.py",
    "server/billing/migrations/0015_customerinvoice_opening_balance_batch_id_and_more.py",
    "server/billing/migrations/0017_fiscal_customer_copy_permission.py",
    "server/purchasing/migrations/0013_supplierbill_opening_balance_batch_id_and_more.py",
    "server/purchasing/migrations/0014_alter_supplierbill_invoice_number.py",
    "server/purchasing/migrations/0015_supplierbillcfdi_issuer_seal_verification.py",
    "server/purchasing/migrations/0018_purchase_framework_agreements.py",
    "server/expenses/migrations/0003_alter_expensereceipt_file.py",
    "server/accounting/reports.py",
    "server/accounting/views.py",
    "server/accounting/urls.py",
    "dist/app.js",
    "dist/index.html",
    "docs/apertura-saldos-auxiliares-v1.md",
    "docs/guia-synology-ds720-redmagna-erp.md",
    "tools/preflight_synology.sh",
    "server/repairs/migrations/0001_initial.py",
    "server/repairs/migrations/0002_repaircase_physical_custody.py",
    "server/repairs/migrations/0003_correct_custody_event_transitions.py",
    "server/support/migrations/0008_support_inbound_email_receipt.py",
    "server/support/migrations/0009_business_time_sla_calendar.py",
    "server/support/migrations/0010_rename_inbound_email_fields.py",
    "server/support/management/commands/receive_support_emails.py",
    "source.zip",
    "server/sales/forms.py",
    "server/sales/migrations/0023_public_lead_submissions.py",
    "server/sales/migrations/0024_opportunity_utm_attribution.py",
    "server/sales/migrations/0025_public_lead_notifications.py",
    "server/sales/migrations/0026_public_lead_notification_manual_retry.py",
    "server/sales/migrations/0027_customer_quote_payment_terms.py",
    "server/sales/migrations/0028_customer_contacts.py",
    "server/sales/migrations/0029_quote_customer_contact_recipient.py",
    "server/sales/migrations/0030_quote_cost_sheets.py",
    "server/sales/migrations/0031_quote_discount_approval.py",
    "server/sales/migrations/0032_alter_quotecostitem_quantity_and_more.py",
    "server/sales/templates/sales/public_quote_request.html",
    "server/sales/management/commands/send_public_lead_notifications.py",
    "server/inventory/migrations/0010_product_sat_border_8_review.py",
    "server/inventory/migrations/0011_inventory_product_location_barcodes.py",
    "server/inventory/migrations/0013_inventory_counts.py",
    "server/inventory/migrations/0014_inventory_count_serials.py",
}
REQUIRED_SOURCE_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    ".dockerignore",
    "server/accounting/open_items.py",
    "server/accounting/opening_balance_services.py",
    "server/accounting/migrations/0009_openingbalancebatch_openingbalanceitem.py",
    "server/accounting/migrations/0010_remove_openingbalanceitem_accounting_opening_external_item_uniq_and_more.py",
    "server/accounting/migrations/0011_openingbalancebatch_accounting_opening_batch_idempotent_uniq.py",
    "server/accounting/migrations/0012_remove_openingbalanceitem_accounting_opening_external_item_uniq_and_more.py",
    "server/accounting/migrations/0013_postingconfigurationevent.py",
    "server/billing/migrations/0015_customerinvoice_opening_balance_batch_id_and_more.py",
    "server/billing/migrations/0017_fiscal_customer_copy_permission.py",
    "server/purchasing/migrations/0013_supplierbill_opening_balance_batch_id_and_more.py",
    "server/purchasing/migrations/0014_alter_supplierbill_invoice_number.py",
    "server/purchasing/migrations/0015_supplierbillcfdi_issuer_seal_verification.py",
    "server/purchasing/migrations/0018_purchase_framework_agreements.py",
    "server/expenses/migrations/0003_alter_expensereceipt_file.py",
    "server/accounting/reports.py",
    "server/accounting/views.py",
    "server/accounting/urls.py",
    "dist/app.js",
    "dist/index.html",
    "docs/apertura-saldos-auxiliares-v1.md",
    "docs/guia-synology-ds720-redmagna-erp.md",
    "tools/preflight_synology.sh",
    "server/repairs/migrations/0001_initial.py",
    "server/repairs/migrations/0002_repaircase_physical_custody.py",
    "server/repairs/migrations/0003_correct_custody_event_transitions.py",
    "server/support/migrations/0008_support_inbound_email_receipt.py",
    "server/support/migrations/0009_business_time_sla_calendar.py",
    "server/support/migrations/0010_rename_inbound_email_fields.py",
    "tools/package_synology.py",
    "server/sales/migrations/0023_public_lead_submissions.py",
    "server/sales/migrations/0024_opportunity_utm_attribution.py",
    "server/sales/migrations/0025_public_lead_notifications.py",
    "server/sales/migrations/0026_public_lead_notification_manual_retry.py",
    "server/sales/migrations/0027_customer_quote_payment_terms.py",
    "server/sales/migrations/0028_customer_contacts.py",
    "server/sales/migrations/0029_quote_customer_contact_recipient.py",
    "server/sales/migrations/0031_quote_discount_approval.py",
    "server/sales/migrations/0032_alter_quotecostitem_quantity_and_more.py",
    "server/sales/forms.py",
    "server/sales/templates/sales/public_quote_request.html",
    "server/sales/management/commands/send_public_lead_notifications.py",
    "server/inventory/migrations/0010_product_sat_border_8_review.py",
    "server/inventory/migrations/0011_inventory_product_location_barcodes.py",
    "server/inventory/migrations/0013_inventory_counts.py",
    "server/inventory/migrations/0014_inventory_count_serials.py",
}


def project_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in {".pyc", ".pyo", *SENSITIVE_SUFFIXES} or is_sensitive_name(path.name) or path.name == "source.zip":
            continue
        yield path, relative.as_posix()


def is_sensitive_name(name):
    lowered = name.lower()
    return lowered == "csd_password" or lowered == ".env" or (lowered.startswith(".env.") and lowered != ".env.example")


def has_sensitive_archive_path(name):
    path = Path(name)
    return "secrets" in {part.lower() for part in path.parts} or path.suffix.lower() in SENSITIVE_SUFFIXES or is_sensitive_name(path.name)


def validate_postgres_image_pins():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    configured = dict(re.findall(r"(?m)^  (db|db-backup|db-restore-test):\s*\n    image:\s*(\S+)", compose))
    expected_services = {"db", "db-backup", "db-restore-test"}
    if set(configured) != expected_services or len(set(configured.values())) != 1:
        raise SystemExit("Los servicios db, db-backup y db-restore-test deben usar la misma imagen PostgreSQL.")
    image = configured["db"]
    if "@sha256:" not in image:
        raise SystemExit("La imagen PostgreSQL debe quedar fijada por digest.")
    required_backup_controls = (
        "pg_restore --list",
        "tar -tzf",
        "manifest_final=",
        "sha256sum -c",
        "redmagna-checksums-",
    )
    missing_controls = [control for control in required_backup_controls if control not in compose]
    if missing_controls:
        raise SystemExit(f"Backup/restore integrity controls missing from docker-compose.yml: {missing_controls}")


def main():
    parser = argparse.ArgumentParser(description="Empaqueta Redmagna ERP para Synology y genera el código fuente AGPL.")
    parser.add_argument("--output-dir", type=Path, default=ROOT.parent / "outputs", help="Carpeta de salida fuera del proyecto")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.is_relative_to(ROOT):
        raise SystemExit("La carpeta de salida debe estar fuera del proyecto.")

    validate_postgres_image_pins()
    subprocess.run([sys.executable, str(ROOT / "tools" / "verify_sat_resources.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "server" / "package_source.py")], check=True)
    with ZipFile(ROOT / "source.zip") as source_archive:
        source_names = set(source_archive.namelist())
        source_missing = REQUIRED_SOURCE_FILES - source_names
        source_sensitive = sorted(name for name in source_names if has_sensitive_archive_path(name))
        source_corrupt = source_archive.testzip()
        if source_missing or source_sensitive or source_corrupt:
            raise SystemExit(f"Source archive verification failed: missing={sorted(source_missing)}, sensitive={source_sensitive}, corrupt={source_corrupt}")
    output_dir.mkdir(parents=True, exist_ok=True)
    versions = [
        int(match.group(1))
        for path in output_dir.glob("redmagna-erp-nucleo-synology-v*.zip")
        if (match := re.fullmatch(r"redmagna-erp-nucleo-synology-v(\d+)\.zip", path.name))
    ]
    version = max(versions, default=0) + 1
    output = output_dir / f"redmagna-erp-nucleo-synology-v{version}.zip"
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=8) as archive:
        for path, name in project_files():
            archive.write(path, name)
        archive.write(ROOT / "source.zip", "source.zip")

    with ZipFile(output) as archive:
        names = set(archive.namelist())
        missing = REQUIRED_FILES - names
        sensitive = sorted(name for name in names if has_sensitive_archive_path(name))
        corrupt = archive.testzip()
        if missing or sensitive or corrupt:
            output.unlink(missing_ok=True)
            raise SystemExit(f"Package verification failed: missing={sorted(missing)}, sensitive={sensitive}, corrupt={corrupt}")
    print(f"Created {output} ({output.stat().st_size} bytes; {len(names)} files)")


if __name__ == "__main__":
    main()
