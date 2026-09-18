"""arXiv: primary categories, and where a work's source is.

Categories come from the export API, up to fifty identifiers to a request. The host budget gives arxiv.org and export.arxiv.org three seconds between requests, whatever command asked.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from weft.crawl.net import Service, ServiceError

API = "https://export.arxiv.org/api/query"
BATCH = 50
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_ABS = re.compile(r"arxiv\.org/abs/(.+?)(v\d+)?$")


def eprint_url(ident: str) -> str:
    """Where an arXiv identifier's source is downloaded from."""
    return f"https://arxiv.org/e-print/{ident}"


class Arxiv:
    """The export API, for the one thing the crawl needs from it."""

    def __init__(self, service: Service) -> None:
        self.service = service

    def categories(self, idents: list[str]) -> dict[str, str]:
        """Primary category by arXiv number (without version), for the numbers arXiv knows.

        Parameters
        ----------
        idents : list of str
            arXiv numbers, deduplicated and batched here.

        Returns
        -------
        dict of str to str
            Only the numbers arXiv answered for; a refused or unparseable batch contributes nothing rather than failing the plan.
        """
        out: dict[str, str] = {}
        todo = sorted(set(idents))
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            url = API + "?" + urllib.parse.urlencode({"id_list": ",".join(chunk), "max_results": str(len(chunk))})
            try:
                root = ET.fromstring(self.service.get(url))
            except (ServiceError, ET.ParseError):
                continue
            for entry in root.findall("atom:entry", _NS):
                ident = entry.findtext("atom:id", default="", namespaces=_NS)
                cat = entry.find("arxiv:primary_category", _NS)
                if (m := _ABS.search(ident)) and cat is not None:
                    out[m.group(1)] = cat.get("term", "")
        return out
