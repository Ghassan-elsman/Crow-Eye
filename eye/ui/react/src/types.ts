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
  block_type: 'text' | 'table' | 'image' | 'reference' | 'chat' | 'chart';
  metadata: {
    timestamp: string;
    author?: string;
    last_modified?: string;
    last_modified_by?: string;
  };
}

export interface ChartBlock extends ReportBlock {
  block_type: 'chart';
  chart_type: 'bar' | 'line' | 'pie';
  title: string;
  labels: string[];
  datasets: { label: string; data: number[]; backgroundColor?: string; borderColor?: string }[];
}

export interface ReportBlock {
  block_id: string;
  block_type: 'text' | 'table' | 'image' | 'reference' | 'chat' | 'chart';
  metadata: {
    timestamp: string;
    author?: string;
    last_modified?: string;
    last_modified_by?: string;
  };
}

export interface ChartBlock extends ReportBlock {
  block_type: 'chart';
  chart_type: 'bar' | 'line' | 'pie';
  title: string;
  labels: string[];
  datasets: { label: string; data: number[]; backgroundColor?: string; borderColor?: string }[];
}

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
  switch_active_model: (model_name: string) => Promise<boolean>;
  set_report_pane_visible: (visible: boolean) => void;
  requestCaseContext: () => void;
  requestCaseSummary: () => void;
  requestSettings: () => void;
  // Evidence preservation methods
  pin_message: (message_id: string) => Promise<string>;
  unpin_message: (message_id: string) => Promise<string>;
  export_audit_trail: (output_path: string) => Promise<string>;
  update_token_budget: (budget_json: string) => Promise<string>;
}

declare global {
  interface Window {
    bridge?: EYEBridge;
  }
}
