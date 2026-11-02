# Correlation Engine Documentation

Welcome to the Crow-Eye Correlation Engine documentation! This directory contains comprehensive documentation for developers and contributors.

## 🚀 What's New in Crow-Eye 0.15.0: the Behavioural Engine

- **A third engine.** `engine/behavioural_engine.py` runs **Behaviour Wings** over the behaviours User Behavior found, one person (SID) at a time, finding chains of them in order or in any order within a set number of minutes. Two people's actions are never chained together.
- **Every Wing has a category** (Time, Identity or Behaviour); `engine/engine_registry.py` routes it to its engine, and a Wing given to the wrong engine is skipped with the reason.
- **35 Wings ship** in `integration/default_wings/`: 11 Identity, 6 Time, 18 Behaviour.
- **Behaviour Results** (`gui/behaviour_results_view.py`) lists each hit with the person, the Wing and its steps; **Open in User Behavior** goes back to the behaviours.
- **Behaviour is context, never corroboration**: a behaviour hit is shown beside Time and Identity matches and never adds to their score.
- **The Time-Window and Identity engines are deterministic**: the same results and match ids on every run.

## Earlier: v0.7.1 - Comprehensive Dual-Engine Update

The Correlation Engine is production-ready with a robust dual-engine architecture for optimal performance and analytical flexibility:

### ⭐ Time-Window Scanning Engine (TWSE)
- **O(N log N) Performance** - Indexed timestamp queries for efficient time-based correlation.
- **Up to 76x Faster** - Batch processing with parallel windows delivers high throughput.
- **Systematic Temporal Analysis** - Scans through time from year 2000 in fixed intervals.
- **Universal Timestamp Support** - Handles any timestamp format automatically with robust parsing.
- **Memory Efficient** - Optimized for large datasets with intelligent caching and spill-to-disk capabilities.
- **Production-Ready** - Battle-tested for time-based artifact analysis.

### ⭐ Identity-Based Correlation Engine (IBCE)
- **O(N log N) Performance** - Fast, scalable correlation for large datasets.
- **Identity-First Approach** - Comprehensive identity extraction, normalization, and validation.
- **Streaming Mode** - Memory-efficient processing for millions of records by persisting results incrementally.
- **Advanced Validation** - Field-aware identity validation with prioritization.
- **Semantic Integration** - Built-in semantic rule evaluation and enrichment of matches.
- **Production-Ready** - Recommended for identity-centric investigations and entity tracing.

### Enhanced GUI Viewers (Production-Ready)
- **Time-Based Results Viewer** - Hierarchical window-based view with dynamic grouping.
- **Identity Results Viewer** - Compact identity-centric view with pagination.
- **Semantic Columns** - Semantic mapping display in both viewers.
- **Scoring Breakdown** - Detailed confidence score visualization.
- **Multi-Tab Support** - View multiple correlation results simultaneously.

**Updated Documentation**:
- **[Engine Documentation](engine/ENGINE_DOCUMENTATION.md)** - **COMPREHENSIVELY UPDATED!** Detailed dual-engine architecture, full component breakdown, engine comparison, and selection guide. This is your go-to resource for engine internals.
- **[GUI Viewers](gui/GUI_DOCUMENTATION.md)** - Enhanced results visualization.

## Quick Navigation

### 📖 Start Here
- **[CORRELATION_ENGINE_OVERVIEW.md](CORRELATION_ENGINE_OVERVIEW.md)** - Main overview with all architecture diagrams, quick start guide, and navigation.
- **[Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide)** - **UPDATED!** Comprehensive guidance on choosing between Time-Window Scanning and Identity-Based engines.

### 📁 Detailed Documentation by Directory

- **[engine/ENGINE_DOCUMENTATION.md](engine/ENGINE_DOCUMENTATION.md)** - **COMPREHENSIVELY UPDATED!** Dual-engine architecture, Time-Window Scanning Engine (TWSE), Identity-Based Correlation Engine (IBCE), engine comparison and selection guide, performance optimization, troubleshooting, and detailed file-by-file component documentation.
- **[feather/FEATHER_DOCUMENTATION.md](feather/FEATHER_DOCUMENTATION.md)** - Data normalization, import, transformation.
- **[wings/WINGS_DOCUMENTATION.md](wings/WINGS_DOCUMENTATION.md)** - Correlation rule definitions, validation, wing models.
- **[config/CONFIG_DOCUMENTATION.md](config/CONFIG_DOCUMENTATION.md)** - Configuration management, semantic mappings, session state.
  - **[Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md)** - **NEW!** Centralized artifact type definitions.
  - **[Weight Precedence](config/WEIGHT_PRECEDENCE.md)** - **NEW!** Weight resolution hierarchy.
  - **[Configuration Reload](config/CONFIGURATION_RELOAD.md)** - **NEW!** Live configuration updates.
