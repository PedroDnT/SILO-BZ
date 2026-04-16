"""
Relayer configuration — loaded from environment variables.
"""

import os

# Solana connection
SOLANA_RPC_URL: str = os.getenv(
    "SOLANA_RPC_URL", "https://api.devnet.solana.com"
)

# Anchor program ID (populated after anchor build + deploy)
ANCHOR_PROGRAM_ID: str = os.getenv(
    "ANCHOR_PROGRAM_ID",
    "DeLoSXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
)

# Oracle authority keypair — JSON array of 64 bytes, base-58 secret key,
# or path to a keypair file. Set ORACLE_KEYPAIR_JSON for the array form.
ORACLE_KEYPAIR_JSON: str = os.getenv("ORACLE_KEYPAIR_JSON", "")
ORACLE_KEYPAIR_FILE: str = os.getenv(
    "ORACLE_KEYPAIR_FILE",
    os.path.expanduser("~/.config/solana/id.json"),
)

# PDA seed (must match the Rust program)
PDA_SEED: bytes = b"macro_state"

# Scaling constants (must match Rust program documentation)
SCALE_RATE: int = 100       # percentage → basis points  (10.75% → 1075)
SCALE_FX:   int = 10_000    # FX rate → integer × 10_000 (5.1234 → 51234)
