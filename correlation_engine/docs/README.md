# Correlation Engine Documentation

Welcome to the Crow-Eye Correlation Engine documentation! This directory contains comprehensive documentation for developers and contributors.

## Quick Navigation

### 📖 Start Here
- **[CORRELATION_ENGINE_OVERVIEW.md](CORRELATION_ENGINE_OVERVIEW.md)** - Main overview with all architecture diagrams, quick start guide, and navigation

### 📁 Detailed Documentation by Directory

- **[engine/ENGINE_DOCUMENTATION.md](engine/ENGINE_DOCUMENTATION.md)** - Core correlation engine, feather loading, scoring, timestamp parsing
- **[feather/FEATHER_DOCUMENTATION.md](feather/FEATHER_DOCUMENTATION.md)** - Data normalization, import, transformation
- **[wings/WINGS_DOCUMENTATION.md](wings/WINGS_DOCUMENTATION.md)** - Correlation rule definitions, validation, wing models
- **[config/CONFIG_DOCUMENTATION.md](config/CONFIG_DOCUMENTATION.md)** - Configuration management, semantic mappings, session state
- **[pipeline/PIPELINE_DOCUMENTATION.md](pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration, pipeline execution, dependency management
- **[gui/GUI_DOCUMENTATION.md](gui/GUI_DOCUMENTATION.md)** - User interface components, visualization, timeline widgets
- **[integration/INTEGRATION_DOCUMENTATION.md](integration/INTEGRATION_DOCUMENTATION.md)** - Crow-Eye integration, auto-generation, case initialization

## Documentation Structure

This documentation follows a two-tier structure:

1. **Overview File** (`CORRELATION_ENGINE_OVERVIEW.md`)
   - Contains ALL architecture diagrams
   - High-level system overview
   - Quick start guide
   - Common modification scenarios
   - Navigation links to detailed docs

2. **Directory-Specific Files** (7 files)
   - Detailed file-by-file documentation
   - Class and method descriptions
   - Dependencies and dependents
   - Impact analysis
   - Code examples
   - Modification scenarios

## For New Developers

If you're new to the Correlation Engine:

1. **Start with the [Overview](CORRELATION_ENGINE_OVERVIEW.md)** - Read the introduction and look at the diagrams
2. **Understand the architecture** - Review the system architecture and data flow diagrams
3. **Identify your area** - Determine which directory you'll be working in
4. **Read detailed docs** - Read the detailed documentation for that directory
5. **Review scenarios** - Look at modification scenarios similar to your task

## For Contributors

If you're contributing to the Correlation Engine:

1. **Read relevant documentation** - Understand the area you're modifying
2. **Check dependencies** - Review what depends on your changes
3. **Follow scenarios** - Use modification scenarios as guides
4. **Test thoroughly** - Test with multiple artifact types and configurations
5. **Update documentation** - Update docs if you change behavior

## Quick Reference

### Finding Specific Information

- **How correlation works**: [Overview - Correlation Execution Flow](CORRELATION_ENGINE_OVERVIEW.md#correlation-execution-flow)
- **Adding new artifact type**: [Feather Documentation - Scenario 1](feather/FEATHER_DOCUMENTATION.md#scenario-1-adding-support-for-a-new-artifact-type)
- **Modifying correlation logic**: [Engine Documentation - Scenario 2](engine/ENGINE_DOCUMENTATION.md#scenario-2-modifying-scoring-weights)
- **Adding GUI feature**: [GUI Documentation - Scenario 1](gui/GUI_DOCUMENTATION.md#scenario-1-adding-a-new-tab-to-main-window)
- **Understanding Wings**: [Wings Documentation](wings/WINGS_DOCUMENTATION.md)
- **Pipeline execution**: [Pipeline Documentation](pipeline/PIPELINE_DOCUMENTATION.md)

### Key Files by Function

**Correlation**:
- `engine/correlation_engine.py` - Main correlation logic
- `engine/weighted_scoring.py` - Confidence scoring

**Data Loading**:
- `engine/feather_loader.py` - Load feather databases
- `feather/transformer.py` - Transform source data

**Configuration**:
- `config/config_manager.py` - Manage all configs
- `wings/core/wing_model.py` - Wing data models

**Execution**:
- `pipeline/pipeline_executor.py` - Execute pipelines
- `gui/execution_control.py` - GUI execution control

**Integration**:
- `integration/crow_eye_integration.py` - Crow-Eye bridge
- `integration/case_initializer.py` - Case setup

## Documentation Files

Total: 8 documentation files

1. `CORRELATION_ENGINE_OVERVIEW.md` (Main overview with all diagrams)
2. `engine/ENGINE_DOCUMENTATION.md` (15 Python files documented)
3. `feather/FEATHER_DOCUMENTATION.md` (4 Python files + UI)
4. `wings/WINGS_DOCUMENTATION.md` (3 Python files + UI)
5. `config/CONFIG_DOCUMENTATION.md` (10 Python files)
6. `pipeline/PIPELINE_DOCUMENTATION.md` (7 Python files)
7. `gui/GUI_DOCUMENTATION.md` (26 Python files)
8. `integration/INTEGRATION_DOCUMENTATION.md` (7 Python files)

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

## Contributing to Documentation

When updating documentation:

1. Keep the overview file as the main entry point
2. Update directory-specific files for detailed changes
3. Add new modification scenarios when appropriate
4. Update diagrams if architecture changes
5. Keep code examples current and working

---

**Last Updated**: 2024  
**Correlation Engine Version**: 0.1.0  
**Documentation Version**: 1.0