- **[Semantic Mapping Guide](semantic_mapping/SEMANTIC_MAPPING_GUIDE.md)** - Explains the semantic mapping system, its components, and integration.
- **[pipeline/PIPELINE_DOCUMENTATION.md](pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration, pipeline execution, dependency management.
- **[gui/GUI_DOCUMENTATION.md](gui/GUI_DOCUMENTATION.md)** - User interface components, visualization, timeline widgets.
- **[integration/INTEGRATION_DOCUMENTATION.md](integration/INTEGRATION_DOCUMENTATION.md)** - Crow-Eye integration, auto-generation, case initialization.
  - **[Integration Interfaces](integration/INTEGRATION_INTERFACES.md)** - **NEW!** Dependency injection and testing.

### 🏗️ Architecture Documentation
- **[WING_FEATHER_GUIDE.md](WING_FEATHER_GUIDE.md)** - Wing vs Feather comparison, data flow diagrams.

## Documentation Structure

This documentation follows a two-tier structure:

1. **Overview File** (`CORRELATION_ENGINE_OVERVIEW.md`)
   - Contains ALL architecture diagrams
   - High-level system overview
   - Quick start guide
   - Common modification scenarios
   - Navigation links to detailed docs

2. **Directory-Specific Files** (7 files + 4 new specialized docs)
   - Detailed file-by-file documentation
   - Class and method descriptions
   - Dependencies and dependents
   - Impact analysis
   - Code examples
   - Modification scenarios

## For New Developers

If you're new to the Correlation Engine:

1. **Start with the [Overview](CORRELATION_ENGINE_OVERVIEW.md)** - Read the introduction and look at the diagrams.
2. **Understand the dual-engine architecture** - Read about the [Time-Window Scanning Engine](#time-window-scanning-engine-twse) and [Identity-Based Correlation Engine](#identity-based-correlation-engine-ibce) in the main `ENGINE_DOCUMENTATION.md`.
3. **Learn engine selection** - Review the [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) to understand when to use each engine.
4. **Understand configuration** - Review [Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md) and [Weight Precedence](config/WEIGHT_PRECEDENCE.md).
5. **Understand the architecture** - Review the system architecture and data flow diagrams.
6. **Identify your area** - Determine which directory you'll be working in.
7. **Read detailed docs** - Read the detailed documentation for that directory.
8. **Review scenarios** - Look at modification scenarios similar to your task.

## Engine Selection Quick Guide

**Choose Time-Window Scanning Engine (TWSE) when:**
- ⭐ You need time-based artifact analysis (production-ready).
- ✅ Dataset has any size (optimized for large datasets).
- ✅ You need `O(N log N)` performance with indexed queries.
- ✅ You want systematic temporal analysis.
- ✅ Memory efficiency is important.
- ✅ You need universal timestamp format support.
- ✅ You want high throughput batch processing.

**Choose Identity-Based Correlation Engine (IBCE) when:**
- ⭐ You need identity tracking across artifacts (production-ready).
- ✅ Dataset has `> 1,000` records.
- ✅ You want to filter by specific applications or entities.
- ✅ You need relationship mapping between identities.
- ✅ Memory constraints require streaming mode.
- ✅ You want `O(N log N)` performance with strong identity normalization.

**Both engines are production-ready and optimized for large datasets. Refer to the [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) for comprehensive decision criteria.**

## For Contributors

If you're contributing to the Correlation Engine:

1. **Read relevant documentation** - Understand the area you're modifying.
2. **Check dependencies** - Review what depends on your changes.
3. **Follow scenarios** - Use modification scenarios as guides.
4. **Test thoroughly** - Test with multiple artifact types and configurations.
5. **Update documentation** - Update docs if you change behavior.
6. **Use interfaces** - Implement integration interfaces for new components.
7. **Test configuration reload** - Ensure your changes support live reload.

## Quick Reference

### Finding Specific Information

- **How correlation works**: [Overview - Correlation Execution Flow](CORRELATION_ENGINE_OVERVIEW.md#correlation-execution-flow)
- **Choosing an engine**: [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide)
- **Time-Window Scanning Engine (TWSE) details**: [Time-Window Scanning Engine (TWSE)](engine/ENGINE_DOCUMENTATION.md#time-window-scanning-engine-twse)
- **Identity-Based Correlation Engine (IBCE) details**: [Identity-Based Correlation Engine (IBCE)](engine/ENGINE_DOCUMENTATION.md#identity-based-correlation-engine-ibce)
- **Performance optimization**: [Performance and Optimization](engine/ENGINE_DOCUMENTATION.md#performance-and-optimization) (refer to `ENGINE_DOCUMENTATION.md` for overall engine performance, `performance_analysis.py` and `performance_monitor.py` details)
- **Troubleshooting engines**: [Troubleshooting](engine/ENGINE_DOCUMENTATION.md#troubleshooting) (refer to `ENGINE_DOCUMENTATION.md` for general engine troubleshooting, `integration_error_handler.py` and `integration_monitor.py` for integration-specific issues)
- **Artifact type registry**: [Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md) **NEW!**
- **Weight precedence**: [Weight Precedence](config/WEIGHT_PRECEDENCE.md) **NEW!**
- **Configuration reload**: [Configuration Reload](config/CONFIGURATION_RELOAD.md) **NEW!**
- **Integration interfaces**: [Integration Interfaces](integration/INTEGRATION_INTERFACES.MD) **NEW!**
- **Adding new artifact type**: [Feather Documentation - Scenario 1](feather/FEATHER_DOCUMENTATION.md#scenario-1-adding-support-for-a-new-artifact-type) or [Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md#adding-new-artifact-types)
- **Modifying correlation logic**: [Common Modification Scenarios](engine/ENGINE_DOCUMENTATION.md#common-modification-scenarios) (refer to `ENGINE_DOCUMENTATION.md` for detailed scenarios)
- **Adding GUI feature**: [GUI Documentation - Scenario 1](gui/GUI_DOCUMENTATION.md#scenario-1-adding-a-new-tab-to-main-window)
- **Understanding Wings**: [Wings Documentation](wings/WINGS_DOCUMENTATION.md)
- **Pipeline execution**: [Pipeline Documentation](pipeline/PIPELINE_DOCUMENTATION.md)
- **Component integration**: [Architecture - Component Integration](../ARCHITECTURE.md#component-integration)
- **Wing vs Feather**: [Wing vs Feather: Key Differences](WING_FEATHER_GUIDE.md)

### Key Files by Function

**Configuration & Registry**:
- `config/artifact_type_registry.py` - **NEW!** Centralized artifact type definitions
- `config/artifact_types.json` - **NEW!** Artifact type configuration file
- `config/integrated_configuration_manager.py` - **ENHANCED!** Configuration with observer pattern
- `integration/interfaces.py` - **NEW!** Integration interface definitions

**Engine Selection & Creation**:
- `engine/engine_selector.py` - Engine factory and selection
- `engine/base_engine.py` - Common engine interface

**Correlation Engines**:
- `engine/time_based_engine.py` - Time-Window Scanning Engine (TWSE) implementation
- `engine/identity_based_engine_adapter.py` - Identity-Based Correlation Engine (IBCE) implementation
- `engine/two_phase_correlation.py` - Two-phase architecture components for TWSE
- `engine/weighted_scoring.py` - Core confidence scoring logic

**Integration Components**:
- `integration/weighted_scoring_integration.py` - **ENHANCED!** Implements IScoringIntegration
- `integration/semantic_mapping_integration.py` - **ENHANCED!** Implements ISemanticMappingIntegration

**Data Structures**:
- `engine/data_structures.py` - Identity, Anchor, EvidenceRow structures

**Data Loading**:
- `engine/feather_loader.py` - Load feather databases
- `feather/transformer.py` - Transform source data

**Configuration**:
- `config/config_manager.py` - Manage all configs
- `wings/core/wing_model.py` - Wing data models

**Execution**:
- `pipeline/pipeline_executor.py` - Execute pipelines (uses EngineSelector)
- `gui/execution_control.py` - GUI execution control

**Integration**:
- `integration/crow_eye_integration.py` - Crow-Eye bridge
- `integration/case_initializer.py` - Case setup

## Documentation Files

Total: 13 documentation files (note: `IDENTIFIER_EXTRACTION_README.md` content integrated into `ENGINE_DOCUMENTATION.md`)

1. `CORRELATION_ENGINE_OVERVIEW.md` (Main overview with diagrams and quick start)
2. `engine/ENGINE_DOCUMENTATION.md` - **COMPREHENSIVELY UPDATED!** Core architecture, dual-engine details, engine comparison, selection guide, performance, troubleshooting, and detailed file-by-file component documentation.
3. `feather/FEATHER_DOCUMENTATION.md` (4 Python files + UI)
4. `wings/WINGS_DOCUMENTATION.md` (3 Python files + UI)
5. `config/CONFIG_DOCUMENTATION.md` (10 Python files)
6. `config/ARTIFACT_TYPE_REGISTRY.md` **NEW!** (Artifact type registry)
7. `config/WEIGHT_PRECEDENCE.md` **NEW!** (Weight precedence system)
8. `config/CONFIGURATION_RELOAD.md` **NEW!** (Live configuration reload)
9. `semantic_mapping/SEMANTIC_MAPPING_GUIDE.md` (Semantic Mapping System, Components, and Integration)
10. `pipeline/PIPELINE_DOCUMENTATION.md` (7 Python files)
11. `gui/GUI_DOCUMENTATION.md` (26 Python files)
12. `integration/INTEGRATION_DOCUMENTATION.md` (7 Python files)
13. `integration/INTEGRATION_INTERFACES.md` **NEW!** (Integration interfaces)
14. `WING_FEATHER_GUIDE.md` (Wing vs Feather comparison, relationship flow)

**Total Documentation**: ~10,000 lines covering dual-engine architecture and structural improvements

## Additional Resources

- **[FEATHER_METADATA_OPTIONAL.md](FEATHER_METADATA_OPTIONAL.md)** - Feather metadata table details
- **[PIPELINE_CONFIG_MANAGER_README.md](PIPELINE_CONFIG_MANAGER_README.md)** - Pipeline configuration management
- **[../gui/README.md](../gui/README.md)** - GUI architecture overview

## Getting Help

If you need help:

1. Check the [Overview](CORRELATION_ENGINE_OVERVIEW.md) first
2. Look at the relevant directory documentation
3. Review the diagrams to understand data flow
4. Check modification scenarios for similar tasks
5. Look at code examples in the documentation
6. Review [Integration Interfaces](integration/INTEGRATION_INTERFACES.md) for dependency injection
7. Check [Configuration Reload](config/CONFIGURATION_RELOAD.md) for live updates

## Contributing to Documentation

When updating documentation:

1. Keep the overview file as the main entry point
2. Update directory-specific files for detailed changes
3. Add new modification scenarios when appropriate
4. Update diagrams if architecture changes
5. Keep code examples current and working
6. Document new interfaces and patterns
7. Update configuration examples

---

**Last Updated**: February 2026 (Updated to reflect comprehensive engine documentation)
**Correlation Engine Version**: 0.7.1 (Production-Ready Dual-Engine Architecture)
**Documentation Version**: 0.8 (Major update for engine internals)

**Major Updates in v0.7.1**:
- ⭐ Time-Window Scanning Engine - Production-ready with O(N log N) performance (76x faster)
- ⭐ Identity-Based Engine - Production-ready with advanced validation and streaming
- 📊 Enhanced GUI Viewers (Time-Based and Identity Results)
- 🔍 Semantic Rule Evaluation at identity level
- 💾 Streaming Mode for memory-efficient processing
- 📖 **Comprehensive Engine Documentation** - Overhaul of `ENGINE_DOCUMENTATION.md` to detail dual-engine architecture, component interaction, and advanced features.

## 🚀 Coming Soon Features

### Acquisition & Offline Analysis
- 💾 **Acquisition Function** - Collect and save artifacts for later parsing without immediate analysis
  - Batch collection from multiple systems
  - Preserve artifacts before Windows deletes them
  - Store for historical forensic analysis
- 🔧 **Offline Parser** - Parse saved artifacts without live system access
  - Batch processing of collected artifacts
  - Remote analysis capabilities
  - Historical data investigation

### Enhanced Correlation Features
- 🎯 **Enhanced Semantic Mapping** - Comprehensive field mapping across all artifact types
- 📈 **Advanced Correlation Scoring** - Refined confidence scoring algorithms with explainability
- 🔍 **Cross-Machine Correlation** - Correlate artifacts across multiple systems
- 📊 **Advanced Reporting** - Customizable reports with visual correlation graphs
