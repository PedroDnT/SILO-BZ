"""
Delos Oracle — Python relayer / crank.

Fetches the latest BCB macroeconomic data via BacenClient and posts it
to the Delos Oracle Anchor program on Solana (devnet → mainnet).

Usage:
    python -m delos_oracle.relayer.relayer

Required env vars:
    ORACLE_KEYPAIR_JSON   — JSON array of 64 bytes (keypair)
    SOLANA_RPC_URL        — Solana RPC endpoint
    ANCHOR_PROGRAM_ID     — Deployed program ID

Run from the iliquid_nightly repo root so that src.clients.bacen_client
is importable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Ensure repo root is on path so BacenClient can be imported
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from src.clients.bacen_client import BacenClient  # noqa: E402

logger = logging.getLogger("delos_oracle.relayer")

# ---------------------------------------------------------------------------
# Lazy imports for Solana / Anchor (not available in every environment)
# ---------------------------------------------------------------------------

def _import_solana():
    try:
        from anchorpy import Program, Provider, Wallet, Idl  # type: ignore
        from anchorpy.provider import Keypair as AnchorKeypair  # type: ignore
        from solders.keypair import Keypair  # type: ignore
        from solders.pubkey import Pubkey  # type: ignore
        from solana.rpc.async_api import AsyncClient  # type: ignore
        return Program, Provider, Wallet, Idl, Keypair, Pubkey, AsyncClient
    except ImportError as exc:
        raise ImportError(
            "Solana dependencies missing. "
            "Run: pip install anchorpy solders solana"
        ) from exc


# ---------------------------------------------------------------------------
# BCB data fetching
# ---------------------------------------------------------------------------

BCB_SERIES: Dict[str, int] = {
    "SELIC_META":   432,
    "SELIC_DIARIA": 11,
    "CDI":          12,
    "IPCA":         433,
    "IGPM":         189,
    "USDBRL":       1,
}


async def fetch_bcb_snapshot() -> Dict[str, float]:
    """
    Return the latest available values for each BCB series as floats.

    Values:
        SELIC_META   — % per year (e.g. 13.25)
        SELIC_DIARIA — % per day
        CDI          — % per day
        IPCA         — % accumulated (12 months)
        IGPM         — % accumulated (12 months)
        USDBRL       — BRL per 1 USD (e.g. 5.8921)
    """
    client = BacenClient()
    records = await client.get_sgs_series(codes=BCB_SERIES, last=1)
    if not records:
        raise RuntimeError("BacenClient returned no SGS data")

    latest = records[-1]
    logger.info("BCB snapshot: %s", latest)

    snapshot: Dict[str, float] = {}
    for key in BCB_SERIES:
        raw = latest.get(key)
        if raw is not None and not _is_nan(raw):
            snapshot[key] = float(raw)
        else:
            logger.warning("Missing value for %s in BCB snapshot", key)
            snapshot[key] = 0.0

    return snapshot


def _is_nan(v: Any) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Scaling helpers
# ---------------------------------------------------------------------------

def scale_rate(pct: float) -> int:
    """Convert percentage to basis-point integer. 10.75% → 1075."""
    return round(pct * 100)


def scale_fx(rate: float) -> int:
    """Scale FX rate × 10,000. 5.1234 → 51234."""
    return round(rate * 10_000)


# ---------------------------------------------------------------------------
# Keypair loading
# ---------------------------------------------------------------------------

def load_keypair():
    """Load oracle authority keypair from env or file."""
    from config import ORACLE_KEYPAIR_JSON, ORACLE_KEYPAIR_FILE  # type: ignore
    _, _, _, _, Keypair, _, _ = _import_solana()

    json_str = ORACLE_KEYPAIR_JSON
    if json_str:
        secret_bytes = bytes(json.loads(json_str))
        return Keypair.from_bytes(secret_bytes)

    keypair_path = Path(ORACLE_KEYPAIR_FILE)
    if keypair_path.exists():
        secret_bytes = bytes(json.loads(keypair_path.read_text()))
        return Keypair.from_bytes(secret_bytes)

    raise EnvironmentError(
        "No keypair found. Set ORACLE_KEYPAIR_JSON or ORACLE_KEYPAIR_FILE."
    )


# ---------------------------------------------------------------------------
# Solana submission
# ---------------------------------------------------------------------------

async def post_to_solana(snapshot: Dict[str, float]) -> str:
    """
    Submit an update_macro_state instruction with the latest BCB data.

    Returns the transaction signature.
    """
    from config import SOLANA_RPC_URL, ANCHOR_PROGRAM_ID, PDA_SEED  # type: ignore
    Program, Provider, Wallet, Idl, Keypair, Pubkey, AsyncClient = _import_solana()

    keypair = load_keypair()

    # Load IDL from the build artefact
    idl_path = Path(__file__).parent.parent / "target" / "idl" / "delos_oracle.json"
    if not idl_path.exists():
        raise FileNotFoundError(
            f"IDL not found at {idl_path}. "
            "Run 'anchor build' inside the delos-oracle directory first."
        )
    idl = Idl.from_json(idl_path.read_text())

    program_id = Pubkey.from_string(ANCHOR_PROGRAM_ID)

    async with AsyncClient(SOLANA_RPC_URL) as connection:
        wallet   = Wallet(keypair)
        provider = Provider(connection, wallet)
        program  = Program(idl, program_id, provider)

        # Derive PDA
        authority_bytes = bytes(keypair.pubkey())
        macro_pda, _bump = Pubkey.find_program_address(
            [PDA_SEED, authority_bytes], program_id
        )

        updated_ts = int(time.time())

        # Scale snapshot values
        selic_meta   = scale_rate(snapshot.get("SELIC_META",   0.0))
        selic_diaria = scale_rate(snapshot.get("SELIC_DIARIA", 0.0))
        cdi          = scale_rate(snapshot.get("CDI",          0.0))
        ipca         = scale_rate(snapshot.get("IPCA",         0.0))
        igpm         = scale_rate(snapshot.get("IGPM",         0.0))
        usdbrl       = scale_fx(snapshot.get("USDBRL",         0.0))

        logger.info(
            "Posting: SELIC=%d IPCA=%d USDBRL=%d ts=%d",
            selic_meta, ipca, usdbrl, updated_ts,
        )

        tx = await program.rpc["update_macro_state"](
            selic_meta,
            selic_diaria,
            cdi,
            ipca,
            igpm,
            usdbrl,
            updated_ts,
            ctx=program.provider,
            # accounts
            remaining_accounts=[],
        )

        logger.info("Transaction signature: %s", tx)
        return str(tx)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    logger.info("Delos Oracle relayer starting")

    snapshot = await fetch_bcb_snapshot()
    sig = await post_to_solana(snapshot)

    logger.info("Done — tx=%s", sig)
    print(f"Posted BCB macro state to Solana: {sig}")


if __name__ == "__main__":
    asyncio.run(main())
