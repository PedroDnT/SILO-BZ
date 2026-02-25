import os
from enum import Enum


class BaseConfig:
    API_TITLE = "B3 CALC API"
    API_VERSION = "1.0.0"
    API_DESCRIPTION = "API for accessing B3 CALC fixed income data"

    B3_CALC_BASE_URL = os.getenv("B3_CALC_BASE_URL", "https://calculadorarendafixa.com.br/webservice")

    DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "100"))
    MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "1000"))

    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))
    CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "64"))


class SecurityType(str, Enum):
    DEBENTURE = "debentures"
    CRA = "cra"
    CRI = "cri"


config = BaseConfig()


B3_CALC_ENDPOINTS = {
    "debentures_list": "/debentures",
    "cra_list": "/cra",
    "cri_list": "/cri",
    "debenture_price": "/debentures/price",
    "cra_price": "/cra/price",
    "cri_price": "/cri/price",
    "indexes": "/indexes",
}


SAMPLE_DEBENTURES = [
    {
        "code": "VALE12",
        "name": "Vale Debenture",
        "issuer": "Vale S.A.",
        "security_type": "debentures",
        "index": "CDI",
        "status": "active",
    }
]

SAMPLE_CRAS = [
    {
        "code": "22A0001234-11",
        "name": "CRA Example",
        "issuer": "Issuer CRA",
        "security_type": "cra",
        "index": "CDI",
        "status": "active",
    }
]

SAMPLE_CRIS = [
    {
        "code": "22A0001111-20",
        "name": "CRI Example",
        "issuer": "Issuer CRI",
        "security_type": "cri",
        "index": "IPCA",
        "status": "active",
    }
]

SAMPLE_INDEXES = {
    "CDI": {"value": 11.15, "change": 0.0, "change_percent": 0.0},
    "SELIC": {"value": 11.25, "change": 0.0, "change_percent": 0.0},
    "IPCA": {"value": 4.5, "change": 0.0, "change_percent": 0.0},
}
