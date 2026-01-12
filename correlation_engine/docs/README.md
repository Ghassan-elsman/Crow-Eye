# Correlation Engine Documentation

Welcome to the Crow-Eye Correlation Engine documentation! This directory contains comprehensive documentation for developers and contributors.

## 🚀 What's New: Structural Improvements (v2.1)

The Correlation Engine has been enhanced with significant structural improvements:

- **Artifact Type Registry** - Centralized, configuration-driven artifact type management
- **Integration Interfaces** - ABC-based interfaces for dependency injection and testing
- **Configuration Live Reload** - Update configuration without application restart
- **Weight Precedence System** - Clear wing > case > global > default weight hierarchy
- **Observer Pattern** - Configuration change notifications for reactive components

**New Documentation**:
- **[Artifact Type Registry](config/ARTIFACT_TYPE_REGISTRY.md)** - Centralized artifact definitions
- **[Integration Interfaces](integration/INTEGRATION_INTERFACES.md)** - Dependency injection and testing
- **[Weight Precedence](config/WEIGHT_PRECEDENCE.md)** - Weight resolution hierarchy
- **[Configuration Reload](config/CONFIGURATION_RELOAD.md)** - Live configuration updates

## 🚀 Dual-Engine Architecture (v2.0)

The Correlation Engine features a **dual-engine architecture** with two distinct correlation strategies:

- **Time-Based Engine** (O(N²)) - Comprehensive field matching for small datasets (< 1,000 records)
- **Identity-Based Engine** (O(N log N)) - Fast, scalable correlation for large datasets with identity tracking

**Documentation**:
- **[Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide)** - Choose the right engine for your needs
- **[Dual-Engine Architecture](engine/ENGINE_DOCUMENTATION.md#dual-engine-architecture)** - Understand both engines
- **[Performance Comparison](engine/ENGINE_DOCUMENTATION.md#performance-and-optimization)** - Benchmarks and optimization tips

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

**Choose Time-Based Engine when:**
- ✅ Dataset has < 1,000 records
- ✅ You need comprehensive field-level analysis
- ✅ You're debugging or doing research
- ✅ Detailed semantic matching is critical

**Choose Identity-Based Engine when:**
- ✅ Dataset has > 1,000 records
- ✅ Performance is critical
- ✅ You need identity tracking across artifacts
- ✅ You want to filter by specific applications
- ✅ Memory constraints require streaming mode

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
- `engine/time_based_engine.py` - Time-Based correlation (O(N²))
- `engine/identity_correlation_engine.py` - Identity-Based correlation (O(N log N))
- `engine/correlation_engine.py` - Original correlation logic (used by Time-Based)
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

**Last Updated**: January 2025  
**Correlation Engine Version**: 2.1.0 (Structural Improvements)  
**Documentation Version**: 2.1

**Major Updates in v2.1**:
- ✨ Artifact Type Registry for centralized artifact management
- 🔌 Integration Interfaces for dependency injection
- 🔄 Configuration Live Reload without restart
- ⚖️ Weight Precedence System (wing > case > global > default)
- 👁️ Observer Pattern for configuration changes
- 📖 ~3,000 lines of new documentation

**Major Updates in v2.0**:
- ✨ Dual-Engine Architecture with Time-Based and Identity-Based engines
- 📊 Comprehensive Engine Selection Guide
- ⚡ Performance optimization documentation
- 🔧 Troubleshooting guide for both engines
- 🏗️ Enhanced architecture documentation with component integration
- 📖 ~7,200 lines of new documentation
