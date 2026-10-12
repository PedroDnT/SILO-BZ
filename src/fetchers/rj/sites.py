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

# WordPress sites with a custom post type per case. Each has its own slug, so
# each carries its own patterns; documents are PDFs in wp-content/uploads
# (icon-only links, titled from the file name) or Google Drive file links.
WP_UPLOADS_PDF = r"/wp-content/uploads/[^?#]+\.pdf$"

SITES += (
    # FVS: the list is a table whose rows carry the case URL in onclick.
    Site(domain="fvsadmj.com.br", aj_name="FVS Administração e Gestão Judicial Ltda",
         list_urls=("https://fvsadmj.com.br/recuperacoes/",),
         case_pattern=r"^https://fvsadmj\.com\.br/recuperacao/[^/?#]+/?$",
         doc_pattern=r"^https://fvsadmj\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress, custom post type"),
    Site(domain="excelia-aj.com.br", aj_name="Excelia Consultoria, Gestão e Negócios Ltda.",
         list_urls=("https://excelia-aj.com.br/recuperacoes-judiciais/",),
         case_pattern=r"^https://excelia-aj\.com\.br/recuperacao-judicial/[^/?#]+/?$",
         doc_pattern=r"^https?://excelia-aj\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress, custom post type"),
    # Expertisemais: documents are Google Drive files. Two list entries sit
    # under /recuperacoes-judiciais-2/; the ?page_id=..&preview=true drafts
    # on the list are not published case pages and are not matched.
    Site(domain="expertisemais.com.br", aj_name="Expertisemais Serviços Contábeis e Administrativos",
         list_urls=("https://expertisemais.com.br/recuperacoes-judiciais/",),
         case_pattern=r"^https://expertisemais\.com\.br/recuperacoes-judiciais(?:-2)?/[^/?#]+/?$",
         doc_pattern=r"^https://drive\.google\.com/file/d/",
         platform="WordPress, Google Drive documents"),
    # Tapxure & Severino: three list pages (RJ and falência cases mixed); the
    # cartilha on the list is a guide, not a case.
    Site(domain="tapxure.com.br", aj_name="Tapxure & Severino Sociedade de Advogados",
         list_urls=("https://www.tapxure.com.br/processos/",
                    "https://www.tapxure.com.br/processos/page/2/",
                    "https://www.tapxure.com.br/processos/page/3/"),
         case_pattern=r"^https://www\.tapxure\.com\.br/processos/(?!cartilha|page/)[^/?#]+/?$",
         doc_pattern=r"^https://www\.tapxure\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress, custom post type"),
    # Érika Santiago: documents come through the Download Attachments plugin.
    Site(domain="erikasantiago.adv.br", aj_name="Erika Santiago Sociedade Individual de Advocacia",
         list_urls=("http://erikasantiago.adv.br/portfolio-group/recuperacoes-judiciais/",),
         case_pattern=r"^http://erikasantiago\.adv\.br/portfolio-item/[^/?#]+/?$",
         doc_pattern=r"/wp-content/plugins/download-attachments/includes/download\.php\?id=\d+",
         platform="WordPress, Download Attachments"),
)
