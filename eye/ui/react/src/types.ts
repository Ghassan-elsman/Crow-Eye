// TypeScript interfaces for EYE AI Chat Interface

export interface ThinkingStep {
  step_id: string;
  type: 'thinking' | 'rag' | 'tool_call' | 'synthesis' | 'report_updated';
  label: string;
  status: 'active' | 'done' | 'error';
  tool?: string;
  params?: Record<string, any>;
  detail?: string;
  data?: any; // For report_updated event
}

export interface OptionMenuItem {
  id: string;
  label: string;
  description?: string;
  query: string;
}

// One entry in the Eye<->LLM conversation transcript (how the Eye is thinking):
// the prompt the Eye sent, the model's reply, a tool result, or a synthesis turn.
export interface EyeDialogueEntry {
  seq: number;
  timestamp: string;
  iteration: number | null;
  phase: 'request' | 'response' | 'tool_result' | 'synthesis_request' | 'synthesis_response';
  // request / synthesis_request
  system_prompt?: string;
  user_message?: string;
  tools_offered?: string[];
  history_count?: number;
  // response / synthesis_response
  content?: string;
  tool_calls?: { name: string; arguments: any }[];
  // tool_result
  tool_name?: string;
  parameters?: Record<string, any>;
  success?: boolean;
  result?: string;
}

export interface MessageMetadata {
  preserve_evidence?: boolean;
  evidence_patterns?: string[];
  evidence_confidence?: number;
  pinned?: boolean;
  pinned_at?: string;
  is_summary?: boolean;
  summarized_count?: number;
  message_hash?: string;
  created_at?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  data_viewer?: DataViewerProps;
  action_chips?: ActionChip[];
  option_menu?: OptionMenuItem[];
  thinking_steps?: ThinkingStep[];
  eye_dialogue?: EyeDialogueEntry[];
  metadata?: MessageMetadata;
}

export interface ContextStats {
  total_messages: number;
  total_tokens: number;
  budget_remaining: number;
  truncation_count: number;
  max_total_tokens: number;
  backend?: string;
  model_name?: string;
}

export interface ActionChip {
  id: string;
  label: string;
  query: string;
  icon?: string;
}

export interface DataViewerProps {
  columns: string[];
  rows: Record<string, any>[];
  query: string;
  database: string;
  table: string;
}

export interface ReportBlock {
  block_id: string;
  block_type: 'text' | 'table' | 'image' | 'reference' | 'chat' | 'chart' | 'timeline' | 'heatmap' | 'chain_of_custody';
  category?: string;
  metadata: {
    timestamp: string;
    author?: string;
    source_query?: string;
    last_modified?: string;
    last_modified_by?: string;
    chart_config?: any;
  };
}

export interface ChartBlock extends ReportBlock {
  block_type: 'chart';
  title: string;
  labels: string[];
  datasets: any[];
  chart_type: 'bar' | 'line' | 'pie' | 'doughnut' | 'radar';
}

export interface TimelineBlock extends ReportBlock {
  block_type: 'timeline';
  title: string;
  events: { timestamp: string; label: string; description: string; category?: string }[];
}

export interface HeatmapBlock extends ReportBlock {
  block_type: 'heatmap';
  title: string;
  x_labels: string[];
  y_labels: string[];
  intensity_values: number[][];
}

export interface TextBlock extends ReportBlock {
  block_type: 'text';
  title: string;
  markdown_content: string;
}

export interface TableBlock extends ReportBlock {
  block_type: 'table';
  sql_query: string;
  columns: string[];
  rows: Record<string, any>[];
  caption: string;
}

export interface ImageBlock extends ReportBlock {
  block_type: 'image';
  image_path: string;
  caption: string;
}

export interface ReferenceBlock extends ReportBlock {
  block_type: 'reference';
  reference_text: string;
  source_link: string;
  columns?: string[];
  evidence_data?: Record<string, any>[];
}

export interface ChatBlock extends ReportBlock {
  block_type: 'chat';
  messages: { role: string; content: string }[];
}

export interface ChainOfCustodyBlock extends ReportBlock {
  block_type: 'chain_of_custody';
  entries: { evidence_id: string; handler_name: string; action: string; timestamp: string }[];
}

export type AnyBlock = 
  | TextBlock 
  | TableBlock 
  | ImageBlock 
  | ReferenceBlock 
  | ChatBlock 
  | ChartBlock 
  | TimelineBlock 
  | HeatmapBlock 
  | ChainOfCustodyBlock;

// QWebChannel bridge interface
export interface EYEBridge {
  initialize_triage: () => Promise<string>;
  process_query: (query: string) => Promise<string>;
  query_database: (database: string, sql: string) => Promise<string>;
  search_artifacts: (searchConfig: string) => Promise<string>;
  get_schema: (database: string, table: string) => Promise<string>;
  propose_semantic_mapping: (ruleJson: string) => Promise<string>;
  get_report_state: () => Promise<string>;
  report_append_section: (title: string, content: string) => Promise<string>;
  report_add_data_table: (query: string, columns: string) => Promise<string>;
  report_add_image: (path: string, caption: string) => Promise<string>;
  report_edit_section: (blockId: string, content: string) => Promise<string>;
  report_delete_section: (blockId: string) => Promise<string>;
  export_report: (format: string) => Promise<string>;
  get_context_stats: () => Promise<string>;
  get_conversation_history: () => Promise<string>;
  clear_conversation_history: () => Promise<string>;
  get_available_models_with_quota: () => Promise<string>;
  get_grouped_backend_connections: () => Promise<string>;
  switch_active_model: (model_name: string) => Promise<boolean>;
  set_report_pane_visible: (visible: boolean) => void;
  requestCaseContext: () => void;
  requestCaseSummary: () => void;
  requestSettings: () => void;
  requestComplianceWindow: () => void;
  report_add_evidence: (text: string, link: string, evidenceJson: string) => Promise<string>;
  // Evidence preservation methods
  pin_message: (message_id: string) => Promise<string>;
  unpin_message: (message_id: string) => Promise<string>;
  export_audit_trail: (output_path: string) => Promise<string>;
  update_token_budget: (budget_json: string) => Promise<string>;
  // GEP Rule 7 / Protocol Compliance dashboard
  get_gep_compliance_status: () => Promise<string>;
  // Activity audit timeline shown on the Compliance window
  get_activity_audit: () => Promise<string>;
  // Per-step execution history (grouped by step) for the Compliance window
  get_step_history: () => Promise<string>;
  // Full Eye<->LLM conversation (grouped by question) for the Compliance window
  get_dialogue_history: () => Promise<string>;
  // Per-answer behavioral GEP compliance evaluations for the Compliance window
  get_gep_turns: () => Promise<string>;
  // Chain-of-custody evidence seals (exact bytes the model saw) for Compliance
  get_payload_seals: () => Promise<string>;
  // Chain-of-custody audit events (preserve/summarize/truncate/pin/refuse)
  get_truncation_events: () => Promise<string>;
  // Flattened per-payload cuts (processed vs dropped) for the Compliance window
  get_payload_cut_details: () => Promise<string>;
  // Full dropped/processed bytes for one cut, read on demand from its sidecar
  get_dropped_payload_full: (sha256: string) => Promise<string>;
  // Full sent payload (system prompt + history + tools) for one seal, decompressed on demand
  get_sealed_payload_full: (sha256: string) => Promise<string>;
  // Backend connectivity check for EYE Synchronization
  get_backend_status: () => Promise<string>;
}

declare global {
  interface Window {
    bridge?: EYEBridge;
  }
}
