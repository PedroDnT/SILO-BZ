import React from "react";
import type { MacroData } from "../hooks/useOracleData";

interface Props {
  data:    MacroData;
  loading: boolean;
  onRefresh: () => void;
}

interface MetricCardProps {
  label:    string;
  value:    string;
  sublabel?: string;
}

function MetricCard({ label, value, sublabel }: MetricCardProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col gap-1">
      <span className="text-xs text-gray-400 uppercase tracking-widest">{label}</span>
      <span className="text-3xl font-mono font-bold text-green-400">{value}</span>
      {sublabel && (
        <span className="text-xs text-gray-500">{sublabel}</span>
      )}
    </div>
  );
}

function fmt(n: number, decimals = 2): string {
  return n.toFixed(decimals);
}

export function MacroDisplay({ data, loading, onRefresh }: Props) {
  const updatedAt = data.updatedTs.toLocaleString("pt-BR", {
    timeZone:     "America/Sao_Paulo",
    dateStyle:    "medium",
    timeStyle:    "short",
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">
            BCB Macroeconomic State
          </h2>
          <p className="text-sm text-gray-400 mt-0.5">
            Last posted: {updatedAt} BRT &nbsp;&bull;&nbsp; Slot {data.slot.toLocaleString()}
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="px-4 py-2 text-sm rounded-lg bg-gray-800 hover:bg-gray-700
                     text-gray-300 disabled:opacity-50 transition-colors"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Rates grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <MetricCard
          label="SELIC Meta"
          value={`${fmt(data.selicMeta)}%`}
          sublabel="Target rate (p.a.)"
        />
        <MetricCard
          label="SELIC Diária"
          value={`${fmt(data.selicDiaria)}%`}
          sublabel="Overnight rate (p.a.)"
        />
        <MetricCard
          label="CDI"
          value={`${fmt(data.cdi)}%`}
          sublabel="Interbank rate (p.a.)"
        />
        <MetricCard
          label="IPCA 12m"
          value={`${fmt(data.ipca)}%`}
          sublabel="CPI inflation (accumulated)"
        />
        <MetricCard
          label="IGP-M 12m"
          value={`${fmt(data.igpm)}%`}
          sublabel="General price index"
        />
        <MetricCard
          label="USD/BRL"
          value={fmt(data.usdbrl, 4)}
          sublabel="PTAX closing rate"
        />
      </div>

      {/* Raw on-chain note */}
      <p className="text-xs text-gray-600 text-right">
        Source: Banco Central do Brasil · Posted via Delos Oracle on Solana devnet
      </p>
    </div>
  );
}
