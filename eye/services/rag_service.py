"""
RAG Service for EYE AI Forensic Assistant.

This module provides Retrieval-Augmented Generation (RAG) capabilities by managing
a local knowledge base of forensic artifact documentation and parser information.
It now features an API-based vector embedding search with a lightweight in-memory 
cosine similarity index, falling back to legacy keyword matching if needed.
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
import json
import logging
import math
import requests

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)


class EmbeddingClient:
    """Base class for embedding generation."""
    def embed_text(self, text: str) -> List[float]:
        return []


class OllamaEmbeddingClient(EmbeddingClient):
    """Generates embeddings using a local Ollama API."""
    def __init__(self, api_endpoint: str = "http://localhost:11434", model_name: str = "all-minilm"):
        self.api_endpoint = api_endpoint.rstrip('/')
        self.model_name = model_name
        self.logger = logging.getLogger(__name__)

    def embed_text(self, text: str) -> List[float]:
        try:
            response = requests.post(
                f"{self.api_endpoint}/api/embeddings",
                json={"model": self.model_name, "prompt": text},
                timeout=10
            )
            response.raise_for_status()
            return response.json().get("embedding", [])
        except Exception as e:
            self.logger.error(f"Ollama embedding failed: {e}")
            return []


class RAGService:
    """
    Retrieval-Augmented Generation service for forensic knowledge.
    
    This service manages a local knowledge base containing:
    - Forensic artifact definitions and significance
    - Crow-eye parser logic documentation
    - Database schema information
    - Timestamp interpretation guidelines
    - Parser source code mappings
    
    The service uses vector embeddings to detect relevant knowledge base
    content to augment LLM prompts, falling back to keyword detection.
    """
    
    def __init__(self, knowledge_base_dir: str = "configs/knowledge_base", embedding_client: Optional[EmbeddingClient] = None):
        """
        Initialize RAG service with knowledge base directory.
        
        Args:
            knowledge_base_dir: Path to directory containing knowledge base files
            embedding_client: Optional embedding client for vector search
        """
        self.logger = logging.getLogger(__name__)
        self.knowledge_base_dir = Path(knowledge_base_dir)
        self.keyword_mapping = self._load_keyword_mapping()
        self.cache: Dict[str, str] = {}
        self.parser_mappings = self._load_parser_mappings()
        
        # Setup vector index
        self.embedding_client = embedding_client
        self.vector_index: List[Dict[str, Any]] = []
        self.index_built = False
        
        # Validate knowledge base directory exists
        if not self.knowledge_base_dir.exists():
            self.logger.warning(
                f"Knowledge base directory not found: {self.knowledge_base_dir}"
            )
    
    def _build_vector_index(self):
        """Builds an in-memory vector index for all markdown files."""
        if self.index_built or not self.embedding_client:
            return
            
        self.logger.info("Building RAG vector index...")
        try:
            for file_path in self.knowledge_base_dir.glob("*.md"):
                content = self._load_knowledge_file(file_path.name)
                if content:
                    # Simple chunking: by paragraphs or headers
                    chunks = [chunk.strip() for chunk in content.split("\n\n") if len(chunk.strip()) > 50]
                    for chunk in chunks:
                        emb = self.embedding_client.embed_text(chunk)
                        if emb:
                            self.vector_index.append({
                                "filename": file_path.name,
                                "content": chunk,
                                "embedding": emb
                            })
            self.index_built = True
            self.logger.info(f"Built vector index with {len(self.vector_index)} chunks.")
        except Exception as e:
            self.logger.error(f"Failed to build vector index: {e}")
    
    def _load_keyword_mapping(self) -> Dict[str, str]:
        """
        Load keyword to knowledge file mapping.
        
        Returns:
            Dictionary mapping keywords to knowledge file names
        """
        return {
            "prefetch": "prefetch_knowledge.md",
            "mft": "mft_knowledge.md",
            "amcache": "amcache_knowledge.md",
            "shimcache": "shimcache_knowledge.md",
            "registry": "registry_knowledge.md",
            "usn": "usn_knowledge.md",
            "usn journal": "usn_knowledge.md",
            "jump list": "jumplist_knowledge.md",
            "jumplist": "jumplist_knowledge.md",
            "recycle bin": "recyclebin_knowledge.md",
            "recyclebin": "recyclebin_knowledge.md",
            "srum": "srum_knowledge.md",
            "event log": "eventlog_knowledge.md",
            "eventlog": "eventlog_knowledge.md",
            "remote access": "remote_access_knowledge.md",
            "rdp": "remote_access_knowledge.md",
            "teamviewer": "remote_access_knowledge.md",
            "anydesk": "remote_access_knowledge.md",
            # Intelligence & Reasoning Mappings
            "forensic_methodology": "forensic_methodology.md",
            "evidence_intelligence": "evidence_intelligence.md",
            "global_schema_databse_refrence": "Global_schema_databse_Refrence.md",
            "app runs": "evidence_intelligence.md",
            "app execution": "evidence_intelligence.md",
            "system browsing": "evidence_intelligence.md",
            "browsing": "evidence_intelligence.md",
            "folder navigation": "evidence_intelligence.md",
            "file interactions": "evidence_intelligence.md",
            "file interaction": "evidence_intelligence.md",
            "file creation": "evidence_intelligence.md",
            "file deletion": "evidence_intelligence.md",
            "file edition": "evidence_intelligence.md",
            "file lifecycle": "evidence_intelligence.md",
        }
    
    def _load_parser_mappings(self) -> Dict:
        """
        Load parser mappings from parser_mappings.json.
        
        Returns:
            Dictionary containing parser file paths and GitHub URLs
        """
        mappings_file = self.knowledge_base_dir / "parser_mappings.json"
        
        if not mappings_file.exists():
            self.logger.warning(f"Parser mappings file not found: {mappings_file}")
            return {}
        
        try:
            with open(mappings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load parser mappings: {e}")
            return {}
    
    def retrieve_context(self, keywords: Optional[List[str]] = None, user_query: str = "", max_tokens: int = 3000) -> str:
        """
        Retrieve knowledge base content using semantic search or keyword fallback.
        
        Args:
            keywords: List of detected forensic artifact keywords (legacy)
            user_query: The user's natural language query for semantic search
            max_tokens: Maximum tokens to return for the context (to prevent prompt bloat)
            
        Returns:
            Concatenated knowledge base content with section headers
        """
        # Try semantic search if we have a query and an embedding client
        context_parts = []
        
        if user_query and self.embedding_client:
            if not self.index_built:
                self._build_vector_index()
                
            if self.vector_index:
                query_emb = self.embedding_client.embed_text(user_query)
                if query_emb:
                    results = []
                    for item in self.vector_index:
                        score = cosine_similarity(query_emb, item["embedding"])
                        if score > 0.4:  # Threshold for relevance
                            results.append((score, item))
                    
                    if results:
                        results.sort(key=lambda x: x[0], reverse=True)
                        top_results = results[:3]  # Get top 3 chunks
                        
                        for score, item in top_results:
                            filename = item["filename"].replace("_knowledge.md", "").title()
                            context_parts.append(f"## {filename} Knowledge (Semantic Match)\n{item['content']}")
                        
                        self.logger.info(f"Retrieved {len(top_results)} semantic knowledge sections.")
        
        # Fallback to legacy keyword retrieval (only if we need more or have no semantic matches)
        if keywords:
            for keyword in keywords:
                # Avoid duplicates if semantic search already found it
                if any(keyword.title() in p for p in context_parts):
                    continue
                    
                keyword_lower = keyword.lower()
                if keyword_lower in self.keyword_mapping:
                    content = self._load_knowledge_file(
                        self.keyword_mapping[keyword_lower]
                    )
                    if content:
                        context_parts.append(
                            f"## {keyword.title()} Knowledge\n{content}"
                        )
                        self.logger.debug(f"Retrieved knowledge for keyword: {keyword}")
        
        if not context_parts:
            return ""
            
        full_context = "\n\n".join(context_parts)
        
        # FINAL SAFETY: Ensure we don't blow the context window
        # We use a rough estimation if token_counter isn't passed (handled by caller usually)
        if len(full_context) // 4 > max_tokens:
            self.logger.warning(f"RAG context exceeded {max_tokens} tokens. Truncating.")
            # Take first max_tokens * 4 characters as a safe buffer
            return full_context[:max_tokens * 4] + "\n\n... [RAG Context Truncated for token safety] ..."
            
        return full_context
    
    def _load_knowledge_file(self, filename: str) -> str:
        """
        Load knowledge file with caching.
        
        Args:
            filename: Name of the knowledge file to load
            
        Returns:
            Content of the knowledge file, or empty string if not found
        """
        if filename in self.cache:
            return self.cache[filename]
        
        file_path = self.knowledge_base_dir / filename
        if not file_path.exists():
            self.logger.warning(f"Knowledge file not found: {file_path}")
            return ""
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self.cache[filename] = content
                self.logger.debug(f"Loaded and cached knowledge file: {filename}")
                return content
        except Exception as e:
            self.logger.error(f"Failed to load knowledge file {filename}: {e}")
            return ""
    
    def get_parser_source_link(self, artifact_type: str) -> str:
        """
        Get GitHub link to parser source code.
        
        Args:
            artifact_type: Type of forensic artifact (e.g., 'prefetch', 'mft')
            
        Returns:
            GitHub URL to parser source file, or empty string if not found
        """
        artifact_lower = artifact_type.lower()
        
        if not self.parser_mappings:
            self.logger.warning("Parser mappings not loaded")
            return ""
        
        mappings = self.parser_mappings.get("parser_mappings", {})
        github_base = self.parser_mappings.get("github_base_url", "")
        
        if artifact_lower not in mappings:
            self.logger.debug(f"No parser mapping found for: {artifact_type}")
            return ""
        
        parser_info = mappings[artifact_lower]
        parser_file = parser_info.get("parser_file", "")
        
        if not parser_file or not github_base:
            return ""
        
        github_url = f"{github_base}/blob/main/{parser_file}"
        self.logger.debug(f"Generated parser link for {artifact_type}: {github_url}")
        return github_url
    
    def clear_cache(self):
        """Clear the knowledge file cache and vector index."""
        self.cache.clear()
        self.vector_index.clear()
        self.index_built = False
        self.logger.info("Knowledge file cache and vector index cleared")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache size and available knowledge files count
        """
        return {
            "cached_files": len(self.cache),
            "available_keywords": len(self.keyword_mapping),
            "vector_chunks": len(self.vector_index)
        }
