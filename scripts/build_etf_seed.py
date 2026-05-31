"""Generate / refresh the curated B3 ETF seed (src/store/seeds/etf_registry_seed.csv).

Why a curated seed?  CVM open data has no ETF flag — neither TP_FUNDO
(FI/FACFIF/FAPI/FCCE) nor the CVM-175 `Classificacao` distinguishes ETFs.
B3 (which assigns the ticker) is the only authoritative ETF enumerator, and its
public funds API returns no ETF rows from CI IPs.  So we maintain a small,
verified ticker->CNPJ map here and join it to CVM\'s existing data.

Each curated CNPJ below was resolved against CVM\'s own registries (cad_fi.csv +
registro_fundo_classe.zip) — live ETFs are named "... CLASSE DE ÍNDICE" /
"FUNDO DE ÍNDICE" and resolve to an active class CNPJ that appears in
cvm_fi_diario (CNPJ_FUNDO_CLASSE).  This script re-fetches those registries to
fill the legal name + situacao and to verify each CNPJ still resolves, then
writes the CSV the ingest path loads.

NOTE on multi-class umbrellas: some Investo ETF umbrellas host two share classes
under the same CNPJ (e.g. CHIP11 and 5GTK11 both use 42280376000147, and
BTEK11/NUCL11 share 42280298000180, and FOOD11/GLDX11 share 43210419000180).
The duplicate CNPJ is intentional — each row maps a distinct B3 ticker/class to
the same underlying fund entity.  The ingest layer upserts on ticker (PK) so
each class gets its own registry row.

To add an ETF: append a row to CURATED with its ticker, the class CNPJ, the
provider, the underlying index, the segment, and the BlackRock product ID (or ""
if not iShares), then re-run this script.

Usage:
    python scripts/build_etf_seed.py            # fetch CVM, verify, write CSV
    python scripts/build_etf_seed.py --offline  # write CSV from CURATED only
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import urllib.request
import zipfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_PATH = os.path.join(_REPO_ROOT, "src", "store", "seeds", "etf_registry_seed.csv")

FIELDS = [
    "ticker", "cnpj", "fund_name", "provider", "underlying_index", "segment",
    "situacao", "is_active", "dt_cancel", "gestor", "taxa_adm",
    "blackrock_product_id", "blackrock_csv_url",
]

# Status tokens that mean "operating" (kept in sync with mapping.derive_is_active).
_ACTIVE_TOKENS = ("FUNCIONAMENTO NORMAL", "EM FUNCIONAMENTO", "ATIVO")

# BlackRock Brazil holdings CSV URL template
_BR_CSV_TMPL = (
    "https://www.blackrock.com/br/products/{pid}/"
    "{slug}/1506433276998.ajax?fileType=csv&fileName={ticker}_holdings&dataType=fund"
)

_BLACKROCK_PRODUCTS: dict[str, tuple[str, str]] = {
    # ticker: (product_id, url_slug)
    "BOVA11": ("251816", "ishares-ibovespa-fundo-de-ndice-fund"),
    "BRAX11": ("251817", "ishares-ibrxndice-brasil-ibrx100-fundo-de-ndice-fund"),
    "SMAL11": ("251752", "ishares-bmfbovespa-small-cap-fundo-de-ndice-fund"),
    "IVVB11": ("251902", "ishares-sp-500-fi-em-cotas-de-fundo-de-ndice-inv-no-exterior-fund"),
    "ECOO11": ("251711", "ishares-ndice-carbono-eficiente-ico2-brasil-fundo-de-ndice-fund"),
    "CAPE11": ("342108", "ishares-bovespa-br+-cap-5-fundo-de-ndice"),
    "EWBZ11": ("341926", "ishares-bovespa-br+-equal-weight-fundo-de-ndice"),
}

# ticker, class CNPJ (14 digits, no formatting), provider, underlying index, segment,
# blackrock_product_id ("" for non-iShares)
CURATED = [
    ("5GTK11", "42280376000147", "Investo", "Bluestar 5G Comm Index", "equities_intl", ""),
    ("5PRE11", "64538158000100", "Itaú (It Now)", "ITBR Pré 5 Anos", "fixed_income_br", ""),
    ("ACWI11", "38542889000101", "XP Asset (Trend)", "Bloomberg All Countries (ACWI)", "equities_intl", ""),
    ("AGRI11", "45081470000165", "BB Asset", "IAgro FFS B3", "commodities", ""),
    ("ALUG11", "42280328000159", "Investo", "MSCI US Real Estate", "real_estate", ""),
    ("AREA11", "62579973000184", "BTG Pactual", "TEVA AUVP ITBR IPCA Rendimento", "fixed_income_br", ""),
    ("ARGE11", "61604144000141", "Investo", "MSCI Argentina", "equities_intl", ""),
    ("AUPO11", "63905124000136", "BTG Pactual", "TEVA AUVP ITBR Liquidez", "fixed_income_br", ""),
    ("AURO11", "62211601000109", "Buena Vista", "Neos Gold High Income Index", "commodities", ""),
    ("AUVP11", "61273759000132", "BTG Pactual", "TEVA AUVP Ações Fundamentos", "equities_br", ""),
    ("B3BR11", "56211321000190", "Itaú (It Now)", "Ibovespa B3 BR+", "equities_br", ""),
    ("B5MB11", "34081072000122", "Bradesco Asset", "IMA-B 5+", "fixed_income_br", ""),
    ("B5P211", "38354864000184", "Itaú (It Now)", "IMA-B5 P2 (IPCA curto)", "fixed_income_br", ""),
    ("BBOI11", "46610422000180", "BB Asset", "Índice Futuro Boi Gordo B3", "commodities", ""),
    ("BBOV11", "34606480000150", "BB Asset", "Ibovespa", "equities_br", ""),
    ("BBSD11", "17817528000150", "BB Asset", "S&P Dividendos Brasil", "equities_br", ""),
    ("BCIC11", "48643170000110", "B-Index (Bradesco)", "Morningstar Setores Cíclicos Brasil", "equities_br", ""),
    ("BDAP11", "51921067000108", "BB Asset", "Índice DAP5 B3", "fixed_income_br", ""),
    ("BDEF11", "48643220000160", "B-Index (Bradesco)", "Morningstar Setores Defensivos Brasil", "equities_br", ""),
    ("BDOM11", "45823539000189", "Investo", "MarketVector Brazil Domestic Exposure", "equities_br", ""),
    ("BEST11", "61950414000176", "Investo", "Brazil BESST Quality", "equities_br", ""),
    ("BITH11", "41256573000168", "Hashdex", "Nasdaq Bitcoin Reference Price", "crypto", ""),
    ("BITI11", "38000706000126", "Itaú (It Now)", "Bloomberg Galaxy Bitcoin", "crypto", ""),
    ("BIZD11", "60057113000155", "Investo", "MVIS US Business Development Cos", "equities_intl", ""),
    ("BLFT11", "62390395000133", "B-Index (Bradesco)", "TEVA LFT Curto Prazo", "fixed_income_br", ""),
    ("BLOK11", "44106937000111", "Investo", "MarketVector Smart Contract Leaders", "equities_intl", ""),
    ("BMMT11", "48643091000100", "B-Index (Bradesco)", "Morningstar Brasil Momento", "equities_br", ""),
    ("BOL511", "62319584000110", "B-Index (Bradesco)", "IMA-B 5 P2", "fixed_income_br", ""),
    ("BOVA11", "10406511000161", "BlackRock (iShares)", "Ibovespa", "equities_br", "251816"),
    ("BOVB11", "32203211000118", "Bradesco Asset", "Ibovespa", "equities_br", ""),
    ("BOVS11", "38350645000127", "Safra Asset", "Ibovespa", "equities_br", ""),
    ("BOVV11", "21407758000119", "Itaú (It Now)", "Ibovespa", "equities_br", ""),
    ("BOVX11", "40155573000109", "XP Asset (Trend)", "Ibovespa", "equities_br", ""),
    ("BPRE11", "62363807000146", "B-Index (Bradesco)", "IRF-M P2 (Prefixado)", "fixed_income_br", ""),
    ("BRAX11", "11455378000104", "BlackRock (iShares)", "IBrX-100", "equities_br", "251817"),
    ("BRAZ11", "57848980000102", "BB Asset", "Ibovespa B3 BR+", "equities_br", ""),
    ("BREW11", "48643130000179", "B-Index (Bradesco)", "Morningstar Brasil Pesos Iguais", "equities_br", ""),
    ("BRXC11", "59506849000184", "BTG Pactual", "TEVA IABR Selector", "equities_br", ""),
    ("BTEK11", "42280298000180", "Investo", "S&P Biotechnology Selection", "equities_intl", ""),
    ("BULZ11", "63428769000125", "Genial Investimentos", "Ações High Beta", "equities_br", ""),
    ("BVBR11", "63407496000132", "Investo", "Constância Fatores Defensividade", "equities_br", ""),
    ("BXPO11", "45814375000123", "Investo", "MarketVector Brazil Global Exposure", "equities_br", ""),
    ("CAPE11", "60553995000140", "BlackRock (iShares)", "Ibovespa BR+ Cap 5%", "equities_br", "342108"),
    ("CASA11", "59680030000139", "Buena Vista", "Neos Real Estate High Income BR", "real_estate", ""),
    ("CHIP11", "42280376000147", "Investo", "MVIS US Listed Semiconductor 25", "equities_intl", ""),
    ("CMDB11", "43391410000113", "BTG Pactual", "TEVA Ações Commodities Brasil", "equities_br", ""),
    ("COIN11", "57920798000107", "Buena Vista", "Neos Bitcoin High Income Index", "crypto", ""),
    ("CORN11", "46467170000181", "BB Asset", "Índice Futuro Milho B3", "commodities", ""),
    ("CRPT11", "36669709000121", "Empiricus", "Criptomoedas Top20", "crypto", ""),
    ("DEBB11", "45064129000100", "BTG Pactual", "TEVA Debêntures DI", "fixed_income_br", ""),
    ("DEFI11", "40755515000116", "Hashdex", "Hashdex DeFi Index", "crypto", ""),
    ("DIVD11", "54314981000170", "Itaú (It Now)", "IDIV Renda Dividendos", "equities_br", ""),
    ("DIVO11", "13416245000146", "Itaú (It Now)", "IDIV (Dividendos)", "equities_br", ""),
    ("DNAI11", "41054459000155", "Itaú (It Now)", "MSCI USA IMI Genomic Innovation", "equities_intl", ""),
    ("DOLA11", "55620015000144", "BB Asset", "Índice Futuro Dólar S&P/B3", "multi_asset", ""),
    ("DOLB11", "60310645000152", "BTG Pactual", "S&P/B3 Cambial", "multi_asset", ""),
    ("DOLX11", "63747438000158", "XP Asset (Trend)", "S&P/B3 Dólar", "multi_asset", ""),
    ("DVER11", "52203750000164", "BB Asset", "Índice Diversidade B3 IS", "equities_br", ""),
    ("ECOO11", "15562377000101", "BlackRock (iShares)", "ICO2 (Carbono Eficiente)", "equities_br", "251711"),
    ("ELAS11", "43210658000130", "Safra Asset", "Mulheres na Liderança (S&P)", "equities_br", ""),
    ("ESGB11", "37843293000189", "BTG Pactual", "S&P/B3 Brazil ESG", "equities_br", ""),
    ("ESGD11", "40953905000109", "XP Asset (Trend)", "MSCI EAFE ESG", "equities_intl", ""),
    ("ESGE11", "40953725000119", "XP Asset (Trend)", "MSCI Emerging Markets ESG", "equities_intl", ""),
    ("ESGU11", "40953254000149", "XP Asset (Trend)", "MSCI USA ESG", "equities_intl", ""),
    ("ETHE11", "41907631000176", "Hashdex", "Nasdaq Ethereum Reference Price", "crypto", ""),
    ("EURP11", "38595988000151", "XP Asset", "MSCI Europe Index", "equities_intl", ""),
    ("EWBZ11", "60554347000108", "BlackRock (iShares)", "Ibovespa BR+ Equal Weight", "equities_br", "341926"),
    ("FIND11", "11961094000181", "Itaú (It Now)", "IFNC (Financeiro)", "equities_br", ""),
    ("FIXA11", "26845780000164", "BB Asset", "Índice Futuro Taxas Juros S&P/B3", "fixed_income_br", ""),
    ("FIXX11", "59783336000110", "Buena Vista", "Neos Enhanced Income 1-3M T-Bill", "fixed_income_intl", ""),
    ("FOMO11", "47758831000190", "Hashdex", "Hashdex Crypto Momentum", "crypto", ""),
    ("FOOD11", "43210419000180", "Investo", "Solactive Gold Spot / Agribusiness", "equities_intl", ""),
    ("GDIV11", "63209544000188", "Buena Vista", "Neos International High Income", "equities_intl", ""),
    ("GENB11", "42134357000102", "BTG Pactual", "S&P/B3 Ingenius", "equities_br", ""),
    ("GICP11", "61736225000103", "BTG Pactual", "TEVA Debêntures DI Quality High Beta", "fixed_income_br", ""),
    ("GLDI11", "63289842000125", "Itaú (It Now)", "Ouro BRL", "commodities", ""),
    ("GLDX11", "43210419000180", "Investo", "Solactive Gold Spot Index", "commodities", ""),
    ("GLFT11", "62794396000143", "Galapagos Capital", "TEVA Tesouro Selic", "fixed_income_br", ""),
    ("GOLB11", "62415896000127", "BTG Pactual", "Futuro de Ouro B3", "commodities", ""),
    ("GOLD11", "37985763000149", "XP Asset (Trend)", "LBMA Ouro (USD)", "commodities", ""),
    ("GOLX11", "63715020000169", "BTG Pactual", "B3 Ouro", "commodities", ""),
    ("GOVE11", "11184136000115", "Itaú (It Now)", "IGCT (Governança Corporativa)", "equities_br", ""),
    ("GPCA11", "65819277000196", "Grão Gestora", "TEVA ITBR Tesouro IPCA 2 Anos", "fixed_income_br", ""),
    ("GPUS11", "60832345000133", "Investo", "S&P 500 (GP)", "equities_intl", ""),
    ("GURU11", "43955479000122", "Inter", "Grandes Gurus do Mercado", "equities_intl", ""),
    ("GXUS11", "63429736000108", "Galapagos Capital", "FTSE Global Equities Ex-US", "equities_intl", ""),
    ("HASH11", "38314708000190", "Hashdex", "Nasdaq CME Crypto Index", "crypto", ""),
    ("HERT11", "60419043000138", "Hedge Investments", "Brasil Equity REITs", "real_estate", ""),
    ("HGBR11", "62344793000113", "Nu Asset", "iBoxx Investment Grade Hedge Carry BRL", "fixed_income_br", ""),
    ("HIGH11", "55705611000127", "Itaú (It Now)", "Ibovespa Smart High Beta", "equities_br", ""),
    ("HODL11", "56158890000119", "Investo", "MarketVector Bitcoin Benchmark Rate", "crypto", ""),
    ("HTEK11", "41054515000151", "Itaú (It Now)", "Morningstar XT US Healthcare", "equities_intl", ""),
    ("HYBR11", "62344693000197", "Nu Asset", "iBoxx High Yield Hedge Carry BRL", "fixed_income_br", ""),
    ("IBOB11", "42427783000134", "BTG Pactual", "Ibovespa", "equities_br", ""),
    ("IDKA11", "57055305000118", "Itaú (It Now)", "IRF-M P3 (Prefixado longo)", "fixed_income_br", ""),
    ("IMAB11", "31024153000100", "Itaú (It Now)", "IMA-B", "fixed_income_br", ""),
    ("IMBB11", "34081054000140", "Bradesco Asset", "IMA-B 5+", "fixed_income_br", ""),
    ("IRFM11", "32880642000119", "Itaú (It Now)", "IRF-M P2 (Prefixado)", "fixed_income_br", ""),
    ("ISUS11", "12984444000198", "Itaú (It Now)", "ISE (Sustentabilidade)", "equities_br", ""),
    ("IVVB11", "19909560000191", "BlackRock (iShares)", "S&P 500", "equities_intl", "251902"),
    ("IVWO11", "65836654000103", "Investo", "FTSE Emerging Markets China A", "equities_intl", ""),
    ("IWMI11", "57922206000196", "Buena Vista", "Neos Russell 2000 High Income", "equities_intl", ""),
    ("JOGO11", "43105466000164", "Investo", "ETFMG Video Gaming & Esports", "equities_intl", ""),
    ("LFIN11", "62087419000180", "BTG Pactual", "TEVA Letras Financeiras DI Qualidade", "fixed_income_br", ""),
    ("LFIX11", "64731230000103", "Investo", "V8 Letra Financeira S1 DI B3", "fixed_income_br", ""),
    ("LFTB11", "56176507000155", "Investo", "MarketVector Brazil Treasury 760D", "fixed_income_br", ""),
    ("LFTI11", "63702230000112", "Itaú (It Now)", "Tesouro Selic (LFT)", "fixed_income_br", ""),
    ("LFTS11", "45823821000166", "Investo", "TEVA Tesouro Selic", "fixed_income_br", ""),
    ("LFTX11", "65573794000128", "XP Asset (Trend)", "Tesouro Selic B3", "fixed_income_br", ""),
    ("LLFT11", "61088467000120", "BTG Pactual", "Tesouro Selic (LFT)", "fixed_income_br", ""),
    ("LTBX11", "65573738000193", "XP Asset (Trend)", "TEVA ITBR Selic Target 760", "fixed_income_br", ""),
    ("LTNB11", "61433644000168", "BTG Pactual", "IRF-M P2 (Prefixado)", "fixed_income_br", ""),
    ("LVOL11", "55705668000126", "Itaú (It Now)", "Ibovespa Smart Low Volatility", "equities_br", ""),
    ("MARG11", "59172415000195", "BTG Pactual", "Margem Debêntures Ultra Qualidade DI", "fixed_income_br", ""),
    ("MATB11", "13416228000109", "Itaú (It Now)", "IMAT (Materiais Básicos)", "equities_br", ""),
    ("META11", "44124505000133", "Hashdex", "Hashdex Crypto Metaverse", "crypto", ""),
    ("MIDB11", "64690760000150", "BTG Pactual", "TEVA ITBR Tesouro IPCA 2035", "fixed_income_br", ""),
    ("MILL11", "41054489000161", "Itaú (It Now)", "Morningstar US Digital Lifestyle", "equities_intl", ""),
    ("NASD11", "35578672000163", "XP Asset (Trend)", "Nasdaq-100", "equities_intl", ""),
    ("NBOV11", "56107650000195", "Nu Asset", "Nu Ibovespa B3 BR+", "equities_br", ""),
    ("NCDI11", "63001985000190", "Nu Asset", "CDI Tesouro Selic B3", "fixed_income_br", ""),
    ("NDIV11", "52116337000162", "Itaú (It Now)", "Ibovespa Smart Dividendos Renda", "equities_br", ""),
    ("NFTS11", "44107447000130", "Investo", "MarketVector Media & Entertainment", "equities_intl", ""),
    ("NLFA11", "63734820000127", "Nu Asset", "Letras Financeiras ANBIMA", "fixed_income_br", ""),
    ("NSDV11", "52116361000100", "Itaú (It Now)", "Ibovespa Smart Dividendos", "equities_br", ""),
    ("NTNS11", "50642881000112", "Investo", "TEVA Tesouro IPCA+ 0-4 Anos", "fixed_income_br", ""),
    ("NUCL11", "42280298000180", "Investo", "MVIS Global Uranium & Nuclear Energy", "equities_intl", ""),
    ("OURO11", "63728394000119", "B-Index (Bradesco)", "Ouro BRL B3", "commodities", ""),
    ("PACB11", "44702829000101", "BTG Pactual", "TEVA Tesouro IPCA Ultra Longo", "fixed_income_br", ""),
    ("PACC11", "57656453000198", "BTG Pactual", "IMA-B 5 P2", "fixed_income_br", ""),
    ("PACG11", "57656200000114", "BTG Pactual", "IMA-B", "fixed_income_br", ""),
    ("PACL11", "61433898000186", "BTG Pactual", "IMA-B 5+", "fixed_income_br", ""),
    ("PEVC11", "45295262000169", "Investo", "Bluestar Top 10 US Alt Asset Managers", "equities_intl", ""),
    ("PHIP11", "58312917000101", "Phronesis", "TEVA IPCA Dynamic Selection", "fixed_income_br", ""),
    ("PIBB11", "06323688000127", "Itaú (It Now)", "IBrX-50", "equities_br", ""),
    ("PIPE11", "64423976000150", "Buena Vista", "VettaFi Neos Energy Infrastructure", "equities_intl", ""),
    ("PKIN11", "60023816000162", "B-Index (Bradesco)", "CSI 300 (China A)", "equities_intl", ""),
    ("POSB11", "65180394000152", "Galapagos Capital", "TEVA Tesouro Selic & IPCA+", "fixed_income_br", ""),
    ("PREX11", "65594290000194", "XP Asset (Trend)", "IRF-M P2 (Prefixado)", "fixed_income_br", ""),
    ("QBTC11", "39979022000180", "QR Asset", "CME CF Bitcoin Reference Rate", "crypto", ""),
    ("QDFI11", "42682790000182", "QR Asset", "Bloomberg DeFi", "crypto", ""),
    ("QETH11", "41706298000137", "QR Asset", "CME CF Ether Reference Rate", "crypto", ""),
    ("QLBR11", "63063704000123", "Investo", "MarketVector Brazil Multifactor Quality", "equities_br", ""),
    ("QQQI11", "54825284000184", "Buena Vista", "Nasdaq-100 Neos High Income", "equities_intl", ""),
    ("QQQQ11", "58348330000152", "Buena Vista", "Nasdaq-100 High Beta Index", "equities_intl", ""),
    ("QSOL11", "56043036000107", "QR Asset", "CME CF Solana Dollar Reference Rate", "crypto", ""),
    ("REVE11", "41054432000162", "Itaú (It Now)", "Russell 1000 Green Revenues", "equities_intl", ""),
    ("RICO11", "59719389000172", "Buena Vista", "Bloomberg US Billionaires Select", "equities_intl", ""),
    ("SCVB11", "45814400000179", "Investo", "MarketVector Brazil Small Cap Value", "equities_br", ""),
    ("SFIX11", "62320381000143", "BTG Pactual", "TEVA ITBR IPCA 95-5", "fixed_income_br", ""),
    ("SHOT11", "41012711000163", "Itaú (It Now)", "S&P Kensho Moonshots", "equities_intl", ""),
    ("SILK11", "61231268000129", "Itaú (It Now)", "MSCI China A50", "equities_intl", ""),
    ("SLVR11", "65594464000119", "XP Asset (Trend)", "LBMA Prata", "commodities", ""),
    ("SMAB11", "42682281000150", "BTG Pactual", "SMLL (Small Cap)", "equities_br", ""),
    ("SMAC11", "34803814000186", "Itaú (It Now)", "SMLL (Small Cap)", "equities_br", ""),
    ("SMAL11", "10406600000108", "BlackRock (iShares)", "SMLL (Small Cap)", "equities_br", "251752"),
    ("SOLH11", "56746166000106", "Hashdex", "Nasdaq Solana", "crypto", ""),
    ("SPBZ11", "63175655000110", "BTG Pactual", "S&P 500 Futures Quanto BRL", "equities_intl", ""),
    ("SPUB11", "57091257000113", "Safra Asset", "Ibovespa Empresas Estatais", "equities_br", ""),
    ("SPVT11", "57091195000140", "Safra Asset", "Ibovespa Empresas Privadas", "equities_br", ""),
    ("SPXB11", "42682199000125", "BTG Pactual", "S&P 500", "equities_intl", ""),
    ("SPXH11", "63747287000138", "XP Asset (Trend)", "S&P 500 Quanto", "equities_intl", ""),
    ("SPXI11", "17036289000100", "Itaú (It Now)", "S&P 500 TRN", "equities_intl", ""),
    ("SPXR11", "58022660000153", "Itaú (It Now)", "S&P 500 Futures Quanto BRL", "equities_intl", ""),
    ("SPYI11", "51949867000129", "Buena Vista", "Neos US Equity High Income ETF", "equities_intl", ""),
    ("SPYR11", "63823417000174", "B-Index (Bradesco)", "S&P 500 BRL", "equities_intl", ""),
    ("SVAL11", "43210375000199", "Investo", "S&P SmallCap 600 Value", "equities_intl", ""),
    ("TD3511", "64758770000180", "Itaú (It Now)", "NTN-B 2035", "fixed_income_br", ""),
    ("TD5011", "64758102000153", "Itaú (It Now)", "NTN-B 2050", "fixed_income_br", ""),
    ("TD6011", "64759097000101", "Itaú (It Now)", "NTN-B 2060", "fixed_income_br", ""),
    ("TECB11", "42682113000164", "BTG Pactual", "Tech Brasil Ações", "equities_br", ""),
    ("TECK11", "38354844000103", "Itaú (It Now)", "NYSE FANG+", "equities_intl", ""),
    ("TECX11", "60553176000100", "B-Index (Bradesco)", "China AMC ChiNext", "equities_intl", ""),
    ("TIRB11", "57063444000193", "BTG Pactual", "TEVA Dividendos Ativos Reais", "equities_br", ""),
    ("TRIG11", "43140303000112", "Trígono Capital", "Micro/Small Cap Brasil", "equities_br", ""),
    ("URET11", "40955945000181", "XP Asset (Trend)", "FTSE US REITs", "real_estate", ""),
    ("USAL11", "42101885000165", "XP Asset (Trend)", "CRSP US Large Cap (S&P 500 equiv)", "equities_intl", ""),
    ("USTK11", "40751130000180", "Investo", "MSCI US Technology", "equities_intl", ""),
    ("UTEC11", "40952802000116", "XP Asset (Trend)", "Bloomberg US 3000 Technology", "equities_intl", ""),
    ("UTLL11", "62494142000100", "Investo", "B3 Utilidade Pública", "equities_br", ""),
    ("WEJR11", "62999367000118", "BTG Pactual", "TEVA ITBR IPCA", "fixed_income_br", ""),
    ("WRLD11", "61689798000115", "Investo", "FTSE All-World", "equities_intl", ""),
    ("XBCI11", "65602949000107", "Buena Vista", "VettaFi Neos Boosted Bitcoin High Inc", "crypto", ""),
    ("XBOV11", "14120533000111", "Caixa Asset", "Ibovespa", "equities_br", ""),
    ("XFIX11", "36046508000178", "XP Asset (Trend)", "IFIX-L (FIIs)", "real_estate", ""),
    ("XINA11", "38542870000165", "XP Asset (Trend)", "Bloomberg China", "equities_intl", ""),
    ("XRPH11", "58430507000165", "Hashdex", "Nasdaq XRP", "crypto", ""),
    ("XSPI11", "65603290000103", "Buena Vista", "VettaFi Neos Boosted S&P 500 High Inc", "equities_intl", ""),
    ("YDRO11", "42264597000121", "Itaú Asset", "S&P Kensho Hydrogen", "equities_intl", ""),
]

_BASE = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=90).read()


def _norm(cnpj: str) -> str:
    digits = re.sub(r"\D", "", cnpj or "")
    return digits.zfill(14) if digits else ""


def _build_cvm_index() -> dict:
    """Map normalised CNPJ -> [legal_name, situacao, dt_cancel, gestor, taxa_adm].

    cad_fi.csv is processed first (mostly cancelled legacy funds — carries
    DT_CANCEL + gestor + taxa_adm). The CVM-175 registry then overrides
    name/situacao with the current value (active universe) while preserving any
    cancellation date and fee data already captured.
    """
    index: dict = {}
    print("Fetching cad_fi.csv …", file=sys.stderr)
    cad = _fetch(f"{_BASE}/cad_fi.csv").decode("latin-1", "replace")
    for r in csv.DictReader(io.StringIO(cad), delimiter=";"):
        index[_norm(r.get("CNPJ_FUNDO"))] = [
            r.get("DENOM_SOCIAL", ""),
            r.get("SIT", ""),
            r.get("DT_CANCEL", ""),
            r.get("GESTOR", ""),
            r.get("TAXA_ADM", ""),
        ]
    print("Fetching registro_fundo_classe.zip …", file=sys.stderr)
    zf = zipfile.ZipFile(io.BytesIO(_fetch(f"{_BASE}/registro_fundo_classe.zip")))
    for member, cnpj_col in (
        ("registro_classe.csv", "CNPJ_Classe"),
        ("registro_fundo.csv",  "CNPJ_Fundo"),
    ):
        text = zf.read(member).decode("latin-1", "replace")
        for r in csv.DictReader(io.StringIO(text), delimiter=";"):
            cnpj = _norm(r.get(cnpj_col))
            if not cnpj:
                continue
            name     = r.get("Denominacao_Social", "")
            situacao = r.get("Situacao", "")
            if cnpj in index:
                index[cnpj][0] = name     or index[cnpj][0]
                index[cnpj][1] = situacao or index[cnpj][1]
            else:
                index[cnpj] = [name, situacao, "", "", ""]
    return index


def _is_active(situacao: str) -> str:
    s = (situacao or "").strip().upper()
    if not s:
        return ""
    return "True" if any(t in s for t in _ACTIVE_TOKENS) else "False"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip CVM fetch/verify")
    args = ap.parse_args()

    index = {} if args.offline else _build_cvm_index()
    if index:
        print(f"CVM registry index: {len(index)} CNPJs", file=sys.stderr)

    rows = []
    for entry in CURATED:
        ticker, cnpj_raw, provider, idx, segment, bpid = entry
        cnpj = _norm(cnpj_raw)
        rec  = index.get(cnpj, ["", "", "", "", ""])
        name, sit, dt_cancel, gestor, taxa_adm = rec
        if index and not name:
            print(f"  WARNING: {ticker} {cnpj} not found in CVM registry", file=sys.stderr)
        elif index:
            print(f"  ok {ticker} {cnpj} [{sit}] {name[:55]}", file=sys.stderr)
        # BlackRock CSV URL
        if bpid and ticker in _BLACKROCK_PRODUCTS:
            pid, slug = _BLACKROCK_PRODUCTS[ticker]
            br_url = _BR_CSV_TMPL.format(pid=pid, slug=slug, ticker=ticker)
        else:
            br_url = ""
        rows.append({
            "ticker":               ticker,
            "cnpj":                 cnpj,
            "fund_name":            name,
            "provider":             provider,
            "underlying_index":     idx,
            "segment":              segment,
            "situacao":             sit,
            "is_active":            _is_active(sit),
            "dt_cancel":            dt_cancel,
            "gestor":               gestor,
            "taxa_adm":             taxa_adm,
            "blackrock_product_id": bpid,
            "blackrock_csv_url":    br_url,
        })

    rows.sort(key=lambda r: r["ticker"])
    os.makedirs(os.path.dirname(SEED_PATH), exist_ok=True)
    with open(SEED_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {len(rows)} ETFs -> {os.path.relpath(SEED_PATH, _REPO_ROOT)}")


if __name__ == "__main__":
    main()
