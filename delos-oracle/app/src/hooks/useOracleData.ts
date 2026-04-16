/**
 * useOracleData — reads the Delos Oracle MacroState PDA from Solana.
 *
 * Returns human-readable BCB macroeconomic values decoded from the
 * on-chain integer representation.
 */

import { useEffect, useState, useCallback } from "react";
import { useConnection } from "@solana/wallet-adapter-react";
import { PublicKey } from "@solana/web3.js";
import { Program, AnchorProvider, Idl, setProvider } from "@coral-xyz/anchor";

// Scaling constants — must match programs/delos_oracle/src/lib.rs
const SCALE_RATE = 100;     // stored as bp × 100; divide by 100 to get %
const SCALE_FX   = 10_000;  // stored × 10_000; divide to get rate

const PROGRAM_ID = new PublicKey(
  import.meta.env.VITE_PROGRAM_ID ?? "DeLoSXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
);

const AUTHORITY = new PublicKey(
  import.meta.env.VITE_ORACLE_AUTHORITY ?? PublicKey.default.toBase58()
);

export interface MacroData {
  selicMeta:    number;   // % per year
  selicDiaria:  number;   // % per day
  cdi:          number;
  ipca:         number;   // 12-month %
  igpm:         number;   // 12-month %
  usdbrl:       number;   // BRL per USD
  updatedTs:    Date;
  slot:         number;
}

export interface OracleState {
  data:    MacroData | null;
  loading: boolean;
  error:   string | null;
  refresh: () => void;
}

export function useOracleData(idl: Idl | null): OracleState {
  const { connection } = useConnection();
  const [data,    setData]    = useState<MacroData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!idl) return;
    setLoading(true);
    setError(null);

    try {
      // Read-only provider — no wallet needed
      const provider = new AnchorProvider(connection, {} as any, {
        commitment: "confirmed",
      });
      setProvider(provider);

      const program = new Program(idl, PROGRAM_ID, provider);

      const [macroPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("macro_state"), AUTHORITY.toBuffer()],
        PROGRAM_ID
      );

      const state = await (program.account as any).macroState.fetch(macroPDA);

      setData({
        selicMeta:   state.selicMeta.toNumber()   / SCALE_RATE,
        selicDiaria: state.selicDiaria.toNumber() / SCALE_RATE,
        cdi:         state.cdi.toNumber()          / SCALE_RATE,
        ipca:        state.ipca.toNumber()         / SCALE_RATE,
        igpm:        state.igpm.toNumber()         / SCALE_RATE,
        usdbrl:      state.usdbrl.toNumber()       / SCALE_FX,
        updatedTs:   new Date(state.updatedTs.toNumber() * 1000),
        slot:        state.slot.toNumber(),
      });
    } catch (err: any) {
      setError(err?.message ?? String(err));
    } finally {
      setLoading(false);
    }
  }, [connection, idl]);

  useEffect(() => {
    fetch();
    // Refresh every 5 minutes
    const interval = setInterval(fetch, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetch]);

  return { data, loading, error, refresh: fetch };
}
