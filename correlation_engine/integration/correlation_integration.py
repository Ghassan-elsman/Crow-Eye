"""
Correlation Engine Integration for Crow-Eye

This module provides the integration bridge between the main Crow-Eye application
and the Correlation Engine. It handles launching the Correlation Engine GUI,
initializing case directories, and applying consistent styling.

Classes:
    CorrelationIntegration: Main integration class that bridges Crow-Eye and Correlation Engine

Key Responsibilities:
    - Launch Correlation Engine GUI from Crow-Eye
    - Initialize case directory structure for correlation analysis
    - Auto-generate feathers from Crow-Eye parsed data
    - Load default wings and create default pipeline
    - Apply Crow-Eye dark theme to Correlation Engine
    - Manage Configuration Manager integration

Usage:
    # In Crow-Eye main window initialization:
    from correlation_engine.integration.correlation_integration import CorrelationIntegration
    
    # Initialize integration
    ui.correlation_integration = CorrelationIntegration(ui)
    
    # Launch Correlation Engine
    ui.correlation_integration.show_correlation_dialog()

Dependencies:
    - correlation_engine.gui.main_window: Main Correlation Engine GUI
    - correlation_engine.integration.case_initializer: Case initialization
    - correlation_engine.integration.default_wings_loader: Default wings
    - config.configuration_manager: Configuration management (optional)

File Location:
    Crow-Eye/correlation_engine/integration/correlation_integration.py

See Also:
    - docs/integration/INTEGRATION_DOCUMENTATION.md: Detailed integration documentation
    - docs/CORRELATION_ENGINE_OVERVIEW.md: System architecture overview
"""

import os
import sys
from pathlib import Path
from PyQt5 import QtWidgets

# Import Configuration Manager
try:
    from config.configuration_manager import ConfigurationManager
    CONFIG_MANAGER_AVAILABLE = True
except ImportError:
    CONFIG_MANAGER_AVAILABLE = False
    print("[Correlation] Warning: Configuration Manager not available")


