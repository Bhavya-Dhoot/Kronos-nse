export interface DimensionScore {
  name: string;
  score: number;
  weight: number;
  is_stale: boolean;
  detail: Record<string, unknown>;
  collected_at: string;
}

export type MarketState = "panic" | "fear" | "uncertain" | "bull_run" | "neutral";

export interface MVSData {
  composite: number;
  market_state: MarketState;
  vix_value: number | null;
  created_at: string;
  dimensions: DimensionScore[];
  temperature_adjustment: number;
  directional_bias: number;
  band_width_multiplier: number;
  signal_threshold: number;
  confidence_override: string | null;
}

export interface WSMessage {
  type: "mvs_update" | "ping" | "error";
  payload?: MVSData;
  channel?: string;
  detail?: string;
}
