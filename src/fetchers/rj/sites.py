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
    case_card: bool = False        # case_text matches the whole list card, not only the anchor text
    debtor_xpath: str = ""         # optional XPath of the element holding the debtor name
    debtor_from_title: bool = False  # the page <title> names the debtor; its headings are document titles
    case_section: str = ""         # optional regex the heading above a case link must match (lists grouped by type)
    case_scope: str = ""           # optional XPath of the elements the case links must sit inside
    doc_title_xpath: str = ""      # optional XPath, from a "Download" button, to the element holding its title

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
# Batch 3. WordPress sites whose case pages are plain posts and whose documents
# are PDFs under wp-content/uploads.
WP_UPLOADS_PDF = r"/wp-content/uploads/[^?#]+\.(?i:pdf)$"

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
# WordPress sites with a custom post type per case. Each has its own slug, so
# each carries its own patterns; documents are PDFs in wp-content/uploads
# (icon-only links, titled from the file name) or Google Drive file links.

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
# --- Batch 6: WordPress sites -------------------------------------------------
# Documents are PDFs in /wp-content/uploads/ (one site also uses /pdf/). Where
# a site has its cases at the root (/<slug>/), the case pattern lists the menu
# slugs it must not match; a menu page that slips through has no CNJ number and
# yields no case.


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

