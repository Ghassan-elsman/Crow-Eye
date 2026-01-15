# Correlation Engine Documentation

Welcome to the Crow-Eye Correlation Engine documentation! This directory contains comprehensive documentation for developers and contributors.

## 🚀 What's New: Latest Features (v0.7.1)

The Correlation Engine is production-ready with dual-engine architecture for optimal performance:

### ⭐ Time-Window Scanning Engine (Production-Ready!)
- **O(N log N) Performance** - Indexed timestamp queries for efficient time-based correlation
- **76x Faster** - Batch processing delivers 2,567 windows per second
- **Systematic Temporal Analysis** - Scans through time from year 2000 in fixed intervals
- **Universal Timestamp Support** - Handles any timestamp format automatically with robust indexing
- **Memory Efficient** - Optimized for large datasets with intelligent caching
- **Production-Ready** - Battle-tested for time-based artifact analysis

### Identity-Based Engine (Production-Ready)
- **O(N log N) Performance** - Fast, scalable correlation for large datasets
- **Identity Tracking** - Comprehensive identity extraction and normalization
- **Streaming Mode** - Memory-efficient processing for millions of records
- **Advanced Validation** - Field-aware validation with prioritization
- **Semantic Integration** - Built-in semantic rule evaluation
- **Production-Ready** - Recommended for identity-centric investigations

### Enhanced GUI Viewers (Production-Ready)
- **Time-Based Results Viewer** - Hierarchical window-based view with dynamic grouping
- **Identity Results Viewer** - Compact identity-centric view with pagination
- **Semantic Columns** - Semantic mapping display in both viewers
- **Scoring Breakdown** - Detailed confidence score visualization
- **Multi-Tab Support** - View multiple correlation results simultaneously

