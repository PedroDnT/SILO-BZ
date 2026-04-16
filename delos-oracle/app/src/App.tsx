import React, { useEffect, useState } from "react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import type { Idl } from "@coral-xyz/anchor";
import { useOracleData } from "./hooks/useOracleData";
import { MacroDisplay } from "./components/MacroDisplay";

/**
 * App — Delos Oracle dashboard.
 *
 * Loads the Anchor IDL at runtime (served from /idl/delos_oracle.json).
 * After `anchor build`, copy target/idl/delos_oracle.json → app/public/idl/
 */
export default function App() {
  const [idl, setIdl] = useState<Idl | null>(null);

  useEffect(() => {
    fetch("/idl/delos_oracle.json")
      .then((r) => r.json())
      .then(setIdl)
      .catch((e) => console.error("Failed to load IDL:", e));
  }, []);

  const { data, loading, error, refresh } = useOracleData(idl);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Nav */}
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold tracking-tight text-white">
            Delos Oracle
          </span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-green-900 text-green-300 font-mono">
            devnet
          </span>
        </div>
        <WalletMultiButton className="!bg-gray-800 hover:!bg-gray-700 !rounded-lg !text-sm" />
      </nav>

      {/* Main */}
      <main className="max-w-4xl mx-auto px-6 py-10 space-y-8">
        {/* Hero */}
        <div className="space-y-2">
          <h1 className="text-3xl font-bold text-white">
            Brazilian Macroeconomic Oracle
          </h1>
          <p className="text-gray-400 max-w-xl">
            BCB reference rates posted on-chain hourly from{" "}
            <a
              href="https://www.bcb.gov.br"
              target="_blank"
              rel="noopener noreferrer"
              className="text-green-400 hover:underline"
            >
              Banco Central do Brasil
            </a>
            . No auth required — public data, open infrastructure.
          </p>
        </div>

        {/* Oracle data */}
        {!idl && (
          <div className="text-gray-500 text-sm">
            Loading IDL…
          </div>
        )}

        {idl && error && (
          <div className="bg-red-950 border border-red-800 rounded-xl p-4 text-red-300 text-sm">
            <strong>Error reading on-chain state:</strong> {error}
          </div>
        )}

        {idl && loading && !data && (
          <div className="text-gray-400 text-sm animate-pulse">
            Fetching on-chain data from Solana devnet…
          </div>
        )}

        {idl && data && (
          <MacroDisplay data={data} loading={loading} onRefresh={refresh} />
        )}

        {/* Footer */}
        <footer className="pt-8 border-t border-gray-800 text-xs text-gray-600 flex items-center justify-between">
          <span>Delos Oracle — Milestone 2</span>
          <a
            href="https://github.com/PedroDnT/iliquid_nightly"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-gray-400 transition-colors"
          >
            GitHub
          </a>
        </footer>
      </main>
    </div>
  );
}