class CorrelationIntegration:
    """
    Handles correlation engine integration with Crow-Eye.
    
    This class serves as the bridge between the main Crow-Eye application and the
    Correlation Engine. It manages the lifecycle of the Correlation Engine GUI,
    initializes case-specific directories, and ensures consistent styling.
    
    Attributes:
        main_window: Reference to Crow-Eye main window (Ui_Crow_Eye object)
        correlation_window: Instance of Correlation Engine MainWindow (when launched)
        config_manager: Configuration Manager instance (if available)
    
    Methods:
        show_correlation_dialog(): Launch the Correlation Engine GUI
        _reusable_window(): The engine window already open for this case, if any

    Integration Flow:
        1. Initialize with reference to Crow-Eye main window
        2. When show_correlation_dialog() is called:
           a. Initialize case directory structure
           b. Auto-generate feathers from Crow-Eye data
           c. Load default wings
           d. Create default pipeline
           e. Launch Correlation Engine GUI
           f. Set default directories
    
    Example:
        >>> # In Crow-Eye initialization
        >>> ui.correlation_integration = CorrelationIntegration(ui)
        >>> 
        >>> # When correlation button is clicked
        >>> ui.correlation_integration.show_correlation_dialog()
    
    Notes:
        - Requires PyQt5 for GUI components
        - Configuration Manager is optional but recommended
        - Automatically creates directory structure in case folder
        - The engine window styles itself (ui/site_theme.py, the site look)

    See Also:
        - case_initializer.py: Case initialization logic
        - default_wings_loader.py: Default wings loading
        - gui/main_window.py: Correlation Engine main window
    """
    
    def __init__(self, main_window):
        """
        Initialize correlation integration.
        
        Sets up the integration bridge between Crow-Eye and the Correlation Engine.
        Initializes the Configuration Manager if available.
        
        Args:
            main_window: Reference to Crow-Eye main window (Ui_Crow_Eye object).
                        This should be the UI object that contains case_paths and
                        other Crow-Eye state information.
        
        Attributes Set:
            self.main_window: Stored reference to Crow-Eye main window
            self.correlation_window: Initially None, set when GUI is launched
            self.config_manager: Configuration Manager instance (if available)
        
        Raises:
            None: Initialization always succeeds, Configuration Manager is optional
        
        Example:
            >>> from correlation_engine.integration.correlation_integration import CorrelationIntegration
            >>> integration = CorrelationIntegration(crow_eye_ui)
            >>> print(integration.config_manager) # None or ConfigurationManager instance
        
        Notes:
            - Configuration Manager is optional but provides enhanced functionality
            - If Configuration Manager is not available, basic functionality still works
            - The main_window reference is used to access case paths and parent widgets
        """
        self.main_window = main_window
        self.correlation_window = None
        self._window_case_root = None
        self.config_manager = None

        # Initialize Configuration Manager if available
        if CONFIG_MANAGER_AVAILABLE:
            self.config_manager = ConfigurationManager.get_instance()
            print("[Correlation] Configuration Manager initialized")
    
    def show_correlation_dialog(self):
        """
        Launch the full Correlation Engine GUI.
        
        This is the main entry point for launching the Correlation Engine from Crow-Eye.
        It performs the following steps:
        
        1. Import required Correlation Engine modules
        2. Get parent widget from Crow-Eye for proper window parenting
        3. Get case directory from Crow-Eye
        4. Initialize case with default wings, feathers, and pipeline
        5. Create the Correlation Engine main window (or reuse the open one)
        6. Set default directories for feathers, wings, pipelines, and results
        7. Show the Correlation Engine window
        
        Directory Structure Created:
            case_root/
            └── Correlation/
                ├── feathers/ (Normalized forensic data)
                ├── wings/ (Correlation rules)
                ├── pipelines/ (Analysis workflows)
                └── results/ (Correlation results)
        
        Case Initialization:
            - Copies default wings to case directory
            - Auto-generates feather configurations from Crow-Eye parsed data
            - Creates default pipeline configuration
            - Sets up file monitoring for auto-refresh
        
        Error Handling:
            - ImportError: Shows error dialog if Correlation Engine modules not found
            - Exception: Shows error dialog for any other launch failures
            - All errors are logged with stack traces for debugging
        
        GUI Integration:
            - The window carries the site look itself (set before its children)
            - Sets parent widget for proper window management
            - Configures default directories based on case location
            - Enables file monitoring for automatic config refresh
        
        Returns:
            None: Window is shown modally or as separate window
        
        Raises:
            None: All exceptions are caught and displayed in error dialogs
        
        Example:
            >>> # From Crow-Eye correlation button click handler
            >>> def on_correlation_button_clicked(self):
            ... self.correlation_integration.show_correlation_dialog()
        
        Notes:
            - Requires case to be loaded in Crow-Eye (case_paths must be set)
            - Creates directory structure automatically if it doesn't exist
            - Configuration Manager integration is optional but recommended
            - Re-launching for the same case raises the window already open

        See Also:
            - case_initializer.py: Case initialization logic
            - gui/main_window.py: Correlation Engine main window
            - _reusable_window(): Window reuse
        """
        try:
            # Import the main GUI window (correct class name is MainWindow)
            # Now using relative imports since we're inside correlation_engine package
            from ..gui.main_window import MainWindow
            from .default_wings_loader import DefaultWingsLoader
            from .case_initializer import CaseInitializer

            
            # Get the actual QMainWindow widget for parent
            parent_widget = None
            if hasattr(self.main_window, 'main_window'):
                parent_widget = self.main_window.main_window
            
            if not parent_widget:
                if hasattr(self.main_window, 'centralwidget'):
                    parent_widget = self.main_window.centralwidget.window()
            
            # Get case directory for default paths
            case_root = None
            if hasattr(self.main_window, 'case_paths') and self.main_window.case_paths:
                case_root = self.main_window.case_paths.get('case_root')
            
            # Set case directory in Configuration Manager
            if case_root and self.config_manager:
                self.config_manager.set_case_directory(case_root)
                print(f"[Correlation] Set case directory: {case_root}")
            
            # Initialize case with Default Wings, feather configs, and default pipeline
            if case_root:
                try:
                    print(f"[Correlation] Initializing case: {case_root}")
                    init_result = CaseInitializer.initialize_case(Path(case_root))
                    
                    if init_result.success:
                        print(f"[Correlation] [OK] Case initialization successful")
                        print(f"[Correlation] Wings copied: {len(init_result.wings_copied)}")
                        print(f"[Correlation] Feather configs generated: {len(init_result.feather_configs_generated)}")
                        if init_result.pipeline_created:
                            print(f"[Correlation] Pipeline created: {init_result.pipeline_created.name}")
                    else:
                        print(f"[Correlation] [WARN] Case initialization had errors:")
                        for error in init_result.errors:
                            print(f"[Correlation] - {error}")
                    
                    if init_result.has_warnings():
                        print(f"[Correlation] [WARN] Warnings during initialization:")
                        for warning in init_result.warnings:
                            print(f"[Correlation] - {warning}")
                            
                except Exception as e:
                    print(f"[Correlation] Error during case initialization: {e}")
                    import traceback
                    traceback.print_exc()
            
            # One engine window: re-opening raises the one already open for
            # this case. It styles itself (the site look, set before its
            # children exist), so nothing is applied over it here.
            window = self._reusable_window(case_root)
            if window is None:
                window = MainWindow()
                # Set parent if available
                if parent_widget:
                    window.setParent(parent_widget, window.windowFlags())
            self.correlation_window = window
            self._window_case_root = case_root

            # If we have a case directory, set it as the default location
            if case_root:
                # Use Configuration Manager to create directory structure
                if self.config_manager:
                    correlation_dir = self.config_manager.get_correlation_directory()
                else:
                    correlation_dir = os.path.join(case_root, 'Correlation')
                    os.makedirs(correlation_dir, exist_ok=True)
                
                # Create subdirectories for feathers and wings
                feathers_dir = os.path.join(correlation_dir, 'feathers')
                wings_dir = os.path.join(correlation_dir, 'wings')
                pipelines_dir = os.path.join(correlation_dir, 'pipelines')
                results_dir = os.path.join(correlation_dir, 'results')
                
                # Only create manually if Configuration Manager not available
                if not self.config_manager:
                    os.makedirs(feathers_dir, exist_ok=True)
                    os.makedirs(wings_dir, exist_ok=True)
                    os.makedirs(pipelines_dir, exist_ok=True)
                    os.makedirs(results_dir, exist_ok=True)
                
                # Set default directory in the correlation engine
                if hasattr(self.correlation_window, 'set_default_directory'):
                    self.correlation_window.set_default_directory(correlation_dir)
                elif hasattr(self.correlation_window, 'default_directory'):
                    self.correlation_window.default_directory = correlation_dir
                
                # Set output directory in pipeline builder
                if hasattr(self.correlation_window, 'pipeline_builder'):
                    # Set output directory field
                    if hasattr(self.correlation_window.pipeline_builder, 'output_dir_input'):
                        self.correlation_window.pipeline_builder.output_dir_input.setText(correlation_dir)
                    
                    # Set watch directories for auto-refresh (as Path objects)
                    self.correlation_window.pipeline_builder._feathers_watch_dir = Path(feathers_dir)
                    self.correlation_window.pipeline_builder._wings_watch_dir = Path(wings_dir)
                    
                    # Pass Configuration Manager to Pipeline Builder
                    if self.config_manager:
                        self.correlation_window.pipeline_builder.set_config_manager(self.config_manager)
                        print("[Correlation] Passed Configuration Manager to Pipeline Builder")
                    
                    # Load existing configs immediately
                    if self.config_manager:
                        self.config_manager.load_all_configurations()
                        print("[Correlation] Loaded all configurations")
                    
                    self.correlation_window.pipeline_builder.load_existing_configs()
                    
                    # Start the file monitoring timer for new files
                    if hasattr(self.correlation_window.pipeline_builder, '_watch_timer'):
                        self.correlation_window.pipeline_builder._watch_timer.start()
                        print(f"[Correlation] Started file monitoring for feathers and wings")
                
                # Also set it in settings
                if hasattr(self.correlation_window, 'settings'):
                    self.correlation_window.settings.setValue('last_directory', correlation_dir)

                print(f"[Correlation] Configured directories:")
                print(f" - Feathers: {feathers_dir}")
                print(f" - Wings: {wings_dir}")
                print(f" - Pipelines: {pipelines_dir}")
                print(f" - Results: {results_dir}")
            
            # Show the window
            self.correlation_window.show()
            self.correlation_window.raise_()
            self.correlation_window.activateWindow()
            
            print(f"[Correlation] Launched Correlation Engine GUI")
            if case_root:
                print(f"[Correlation] Default directory: {correlation_dir}")
            
        except ImportError as e:
            parent_widget = None
            if hasattr(self.main_window, 'main_window'):
                parent_widget = self.main_window.main_window
            
            QtWidgets.QMessageBox.critical(
                parent_widget,
                "Correlation Engine Error",
                f"Failed to import Correlation Engine GUI:\n\n{str(e)}\n\n"
                f"The correlation_engine package should be in the Crow-Eye directory.\n"
                f"Path checked: {Path(__file__).parent / 'correlation_engine'}"
            )
            import traceback
            traceback.print_exc()
            
        except Exception as e:
            parent_widget = None
            if hasattr(self.main_window, 'main_window'):
                parent_widget = self.main_window.main_window
            
            QtWidgets.QMessageBox.critical(
                parent_widget,
                "Correlation Engine Error",
                f"Failed to launch Correlation Engine GUI:\n\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
    
    def _reusable_window(self, case_root):
        """The engine window already open for this case, or None to build one.

        A window for another case is closed (its closeEvent auto-saves) and
        released - unless a correlation is still running in it, then it is
        kept: closing it would pull the widgets out from under the worker.
        """
        window = self.correlation_window
        if window is None:
            return None
        try:
            import sip
            if sip.isdeleted(window):
                return None
        except Exception:
            pass
        if self._window_case_root == case_root:
            return window
        ec = getattr(window, "execution_control", None)
        worker = getattr(ec, "worker_thread", None)
        try:
            if worker is not None and worker.isRunning():
                print("[Correlation] A correlation is still running - keeping its window")
                return window
        except RuntimeError:
            pass
        window.close()
        if window.isVisible():                  # the unsaved-changes prompt said no
            return window
        window.deleteLater()
        return None
