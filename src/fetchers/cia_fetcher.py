"""CIA_ABERTA fetcher — downloads yearly ZIP archives from dados.cvm.gov.br
and enumerates their member CSVs for the listed-companies domain (Domain B).

ITR and DFP zips each contain ~19 CSV members:
  - One per financial statement type x accounting scope (con=consolidated, ind=individual)
  - A summary header CSV (e.g. itr_cia_aberta_2024.csv)
  - composicao_capital and parecer CSVs

Public surface
--------------
CIAFetcher().fetch_zip_members(doc_type, year) -> List[CIAMember]

Each CIAMember exposes:
  .member_name  — raw filename inside the zip (e.g. "itr_cia_aberta_BPA_con_2024.csv")
  .grupo        — statement type slug (e.g. "BPA", "DRE", "composicao_capital")
  .escopo       — "con" | "ind" | None  (None for non-scoped members like parecer)
  .rows         — list[dict] parsed from the CSV

For CAD (single flat CSV, no year parameter) use the standard CVMFetcher.fetch():
  CVMFetcher().fetch("cia_aberta", "cad")

For IPE (single CSV inside yearly ZIP) also use CVMFetcher.fetch():
  CVMFetcher().fetch("cia_aberta", "ipe", year=2024)

Design notes
------------
- Reuses CVMFetcher internals (_download, _parse_csv) to get retry, DNS rotation,
  and on-disk caching for free.
- Does NOT store to the database — callers own the upsert logic.
- Encoding: latin-1 (same as all other CVM CSV files).
- Separator: ";" (same as all other CVM CSV files).
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from .cvm_config import config, dataset_config
from .cvm_fetcher import CVMFetcher

logger = logging.getLogger(__name__)

# Regex to extract grupo + escopo from a member filename.
# Examples:
#   itr_cia_aberta_BPA_con_2024.csv   -> grupo=BPA,  escopo=con
#   dfp_cia_aberta_DFC_MD_ind_2024.csv-> grupo=DFC_MD, escopo=ind
#   itr_cia_aberta_composicao_capital_2024.csv -> grupo=composicao_capital, escopo=None
#   itr_cia_aberta_parecer_2024.csv   -> grupo=parecer, escopo=None
#   itr_cia_aberta_2024.csv           -> grupo=_summary, escopo=None
# Matches statement members: itr_cia_aberta_BPA_con_2024.csv
#   -> rest = "BPA_con"
# Also matches: itr_cia_aberta_composicao_capital_2024.csv
#   -> rest = "composicao_capital"
_MEMBER_RE = re.compile(
    r"(?:itr|dfp)_cia_aberta_"  # prefix
    r"(?P<rest>.+?)"             # everything between prefix and _YYYY.csv
    r"_\d{4}\.csv$",
    re.IGNORECASE,
)

# Matches the top-level header file: itr_cia_aberta_2024.csv (no inner segment)
_SUMMARY_RE = re.compile(
    r"(?:itr|dfp)_cia_aberta_\d{4}\.csv$",
    re.IGNORECASE,
)

_SCOPED_SUFFIXES = {"con", "ind"}


def _parse_member_name(filename: str, doc_type: str) -> tuple[str, Optional[str]]:
    """Return (grupo, escopo) for a zip member filename.

    Returns ("_summary", None) for the top-level header CSV
    (e.g. itr_cia_aberta_2024.csv) which contains general filing metadata
    and not line-item account data.
    """
    # Check for the summary header file first (no inner segment).
    if _SUMMARY_RE.match(filename):
        return "_summary", None

    m = _MEMBER_RE.match(filename)
    if not m:
        # Unexpected name — return the raw stem as grupo.
        return filename.rsplit(".", 1)[0], None

    rest = m.group("rest")  # e.g. "BPA_con", "DFC_MD_ind", "composicao_capital", "parecer"

    # Check whether the last segment is a scope token.
    parts = rest.rsplit("_", 1)
    if len(parts) == 2 and parts[1].lower() in _SCOPED_SUFFIXES:
        grupo = parts[0]           # e.g. "BPA", "DFC_MD", "DRE"
        escopo = parts[1].lower()  # "con" or "ind"
    else:
        grupo = rest               # e.g. "composicao_capital", "parecer"
        escopo = None

    return grupo, escopo


@dataclass
class CIAMember:
    """One CSV extracted from an ITR or DFP yearly zip."""

    member_name: str
    """Raw filename inside the zip (e.g. 'itr_cia_aberta_BPA_con_2024.csv')."""

    grupo: str
    """Statement type slug: BPA | BPP | DRE | DFC_MD | DFC_MI | DMPL | DRA | DVA
    | composicao_capital | parecer | _summary."""

    escopo: Optional[str]
    """Accounting scope: 'con' (consolidated) | 'ind' (individual) | None."""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    """Parsed CSV rows as list of dicts (keys = column headers)."""

    @property
    def is_account_data(self) -> bool:
        """True for scoped statement members (BPA/BPP/DRE/etc.) that feed cia_account."""
        return self.escopo is not None

    @property
    def is_summary(self) -> bool:
        return self.grupo == "_summary"


class CIAFetcher:
    """Fetcher for the CIA_ABERTA domain.

    Wraps CVMFetcher to add multi-CSV zip enumeration needed by ITR and DFP.
    """

    def __init__(self) -> None:
        self._fetcher = CVMFetcher()

    # ----------------------------------------------------------------- public

    def fetch_zip_members(
        self,
        doc_type: str,
        year: int,
        *,
        include_summary: bool = False,
        statement_filter: Optional[List[str]] = None,
    ) -> List[CIAMember]:
        """Download the yearly ZIP for doc_type (itr|dfp) and enumerate all
        member CSVs.

        Parameters
        ----------
        doc_type:
            "itr" or "dfp"
        year:
            Calendar year (e.g. 2024). Data available from ~2010 for DFP, ~2012 for ITR.
        include_summary:
            If True, also return the top-level header CSV (grupo="_summary") which
            contains general filing metadata (not line-item account data).
        statement_filter:
            Optional whitelist of grupo slugs (e.g. ["BPA", "DRE"]). When provided,
            only members whose grupo is in the list are parsed and returned.
            Non-scoped members (composicao_capital, parecer) are identified by their
            full grupo name.

        Returns
        -------
        List[CIAMember] — one entry per matching CSV member, in zip-order.
        """
        import asyncio

        doc_type = doc_type.lower()
        if doc_type not in ("itr", "dfp"):
            raise ValueError(f"CIAFetcher.fetch_zip_members only supports itr/dfp; got {doc_type!r}")

        ds = dataset_config.get_dataset_config("cia_aberta", doc_type)
        url = ds["url_pattern"].format(base_url=self._fetcher.base_url, year=year)
        logger.info(f"CIA fetch: cia_aberta/{doc_type} year={year} -> {url}")

        zip_content = asyncio.run(self._fetcher._download(url))
        return list(self._enumerate_members(zip_content, doc_type, year, include_summary, statement_filter))

    async def fetch_zip_members_async(
        self,
        doc_type: str,
        year: int,
        *,
        include_summary: bool = False,
        statement_filter: Optional[List[str]] = None,
    ) -> List[CIAMember]:
        """Async variant of fetch_zip_members for use inside async pipelines."""
        doc_type = doc_type.lower()
        if doc_type not in ("itr", "dfp"):
            raise ValueError(f"CIAFetcher.fetch_zip_members_async only supports itr/dfp; got {doc_type!r}")

        ds = dataset_config.get_dataset_config("cia_aberta", doc_type)
        url = ds["url_pattern"].format(base_url=self._fetcher.base_url, year=year)
        logger.info(f"CIA async fetch: cia_aberta/{doc_type} year={year} -> {url}")

        zip_content = await self._fetcher._download(url)
        return list(self._enumerate_members(zip_content, doc_type, year, include_summary, statement_filter))

    # ----------------------------------------------------------------- internals

    def _enumerate_members(
        self,
        zip_content: bytes,
        doc_type: str,
        year: int,
        include_summary: bool,
        statement_filter: Optional[List[str]],
    ) -> Iterator[CIAMember]:
        """Unpack and parse each CSV member from zip_content."""
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            csv_members = sorted(
                (name for name in zf.namelist() if name.lower().endswith(".csv")),
                key=str.lower,
            )

            if not csv_members:
                raise ValueError(
                    f"No CSV files found in {doc_type}_cia_aberta_{year}.zip. "
                    f"Zip contents: {zf.namelist()}"
                )

            for member_name in csv_members:
                grupo, escopo = _parse_member_name(member_name, doc_type)

                if grupo == "_summary" and not include_summary:
                    logger.debug(f"CIA skip summary member: {member_name}")
                    continue

                if statement_filter is not None and grupo not in statement_filter:
                    logger.debug(f"CIA skip filtered member: {member_name} (grupo={grupo!r})")
                    continue

                csv_text = zf.read(member_name).decode(self._fetcher.encoding)
                rows = self._fetcher._parse_csv(csv_text)
                logger.debug(f"CIA member: {member_name} grupo={grupo!r} escopo={escopo!r} rows={len(rows)}")

                yield CIAMember(
                    member_name=member_name,
                    grupo=grupo,
                    escopo=escopo,
                    rows=rows,
                )
