# EYE Architecture Diagrams - Quick Reference Guide

## 📍 Navigation Guide

### I Need to Understand...

#### **How the whole system works**
→ Go to: **Executive Architecture Overview** (Top of document)
- Complete System Architecture diagram
- Technology Stack diagram

#### **How AI backends are integrated**
→ Go to: **Section 1.5 - Backend Strategy Pattern Implementation**
- Shows OpenAI, Anthropic, Gemini, Ollama, LM Studio, CLI backends
- Class hierarchy and ModelRouter

#### **How a query is processed**
→ Go to: **Section 1.5 - Query Processing Pipeline (8 Stages)**
- Detailed sequence diagram showing all 8 stages
- From user input to final response

#### **How data is protected**
→ Go to: **Section 1.5 - Database Service Security Architecture**
- 3-layer security validation
- SQL injection prevention

#### **How reports are structured**
→ Go to: **Section 1.5 - Report Engine Block System**
- TextBlock, TableBlock, ImageBlock, ChartBlock, etc.
- ReportEngine operations

#### **How the UI communicates with backend**
→ Go to: **Section 1.5 - UI Layer Communication Architecture**
- QWebChannel bridge
- Signals and slots
- JavaScript ↔ Python communication

#### **How configuration works**
→ Go to: **Section 1.5 - Configuration and Credential Management**
- Config file locations
- OS keychain integration
- Schema validation

#### **How tools are executed**
→ Go to: **Section 1.5 - Tool Execution Dispatch System**
- Tool handler mapping
- ForensicHandlers vs ReportHandlers

#### **How RAG retrieval works**
→ Go to: **Before Section 3 - RAG Service Architecture**
- Knowledge base structure
- Semantic search flow
- Embedding generation

#### **How data is compressed**
→ Go to: **Before Section 3 - TOON Engine**
- Token-oriented compression strategies
- Data optimization pipeline

#### **How errors are handled**
→ Go to: **Before Section 3 - Error Handling and Recovery Flow**
- State diagram for error states
- Retry logic and fallback

#### **How conversation history is managed**
→ Go to: **Before Section 3 - History Management and Token Budgeting**
- Token budget allocation
- History truncation strategies

#### **How the case directory is organized**
→ Go to: **Before Section 3 - Case Directory Structure**
- File system layout
- Service access patterns

#### **How testing is structured**
→ Go to: **Section 8 - Testing Architecture**
- Unit, integration, property-based tests
- CI/CD pipeline

#### **How the application is packaged**
→ Go to: **Section 9 - Application Packaging Structure**
- Module organization
- Dependencies

#### **How deployment scenarios work**
→ Go to: **Section 9 - Multi-Backend Deployment Scenarios**
- Cloud-only, local server, air-gapped, hybrid

#### **How a complete investigation flows**
→ Go to: **Section 10 - Complete Investigation Workflow**
- End-to-end sequence diagram
- From case opening to report generation

#### **How reports are imported**
→ Go to: **Section 10 - Report Import and Parsing Flow**
- HTML parsing process
- Block extraction and merging

#### **How model switching works**
→ Go to: **Section 10 - Model Switching and Fallback Flow**
- State diagram for backend switching
- Quota error handling

#### **How evidence is protected**
→ Go to: **Section 11 - Data Protection Layers**
- 5-layer security architecture
- Audit trail

#### **How the Ghassan Elsman Protocol is enforced**
→ Go to: **Section 11 - Ghassan Elsman Protocol Enforcement**
- Protocol rules
- Enforcement mechanisms

#### **How token budgets are optimized**
→ Go to: **Section 12 - Token Budget Optimization**
- Context window management
- Optimization strategies

#### **How caching improves performance**
→ Go to: **Section 12 - Caching and Performance Layers**
- Multi-level cache hierarchy
- Performance optimizations

---

## 🎨 Diagram Legend

