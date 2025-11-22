# Crow Eye Contribution Guide

Welcome to the Crow Eye project! We appreciate your interest in contributing. This guide will help you get started with contributing to our Windows forensic investigation tool.

## Table of Contents

- [Introduction](#introduction)
- [Development Environment Setup](#development-environment-setup)
- [Contribution Guidelines](#contribution-guidelines)
  - [Types of Contributions](#types-of-contributions)
  - [Coding Standards](#coding-standards)
  - [Pull Request Process](#pull-request-process)
  - [Commit Message Guidelines](#commit-message-guidelines)
- [Development Workflows](#development-workflows)
- [Community Guidelines](#community-guidelines)

## Introduction

Crow Eye is an open-source Windows forensic investigation tool designed to collect, analyze, and visualize various Windows artifacts with a cyberpunk-themed interface. We welcome contributions from the community to make this tool even better.

## Documentation

To help you understand the codebase, please refer to:

- **[Project Structure](STRUCTURE.md)**: Detailed overview of the project's file structure and architecture.
- **[README](README.md)**: General project overview and usage instructions.

## Development Environment Setup

### Prerequisites

- Python 3.12.4 or higher
- Git
- Windows operating system (recommended for testing artifacts)

### Setting Up Your Development Environment

1. **Fork and Clone the Repository**

   ```bash
   git clone https://github.com/Ghassan-elsman/Crow-Eye.git
   cd Crow-Eye
   ```

2. **Run the Application**

   Simply run the main script. The application handles environment setup automatically.

   ```bash
   python "Crow Eye.py"
   ```

   **Automatic Setup Process:**
   - The script checks for a `crow_eye_venv` virtual environment.
   - If missing, it creates one automatically.
   - It installs all required dependencies.
   - Finally, it restarts itself within the virtual environment.

   > [!NOTE]
   > Run as administrator to ensure access to all system artifacts during live analysis.

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

- Follow **PEP 8** guidelines.
- Use meaningful variable and function names.
- Add **docstrings** to all functions and classes.
- Keep functions focused on a single responsibility.
- Use type hints where possible.

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
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Prefetch file not found: {file_path}")
        
    # Implementation details...
    
    return prefetch_data
```

### Pull Request Process

1. **Create a Branch**: Create a branch for your feature or bugfix.
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**: Implement your changes following the coding standards.

3. **Test Your Changes**: Ensure your changes work as expected and don't break existing functionality.

4. **Commit Your Changes**: Use clear commit messages.

5. **Push to Your Fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request**: Submit a pull request to the main repository.

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

## Development Workflows

### Adding a New Artifact Parser

1. **Create a new file** in the `Artifacts_Collectors/` directory.
2. **Implement the parser** following the existing patterns.
3. **Add database functionality** for storing parsed data.
4. **Integrate with the UI** by adding necessary components.
5. **Update the case management** system to include the new artifact type.

### Enhancing the UI

1. **Use the ComponentFactory** to create consistent UI elements.
2. **Follow the cyberpunk styling** guidelines in `styles.py`.
3. **Ensure responsive design** and proper error handling.

## Community Guidelines

### Code of Conduct

We expect all contributors to follow our Code of Conduct:

- Be respectful and inclusive.
- Focus on constructive feedback.
- Maintain a welcoming environment for all contributors.

### Communication Channels

- **GitHub Issues**: For bug reports and feature requests.
- **Pull Requests**: For code contributions.

Thank you for contributing to Crow Eye!