**New Documentation**:
- **[Time-Window Scanning Engine](engine/ENGINE_DOCUMENTATION.md#time-window-scanning-engine)** - O(N log N) systematic temporal analysis
- **[Identity-Based Engine](engine/ENGINE_DOCUMENTATION.md#identity-based-correlation-engine)** - Identity-first clustering
- **[Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide)** - Choose the right engine
- **[GUI Viewers](gui/GUI_DOCUMENTATION.md)** - Enhanced results visualization

## Quick Navigation

### 📖 Start Here
- **[CORRELATION_ENGINE_OVERVIEW.md](CORRELATION_ENGINE_OVERVIEW.md)** - Main overview with all architecture diagrams, quick start guide, and navigation
- **[Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide)** - Choose between Time-Based and Identity-Based engines

### 📁 Detailed Documentation by Directory

- **[engine/ENGINE_DOCUMENTATION.md](engine/ENGINE_DOCUMENTATION.md)** - Dual-engine architecture, Time-Based engine, Identity-Based engine, engine selection guide, performance optimization, troubleshooting
- **[feather/FEATHER_DOCUMENTATION.md](feather/FEATHER_DOCUMENTATION.md)** - Data normalization, import, transformation
- **[wings/WINGS_DOCUMENTATION.md](wings/WINGS_DOCUMENTATION.md)** - Correlation rule definitions, validation, wing models
- **[config/CONFIG_DOCUMENTATION.md](config/CONFIG_DOCUMENTATION.md)** - Configuration management, semantic mappings, session state
  - **[Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md)** - **NEW!** Centralized artifact type definitions
  - **[Weight Precedence](config/WEIGHT_PRECEDENCE.md)** - **NEW!** Weight resolution hierarchy
  - **[Configuration Reload](config/CONFIGURATION_RELOAD.md)** - **NEW!** Live configuration updates
- **[pipeline/PIPELINE_DOCUMENTATION.md](pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration, pipeline execution, dependency management
- **[gui/GUI_DOCUMENTATION.md](gui/GUI_DOCUMENTATION.md)** - User interface components, visualization, timeline widgets
- **[integration/INTEGRATION_DOCUMENTATION.md](integration/INTEGRATION_DOCUMENTATION.md)** - Crow-Eye integration, auto-generation, case initialization
  - **[Integration Interfaces](integration/INTEGRATION_INTERFACES.md)** - **NEW!** Dependency injection and testing

### 🏗️ Architecture Documentation
- **[ARCHITECTURE.md](../ARCHITECTURE.md)** - Component integration, Wing vs Feather comparison, data flow diagrams

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

1. **Start with the [Overview](CORRELATION_ENGINE_OVERVIEW.md)** - Read the introduction and look at the diagrams
2. **Understand the dual-engine architecture** - Read about [Time-Based](engine/ENGINE_DOCUMENTATION.md#time-based-correlation-engine) and [Identity-Based](engine/ENGINE_DOCUMENTATION.md#identity-based-correlation-engine) engines
3. **Learn engine selection** - Review the [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) to understand when to use each engine
4. **Understand configuration** - Review [Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md) and [Weight Precedence](config/WEIGHT_PRECEDENCE.md)
5. **Understand the architecture** - Review the system architecture and data flow diagrams
6. **Identify your area** - Determine which directory you'll be working in
7. **Read detailed docs** - Read the detailed documentation for that directory
8. **Review scenarios** - Look at modification scenarios similar to your task

## Engine Selection Quick Guide

**Choose Time-Window Scanning Engine when:**
- ⭐ You need time-based artifact analysis (production-ready)
- ✅ Dataset has any size (optimized for large datasets)
- ✅ You need O(N log N) performance with indexed queries
- ✅ You want systematic temporal analysis
- ✅ Memory efficiency is important
- ✅ You need universal timestamp format support
- ✅ You want 76x faster batch processing

**Choose Identity-Based Engine when:**
- ⭐ You need identity tracking across artifacts (production-ready)
- ✅ Dataset has > 1,000 records
- ✅ You want to filter by specific applications
- ✅ You need relationship mapping between identities
- ✅ Memory constraints require streaming mode
- ✅ You want O(N log N) performance

**Both engines are production-ready and optimized for large datasets.**

**See the full [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) for detailed decision criteria.**

## For Contributors

If you're contributing to the Correlation Engine:

1. **Read relevant documentation** - Understand the area you're modifying
2. **Check dependencies** - Review what depends on your changes
3. **Follow scenarios** - Use modification scenarios as guides
4. **Test thoroughly** - Test with multiple artifact types and configurations
5. **Update documentation** - Update docs if you change behavior
6. **Use interfaces** - Implement integration interfaces for new components
7. **Test configuration reload** - Ensure your changes support live reload

## Quick Reference

### Finding Specific Information

- **How correlation works**: [Overview - Correlation Execution Flow](CORRELATION_ENGINE_OVERVIEW.md#correlation-execution-flow)
- **Choosing an engine**: [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide)
- **Time-Based Engine**: [Time-Based Correlation Engine](engine/ENGINE_DOCUMENTATION.md#time-based-correlation-engine)
- **Identity-Based Engine**: [Identity-Based Correlation Engine](engine/ENGINE_DOCUMENTATION.md#identity-based-correlation-engine)
- **Performance optimization**: [Performance and Optimization](engine/ENGINE_DOCUMENTATION.md#performance-and-optimization)
- **Troubleshooting engines**: [Troubleshooting](engine/ENGINE_DOCUMENTATION.md#troubleshooting)
- **Artifact type registry**: [Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md) **NEW!**
- **Weight precedence**: [Weight Precedence](config/WEIGHT_PRECEDENCE.md) **NEW!**
- **Configuration reload**: [Configuration Reload](config/CONFIGURATION_RELOAD.md) **NEW!**
- **Integration interfaces**: [Integration Interfaces](integration/INTEGRATION_INTERFACES.md) **NEW!**
- **Adding new artifact type**: [Feather Documentation - Scenario 1](feather/FEATHER_DOCUMENTATION.md#scenario-1-adding-support-for-a-new-artifact-type) or [Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md#adding-new-artifact-types)
- **Modifying correlation logic**: [Engine Documentation - Scenario 2](engine/ENGINE_DOCUMENTATION.md#scenario-2-modifying-scoring-weights)
- **Adding GUI feature**: [GUI Documentation - Scenario 1](gui/GUI_DOCUMENTATION.md#scenario-1-adding-a-new-tab-to-main-window)
- **Understanding Wings**: [Wings Documentation](wings/WINGS_DOCUMENTATION.md)
- **Pipeline execution**: [Pipeline Documentation](pipeline/PIPELINE_DOCUMENTATION.md)
- **Component integration**: [Architecture - Component Integration](../ARCHITECTURE.md#component-integration)
- **Wing vs Feather**: [Architecture - Wing vs Feather](../ARCHITECTURE.md#wing-vs-feather-key-differences)

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
- `engine/time_based_engine.py` - Time-Window Scanning Engine (O(N))
- `engine/identity_correlation_engine.py` - Identity-Based correlation (O(N log N))
- `engine/two_phase_correlation.py` - Two-phase architecture components
- `engine/weighted_scoring.py` - Confidence scoring

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

Total: 12 documentation files + 1 architecture document

1. `CORRELATION_ENGINE_OVERVIEW.md` (Main overview with all diagrams)
2. `engine/ENGINE_DOCUMENTATION.md` (18 Python files documented)
   - Dual-Engine Architecture
   - Time-Based Correlation Engine
   - Identity-Based Correlation Engine
   - Engine Selection Guide
   - Configuration and Integration
   - Performance and Optimization
   - Migration and Compatibility
   - Troubleshooting
3. `feather/FEATHER_DOCUMENTATION.md` (4 Python files + UI)
4. `wings/WINGS_DOCUMENTATION.md` (3 Python files + UI)
5. `config/CONFIG_DOCUMENTATION.md` (10 Python files)
6. `config/ARTIFACT_TYPE_REGISTRY.md` **NEW!** (Artifact type registry)
7. `config/WEIGHT_PRECEDENCE.md` **NEW!** (Weight precedence system)
8. `config/CONFIGURATION_RELOAD.md` **NEW!** (Live configuration reload)
9. `pipeline/PIPELINE_DOCUMENTATION.md` (7 Python files)
10. `gui/GUI_DOCUMENTATION.md` (26 Python files)
11. `integration/INTEGRATION_DOCUMENTATION.md` (7 Python files)
12. `integration/INTEGRATION_INTERFACES.md` **NEW!** (Integration interfaces)
13. `../ARCHITECTURE.md` (System architecture)
    - Component Integration
    - Wing vs Feather: Key Differences

**Total Documentation**: ~10,000 lines covering dual-engine architecture and structural improvements

## Additional Resources

- **[FEATHER_METADATA_OPTIONAL.md](FEATHER_METADATA_OPTIONAL.md)** - Feather metadata table details
- **[PIPELINE_CONFIG_MANAGER_README.md](PIPELINE_CONFIG_MANAGER_README.md)** - Pipeline configuration management
- **[../engine/IDENTIFIER_EXTRACTION_README.md](../engine/IDENTIFIER_EXTRACTION_README.md)** - Identifier extraction system
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

**Last Updated**: January 2026  
**Correlation Engine Version**: 0.7.1 (Production-Ready Dual-Engine Architecture)  
**Documentation Version**: 0.7

**Major Updates in v0.7.1**:
- ⭐ Time-Window Scanning Engine - Production-ready with O(N log N) performance (76x faster)
- ⭐ Identity-Based Engine - Production-ready with advanced validation
- 📊 Enhanced GUI Viewers (Time-Based and Identity Results)
- 🔍 Semantic Rule Evaluation at identity level
- 💾 Streaming Mode for memory-efficient processing
- 📖 ~10,000 lines of comprehensive documentation

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
