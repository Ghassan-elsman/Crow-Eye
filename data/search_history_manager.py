"""
Search History Manager for Crow Eye Unified Database Search.

Manages persistence of search history and saved searches to JSON files,
providing investigators with quick access to recent and frequently used searches.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class SearchHistoryEntry:
    """
    Represents a single search history entry.
    
    Attributes:
        term: Search term or pattern
        databases: List of database names searched
        tables: Dictionary mapping database names to table lists
        case_sensitive: Whether search was case-sensitive
        exact_match: Whether search was exact match
        use_regex: Whether search used regex
        timestamp: ISO format timestamp of when search was performed
        start_time: Optional start datetime for time filtering (ISO format)
        end_time: Optional end datetime for time filtering (ISO format)
        time_preset: Optional preset name used for time filtering
    """
    term: str
    databases: List[str]
    tables: Dict[str, List[str]]
    case_sensitive: bool
    exact_match: bool
    use_regex: bool
    timestamp: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    time_preset: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SearchHistoryEntry':
        """Create from dictionary loaded from JSON."""
        # Handle legacy entries without time filter fields
        if 'start_time' not in data:
            data['start_time'] = None
        if 'end_time' not in data:
            data['end_time'] = None
        if 'time_preset' not in data:
            data['time_preset'] = None
        return cls(**data)


@dataclass
class SavedSearch:
    """
    Represents a named saved search.
    
    Attributes:
        name: User-provided name for the search
        term: Search term or pattern
        databases: List of database names to search
        tables: Dictionary mapping database names to table lists
        case_sensitive: Whether search is case-sensitive
        exact_match: Whether search is exact match
        use_regex: Whether search uses regex
        created: ISO format timestamp of when search was saved
        last_used: ISO format timestamp of when search was last used
        start_time: Optional start datetime for time filtering (ISO format)
        end_time: Optional end datetime for time filtering (ISO format)
        time_preset: Optional preset name used for time filtering
    """
    name: str
    term: str
    databases: List[str]
    tables: Dict[str, List[str]]
    case_sensitive: bool
    exact_match: bool
    use_regex: bool
    created: str
    last_used: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    time_preset: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SavedSearch':
        """Create from dictionary loaded from JSON."""
        # Handle legacy saved searches without time filter fields
        if 'start_time' not in data:
            data['start_time'] = None
        if 'end_time' not in data:
            data['end_time'] = None
        if 'time_preset' not in data:
            data['time_preset'] = None
        return cls(**data)


class SearchHistoryManager:
    """
    Manages search history and saved searches persistence.
    
    Stores search history and saved searches in JSON files within the case
    directory, providing methods to save, load, update, and delete searches.
    """
    
    HISTORY_FILENAME = ".crow_eye_search_history.json"
    SAVED_SEARCHES_FILENAME = ".crow_eye_saved_searches.json"
    MAX_HISTORY_ENTRIES = 20
    
    def __init__(self, case_directory: Path):
        """
        Initialize the Search History Manager.
        
        Args:
            case_directory: Path to case directory for storing history files
        """
        self.case_directory = Path(case_directory)
        self.history_file = self.case_directory / self.HISTORY_FILENAME
        self.saved_searches_file = self.case_directory / self.SAVED_SEARCHES_FILENAME
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.logger.info(f"Initialized SearchHistoryManager for: {case_directory}")
    
    def save_history(
        self,
        term: str,
        databases: List[str],
        tables: Dict[str, List[str]],
        case_sensitive: bool = False,
        exact_match: bool = False,
        use_regex: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        time_preset: Optional[str] = None
    ) -> bool:
        """
        Save a search to history.
        
        Adds the search parameters to the history file, maintaining a maximum
        of MAX_HISTORY_ENTRIES (20) most recent searches. Older searches are
        automatically removed.
        
        Args:
            term: Search term or pattern
            databases: List of database names searched
            tables: Dictionary mapping database names to table lists
            case_sensitive: Whether search was case-sensitive
            exact_match: Whether search was exact match
            use_regex: Whether search used regex
            start_time: Optional start datetime for time filtering (ISO format)
            end_time: Optional end datetime for time filtering (ISO format)
            time_preset: Optional preset name used for time filtering
            
        Returns:
            True if save was successful, False otherwise
        """
        try:
            # Load existing history
            history = self.load_history()
            
            # Create new entry
            entry = SearchHistoryEntry(
                term=term,
                databases=databases,
                tables=tables,
                case_sensitive=case_sensitive,
                exact_match=exact_match,
                use_regex=use_regex,
                timestamp=datetime.now().isoformat(),
                start_time=start_time,
                end_time=end_time,
                time_preset=time_preset
            )
            
            # Add to beginning of list (most recent first)
            history.insert(0, entry)
            
            # Limit to MAX_HISTORY_ENTRIES
            history = history[:self.MAX_HISTORY_ENTRIES]
            
            # Convert to dictionaries for JSON serialization
            history_data = [entry.to_dict() for entry in history]
            
            # Write to file
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, indent=2, ensure_ascii=False)
            
            self.logger.debug(f"Saved search to history: '{term}' (time_filter: {start_time is not None or end_time is not None})")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving search history: {e}", exc_info=True)
            return False
    
    def load_history(self) -> List[SearchHistoryEntry]:
        """
        Load search history from file.
        
        Retrieves up to MAX_HISTORY_ENTRIES (20) most recent searches from
        the history file.
        
        Returns:
            List of SearchHistoryEntry objects, most recent first
        """
        try:
            # Check if history file exists
            if not self.history_file.exists():
                self.logger.debug("History file does not exist, returning empty list")
                return []
            
            # Read and parse JSON
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            
            # Convert to SearchHistoryEntry objects
            history = [
                SearchHistoryEntry.from_dict(entry_data)
                for entry_data in history_data
            ]
            
            # Ensure we don't exceed max entries
            history = history[:self.MAX_HISTORY_ENTRIES]
            
            self.logger.debug(f"Loaded {len(history)} history entries")
            return history
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing history JSON: {e}", exc_info=True)
            return []
        except Exception as e:
            self.logger.error(f"Error loading search history: {e}", exc_info=True)
            return []
    
    def clear_history(self) -> bool:
        """
        Clear all search history.
        
        Deletes the history file, removing all saved search history.
        
        Returns:
            True if clear was successful, False otherwise
        """
        try:
            if self.history_file.exists():
                self.history_file.unlink()
                self.logger.info("Cleared search history")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing history: {e}", exc_info=True)
            return False
    
    def save_named_search(
        self,
        name: str,
        term: str,
        databases: List[str],
        tables: Dict[str, List[str]],
        case_sensitive: bool = False,
        exact_match: bool = False,
        use_regex: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        time_preset: Optional[str] = None
    ) -> bool:
        """
        Save a search with a user-provided name.
        
        Stores the search parameters with a name for easy retrieval later.
        If a saved search with the same name already exists, it will be updated.
        
        Args:
            name: User-provided name for the search
            term: Search term or pattern
            databases: List of database names to search
            tables: Dictionary mapping database names to table lists
            case_sensitive: Whether search is case-sensitive
            exact_match: Whether search is exact match
            use_regex: Whether search uses regex
            start_time: Optional start datetime for time filtering (ISO format)
            end_time: Optional end datetime for time filtering (ISO format)
            time_preset: Optional preset name used for time filtering
            
        Returns:
            True if save was successful, False otherwise
        """
        try:
            # Validate name
            if not name or not name.strip():
                self.logger.warning("Cannot save search with empty name")
                return False
            
            # Load existing saved searches
            saved_searches = self.load_saved_searches()
            
            # Check if name already exists
            existing_index = None
            for i, search in enumerate(saved_searches):
                if search.name == name:
                    existing_index = i
                    break
            
            # Create new saved search
            saved_search = SavedSearch(
                name=name,
                term=term,
                databases=databases,
                tables=tables,
                case_sensitive=case_sensitive,
                exact_match=exact_match,
                use_regex=use_regex,
                created=datetime.now().isoformat(),
                last_used=None,
                start_time=start_time,
                end_time=end_time,
                time_preset=time_preset
            )
            
            # Update or add
            if existing_index is not None:
                # Preserve original created timestamp
                saved_search.created = saved_searches[existing_index].created
                saved_searches[existing_index] = saved_search
                self.logger.debug(f"Updated saved search: '{name}'")
            else:
                saved_searches.append(saved_search)
                self.logger.debug(f"Added new saved search: '{name}'")
            
            # Convert to dictionaries for JSON serialization
            searches_data = [search.to_dict() for search in saved_searches]
            
            # Write to file
            with open(self.saved_searches_file, 'w', encoding='utf-8') as f:
                json.dump(searches_data, f, indent=2, ensure_ascii=False)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving named search: {e}", exc_info=True)
            return False
    
    def load_saved_searches(self) -> List[SavedSearch]:
        """
        Load all saved searches from file.
        
        Returns:
            List of SavedSearch objects
        """
        try:
            # Check if file exists
            if not self.saved_searches_file.exists():
                self.logger.debug("Saved searches file does not exist, returning empty list")
                return []
            
            # Read and parse JSON
            with open(self.saved_searches_file, 'r', encoding='utf-8') as f:
                searches_data = json.load(f)
            
            # Convert to SavedSearch objects
            saved_searches = [
                SavedSearch.from_dict(search_data)
                for search_data in searches_data
            ]
            
            self.logger.debug(f"Loaded {len(saved_searches)} saved searches")
            return saved_searches
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing saved searches JSON: {e}", exc_info=True)
            return []
        except Exception as e:
            self.logger.error(f"Error loading saved searches: {e}", exc_info=True)
            return []
    
    def get_saved_search(self, name: str) -> Optional[SavedSearch]:
        """
        Get a specific saved search by name.
        
        Args:
            name: Name of the saved search
            
        Returns:
            SavedSearch object if found, None otherwise
        """
        saved_searches = self.load_saved_searches()
        
        for search in saved_searches:
            if search.name == name:
                return search
        
        return None
    
    def delete_saved_search(self, name: str) -> bool:
        """
        Delete a saved search by name.
        
        Args:
            name: Name of the saved search to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            # Load existing saved searches
            saved_searches = self.load_saved_searches()
            
            # Find and remove the search
            original_count = len(saved_searches)
            saved_searches = [s for s in saved_searches if s.name != name]
            
            if len(saved_searches) == original_count:
                self.logger.warning(f"Saved search not found: '{name}'")
                return False
            
            # Convert to dictionaries for JSON serialization
            searches_data = [search.to_dict() for search in saved_searches]
            
            # Write to file
            with open(self.saved_searches_file, 'w', encoding='utf-8') as f:
                json.dump(searches_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Deleted saved search: '{name}'")
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting saved search: {e}", exc_info=True)
            return False
    
    def update_saved_search_last_used(self, name: str) -> bool:
        """
        Update the last_used timestamp for a saved search.
        
        Called when a saved search is loaded and executed.
        
        Args:
            name: Name of the saved search
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Load existing saved searches
            saved_searches = self.load_saved_searches()
            
            # Find and update the search
            found = False
            for search in saved_searches:
                if search.name == name:
                    search.last_used = datetime.now().isoformat()
                    found = True
                    break
            
            if not found:
                self.logger.warning(f"Saved search not found: '{name}'")
                return False
            
            # Convert to dictionaries for JSON serialization
            searches_data = [search.to_dict() for search in saved_searches]
            
            # Write to file
            with open(self.saved_searches_file, 'w', encoding='utf-8') as f:
                json.dump(searches_data, f, indent=2, ensure_ascii=False)
            
            self.logger.debug(f"Updated last_used for saved search: '{name}'")
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating saved search: {e}", exc_info=True)
            return False
    
    def clear_saved_searches(self) -> bool:
        """
        Clear all saved searches.
        
        Deletes the saved searches file, removing all saved searches.
        
        Returns:
            True if clear was successful, False otherwise
        """
        try:
            if self.saved_searches_file.exists():
                self.saved_searches_file.unlink()
                self.logger.info("Cleared all saved searches")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing saved searches: {e}", exc_info=True)
            return False
