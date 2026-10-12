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
    debtor_from_title: bool = False  # the page <title> names the debtor; its headings are document titles

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

# --- Batch 6: WordPress sites -------------------------------------------------
# Documents are PDFs in /wp-content/uploads/ (one site also uses /pdf/). Where
# a site has its cases at the root (/<slug>/), the case pattern lists the menu
# slugs it must not match; a menu page that slips through has no CNJ number and
# yields no case.
WP_UPLOADS_PDF = r"/wp-content/uploads/[^?#]+\.(?i:pdf)$"


def _root_cases(domain: str, menu: str) -> str:
    """Case pages at https://<domain>/<slug>[/], except the menu slugs in ``menu``."""
    return rf"^https://{domain.replace('.', r'\.')}/(?!(?:{menu})/?$)[a-z0-9][a-z0-9-]*/?$"


SITES += (
    Site(domain="k2consultoria.com", aj_name="K2 Consultoria Econômica",
         list_urls=("https://k2consultoria.com/administracao-judicial",),
         case_pattern=_root_cases("k2consultoria.com", "administracao-judicial|modelos|duvidas|contato|home"),
         # Files in uploads, PDFs on the Wix host the old site used, and Google Drive files and folders.
         doc_pattern=(r"/wp-content/uploads/[^?#]+\.(?i:pdf)$|^https://[a-z0-9-]+\.filesusr\.com/ugd/[^?#]+\.(?i:pdf)$"
                      r"|^https://drive\.google\.com/(?:file/d|drive/folders)/"),
         platform="WordPress, cases at /<slug>"),
    Site(domain="bbsadvogados.com.br", aj_name="Brazilio Bacellar, Shirai Advogados",
         list_urls=("https://bbsadvogados.com.br/recuperacao-judicial/",),
         case_pattern=_root_cases("bbsadvogados.com.br",
                                  "somos-bbs|somos-equipe|somos-multidisciplinares|somos-on|contato|recuperacao-judicial|falencia"),
         # Two folders hold the files; the two cartilhas are site brochures, not case documents.
         doc_pattern=r"^https://(?:www\.)?bbsadvogados\.com\.br/(?:pdf|wp-content/uploads/\d{4}/\d{2})/(?!(?i:cartilha))[^?#]+\.(?i:pdf)$",
         platform="WordPress + Elementor, cases at /<slug>"),
    Site(domain="madgav.com.br", aj_name="MADGAV Advogados Associados",
         list_urls=("https://madgav.com.br/recuperacao-judicial/",),
         case_pattern=r"^https://madgav\.com\.br/recuperacao-judicial/[^/?#]+/?$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress + Elementor"),
    # The judicial subdomain of Rodrigues & Zanchetta; its home page lists the cases.
    Site(domain="rroadvogados.adv.br", aj_name="Rodrigues & Zanchetta Administração de Falências",
         list_urls=("https://judicial.rroadvogados.adv.br/",),
         case_pattern=r"^https://judicial\.rroadvogados\.adv\.br/administracoes-judiciais/[^/?#]+/?$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress + Elementor"),
    # FRAJ's document links are /download/<slug>/ redirects to the file.
    Site(domain="fraj.com.br", aj_name="F. Rezende Consultoria e Administração Judicial",
         list_urls=("https://fraj.com.br/recuperacoes-judiciais/",),
         case_pattern=r"^https://fraj\.com\.br/recuperacoes/[^/?#]+/?$",
         doc_pattern=r"^https://fraj\.com\.br/download/[^/?#]+/?$",
         platform="WordPress + Elementor (Agencia MSEO)", debtor_from_title=True),
    # Same theme and case URLs as FRAJ, but direct PDFs; the LGPD notice in the footer is not a case document.
    Site(domain="rlg-aj.com.br", aj_name="RLG Administração Judicial",
         list_urls=("https://rlg-aj.com.br/recuperacoes-judiciais/",),
         case_pattern=r"^https://rlg-aj\.com\.br/recuperacoes/[^/?#]+/?$",
         doc_pattern=r"/wp-content/uploads/\d{4}/\d{2}/(?!LGPD)[^?#]+\.(?i:pdf)$",
         platform="WordPress + Elementor (Agencia MSEO)", debtor_from_title=True),
    Site(domain="clesciogalvao.adv.br", aj_name="Clescio Galvão Sociedade Individual de Advocacia",
         list_urls=("https://clesciogalvao.adv.br/recuperacao-judicial/",),
         case_pattern=_root_cases(
             "clesciogalvao.adv.br",
             "contato|sobre|servicos|direito-[a-z-]+|holding-patrimonial-familiar|recuperacao-judicial-e-falencia|"
             "artigos|links|noticias|politica-de-privacidade|recuperacao-judicial|falencia"),
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress + Elementor"),
    # Documents are Google Drive files; the RJ list is separate from /falencias/.
    Site(domain="fatorfiscal.com.br", aj_name="Fator Fiscal Administração Judicial",
         list_urls=("https://fatorfiscal.com.br/recuperacoes-judiciais/",),
         case_pattern=_root_cases(
             "fatorfiscal.com.br",
             "recuperacoes-judiciais|falencias|habilitacoes-e-divergencias|leiloes|legislacao|contact-2"),
         doc_pattern=r"^https://drive\.google\.com/file/d/[^/]+/view(?:\?usp=(?:sharing|drive_link))?$",
         platform="WordPress + Elementor, documents on Google Drive"),
)
