# Crow Eye Contribution Guide

## Introduction

Welcome to the Crow Eye project! This guide combines our contribution guidelines and documentation index to help you get started quickly. Crow Eye is an open-source Windows forensic investigation tool designed to collect, analyze, and visualize various Windows artifacts with a cyberpunk-themed interface.

## Documentation Index

This section provides a comprehensive overview of all project documentation to help you navigate the codebase effectively.

### Core Documentation

- **README.md**: Project overview, features, installation, and basic usage
- **CROW_EYE_TECHNICAL_DOCUMENTATION.md**: Comprehensive technical documentation including architecture, components, and development workflows
- **CROW_EYE_CONTRIBUTION_GUIDE.md**: This document - contribution guidelines and documentation index

### Component Details

#### Artifact Collectors

The following components are responsible for collecting and parsing Windows artifacts:

- **Prefetch Parser**: Parses Windows Prefetch files (.pf) to extract execution history
- **Registry Parser**: Extracts forensic artifacts from Windows Registry hives
- **Amcache Parser**: Parses Amcache.hve to identify application execution history
- **Jump Lists/LNK Parser**: Extracts information from Jump Lists and LNK files
- **Event Log Parser**: Parses Windows Event Logs for security events and system activity

#### Data Management

Components for managing data loading and processing:

- **Base Data Loader**: Core functionality for database operations
- **Registry Loader**: Specialized loader for Registry data

#### UI Components

Components for the user interface:

- **Component Factory**: Creates UI elements with consistent styling
- **Loading Dialog**: Custom dialog for displaying loading progress
- **Main Window**: Primary application window and UI orchestration

#### Utilities

Helper functions and utilities:

- **Error Handler**: Consistent error handling and logging
- **File Utilities**: Common file operations

## Development Environment Setup

### Prerequisites

- Python 3.8 or higher
- Git
- Windows operating system (for testing)

### Setting Up Your Development Environment

1. **Fork and Clone the Repository**

   ```bash
   git clone https://github.com/yourusername/Crow-Eye.git
   cd Crow-Eye
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Application**

   ```bash
   python "Crow Eye.py"
   ```

## Contribution Guidelines

### Types of Contributions

We welcome various types of contributions:

- **Bug fixes**: Fixing issues in existing functionality
- **Feature enhancements**: Adding new features or improving existing ones
- **Documentation**: Improving or adding documentation
- **Testing**: Adding or improving tests
- **UI improvements**: Enhancing the user interface

### Coding Standards

#### Python Style Guide

- Follow PEP 8 guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes
- Keep functions focused on a single responsibility

#### Example of Good Code

```python
def parse_prefetch_file(file_path: str) -> Dict[str, Any]:
    """
    Parse a Windows Prefetch file and extract metadata.
    
    Args:
        file_path: Path to the Prefetch file
        
    Returns:
        Dictionary containing parsed Prefetch metadata
        
    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If the file is not a valid Prefetch file
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Prefetch file not found: {file_path}")
        
    # Implementation details...
    
    return prefetch_data
```

### Pull Request Process

1. **Create a Branch**: Create a branch for your feature or bugfix
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**: Implement your changes following the coding standards

3. **Test Your Changes**: Ensure your changes work as expected

4. **Commit Your Changes**: Use clear commit messages
   ```bash
   git commit -m "Add feature: your feature description"
   ```

5. **Push to Your Fork**: Push your changes to your fork
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request**: Submit a pull request to the main repository

### Commit Message Guidelines

Use the following format for commit messages:

```
<type>: <subject>

<body>
```

Where `<type>` is one of:
- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation changes
- **style**: Changes that do not affect the meaning of the code
- **refactor**: Code changes that neither fix a bug nor add a feature
- **test**: Adding or modifying tests
- **chore**: Changes to the build process or auxiliary tools

Example:
```
feat: Add Amcache parser

Implement parser for Amcache.hve to extract application execution history.
Add database schema and UI integration.
```

## Development Workflows

### Adding a New Artifact Parser

1. **Create a new file** in the `Artifacts_Collectors/` directory
2. **Implement the parser** following the existing patterns
3. **Add database functionality** for storing parsed data
4. **Integrate with the UI** by adding necessary components
5. **Update the case management** system to include the new artifact type

### Enhancing the UI

1. **Use the ComponentFactory** to create consistent UI elements
2. **Follow the cyberpunk styling** guidelines in `styles.py`
3. **Ensure responsive design** and proper error handling
4. **Test on different screen sizes** and resolutions

### Improving Data Correlation

1. **Identify common attributes** across artifacts
2. **Implement correlation rules** in the correlation engine
3. **Update the UI** to display correlated data
4. **Test with various datasets** to ensure accuracy

## Testing

### Manual Testing

1. **Test with different Windows versions** (7/10/11)
2. **Verify artifact parsing** with known test files
3. **Check UI rendering** on different screen sizes
4. **Validate database operations** and data integrity

### Automated Testing

We're working on implementing automated tests. Contributions in this area are welcome!

## Documentation

Good documentation is crucial for the project. When adding new features or making significant changes, please update the relevant documentation files.

### Documentation Guidelines

- Use clear, concise language
- Include code examples where appropriate
- Document function parameters and return values
- Explain the purpose and usage of components

## Community Guidelines

### Code of Conduct

We expect all contributors to follow our Code of Conduct:

- Be respectful and inclusive
- Focus on constructive feedback
- Maintain a welcoming environment for all contributors

### Communication Channels

- **GitHub Issues**: For bug reports and feature requests
- **Pull Requests**: For code contributions

## For AI Agents

If you're an AI agent working on Crow Eye, here are some tips:

1. **Understanding the Codebase**:
   - Start with the technical documentation to understand the overall structure
   - Examine the main application file (`Crow Eye.py`) to understand the entry point
   - Look at specific artifact collectors to understand parsing logic

2. **Making Enhancements**:
   - Follow the modular architecture when adding new features
   - Maintain the cyberpunk styling for UI components
   - Ensure proper error handling and logging
   - Add comprehensive documentation for new components

3. **Testing Changes**:
   - Test with different Windows versions (7/10/11)
   - Verify artifact parsing with known test files
   - Check UI rendering on different screen sizes
   - Validate database operations and data integrity

## Roadmap and Future Development

Planned enhancements for Crow Eye include:

- MFT table parsing for file system metadata
- Registry binary data decoding (UserAssist, ShellBags)
- Enhanced LNK file and Jump list structure parsing
- Advanced visualization of artifact timelines
- Reporting functionality for exporting findings

We welcome contributions in these areas, as well as new ideas for improving the project!