# Contributing to Crow-Eye Correlation Engine

Thank you for your interest in contributing to the Crow-Eye Correlation Engine! This guide will help you get started with contributing to this project.

## Table of Contents

- [Our Vision](#our-vision)
- [Getting Started](#getting-started)
- [Development Status](#development-status)
- [Areas for Contribution](#areas-for-contribution)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Code Guidelines](#code-guidelines)
- [Testing Guidelines](#testing-guidelines)
- [Documentation Guidelines](#documentation-guidelines)
- [Submitting Changes](#submitting-changes)
- [Community Guidelines](#community-guidelines)

---

## Our Vision

The Crow-Eye Correlation Engine is designed with a clear vision: **empower investigators to build their assumptions based on rules dependent on their requirements, and provide a way to dive into needed details without being lost in the data**.

### Core Philosophy

**Rule-Based Investigation**: We believe investigators should be able to define correlation rules that match their investigation methodology and requirements. Whether using default rules or building custom ones, the system should adapt to how investigators think and work.

**Meaningful Context, Not Just Data**: Raw technical details can be overwhelming. Our semantic mapping system aims to convert technical values into helpful, meaningful information that investigators can understand and act upon. We bridge the gap between technical artifacts and investigative insights.

**Progressive Detail**: Investigators should start with high-level correlations and progressively drill down into details as needed. The system should guide them through the data without overwhelming them, showing what's important first and allowing deeper exploration when required.

**Still at the Beginning**: We recognize that this is just the beginning of our journey. The Correlation Engine is functional but evolving. We value every idea and contribution, whether it's developing new features, improving existing ones, or sharing insights from real-world investigations.

### What This Means for Contributors

- **User-Centric Design**: Always consider how investigators will use the feature
- **Semantic Over Technical**: Help translate technical data into meaningful insights
- **Flexible Rules**: Support both default and custom correlation rules
- **Progressive Disclosure**: Show high-level first, details on demand
- **Real-World Focus**: Solutions should work for actual investigations
- **Open to Ideas**: We welcome all contributions and perspectives

Your contributions help make forensic investigation more accessible, efficient, and insightful for everyone.

---

## Getting Started

The Crow-Eye Correlation Engine is a forensic artifact correlation system with a dual-engine architecture. Before contributing, please:

1. **Read the Documentation**:
   - [Correlation Engine Overview](docs/CORRELATION_ENGINE_OVERVIEW.md)
   - [Architecture Documentation](ARCHITECTURE.md)
   - [Engine Documentation](docs/engine/ENGINE_DOCUMENTATION.md)

2. **Understand the System**:
   - **Feathers**: Data normalization (SQLite databases)
   - **Wings**: Correlation rules (JSON/YAML configs)
   - **Engines**: Correlation strategies (Time-Based and Identity-Based)
   - **Pipelines**: Workflow orchestration

3. **Review Current Status**:
   - Identity-Based Engine: Production-ready
   - Time-Based Engine: Prototype stage
   - Semantic Mapping: Under development
   - Correlation Scoring: Under development
   - Identity Extractor: Being enhanced

---

## Development Status

### ✅ Production-Ready Components
- **Feather Builder**: Fully functional - imports CSV/JSON/SQLite
- **Wings System**: Fully functional - create and manage correlation rules
- **Pipeline Orchestration**: Fully functional - automate workflows
- **Identity-Based Engine**: Mature and recommended for production use

### 🔄 Under Active Development
- **Identity Extractor**: Working but being enhanced for better accuracy
- **Semantic Mapping**: Implementation in progress
- **Correlation Scoring**: Algorithm development in progress
- **Time-Based Engine**: Prototype stage - needs completion

### ⚠️ Needs Attention
- Time-Based Engine completion
- Identity extraction accuracy improvements
- Semantic field mapping across artifact types
- Scoring algorithm finalization
- Performance optimization

---

## Areas for Contribution

### 🔥 High Priority

#### 1. Identity Extractor Enhancement
**Goal**: Improve identity extraction accuracy across more artifact types

**What's Needed**:
- Add field patterns for new artifact types
- Improve normalization logic
- Handle edge cases in identity extraction
- Test with diverse artifact datasets

**Files to Work On**:
- `engine/identity_correlation_engine.py`
- `engine/data_structures.py`

**Skills Needed**: Python, forensic artifact knowledge, pattern matching

---

#### 2. Semantic Mapping Implementation
**Goal**: Map field names across different artifact types to common semantic meanings

**Vision**: Semantic mapping is our way to link technical details into helpful meanings. Instead of showing raw field names like "executable_name" or "app_path", we translate these into concepts investigators understand: "Application", "File Path", "User", "Timestamp". This bridges the gap between technical artifacts and investigative insights.

**What's Needed**:
- Define semantic field categories (application, path, timestamp, user, hash, etc.)
- Create mappings for each artifact type (Prefetch → Application, ShimCache → Application, etc.)
- Implement mapping resolution logic (handle conflicts, prioritize sources)
- Convert technical field names to meaningful labels in results
- Test cross-artifact field matching

**Example**:
```python
# Technical fields from different artifacts
prefetch_record = {"executable_name": "chrome.exe"}
shimcache_record = {"filename": "chrome.exe"}
srum_record = {"app_name": "chrome.exe"}

# Semantic mapping converts all to:
semantic_result = {"Application": "chrome.exe"}
```

**Files to Work On**:
- `config/semantic_mapping.py`
- `engine/correlation_engine.py`
- `engine/identity_correlation_engine.py`

**Skills Needed**: Python, forensic artifacts knowledge, data modeling

**Impact**: This directly supports our vision of making technical data meaningful and accessible to investigators.

---

#### 3. Correlation Scoring Algorithm
**Goal**: Implement comprehensive scoring for correlation matches

**What's Needed**:
- Define scoring criteria (time proximity, field similarity, artifact importance)
- Implement weighted scoring algorithm
- Add confidence calculation
- Test with real-world scenarios

**Files to Work On**:
- `engine/weighted_scoring.py`
- `engine/correlation_result.py`

**Skills Needed**: Python, algorithm design, statistical analysis

---

#### 4. Time-Based Engine Completion
**Goal**: Finalize Time-Based Engine for production use

**What's Needed**:
- Complete algorithm implementation
- Add comprehensive duplicate prevention
- Optimize performance for medium datasets
- Add progress tracking
- Comprehensive testing

**Files to Work On**:
- `engine/time_based_engine.py`
- `engine/correlation_engine.py`

**Skills Needed**: Python, algorithm optimization, testing

---

### 🎯 Medium Priority

#### 5. New Artifact Type Support
**Goal**: Add support for additional forensic artifact types

**What's Needed**:
- Research artifact structure and fields
- Add field mappings to identity extractor
- Create feather import templates
- Add to artifact detector
- Document the new artifact type

**Files to Work On**:
- `engine/identity_correlation_engine.py` (field patterns)
- `feather/transformer.py` (import logic)
- `wings/core/artifact_detector.py`
- `integration/feather_mappings.py`

**Skills Needed**: Forensic artifact knowledge, Python

---

#### 6. Performance Optimization
**Goal**: Improve correlation performance for large datasets

**What's Needed**:
- Profile code to identify bottlenecks
- Optimize database queries
- Implement caching strategies
- Parallel processing for independent operations
- Memory usage optimization

**Files to Work On**:
- `engine/identity_correlation_engine.py`
- `engine/time_based_engine.py`
- `engine/feather_loader.py`

**Skills Needed**: Python optimization, profiling, database optimization

---

#### 7. GUI Enhancements
**Goal**: Improve user interface for correlation engine

**What's Needed**:
- Enhanced results visualization
- Better progress tracking
- Interactive filtering
- Export options
- Error handling and user feedback

**Files to Work On**:
- `gui/correlation_results_view.py`
- `gui/identity_results_view.py`
- `gui/pipeline_management_tab.py`

**Skills Needed**: PyQt5, Python, UI/UX design

---

### 📚 Documentation

#### 8. Documentation Improvements
**Goal**: Keep documentation accurate and comprehensive

**What's Needed**:
- Update documentation as code changes
- Add more code examples
- Create tutorials and guides
- Improve troubleshooting sections
- Add diagrams and visualizations

**Files to Work On**:
- All `docs/*.md` files
- README files
- Code comments and docstrings

**Skills Needed**: Technical writing, Markdown, Mermaid diagrams

---


## How to Contribute

### 1. Choose a Contribution Area

Pick an area from the [Areas for Contribution](#areas-for-contribution) section that matches your skills and interests.

### 2. Check Existing Issues

- Look for existing issues related to your chosen area
- Comment on the issue to let others know you're working on it
- If no issue exists, create one describing what you plan to do

### 3. Fork and Clone

```bash
# Fork the repository on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/crow-eye.git
cd crow-eye/Crow-Eye/correlation_engine
```

### 4. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 5. Make Your Changes

Follow the [Code Guidelines](#code-guidelines) and [Testing Guidelines](#testing-guidelines).

### 6. Test Your Changes

```bash
# Run tests
python -m pytest tests/

# Test manually with sample data
python -m correlation_engine.main
```

### 7. Commit Your Changes

```bash
git add .
git commit -m "feat: Add identity extraction for new artifact type"
# or
git commit -m "fix: Improve timestamp parsing in identity extractor"
```

**Commit Message Format**:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `perf:` Performance improvements
- `refactor:` Code refactoring
- `test:` Adding tests
- `chore:` Maintenance tasks

### 8. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub with:
- Clear description of changes
- Reference to related issues
- Screenshots (if UI changes)
- Test results

---

## Development Setup

### Prerequisites

- Python 3.7+
- PyQt5 5.15.0+
- SQLite3
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/crow-eye.git
cd crow-eye

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-cov black flake8
```

### Running the Application

```bash
# Launch Feather Builder
python -m correlation_engine.main

# Or run specific components
python -m correlation_engine.feather.feather_builder
python -m correlation_engine.pipeline.pipeline_executor
```

### Project Structure

```
correlation_engine/
├── engine/              # Correlation engines
│   ├── base_engine.py
│   ├── engine_selector.py
│   ├── time_based_engine.py
│   ├── identity_correlation_engine.py
│   └── ...
├── feather/            # Data normalization
├── wings/              # Correlation rules
├── pipeline/           # Workflow orchestration
├── config/             # Configuration management
├── gui/                # User interface
├── integration/        # Crow-Eye integration
└── docs/               # Documentation
```

---

## Code Guidelines

### Python Style

- Follow **PEP 8** style guidelines
- Use **type hints** where applicable
- Maximum line length: **100 characters**
- Use **meaningful variable names**

### Code Formatting

```bash
# Format code with black
black correlation_engine/

# Check with flake8
flake8 correlation_engine/
```

### Docstrings

Use Google-style docstrings:

```python
def extract_identity_info(self, record: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """
    Extract identity information from a forensic record.
    
    Args:
        record: Forensic record dictionary
    
    Returns:
        Tuple of (name, path, hash, identity_type)
        
    Example:
        >>> name, path, hash, type = extractor.extract_identity_info(record)
        >>> print(f"Identity: {name}")
    """
    pass
```

### Error Handling

```python
# Good: Specific exceptions with helpful messages
try:
    result = engine.execute_wing(wing, feather_paths)
except ValueError as e:
    logger.error(f"Invalid wing configuration: {e}")
    raise
except FileNotFoundError as e:
    logger.error(f"Feather database not found: {e}")
    raise

# Bad: Bare except
try:
    result = engine.execute_wing(wing, feather_paths)
except:
    pass
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)

# Use appropriate log levels
logger.debug("Detailed information for debugging")
logger.info("General information about execution")
logger.warning("Warning about potential issues")
logger.error("Error that needs attention")
```

---

## Testing Guidelines


### Code Documentation

- Add docstrings to all public functions and classes
- Include type hints
- Provide usage examples
- Document parameters and return values

### Markdown Documentation

- Use clear, concise language
- Include code examples
- Add diagrams where helpful (Mermaid)
- Keep table of contents updated
- Link to related documentation

### Updating Documentation

When you change code, update:
1. Docstrings in the code
2. Relevant documentation files in `docs/`
3. README files if needed
4. CHANGELOG.md with your changes

---

## Submitting Changes

### Pull Request Checklist

Before submitting a pull request, ensure:

- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] No merge conflicts
- [ ] PR description is complete

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Performance improvement
- [ ] Documentation update
- [ ] Code refactoring

## Related Issues
Fixes #123

## Changes Made
- Added identity extraction for XYZ artifact
- Improved timestamp parsing
- Updated documentation

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing completed

## Screenshots (if applicable)
[Add screenshots for UI changes]

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass
- [ ] Documentation updated
```

---

## Community Guidelines

### Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Provide constructive feedback
- Focus on the code, not the person
- Help others learn and grow

### Communication

- **GitHub Issues**: Bug reports, feature requests
- **Pull Requests**: Code contributions
- **Email**: ghassanelsman@gmail.com for direct contact

### Getting Help

If you need help:
1. Check the [documentation](docs/README.md)
2. Search existing issues
3. Ask in your pull request
4. Contact the maintainer

---

## Priority Contributions Needed

### 🔥 Immediate Needs

1. **Identity Extractor Enhancement**
   - Add field patterns for more artifact types
   - Improve normalization logic
   - Test with diverse datasets

2. **Semantic Mapping Implementation**
   - Define semantic categories
   - Create artifact mappings
   - Implement resolution logic

3. **Correlation Scoring**
   - Design scoring algorithm
   - Implement weighted scoring
   - Add confidence calculation

4. **Time-Based Engine Completion**
   - Finalize algorithm
   - Add duplicate prevention
   - Optimize performance

### 📊 Testing Needs

- Unit tests for identity extractor
- Integration tests for correlation workflow
- Performance benchmarks
- Test with real-world artifact datasets

### 📚 Documentation Needs

- More code examples
- Troubleshooting guides
- Tutorial videos
- API reference documentation

---

## Recognition

Contributors will be:
- Listed in the project README
- Credited in release notes
- Acknowledged in documentation

Thank you for contributing to Crow-Eye Correlation Engine!

---

## Contact

**Project Maintainer**: Ghassan Elsman  
**Email**: ghassanelsman@gmail.com  
**Website**: [https://crow-eye.com/](https://crow-eye.com/)

---

**Last Updated**: December 2024  
**Version**: 2.0.0
