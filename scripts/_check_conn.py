import os, sys, asyncio, asyncpg, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

TABLES = [
    "cvm_ingest_log", "cvm_fi_diario", "cvm_fidc_mensal",
    "cvm_fidc_tranche", "cvm_fidc_tranche_flows", "cvm_fidc_aging",
    "cvm_fii_mensal", "cvm_securit_mensal",
    "cvm_securit_serie", "cvm_securit_fluxo",
]

async def main():
    pooler_url = os.environ["SUPABASE_DB_URL"]
    session_url = re.sub(r":6543/", ":5432/", pooler_url)
    conn = await asyncpg.connect(session_url)
    print("Connection: OK")
    for t in TABLES:
        n = await conn.fetchval(f"SELECT COUNT(*) FROM {t}")
        flag = "✓" if n and n > 0 else "  (empty)"
        print(f"  {t:<40} {n:>10} {flag}")
    await conn.close()

asyncio.run(main())
