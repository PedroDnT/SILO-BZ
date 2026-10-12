"""Which administrador judicial (AJ) websites the RJ collector reads, and how (#845).

One ``Site`` per website: where its case lists are, which anchors on a list
page are case pages, and which anchors on a case page are documents. Sites on
one platform share the patterns (``DOUBLEONE_*``), so a new site on a known
platform is one line here.

A site is listed only if ``aj_sites.csv`` (#844) classed it ``html`` with
``robots_ok`` not ``no``; ``tests/test_rj_collector.py`` pins that. A site that
needs JavaScript or a login is not read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Site:
    domain: str                    # as in aj_sites.csv
    aj_name: str                   # the AJ as the site names itself
    list_urls: Tuple[str, ...]     # pages that list the AJ's RJ cases
    case_pattern: str              # regex an anchor's absolute URL must match to be a case page
    doc_pattern: str               # regex an anchor's absolute URL must match to be a document
    platform: str

    @property
    def source(self) -> str:
        """The ``source`` written on every row this site produces."""
        return f"aj_site:{self.domain}"


# DoubleOne CMS (doubleone.com.br): case pages are /processo/<tipo>_<slug>__<id>
# and documents are <panel>/download.php?file=...&nome=<title>.
DOUBLEONE_CASE = r"/processo/[^/?#]+__\d+$"
DOUBLEONE_DOC = r"/(?:sgc|admin)/download\.php\?file="


def _doubleone(domain: str, aj_name: str, *paths: str) -> Site:
    return Site(domain=domain, aj_name=aj_name,
                list_urls=tuple(f"https://{domain}{p}" for p in paths),
                case_pattern=DOUBLEONE_CASE, doc_pattern=DOUBLEONE_DOC, platform="DoubleOne CMS")


SITES: Tuple[Site, ...] = (
    _doubleone("marquesadmjudicial.com.br", "Marques Administração Judicial", "/processos/recuperacao-judicial"),
    _doubleone("cataliseaj.com.br", "Catalise Administração Judicial", "/processos/recuperacao-judicial"),
    _doubleone("flaviocardosoadv.com.br", "Flávio Cardoso Advogados Associados", "/processos/recuperacao-judicial"),
    _doubleone("recupereadmjudicial.com.br", "Recupere Administração Judicial", "/processos/recuperacao-judicial"),
    _doubleone("scalzilliaj.com.br", "Scalzilli Administração Judicial", "/processos/recuperacao-judicial"),
    _doubleone("mpbadmjudicial.com.br", "MPB Administração Judicial", "/processos/recuperacao-judicial"),
    _doubleone("lasproconsultores.com.br", "Laspro Consultores", "/processos/recuperacao-judicial"),
)

SITES += (
    # Medeiros: relative case links without a numeric id; documents on S3.
    Site(domain="administradorjudicial.adv.br", aj_name="Medeiros Administração Judicial",
         list_urls=("https://administradorjudicial.adv.br/recuperacoes-judiciais",),
         case_pattern=r"/processo/recuperacoes-judiciais__[^/?#]+$",
         doc_pattern=r"^https://ajud-mm\.s3\.amazonaws\.com/arquivos/[^?#]+\.pdf$",
         platform="custom, documents on S3"),
)

SITES += (
    # Next.js site (TPAJ): /processos/<cuid> case pages; PDFs on media.tpaj.com.br.
    # The list mixes recuperações judiciais and falências (the filter is client-side).
    # The canonical host is www; the apex redirects to it.
    Site(domain="tpaj.com.br", aj_name="Tussi & Platchek Administração Judicial",
         list_urls=("https://www.tpaj.com.br/processos",),
         case_pattern=r"^https://www\.tpaj\.com\.br/processos/[^/?#]+$",
         doc_pattern=r"^https://media\.tpaj\.com\.br/uploads/[^?#]+\.pdf$",
         platform="Next.js (server-rendered)"),
    # Static HTML site by Italic: /recuperacao-judicial-<slug>.html, PDFs in /assets/files/.
    Site(domain="costapaivasantiago.com.br", aj_name="Costa Paiva Santiago Administração Judicial",
         list_urls=("https://costapaivasantiago.com.br/recuperacoes-judiciais.html",),
         case_pattern=r"^https://costapaivasantiago\.com\.br/recuperacao-judicial-[^/?#]+\.html$",
         doc_pattern=r"^https://costapaivasantiago\.com\.br/assets/files/[^?#]+\.pdf$",
         platform="static HTML (Italic)"),
    # Sentinela: the WordPress main site mirrors the case app; case pages carry the PDFs.
    # (The case app, www.app.administradorajudicial.adv.br, is not read: its documents
    # sit behind /media/download/<id> and carry no titles.)
    Site(domain="administradorajudicial.adv.br", aj_name="Sentinela Administradora Judicial",
         list_urls=("https://administradorajudicial.adv.br/categoria/recuperacao-judicial/",),
         case_pattern=r"^https://administradorajudicial\.adv\.br/recuperacao-judicial/[^/?#]+/$",
         doc_pattern=r"^https://administradorajudicial\.adv\.br/wp-content/uploads/[^?#]+\.pdf$",
         platform="WordPress (Betheme)"),
    # Wix dynamic-item pages /recuperacaojudicial/<slug>, files on usrfiles.com. The list
    # widget paginates in JavaScript, so only its first page is read.
    Site(domain="mvbrecuperacoesjudiciais.com.br", aj_name="MVB Consultores",
         list_urls=("https://www.mvbrecuperacoesjudiciais.com.br/recuperacaojudicial",),
         case_pattern=r"^https://www\.mvbrecuperacoesjudiciais\.com\.br/recuperacaojudicial/[^/?#]+$",
         doc_pattern=r"^https://[0-9a-f-]+\.usrfiles\.com/ugd/[^?#]+\.pdf$",
         platform="Wix"),
)
