export interface SubstatLine {
  stat: string;
  rolls: number;
}

export interface GearPiece {
  position: string | number;
  set_name: string;
  main_stat: string;
  level: number;
  substats: SubstatLine[];
  locked: boolean;
  initial_substat_count: 3 | 4;
  revealed_next_substat?: string | null;
}

export interface SetRequirement {
  set_name?: string | null;
  set_names?: string[];
  pieces: number;
  role?: string | null;
  priority?: number | null;
}

export interface SetPlan {
  id: string;
  name: string;
  requirements: SetRequirement[];
  notes?: string | null;
}

export interface CharacterPreset {
  id: string;
  game: string;
  name: string;
  target_set: string;
  effective_substats: Record<string, number>;
  substat_priority?: {
    core: string[];
    usable: string[];
    core_tiers?: string[][];
    usable_tiers?: string[][];
  } | null;
  preferred_main_stats: Record<string, string[]>;
  set_plans: SetPlan[];
  default_set_plan?: string | null;
  target_effective_rolls: number;
  target_weighted_score?: number | null;
  rating_thresholds?: Record<string, number>;
  notes?: string | null;
}

export interface GameSummary {
  id: string;
  name: string;
  gear_name: string;
}

export interface PositionOption {
  id: string;
  name: string;
  main_stats: string[];
  set_names: string[];
}

export interface AgentSummary {
  agent_id: string;
  name: string;
  rarity: string;
  attribute: string;
  specialty: string;
  faction: string;
  portrait_path?: string | null;
  card_path?: string | null;
  configured_target_template_id: string;
}

export interface TargetTemplateSummary {
  id: string;
  name: string;
  builtin: boolean;
  source_agent_id: string;
  preferred_main_stats: Record<string, string[]>;
  target_sets: string[];
  priority_stats: string[];
}

export interface ItemOwner {
  agent_id: string;
  agent_name: string;
  loadout_id: string;
  position: string;
}

export interface InventoryItem {
  item_id: string;
  piece: GearPiece;
  status: "backpack" | "equipped";
  equipped_by?: ItemOwner | null;
  referenced_by_snapshots: number;
}

export interface LoadoutSlot {
  position: string;
  position_name: string;
  item_id?: string | null;
  item?: InventoryItem | null;
}

export interface CurrentLoadout {
  loadout_id?: string | null;
  label: string;
  slots: LoadoutSlot[];
  complete: boolean;
}

export interface Capability {
  available: boolean;
  reason: string;
}

export interface Workspace {
  games: GameSummary[];
  game_id: string;
  game_name: string;
  gear_name: string;
  sets: string[];
  sub_stats: string[];
  max_level: number;
  level_step: number;
  positions: PositionOption[];
  agents: AgentSummary[];
  agent_id: string;
  target_templates: TargetTemplateSummary[];
  active_target_template_id?: string | null;
  active_target_template?: CharacterPreset | null;
  inventory: InventoryItem[];
  current_loadout: CurrentLoadout;
  capabilities: Record<string, Capability>;
  inventory_revision: number;
  loadout_revision: number;
  target_selection_revision: number;
  canonical_inventory: boolean;
}

export interface DesktopError {
  code: string;
  message: string;
  details: Record<string, unknown>;
  retryable: boolean;
}

export interface DesktopResponse<T extends Record<string, unknown> = Record<string, unknown>> {
  schema_version: 1;
  request_id: string;
  ok: boolean;
  data?: T | null;
  error?: DesktopError | null;
}

export interface WorkspaceResponseData extends Record<string, unknown> {
  workspace: Workspace;
}

export interface ActionEvPerformanceAudit {
  action_count: number;
  raw_outcome_count: number;
  aggregated_outcome_count: number;
  best_loadout_value_calls: number;
  best_loadout_cache_hits: number;
  best_loadout_cache_misses: number;
  outcome_cache_hits: number;
  outcome_cache_misses: number;
  action_timings: Array<Record<string, unknown>>;
  top_10_slowest_actions: Array<Record<string, unknown>>;
  phase_seconds: Record<string, number>;
  phase_counts: Record<string, number>;
  phase_average_seconds: Record<string, number>;
  top_20_slowest_phase_calls: Array<Record<string, unknown>>;
  total_seconds: number;
}

export interface ActionEvRow {
  strategy: string;
  target_set: string;
  position: string;
  main_stat: string;
  fixed_substats: string;
  horizon: number;
  immediate_ev: string;
  horizon_ev: string;
  expected_gain: string;
  set_completion_probability: number;
  quality_gain: number;
  effective_gain: number;
  mother_cost: number | string;
  quality_per_mother: number | string;
  effective_per_mother: number | string;
  [key: string]: unknown;
}

export interface ActionEvResult {
  run_id: string;
  engine: string;
  action_mode: string;
  input_audit: string;
  input_audit_lines: string[];
  performance_audit: ActionEvPerformanceAudit;
  rows: ActionEvRow[];
}

export interface ActionJob {
  job_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  game_id: string;
  agent_id: string;
  horizon: 1 | 2;
  engine: string;
  action_mode: string;
  started_at: string;
  elapsed_seconds: number;
  completed_units: number;
  total_units: number;
  progress_fraction: number;
  latest_event: Record<string, unknown>;
  result?: ActionEvResult | null;
  error?: Record<string, unknown> | null;
}

export interface ActionJobResponseData extends Record<string, unknown> {
  job: ActionJob;
}

export interface RuntimeEvent {
  ts?: string;
  source?: string;
  event?: string;
  method?: string;
  game_id?: string;
  agent_id?: string;
  elapsed_seconds?: number;
  result?: string;
  error_code?: string;
  [key: string]: unknown;
}

export interface InventoryFilters {
  sets: string[];
  positions: string[];
  mainStats: string[];
  targetMainOnly: boolean;
  ownership: "all" | "backpack" | "equipped";
}
