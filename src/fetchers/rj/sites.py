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
    case_text: str = ""            # optional regex the case anchor's folded text must match (mixed lists)
    debtor_xpath: str = ""         # optional XPath of the element holding the debtor name

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

# Batch 1 (#845): sites with their own CMS, one pattern set each. Lists that mix
# case types keep only the recuperação judicial ones: by URL where the slug or
# folder names the type, by ``case_text`` where only the card does (CB2D).
SITES += (
    # Adobe Muse static export: every case is a flat /<slug>.html next to the menu pages.
    Site(domain="pmmadv.com.br", aj_name="Pinheiro e Marcondes Machado Sociedade de Advogados",
         list_urls=("https://www.pmmadv.com.br/processos---recupera%c3%a7%c3%a3o-judicial.html",),
         case_pattern=r"^https://www\.pmmadv\.com\.br/(?!index\.html|equipe|processos|habilita|contato)[^/?#]+\.html$",
         doc_pattern=r"^https://www\.pmmadv\.com\.br/assets/[^?#]+\.pdf$",
         platform="Adobe Muse export"),
    # N2W: the list also holds falências and extrajudiciais; the slug starts with the type.
    Site(domain="n2wbrasil.com.br", aj_name="N2W Brasil Consultores",
         list_urls=("https://n2wbrasil.com.br/administracao-judicial",),
         case_pattern=r"^https://n2wbrasil\.com\.br/administracao-judicial/recuperacao-judicial-[^/?#]+$",
         doc_pattern=r"^https://n2wbrasil\.com\.br/uploads/(?:judicial_administrations|paragr_adms)/file/[^?#]+$",
         platform="custom CMS", debtor_xpath='//div[contains(@class, "judicial-question-show")]'),
    # Trust: relative links resolve against the page's <base href>.
    Site(domain="trustdobrasil.com.br", aj_name="Trust Serviços Administrativos",
         list_urls=("http://www.trustdobrasil.com.br/processos/recuperacao_judicial",),
         case_pattern=r"^https://www\.trustdobrasil\.com\.br/processos/recuperacao_judicial/[^/?#]+$",
         doc_pattern=r"^https://www\.trustdobrasil\.com\.br/smart/modulos/arquivos/",
         platform="custom PHP CMS"),
    # CB2D: one list page holds every case (the pager is client side); the type is only in the card.
    Site(domain="cb2d.com.br", aj_name="CB2D Serviços Judiciais",
         list_urls=("https://www.cb2d.com.br/processos",),
         case_pattern=r"^https://www\.cb2d\.com\.br/Processos/Detalhe/[^/?#]+$",
         doc_pattern=r"^https://www\.cb2d\.com\.br/portal/_uploads/[0-9a-f-]+\.(?:pdf|docx?|xlsx?)$",
         platform="custom portal", case_text=r"recuperacao judicial"),
    # Integra: Joomla articles, one per case; the link text is "DOWNLOAD AQUI" and the title precedes it.
    Site(domain="integrarecuperacaojudicial.com.br", aj_name="Integra Recuperação Judicial e Falência",
         list_urls=("https://www.integrarecuperacaojudicial.com.br/index.php/processos/recuperacao-judicial",),
         case_pattern=r"^https://www\.integrarecuperacaojudicial\.com\.br/index\.php/processos/recuperacao-judicial/[^/?#]+$",
         doc_pattern=r"^https://www\.integrarecuperacaojudicial\.com\.br/images/recuperacao_judicial/[^?#]+\.pdf$",
         platform="Joomla"),
    # Valorize and JSC: server-rendered Next.js.
    Site(domain="valorizeadmjudicial.com.br", aj_name="Valorize Administração Judicial",
         list_urls=("https://valorizeadmjudicial.com.br/processos?tipo=recuperacao-judicial",),
         case_pattern=r"^https://valorizeadmjudicial\.com\.br/processos/[^/?#]+$",
         doc_pattern=r"^https://valorizeadmjudicial\.com\.br/api/documentos/file/",
         platform="Next.js"),
    Site(domain="jscadministracaojudicial.com.br", aj_name="JSC Administração Judicial",
         list_urls=("https://www.jscadministracaojudicial.com.br/processos",),
         case_pattern=r"^https://www\.jscadministracaojudicial\.com\.br/processos/c[a-z0-9]{24}$",
         doc_pattern=r"^https://cdn\.jscadministracaojudicial\.com\.br/uploads/[^?#]+\.pdf$",
         platform="Next.js"),
)

# WordPress sites whose case pages are a custom post type listed on one page.
SITES += (
    # Recupera Soluções: /processos/<slug>/ is a case, except the "falencia-" and
    # "autofalencia-" slugs, which are bankruptcies and not RJ. Documents come
    # through the Download Attachments plugin (download.php?id=N).
    Site(domain="recuperasolucoes.com", aj_name="Recupera Soluções Empresariais",
         list_urls=("https://recuperasolucoes.com/processos/",),
         case_pattern=r"^https://recuperasolucoes\.com/processos/(?!falencia-|autofalencia-)[^/?#]+/$",
         doc_pattern=r"/wp-content/plugins/download-attachments/includes/download\.php\?id=\d+$",
         platform="WordPress, Download Attachments"),
    # Paoli Balbino & Balbino: /cliente/<slug>/ is a case; the only document
    # link on a case page is the Google Drive folder that holds its main acts.
    Site(domain="pbbadvogados.com.br", aj_name="Paoli Balbino & Balbino Sociedade de Advogados",
         list_urls=("https://pbbadvogados.com.br/recuperacoes-judiciais/",),
         case_pattern=r"^https://pbbadvogados\.com\.br/cliente/[^/?#]+/$",
         doc_pattern=r"^https://drive\.google\.com/drive/(?:u/\d+/)?folders/",
         platform="WordPress, Google Drive folders"),
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
