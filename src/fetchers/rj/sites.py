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

# Batch 3. WordPress sites whose case pages are plain posts and whose documents
# are PDFs under wp-content/uploads.
WP_UPLOADS_PDF = r"/wp-content/uploads/[^?#]+\.pdf$"

SITES += (
    # Case pages are /recuperacao-judicial/<slug>/ (the falencias list is a separate page).
    Site(domain="fontanaexperts.com.br", aj_name="Fontana Experts Consultoria, Administração Judicial e Perícias",
         list_urls=("https://fontanaexperts.com.br/recuperacoes/",),
         case_pattern=r"^https://fontanaexperts\.com\.br/recuperacao-judicial/[^/?#]+/$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress"),
    # Case pages are /processo/<slug>/; the list carries both RJ and falencia cases.
    Site(domain="scalzilliedias.com.br", aj_name="Scalzilli & Dias Administração Judicial",
         list_urls=("https://scalzilliedias.com.br/processos-page/",),
         case_pattern=r"^https://scalzilliedias\.com\.br/processo/[^/?#]+/$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress"),
    # Case pages sit at the root, beside the menu pages, so the menu slugs are excluded.
    # Documents are WordPress Download Manager links.
    Site(domain="atrioconsultores.com.br", aj_name="Átrio Consultores",
         list_urls=("https://atrioconsultores.com.br/recuperacao-judicial/",),
         case_pattern=(r"^https://atrioconsultores\.com\.br/"
                       r"(?!(?:sobre|habilitacoes-e-divergencias|recuperacao-judicial|falencia|"
                       r"penhora-de-faturamento|contato)/)[a-z0-9-]+/$"),
         doc_pattern=r"/download/[^/?#]+/\?wpdmdl=\d+", platform="WordPress + Download Manager"),
    # The list is a Search & Filter view, five cases a page; ?_sft_tipo= keeps only RJ
    # (the unfiltered list mixes in falencias) and sf_paged= pages through it.
    Site(domain="actionaj.com.br", aj_name="Action Administração Judicial",
         list_urls=("https://actionaj.com.br/todos-os-processos/?_sft_tipo=recuperacao-judicial",
                    "https://actionaj.com.br/todos-os-processos/?_sft_tipo=recuperacao-judicial&sf_paged=2"),
         case_pattern=r"^https://actionaj\.com\.br/processos/[^/?#]+/$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress"),
)
