"""CVM URL templates and dataset configuration."""

import os
from enum import Enum
from typing import Dict, List


class FetcherConfig:
    CVM_BASE_URL = os.getenv("CVM_BASE_URL", "https://dados.cvm.gov.br/dados")

    TEMP_DIR = os.path.join(os.getcwd(), "temp")
    CACHE_DIR = os.path.join(os.getcwd(), "cache")
    ENCODING = "latin-1"
    CSV_SEPARATOR = ";"

    REQUEST_TIMEOUT = int(os.getenv("CVM_REQUEST_TIMEOUT", "300"))
    MAX_RETRIES = int(os.getenv("CVM_MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("CVM_RETRY_DELAY", "2"))

    CVM_DNS_NAMESERVERS = os.getenv("CVM_DNS_NAMESERVERS", "1.1.1.1,8.8.8.8,9.9.9.9")


class EntityType(str, Enum):
    FI = "fi"
    FIDC = "fidc"
    FIP = "fip"
    FIAGRO = "fiagro"
    FII = "fii"
    SECURIT = "securit"
    CIA_ABERTA = "cia_aberta"


class DatasetConfig:
    """Only endpoints that actually exist on dados.cvm.gov.br are listed here.
    Endpoints that returned 404 (FIDC/FIP/FIAGRO cadastral / trimestral / anual,
    FIP dfin, SECURIT lca/lci) were intentionally removed."""

    FI_DATASETS: Dict[str, Dict] = {
        # Historical formats (HIST/ directory) — yearly ZIPs, single CSV inside.
        # inf_diario HIST covers 2000-2020; monthly format works from 2021+.
        # cda        HIST covers 2005-2022; monthly format works from 2023+.
        "hist_inf_diario": {
            "url_pattern": "{base_url}/FI/DOC/INF_DIARIO/DADOS/HIST/inf_diario_fi_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_diario_fi_{year}.csv",
            "description": "FI daily snapshots historical (2000-2020) — yearly HIST/ ZIP",
        },
        "hist_cda": {
            "url_pattern": "{base_url}/FI/DOC/CDA/DADOS/HIST/cda_fi_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "cda_fi_{year}.csv",
            "description": "FI portfolio composition historical (2005-2022) — yearly HIST/ ZIP",
        },
        "cad": {
            "url_pattern": "{base_url}/FI/CAD/DADOS/cad_fi.csv",
            "is_zip": False,
            "description": "FI fund registry — DENOM_SOCIAL, SIT, DT_REG, DT_CANCEL (static file, no year/month)",
        },
        # CVM-175 unified registry (registro_fundo_classe.zip): the post-2023
        # active universe across ALL fund families (FIF/FII/FIDC/FIP/FIAGRO/…).
        # cad_fi.csv is now ~99% cancelled legacy funds, so these supply the
        # clean names + current status. Same zip, two CSV members.
        "registro_classe": {
            "url_pattern": "{base_url}/FI/CAD/DADOS/registro_fundo_classe.zip",
            "is_zip": True,
            "csv_name_pattern": "registro_classe.csv",
            "description": "CVM-175 class registry (CNPJ_Classe) — matches inf_diario CNPJ_FUNDO_CLASSE (2023+)",
        },
        "registro_fundo": {
            "url_pattern": "{base_url}/FI/CAD/DADOS/registro_fundo_classe.zip",
            "is_zip": True,
            "csv_name_pattern": "registro_fundo.csv",
            "description": "CVM-175 fund registry (CNPJ_Fundo) — fund-level name/status/cancel date",
        },
        "inf_diario": {
            "url_pattern": "{base_url}/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_diario_fi_{year}{month:02d}.csv",
            "description": "Daily fund snapshot (quota price, NAV, flows, quotaholders) — monthly ZIP",
        },
        "cda": {
            "url_pattern": "{base_url}/FI/DOC/CDA/DADOS/cda_fi_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "cda_fi_BLC_1_{year}{month:02d}.csv",
            "description": "Portfolio composition by asset class — monthly ZIP",
        },
        "perfil_mensal": {
            "url_pattern": "{base_url}/FI/DOC/PERFIL_MENSAL/DADOS/perfil_mensal_fi_{year}{month:02d}.csv",
            "is_zip": False,
            "description": "Monthly investor profile (type, concentration) — monthly CSV",
        },
        "balancete": {
            "url_pattern": "{base_url}/FI/DOC/BALANCETE/DADOS/balancete_fi_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "balancete_fi_{year}{month:02d}.csv",
            "description": "Monthly balance sheet — monthly ZIP",
        },
    }

    FII_DATASETS: Dict[str, Dict] = {
        "cad": {
            "url_pattern": "{base_url}/FII/CAD/DADOS/cad_fii.csv",
            "is_zip": False,
            "description": "FII fund registry — DENOM_SOCIAL, SIT, DT_REG, DT_CANCEL (static file, no year/month)",
        },
        "mensal_geral": {
            "url_pattern": "{base_url}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fii_geral_{year}.csv",
            "description": "Monthly general summary for FII funds — yearly ZIP",
        },
        "mensal_ativo_passivo": {
            "url_pattern": "{base_url}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fii_ativo_passivo_{year}.csv",
            "description": "Monthly assets and liabilities for FII funds — yearly ZIP",
        },
        "mensal_complemento": {
            "url_pattern": "{base_url}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fii_complemento_{year}.csv",
            "description": "Monthly complementary summary for FII funds — contains Patrimonio_Liquido — yearly ZIP",
        },
        "trimestral": {
            "url_pattern": "{base_url}/FII/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_trimestral_fii_{year}.csv",
            "description": "Quarterly report for FII funds — yearly ZIP",
        },
        "anual": {
            "url_pattern": "{base_url}/FII/DOC/INF_ANUAL/DADOS/inf_anual_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_anual_fii_{year}.csv",
            "description": "Annual report for FII funds — yearly ZIP",
        },
        "dfin": {
            "url_pattern": "{base_url}/FII/DOC/DFIN/DADOS/dfin_fii_{year}.csv",
            "is_zip": False,
            "description": "FII financial statements — yearly CSV",
        },
    }

    FIDC_DATASETS: Dict[str, Dict] = {
        # ---------------------------------------------------------------------------
        # Historical format (2013–2024): yearly ZIP in HIST/, monthly CSVs inside.
        # URL uses {year} only; {month} selects the CSV inside the ZIP.
        # tab_II = asset/portfolio composition; tab_III = liabilities.
        # PL = TAB_II_VL_CARTEIRA - TAB_III_VL_PASSIVO.
        # ---------------------------------------------------------------------------
        "hist_mensal_tab_ii": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/HIST/inf_mensal_fidc_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_II_{year}{month:02d}.csv",
            "description": "FIDC historical assets (tab II, 2013-2024) — yearly HIST/ ZIP, monthly CSV inside",
        },
        "hist_mensal_tab_iii": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/HIST/inf_mensal_fidc_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_III_{year}{month:02d}.csv",
            "description": "FIDC historical liabilities (tab III, 2013-2024) — yearly HIST/ ZIP, monthly CSV inside",
        },
        "mensal": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_IV_{year}{month:02d}.csv",
            "description": "Monthly information for FIDC funds — targets tab_IV (NAV/PL)",
        },
        "mensal_tab_vi": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_VI_{year}{month:02d}.csv",
            "description": "FIDC tab_VI — credits without risk, maturity aging + delinquency buckets",
        },
        "mensal_tab_x2": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_X_2_{year}{month:02d}.csv",
            "description": "FIDC tab_X_2 — quota quantity and price per tranche/series",
        },
        "mensal_tab_x3": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_X_3_{year}{month:02d}.csv",
            "description": "FIDC tab_X_3 — monthly return % per tranche/series",
        },
        "mensal_tab_x4": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_X_4_{year}{month:02d}.csv",
            "description": "FIDC tab_X_4 — monthly flows (captações/resgates) per tranche/series",
        },
        "mensal_tab_x6": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_tab_X_6_{year}{month:02d}.csv",
            "description": "FIDC tab_X_6 — expected vs actual performance % per tranche/series",
        },
    }

    FIP_DATASETS: Dict[str, Dict] = {
        "inf_quadrimestral": {
            "url_pattern": "{base_url}/FIP/DOC/INF_QUADRIMESTRAL/DADOS/inf_quadrimestral_fip_{year}.csv",
            "is_zip": False,
            "description": "Four-month period information for FIP funds — yearly CSV (2024+)",
        },
        "inf_trimestral": {
            "url_pattern": "{base_url}/FIP/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fip_{year}.csv",
            "is_zip": False,
            "description": "Quarterly information for FIP funds — yearly CSV (2010–2023)",
        },
    }

    FIAGRO_DATASETS: Dict[str, Dict] = {
        "mensal": {
            "url_pattern": "{base_url}/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fiagro_{year}{month:02d}.csv",
            "description": "Monthly information for FIAGRO funds (available from May 2025)",
        },
    }

    # ---------------------------------------------------------------------------
    # CIA_ABERTA — Listed companies (Domain B, W5 scaffold)
    #
    # URL patterns verified against dados.cvm.gov.br (2026-05-29):
    #   CAD  — single static CSV (no year/month)
    #   IPE  — yearly ZIP, single CSV inside (ipe_cia_aberta_{YYYY}.csv)
    #   ITR  — yearly ZIP, 19 CSV members:
    #              8 statement types x 2 scopes (con/ind) +
    #              itr_cia_aberta_{YYYY}.csv (general header),
    #              composicao_capital, parecer
    #   DFP  — same structure as ITR (19 members, prefix dfp_)
    #
    # For ITR/DFP the multi-CSV nature is handled by CIAFetcher.fetch_zip_members()
    # in src/fetchers/cia_fetcher.py — not by the standard CVMFetcher.fetch().
    # ---------------------------------------------------------------------------
    CIA_ABERTA_DATASETS: Dict[str, Dict] = {
        "cad": {
            "url_pattern": "{base_url}/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv",
            "is_zip": False,
            "multi_csv": False,
            "description": "Listed-company registry — CNPJ, DENOM_CIA, setor, segmento, situacao (static file, no year)",
        },
        "ipe": {
            "url_pattern": "{base_url}/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip",
            "is_zip": True,
            "multi_csv": False,
            "csv_name_pattern": "ipe_cia_aberta_{year}.csv",
            "description": "Eventual press events (IPE) — single CSV per yearly ZIP",
        },
        "itr": {
            "url_pattern": "{base_url}/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{year}.zip",
            "is_zip": True,
            "multi_csv": True,
            "csv_member_prefix": "itr_cia_aberta_",
            "statement_types": [
                "BPA_con", "BPA_ind",
                "BPP_con", "BPP_ind",
                "DFC_MD_con", "DFC_MD_ind",
                "DFC_MI_con", "DFC_MI_ind",
                "DMPL_con", "DMPL_ind",
                "DRA_con", "DRA_ind",
                "DRE_con", "DRE_ind",
                "DVA_con", "DVA_ind",
                "composicao_capital",
                "parecer",
            ],
            "description": (
                "Quarterly ITR financial statements — yearly ZIP with ~19 CSVs "
                "(8 statement types x con/ind scopes + composicao_capital + parecer). "
                "Use CIAFetcher.fetch_zip_members() to enumerate."
            ),
        },
        "dfp": {
            "url_pattern": "{base_url}/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip",
            "is_zip": True,
            "multi_csv": True,
            "csv_member_prefix": "dfp_cia_aberta_",
            "statement_types": [
                "BPA_con", "BPA_ind",
                "BPP_con", "BPP_ind",
                "DFC_MD_con", "DFC_MD_ind",
                "DFC_MI_con", "DFC_MI_ind",
                "DMPL_con", "DMPL_ind",
                "DRA_con", "DRA_ind",
                "DRE_con", "DRE_ind",
                "DVA_con", "DVA_ind",
                "composicao_capital",
                "parecer",
            ],
            "description": (
                "Annual DFP financial statements — yearly ZIP with ~19 CSVs "
                "(8 statement types x con/ind scopes + composicao_capital + parecer). "
                "Use CIAFetcher.fetch_zip_members() to enumerate."
            ),
        },
    }

    SECURIT_DATASETS: Dict[str, Dict] = {
        "cra_mensal": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cra_ativo_passivo_{year}.csv",
            "description": "Monthly CRA securitization data — yearly ZIP",
        },
        "cri_mensal": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRI/DADOS/inf_mensal_cri_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cri_ativo_passivo_{year}.csv",
            "description": "Monthly CRI securitization data — yearly ZIP",
        },
        "ots_mensal": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_OTS/DADOS/inf_mensal_ots_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_ots_ativo_passivo_{year}.csv",
            "description": "Monthly securitization data for other titles — yearly ZIP",
        },
        "cra_classe": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cra_classe_{year}.csv",
            "description": "CRA per-series data (rating, situacao, yield, subordination) — yearly ZIP",
        },
        "cra_fluxo": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cra_fluxo_caixa_{year}.csv",
            "description": "CRA monthly cash flows by tranche class — yearly ZIP",
        },
        "cri_classe": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRI/DADOS/inf_mensal_cri_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cri_classe_{year}.csv",
            "description": "CRI per-series data (rating, situacao, yield, subordination) — yearly ZIP",
        },
        "cri_fluxo": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRI/DADOS/inf_mensal_cri_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cri_fluxo_caixa_{year}.csv",
            "description": "CRI monthly cash flows by tranche class — yearly ZIP",
        },
        "ots_classe": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_OTS/DADOS/inf_mensal_ots_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_ots_classe_{year}.csv",
            "description": "OTS per-series data (rating, situacao, yield, subordination) — yearly ZIP",
        },
        "ots_fluxo": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_OTS/DADOS/inf_mensal_ots_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_ots_fluxo_caixa_{year}.csv",
            "description": "OTS monthly cash flows by tranche class — yearly ZIP",
        },
        "dfin_cra": {
            "url_pattern": "{base_url}/SECURIT/DOC/DFIN_CRA/DADOS/dfin_cra_{year}.csv",
            "is_zip": False,
            "description": "CRA financial statements — yearly CSV (2019+)",
        },
        "dfin_cri": {
            "url_pattern": "{base_url}/SECURIT/DOC/DFIN_CRI/DADOS/dfin_cri_{year}.csv",
            "is_zip": False,
            "description": "CRI financial statements — yearly CSV (2018+)",
        },
    }

    @classmethod
    def get_dataset_config(cls, entity: str, doc_type: str) -> Dict:
        entity_map = {
            "fi": cls.FI_DATASETS,
            "fidc": cls.FIDC_DATASETS,
            "fip": cls.FIP_DATASETS,
            "fiagro": cls.FIAGRO_DATASETS,
            "fii": cls.FII_DATASETS,
            "securit": cls.SECURIT_DATASETS,
            "cia_aberta": cls.CIA_ABERTA_DATASETS,
        }
        datasets = entity_map.get(entity.lower())
        if not datasets:
            raise ValueError(f"Unknown entity type: {entity}")
        cfg = datasets.get(doc_type.lower())
        if not cfg:
            raise ValueError(
                f"Unknown document type '{doc_type}' for entity '{entity}'. "
                f"Available: {', '.join(datasets.keys())}"
            )
        return cfg

    @classmethod
    def get_available_doc_types(cls, entity: str) -> List[str]:
        entity_map = {
            "fi": list(cls.FI_DATASETS.keys()),
            "fidc": list(cls.FIDC_DATASETS.keys()),
            "fip": list(cls.FIP_DATASETS.keys()),
            "fiagro": list(cls.FIAGRO_DATASETS.keys()),
            "fii": list(cls.FII_DATASETS.keys()),
            "securit": list(cls.SECURIT_DATASETS.keys()),
            "cia_aberta": list(cls.CIA_ABERTA_DATASETS.keys()),
        }
        return entity_map.get(entity.lower(), [])


config = FetcherConfig()
dataset_config = DatasetConfig()
