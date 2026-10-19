"""Read the SAT catalog enumerations bundled in catCFDI.xsd."""

from functools import lru_cache
from pathlib import Path

from lxml import etree


SAT_CATALOG_SCHEMA_PATH = Path(__file__).with_name("sat") / "catalogos" / "catCFDI.xsd"
XSD_NS = {"xs": "http://www.w3.org/2001/XMLSchema"}


@lru_cache(maxsize=1)
def _catalogs():
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(str(SAT_CATALOG_SCHEMA_PATH), parser)
    values = {}
    for simple_type in root.xpath("./xs:simpleType", namespaces=XSD_NS):
        name = simple_type.get("name")
        enumerations = simple_type.xpath(".//xs:enumeration/@value", namespaces=XSD_NS)
        if name and enumerations:
            values[name] = frozenset(enumerations)
    return values


def is_sat_catalog_value(catalog_name, value):
    """Return true only for a value enumerated in the bundled SAT catalog XSD."""
    catalog = _catalogs().get(catalog_name)
    return bool(catalog and str(value) in catalog)