# --- Batch 7: WordPress + Elementor sites ---------------------------------------
# Documents are PDFs in /wp-content/uploads/ unless the site says otherwise.
SITES += (
    # Case pages are /processo/<slug>/ (the falência list is /falencia/).
    Site(domain="mdse.com.br", aj_name="MD Serviços Empresariais Ltda",
         list_urls=("https://mdse.com.br/recuperacao-judicial/",),
         case_pattern=r"^https://mdse\.com\.br/processo/[^/?#]+/$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress + Elementor"),
    # The case rows are clickable Elementor containers (data-ha-element-link), not anchors.
    Site(domain="administracaojudicialrs.com.br", aj_name="Albarello & Schmitz Administração Judicial",
         list_urls=("https://administracaojudicialrs.com.br/casos/",),
         case_pattern=r"^https://administracaojudicialrs\.com\.br/caso/[^/?#]+/$",
         # Newer cases link the PDFs in uploads, older ones /download/<id>/?tmstv=... redirects.
         doc_pattern=r"^https://administracaojudicialrs\.com\.br(?:/download/\d+/|/wp-content/uploads/[^?#]+\.(?i:pdf)$)",
         platform="WordPress + Elementor, custom post type"),
    # Case pages sit at the root, beside the menu pages and four articles; the cases are
    # the icon-list links (the falências are pop-ups). The
    # <title> is "<debtor> - Cleverson Neves". The footer holds four creditor-form
    # templates ("Modelo"), which are not case documents.
    Site(domain="cleversonneves.com.br", aj_name="Cleverson Neves Advogados & Consultores",
         list_urls=("https://www.cleversonneves.com.br/adm-judicial/",),
         case_pattern=r"^https://www\.cleversonneves\.com\.br/(?!(?:adm-judicial|conteudos?|contato|equipe)/?$)[a-z0-9][a-z0-9-]*/$",
         case_scope='//li[contains(@class, "elementor-icon-list-item")]', debtor_from_title=True,
         doc_pattern=r"^https://www\.cleversonneves\.com\.br/wp-content/uploads/(?![^?#]*Modelo)[^?#]+\.(?i:pdf)$",
         platform="WordPress + Elementor, cases at /<slug>"),
    # Sibling lists /extrajudicial/ and /falencia/ are separate pages.
    Site(domain="vtladm.com.br", aj_name="VTL Consultoria Empresarial Ltda",
         list_urls=("https://vtladm.com.br/recuperacao-judicial/",),
         case_pattern=r"^https://vtladm\.com\.br/recuperacao-judicial/[^/?#]+/$",
         doc_pattern=WP_UPLOADS_PDF, platform="WordPress + Elementor"),
    # Documents are WordPress Download Manager links /download/<slug>/ with no text; the
    # title is the slug. The list also links a staging host by IP, which the pattern leaves out.
    Site(domain="ecconsultoria.com.br", aj_name="EC Consultoria e Administração Ltda",
         list_urls=("https://www.ecconsultoria.com.br/recuperacoes-judiciais/",),
         case_pattern=(r"^https://www\.ecconsultoria\.com\.br/"
                       r"(?!(?:duvidas|falencias|recuperacoes-judiciais|contato|download)/)[a-z0-9-]+/$"),
         doc_pattern=r"^https://www\.ecconsultoria\.com\.br/download/[^/?#]+/?$",
         platform="WordPress + Elementor + Download Manager"),
    # One list page groups the cases under "Recuperação Judicial", "Falência" and
    # "Insolvência Civil"; each item is a JetEngine container (data-url).
    Site(domain="gomesdemattos.com.br", aj_name="Gomes de Mattos Advogados Associados",
         list_urls=("https://gomesdemattos.com.br/admjudicial/processos/",),
         case_pattern=r"^https://gomesdemattos\.com\.br/admjudicial/lista-de-processos/[^/?#]+/$",
         case_section=r"^recuperacao judicial$",
         # Each document is a row of fields (date, title, "Download" button): the title is the
         # nearest non-empty field before the button.
         doc_title_xpath='preceding::div[contains(@class, "jet-listing-dynamic-field__content")][normalize-space()][1]',
         doc_pattern=r"^https://gomesdemattos\.com\.br/admjudicial" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor + JetEngine"),
    # The recuperações judiciais list is separate from the falência and extrajudicial lists.
    Site(domain="costatellesadjud.com.br", aj_name="Costa Telles Administração Judicial Ltda",
         list_urls=("https://costatellesadjud.com.br/processos/recuperaoes-judiciais/",),
         case_pattern=r"^https://costatellesadjud\.com\.br/recuperacao-judicial/[^/?#]+/$",
         doc_pattern=r"^https://costatellesadjud\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor, custom post type"),
)

# --- Batch 12: custom sites ----------------------------------------------------
SITES += (
    # Matuch de Carvalho: a Rails app. The RJ list is a table whose rows carry
    # onclick="window.location='/processo/<id>'"; falências have their own /falencia list.
    # Each document is a /admin/reports/<id>/download_all link, titled in the list item.
    Site(domain="mcaa.adv.br", aj_name="Matuch de Carvalho Advogados Associados",
         list_urls=("https://www.mcaa.adv.br/recuperacao-judicial",),
         case_pattern=r"^https://www\.mcaa\.adv\.br/processo/[A-Za-z0-9]+$",
         doc_pattern=r"^https://www\.mcaa\.adv\.br/admin/reports/[A-Za-z0-9]+/download_all$",
         platform="custom Rails app"),
    # Zveiter: the "Recuperações" menu lists every case, falências too (airmix, canaamates, txrx,
    # gas), and the type is only on the case page, so the pattern names the recuperação slugs.
    # grppetro, americanas, transporte and costapereira print no CNJ number in the page text
    # (only in file names), so they yield no case and are left out. Document links are relative PDFs.
    Site(domain="zveiter.com.br", aj_name="Escritório de Advocacia Zveiter",
         list_urls=("https://zveiter.com.br/recuperacao",),
         case_pattern=(r"^https://zveiter\.com\.br/(?:mintucano|transcarioca|stcruz|kpfr|rodopetro|qldtotal|rnr)$"),
         doc_pattern=r"^https://zveiter\.com\.br/assets/pdfs/[^?#]+\.(?i:pdf)$",
         platform="custom static site", debtor_xpath="//h1[contains(@class, 'page-hero-title')]"),
)

# Batch 8 (#845).
# Luidy.com.br's "lawyer directory" plugin (Diligence, LRF Líderes): every case is
# /processos/<slug>/ and the card, not the link, prints the type, so ``case_card``
# keeps the recuperação cards. Documents come through Download Attachments
# (download.php?id=N) or plain uploads.
LUIDY_DOC = (r"/wp-content/plugins/download-attachments/includes/download\.php\?id=\d+$"
             r"|/wp-content/uploads/[^?#]+\.(?i:pdf)$")

SITES += (
    # Cases are /recuperacao-judicial/<slug>/ (the falências are under /falencia/); the files are
    # SharePoint share links, one "Download" button each.
    Site(domain="julianamorais.com.br", aj_name="Juliana Morais Sociedade de Advogados",
         list_urls=("https://julianamorais.com.br/recuperacao-judicial/",),
         case_pattern=r"^https://julianamorais\.com\.br/recuperacao-judicial/[a-z0-9-]+/$",
         doc_pattern=r"^https://julianamorais-my\.sharepoint\.com/:b:/",
         debtor_xpath='//h2[contains(@class, "elementor-heading-title")]',
         platform="WordPress + Elementor, documents on SharePoint"),
    # Cases are blog posts in a category archive; only the /rj-<name>/ slugs are read (news posts
    # and a few cases without the prefix are not told apart by URL). The habilitação and
    # divergência forms are templates, not case documents.
    Site(domain="stenius.com.br", aj_name="Stenius Lacerda Bastos",
         list_urls=("https://stenius.com.br/category/recuperacao-judicial/",
                    "https://stenius.com.br/category/recuperacao-judicial/page/2/"),
         case_pattern=r"^https://stenius\.com\.br/rj-[a-z0-9-]+/$",
         doc_pattern=r"/wp-content/uploads/\d{4}/\d{2}/(?!mod-)[^?#]+\.(?i:pdf)$",
         platform="WordPress + Elementor", debtor_from_title=True),
    Site(domain="diligence.adm.br", aj_name="Diligence Administração em Recuperação Judicial e Falência",
         list_urls=("https://diligence.adm.br/processos/",),
         case_pattern=r"^https://diligence\.adm\.br/processos/(?!processo-modelo)[a-z0-9-]+/$",
         doc_pattern=LUIDY_DOC, platform="WordPress + WPBakery (Luidy.com.br)",
         case_text=r"recuperacao judicial", case_card=True),
    Site(domain="lrflideres.com.br", aj_name="LRF Líderes em Recuperação Judicial, Falência e Consultoria Empresarial",
         list_urls=("https://lrflideres.com.br/processos/",),
         case_pattern=r"^https://lrflideres\.com\.br/processos/[a-z0-9-]+/$",
         doc_pattern=LUIDY_DOC, platform="WordPress + WPBakery (Luidy.com.br)",
         case_text=r"recuperacao (?:judicial|extra ?judicial)", case_card=True,
         debtor_xpath='//h2[not(@class)]'),
    # Attorna theme: cases are /recuperacao-judicial/<slug>/.
    # Its /page/2/ repeats the first page's cases, so only the first is read.
    Site(domain="inova-aj.com.br", aj_name="Inova Administração Judicial",
         list_urls=("https://inova-aj.com.br/recuperacao-judicial/",),
         case_pattern=r"^https://inova-aj\.com\.br/recuperacao-judicial/(?!page/)[^/?#]+/?$",
         doc_pattern=r"/wp-content/uploads/[^?#]+\.(?i:pdf)$", platform="WordPress (attorna theme)"),
)

# --- Batch 9: WordPress sites -------------------------------------------------
# Documents are PDFs in /wp-content/uploads/. Credibilità (cases link out to a
# microsite for documents), CSH (no process number on the case pages), Wald (generic
# document links, most of them on sub-pages) and Campi (falências filed under the same
# /recuperacoes/ folder as RJ cases, type only in free text) are not read.
SITES += (
    # AJUDD: cards for RJ, falência, espólio and insolvência civil share one list;
    # the RJ ones carry "recuperacao-judicial" in the slug.
    Site(domain="ajudd.com.br", aj_name="Victor Barbosa Dutra",
         list_urls=("https://www.ajudd.com.br/recuperacao-judicial-e-falencia/",),
         case_pattern=r"^https://www\.ajudd\.com\.br/recuperacao-judicial-e-falencia/[^/?#]*recuperacao-judicial[^/?#]*/$",
         doc_pattern=r"^https://www\.ajudd\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor", debtor_from_title=True),
    Site(domain="chaves-soletti.adv.br", aj_name="Chaves & Soletti Advogados",
         list_urls=("https://chaves-soletti.adv.br/recuperacao-judicial/",),
         case_pattern=r"^https://chaves-soletti\.adv\.br/atuacao/recuperacao-judicial/[^/?#]+/$",
         doc_pattern=r"^https://chaves-soletti\.adv\.br" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor"),
    # Cury: the page prints the main process first and its RMA incident second.
    Site(domain="curyconsultores.com.br", aj_name="Cury Administradora Judicial",
         list_urls=("https://curyconsultores.com.br/recuperacao-judicial/",),
         case_pattern=r"^https://curyconsultores\.com\.br/credor/[^/?#]+/$",
         doc_pattern=r"^https://curyconsultores\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor"),
    # Faccio: cases at the root; the active and the inactive RJ lists.
    Site(domain="faccioadministracoes.com.br", aj_name="Faccio Administrações Judiciais",
         list_urls=("https://faccioadministracoes.com.br/recuperacoes-judiciais-ativas/",
                    "https://faccioadministracoes.com.br/recuperacoes-judiciais-inativas/"),
         case_pattern=_root_cases(
             "faccioadministracoes.com.br",
             "quem-somos|falencias(?:-ativas|-encerradas)?|recuperacoes-judiciais(?:-ativas|-inativas)?|"
             "contato|politica-de-privacidade(?:-2)?"),
         doc_pattern=r"^https://faccioadministracoes\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor"),
    # Fatto: cases at the root; the RJ portal page only (falência and extrajudicial are other portals).
    Site(domain="fattoonline.com.br", aj_name="Fatto Administração Judicial",
         list_urls=("https://fattoonline.com.br/portal-de-processos/recuperacao-judicial/",),
         case_pattern=_root_cases(
             "fattoonline.com.br",
             "institucional|portal-de-processos|habilitacao-e-divergencia|newsletters|contato|home|portal"),
         doc_pattern=r"^https://fattoonline\.com\.br" + WP_UPLOADS_PDF,
         platform="WordPress + Elementor"),
)
