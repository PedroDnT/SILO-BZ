from src.cvm_api.services import CVMCreditDataService


def test_build_url_fidc_mensal_matches_cvm_pattern():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("fidc", "mensal", 2025, 2)

    assert url == "https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_202502.zip"
    assert dataset_conf["is_zip"] is True


def test_build_url_fip_inf_trimestral_yearly_csv():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("fip", "inf_trimestral", 2025, None)

    assert url == "https://dados.cvm.gov.br/dados/FIP/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fip_2025.csv"
    assert dataset_conf["is_zip"] is False


def test_build_url_securit_cra_mensal_yearly_zip():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("securit", "cra_mensal", 2025, None)

    assert url == "https://dados.cvm.gov.br/dados/SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_2025.zip"
    assert dataset_conf["is_zip"] is True


def test_build_url_fip_inf_quadrimestral_yearly_csv():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("fip", "inf_quadrimestral", 2024, None)

    assert url == "https://dados.cvm.gov.br/dados/FIP/DOC/INF_QUADRIMESTRAL/DADOS/inf_quadrimestral_fip_2024.csv"
    assert dataset_conf["is_zip"] is False


def test_build_url_fiagro_mensal_monthly_zip():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("fiagro", "mensal", 2025, 12)

    assert url == "https://dados.cvm.gov.br/dados/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_202512.zip"
    assert dataset_conf["is_zip"] is True


def test_build_url_securit_cri_mensal_yearly_zip():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("securit", "cri_mensal", 2024, None)

    assert url == "https://dados.cvm.gov.br/dados/SECURIT/DOC/INF_MENSAL_CRI/DADOS/inf_mensal_cri_2024.zip"
    assert dataset_conf["is_zip"] is True


def test_build_url_securit_ots_mensal_yearly_zip():
    service = CVMCreditDataService()

    url, dataset_conf = service._build_url("securit", "ots_mensal", 2024, None)

    assert url == "https://dados.cvm.gov.br/dados/SECURIT/DOC/INF_MENSAL_OTS/DADOS/inf_mensal_ots_2024.zip"
    assert dataset_conf["is_zip"] is True