### Node Colors
- 🟠 **Orange** (#f97316): Core brain (ContextManager, QueryProcessor)
- 🔵 **Cyan** (#06b6d4): AI/Model components (ModelRouter, backends)
- 🟢 **Green** (#10b981): Report/output (ReportEngine)
- 🔴 **Pink** (#ec4899): Bridge/communication (EYEBridge)
- 🔴 **Red** (#ef4444): Security/credentials (CredentialManager)
- ⚫ **Gray** (#475569): Data storage (SQLite, files)

### Arrow Types
- **Solid Arrow** (→): Direct function call or data flow
- **Dashed Arrow** (-.->): Signal emission or event
- **Thick Arrow** (==>): Primary/critical path

### Node Shapes
- **Rectangle**: Component or service
- **Rounded Rectangle**: Process or operation
- **Cylinder**: Database or storage
- **Diamond**: Decision point or router
- **Circle**: External actor (user, internet)

---

## 📊 Diagram Types

### Graph Diagrams (TB = Top-to-Bottom, LR = Left-to-Right)
- Show component relationships
- Display data flow
- Illustrate system architecture

### Class Diagrams
- Show object-oriented design
- Display inheritance hierarchies
- Illustrate design patterns

### Sequence Diagrams
- Show temporal interactions
- Display message passing
- Illustrate workflows

### State Diagrams
- Show state transitions
- Display error handling
- Illustrate lifecycle management

---

## 🔍 Common Patterns to Look For

### The Mediator Pattern
**Where**: ContextManager in service layer diagrams
**Why**: Central coordination point for all services
**Look for**: Star topology with CM at center

### The Strategy Pattern
**Where**: Backend integration diagrams
**Why**: Interchangeable AI backends
**Look for**: LLMBackend interface with multiple implementations

### The Repository Pattern
**Where**: ReportEngine diagrams
**Why**: Centralized report block management
**Look for**: ReportEngine managing multiple ReportBlock types

### The Facade Pattern
**Where**: EYEBridge diagrams
**Why**: Simplified interface for frontend
**Look for**: Bridge exposing limited methods to React UI

### The Pipeline Pattern
**Where**: QueryProcessor diagrams
**Why**: Multi-stage query processing
**Look for**: Numbered stages (1-8) in sequence

---

## 🚀 Quick Start Paths

### For New Developers
1. Start with **Executive Architecture Overview**
2. Read **Service Layer Architecture**
3. Study **Query Processing Pipeline**
4. Review **Tool Execution Dispatch System**

### For Frontend Developers
1. Start with **UI Layer Communication Architecture**
2. Study **QWebChannel bridge patterns**
3. Review **Complete Investigation Workflow**
4. Examine **Report Import and Parsing Flow**

### For Backend Developers
1. Start with **Service Layer Architecture**
2. Study **Backend Strategy Pattern Implementation**
3. Review **Database Service Security Architecture**
4. Examine **Tool Execution Dispatch System**

### For Security Auditors
1. Start with **Database Service Security Architecture**
2. Study **Data Protection Layers**
3. Review **Ghassan Elsman Protocol Enforcement**
4. Examine **Configuration and Credential Management**

### For Performance Engineers
1. Start with **Token Budget Optimization**
2. Study **TOON Engine**
3. Review **Caching and Performance Layers**
4. Examine **History Management and Token Budgeting**

### For DevOps Engineers
1. Start with **Application Packaging Structure**
2. Study **Runtime Environment Configuration**
3. Review **Multi-Backend Deployment Scenarios**
4. Examine **Continuous Integration Pipeline**

---

## 📝 Diagram Maintenance Notes

### When Adding New Features
- Update **Service Layer Architecture** if adding new services
- Update **Tool Execution Dispatch System** if adding new tools
- Update **Query Processing Pipeline** if modifying stages
- Update **Backend Strategy Pattern** if adding new AI backends

### When Modifying Security
- Update **Database Service Security Architecture**
- Update **Data Protection Layers**
- Update **Ghassan Elsman Protocol Enforcement**

### When Changing Data Flow
- Update **Complete Investigation Workflow**
- Update **Query Processing Pipeline**
- Update **Report Import and Parsing Flow**

### When Optimizing Performance
- Update **Token Budget Optimization**
- Update **Caching and Performance Layers**
- Update **TOON Engine** if compression changes

---

## 🔗 Cross-References

### Related Documentation
- **README.md**: User-facing documentation
- **eye_deep_analysis.md**: Complete technical analysis (contains all diagrams)
- **ARCHITECTURE_DIAGRAMS_SUMMARY.md**: Summary of diagram additions

### Related Code
- **backends/**: Backend implementation (see Backend Strategy Pattern diagram)
- **services/**: Service layer (see Service Layer Architecture diagram)
- **bridge/**: QWebChannel bridge (see UI Layer Communication diagram)
- **ui/**: User interface (see UI Layer Communication diagram)

---

**Last Updated**: 2024
**Version**: 1.5
**Maintainer**: EYE Development Team
