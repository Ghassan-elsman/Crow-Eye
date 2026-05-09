# EYE Assistant: Strategic Enhancements (v2.0)

This roadmap focuses on evolving EYE from a **reactive query-engine** to a **proactive forensic partner** by leveraging its configuration and validation layers.

---

## 1. Smarter Intelligence

### A. Dynamic Token Budgeting
- **Concept**: Instead of static token limits in `eye_config.json`, the `ContextWindowConfigManager` should auto-adjust based on artifact complexity.
- **Example**: If investigating the MFT (high density), increase RAG context tokens; if chatting about a simple timeline, increase history tokens.
- **Benefit**: Optimized "memory" usage for every specific forensic scenario.

### B. Schema-Driven "Intelligent Settings"
- **Concept**: The Onboarding Wizard and Settings UI should be dynamically generated from `eye_config_schema.json`.
- **Logic**: If the schema adds a new backend, the UI updates automatically. Validation happens in real-time as the user types, using the schema's regex patterns.
- **Benefit**: Error-proof configuration and future-proof UI.

### C. Forensic Hypothesis Generation
- **Concept**: Use the `IntentEngine` to not just detect keywords, but to suggest an "Investigative Hypothesis" to the user before the LLM even runs.
- **Benefit**: Helps the investigator stay focused on the "Ghassan Elsman Protocol" goals.

---

## 2. Faster Performance

### A. Streaming over QWebChannel
- **Concept**: Implement a "Chunked Message Protocol." 
- **Mechanism**: The Python backend emits small JSON chunks via a `token_received` signal. The React frontend appends these to a buffer.
- **Benefit**: Users see the AI "typing" the forensic analysis in real-time, reducing perceived latency to zero.

### B. Pre-emptive Connection Pooling
- **Concept**: The `ModelRouter` should "warm up" the backend (e.g., wake up Ollama or verify the `gemini_cli` path) as soon as the app starts, not when the first query is sent.
- **Benefit**: Saves 2-5 seconds on the very first investigation query.

### C. Parallel Metadata Discovery
- **Concept**: Run `DBSvc.discover_databases()` and `RAGSvc.initialize()` in parallel background threads during boot.
- **Benefit**: Instant readiness when the UI displays.

---

## 3. Advanced Forensic Features

### A. "Ghost Report" Automation
- **Concept**: As tools are executed in Stage 6, the `ReportEngine` automatically drafts a hidden "Evidence Scratchpad."
- **Benefit**: If the final synthesis fails (e.g., LLM timeout), the raw evidence is still preserved and available to the user.

### B. Cross-Case Semantic Search
- **Concept**: Allow RAG to query not just documentation, but *previous* investigation reports from other cases (anonymized).
- **Benefit**: Discover patterns (e.g., same malware signature) across different investigations.
