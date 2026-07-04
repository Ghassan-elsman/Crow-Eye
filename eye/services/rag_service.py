"""
RAG Service for EYE AI Forensic Assistant.

This module provides Retrieval-Augmented Generation (RAG) capabilities by managing
a local knowledge base of forensic artifact documentation and parser information.
It now features an API-based vector embedding search with a lightweight in-memory 
cosine similarity index, falling back to legacy keyword matching if needed.
"""

from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import hashlib
import json
import logging
import math
import re
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


# Lightweight stopword set — keeps lexical ranking focused on forensic terms
# without pulling in any NLP dependency.
_RAG_STOPWORDS = frozenset(
    "the a an and or of to in on for with at by from is are was were be been being "
    "this that these those it its as into about which what when where who how why "
    "do does did has have had can could should would will i you we they me my our "
    "show me find list get all any not no yes".split()
)


def _rag_tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric word tokens (len >= 2), stopwords removed."""
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(t) >= 2 and t not in _RAG_STOPWORDS]


def _chunk_markdown(content: str, min_chars: int = 50, max_chars: int = 1500) -> List[str]:
    """Header-aware chunking shared by the vector and lexical index builders.

    Splits a knowledge-base document on markdown headers (``#``..``######``) so a
    chunk stays within one semantic section, then packs that section's paragraphs
    into chunks no larger than ``max_chars``. The section header is prepended to
    every chunk it produces, so a paragraph never loses the topic it belongs to
    (which sharpens both cosine and BM25 relevance). Falls back to plain
    double-newline paragraphs when a document has no headers. Chunks shorter than
    ``min_chars`` are dropped (same filter the old ``split("\\n\\n")`` used).
    """
    if not content:
        return []

    # 1. Partition the document into (header, body) sections.
    sections: List[Tuple[str, str]] = []
    cur_header = ""
    cur_lines: List[str] = []
    for ln in content.split("\n"):
        if re.match(r"^#{1,6}\s", ln):
            if cur_header or cur_lines:
                sections.append((cur_header, "\n".join(cur_lines)))
            cur_header = ln.strip()
            cur_lines = []
        else:
            cur_lines.append(ln)
    if cur_header or cur_lines:
        sections.append((cur_header, "\n".join(cur_lines)))

    # 2. Pack each section's paragraphs into header-scoped chunks.
    chunks: List[str] = []
    for header, body in sections:
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]

        def _emit(buf: str):
            text = (header + "\n" + buf).strip() if header else buf.strip()
            if len(text) > min_chars:
                chunks.append(text)

        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) + 2 > max_chars:
                _emit(buf)
                buf = p
            else:
                buf = (buf + "\n\n" + p) if buf else p
        if buf:
            _emit(buf)
    return chunks


class EmbeddingClient:
    """Base class for embedding generation."""
    def embed_text(self, text: str, is_query: bool = False) -> List[float]:
        return []


class OllamaEmbeddingClient(EmbeddingClient):
    """Generates embeddings using a local Ollama API.

    Supports task-prefix embedding models (notably ``nomic-embed-text-v1.5``,
    which REQUIRES a ``search_query:`` / ``search_document:`` prefix to retrieve
    correctly). Prefixes auto-default for nomic models and can be overridden or
    cleared for models that don't use them (e.g. ``all-minilm``).
    """
    def __init__(self, api_endpoint: str = "http://localhost:11434",
                 model_name: str = "nomic-embed-text",
                 query_prefix: Optional[str] = None,
                 document_prefix: Optional[str] = None,
                 timeout: int = 10):
        self.api_endpoint = api_endpoint.rstrip('/')
        self.model_name = model_name
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
        # Auto-apply nomic v1.5 task prefixes unless the caller specified them.
        if query_prefix is None and document_prefix is None and "nomic" in model_name.lower():
            query_prefix = "search_query: "
            document_prefix = "search_document: "
        self.query_prefix = query_prefix or ""
        self.document_prefix = document_prefix or ""

    def embed_text(self, text: str, is_query: bool = False) -> List[float]:
        prefix = self.query_prefix if is_query else self.document_prefix
        payload_text = f"{prefix}{text}" if prefix else text
        try:
            response = requests.post(
                f"{self.api_endpoint}/api/embeddings",
                json={"model": self.model_name, "prompt": payload_text},
                timeout=self.timeout
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

        # Dependency-free lexical (BM25) index — the ranked-retrieval fallback
        # when no embedding server is configured (cloud/CLI deployments).
        self.lexical_index: List[Dict[str, Any]] = []
        self.lexical_df: Dict[str, int] = {}
        self.lexical_avg_len: float = 0.0
        self.lexical_built = False

        # The knowledge files actually consulted on the last retrieve_context call,
        # so the pipeline can surface "knowledge consulted" in the Compliance UI.
        self.last_sources: List[str] = []

        # Conversation-memory recall index (long-term memory). When older turns
        # are summarized / slid out of the live window they are archived and fed
        # here, so a specific earlier detail can still be retrieved on demand —
        # nothing is truly lost when the context window fills. Dependency-free
        # BM25 over the same machinery as the knowledge base.
        self.conversation_index: List[Dict[str, Any]] = []
        self.conversation_df: Dict[str, int] = {}
        self.conversation_total_len: int = 0
        self.conversation_avg_len: float = 0.0
        self.last_conversation_sources: List[str] = []
        
        # Validate knowledge base directory exists
        if not self.knowledge_base_dir.exists():
            self.logger.warning(
                f"Knowledge base directory not found: {self.knowledge_base_dir}"
            )
    
    def _emb_cache_file(self) -> Path:
        """On-disk embedding cache path, namespaced by model so switching models
        never mixes incompatible vectors."""
        model = getattr(self.embedding_client, "model_name", "emb") or "emb"
        safe = re.sub(r"[^a-z0-9._-]+", "_", model.lower())
        return self.knowledge_base_dir / ".embcache" / f"{safe}.json"

    def _load_emb_cache(self) -> Dict[str, List[float]]:
        try:
            p = self._emb_cache_file()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            self.logger.debug(f"Embedding cache load failed: {e}")
        return {}

    def _save_emb_cache(self, cache: Dict[str, List[float]]):
        try:
            p = self._emb_cache_file()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cache), encoding="utf-8")
        except Exception as e:
            self.logger.debug(f"Embedding cache save failed: {e}")

    def _build_vector_index(self):
        """Builds an in-memory vector index for all markdown files.

        Embeddings are cached on disk keyed by ``sha256(doc-chunk)`` so the KB is
        not re-embedded on every launch (only new/changed chunks hit the embedding
        server). Cache is namespaced by model name.
        """
        if self.index_built or not self.embedding_client:
            return

        self.logger.info("Building RAG vector index...")
        try:
            cache = self._load_emb_cache()
            dirty = False
            for file_path in self.knowledge_base_dir.glob("*.md"):
                content = self._load_knowledge_file(file_path.name)
                if content:
                    # Header-aware chunking (shared with the lexical index).
                    chunks = _chunk_markdown(content)
                    for chunk in chunks:
                        key = hashlib.sha256(("doc::" + chunk).encode("utf-8", "replace")).hexdigest()
                        emb = cache.get(key)
                        if emb is None:
                            emb = self.embedding_client.embed_text(chunk, is_query=False)
                            if emb:
                                cache[key] = emb
                                dirty = True
                        if emb:
                            self.vector_index.append({
                                "filename": file_path.name,
                                "content": chunk,
                                "embedding": emb
                            })
            if dirty:
                self._save_emb_cache(cache)
            self.index_built = True
            self.logger.info(f"Built vector index with {len(self.vector_index)} chunks.")
        except Exception as e:
            self.logger.error(f"Failed to build vector index: {e}")

    def _build_lexical_index(self):
        """Build a dependency-free BM25 index over the knowledge-base chunks.

        Uses the same paragraph chunking as the vector index, but stores token
        frequencies + document-frequency stats so we can rank chunks by lexical
        relevance with no embedding server. Best-effort; never raises.
        """
        if self.lexical_built:
            return
        self.logger.info("Building RAG lexical (BM25) index...")
        try:
            total_len = 0
            for file_path in self.knowledge_base_dir.glob("*.md"):
                content = self._load_knowledge_file(file_path.name)
                if not content:
                    continue
                chunks = _chunk_markdown(content)
                for chunk in chunks:
                    tokens = _rag_tokenize(chunk)
                    if not tokens:
                        continue
                    tf: Dict[str, int] = {}
                    for tok in tokens:
                        tf[tok] = tf.get(tok, 0) + 1
                    self.lexical_index.append({
                        "filename": file_path.name,
                        "content": chunk,
                        "tf": tf,
                        "len": len(tokens),
                    })
                    total_len += len(tokens)
                    for term in tf:
                        self.lexical_df[term] = self.lexical_df.get(term, 0) + 1
            n = len(self.lexical_index)
            self.lexical_avg_len = (total_len / n) if n else 0.0
            self.lexical_built = True
            self.logger.info(f"Built lexical index with {n} chunks.")
        except Exception as e:
            self.logger.error(f"Failed to build lexical index: {e}")

    @staticmethod
    def _bm25_over(query: str, index: List[Dict[str, Any]], df: Dict[str, int],
                   avg_len: float) -> List[Tuple[float, Dict[str, Any]]]:
        """Generic BM25 ranker over any prebuilt index of ``{tf, len, ...}`` chunks.

        Returns (normalized_score, chunk) pairs sorted desc — scores normalized to
        the top hit (best chunk == 1.0) so a relative ``min_score`` threshold is
        meaningful regardless of query length. Shared by the knowledge-base
        (``_bm25_rank``) and the conversation-recall (``retrieve_conversation``)
        indexes.
        """
        q_terms = set(_rag_tokenize(query))
        if not q_terms or not index:
            return []
        n = len(index)
        k1, b = 1.5, 0.75
        avg = avg_len or 1.0
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for chunk in index:
            tf, dl = chunk["tf"], chunk["len"]
            score = 0.0
            for term in q_terms:
                f = tf.get(term, 0)
                if not f:
                    continue
                d = df.get(term, 0)
                idf = math.log(1 + (n - d + 0.5) / (d + 0.5))
                denom = f + k1 * (1 - b + b * dl / avg)
                score += idf * (f * (k1 + 1)) / denom
            if score > 0:
                scored.append((score, chunk))
        if not scored:
            return []
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[0][0] or 1.0
        return [(s / top, c) for s, c in scored]

    def _bm25_rank(self, query: str) -> List[Tuple[float, Dict[str, Any]]]:
        """Return (normalized_score, chunk) pairs sorted desc for a query over the
        knowledge-base lexical index (building it lazily)."""
        if not self.lexical_built:
            self._build_lexical_index()
        return self._bm25_over(query, self.lexical_index, self.lexical_df, self.lexical_avg_len)

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
            # Eye-Describe Anatomy & technical guides
            "anatomy": "eye_describe_anatomy_index.md",
            "structure": "eye_describe_anatomy_index.md",
            "layout": "eye_describe_anatomy_index.md",
            "offset": "eye_describe_anatomy_index.md",
            "byte": "eye_describe_anatomy_index.md",
            "binary": "eye_describe_anatomy_index.md",
            "header": "eye_describe_anatomy_index.md",
            "guide": "eye_describe_anatomy_index.md",
            "describe": "eye_describe_anatomy_index.md",
            # Intelligence & Reasoning Mappings
            "forensic_methodology": "forensic_methodology.md",
            "evidence_intelligence": "evidence_intelligence.md",
            # IntentEngine emits the file-stem token "eye_describe_anatomy_index"
            # for anatomy/byte/offset/header/describe/guide queries. Without a
            # self-mapping key here, that token never resolves to a file and the
            # Eye-Describe anatomy hub (with the crow-eye.com/eye-describe URLs)
            # is never injected into the prompt. Map the stem to its file.
            "eye_describe_anatomy_index": "eye_describe_anatomy_index.md",
            # Key is the lowercased form of IntentEngine's emitted token
            # ("Global_schema_database_Reference".lower()); the VALUE points at
            # the real on-disk filename.
            "global_schema_database_reference": "Global_schema_database_Reference.md",
            # Correlation Engine — wings, semantic mappings, engine
            # diagnostics, multi-timestamp fan-out, GEP authoring rules.
            "correlation_engine_knowledge": "correlation_engine_knowledge.md",
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
    
    def retrieve_context(self, keywords: Optional[List[str]] = None, user_query: str = "",
                         max_tokens: int = 3000, top_k: int = 3, min_score: float = 0.0,
                         semantic_min_score: float = 0.4) -> str:
        """
        Retrieve knowledge base content using semantic search or keyword fallback.

        Args:
            keywords: List of detected forensic artifact keywords (legacy)
            user_query: The user's natural language query for semantic search
            max_tokens: Maximum tokens to return for the context (to prevent prompt bloat)
            top_k: Max ranked chunks (semantic OR lexical) beyond keyword-mapped docs
            min_score: Minimum relevance score for a ranked LEXICAL (BM25) chunk (0-1)
            semantic_min_score: Minimum cosine similarity for a ranked SEMANTIC
                (embedding) chunk — configurable so investigators can tighten or
                loosen vector relevance per deployment.

        Returns:
            Concatenated knowledge base content with section headers
        """
        # Precedence (deterministic first, semantic fills the remainder):
        #  1. KEYWORD-MAPPED docs — driven by IntentEngine + any force-added
        #     keyword (e.g. the global schema reference). These are explicit
        #     intent, so they MUST be reliably present and are added first.
        #  2. SEMANTIC top matches — fuzzy relevance for whatever the keyword
        #     map didn't already cover.
        # Dedup is by FILENAME (not a fragile keyword-substring check), so a file
        # pulled in by a keyword is never duplicated by a semantic chunk.
        context_parts = []
        seen_files = set()

        # ---- 1. Deterministic keyword-mapped docs (highest priority) ----
        if keywords:
            for keyword in keywords:
                fname = self.keyword_mapping.get(keyword.lower())
                if not fname or fname in seen_files:
                    continue
                content = self._load_knowledge_file(fname)
                if content:
                    seen_files.add(fname)
                    context_parts.append(f"## {keyword.title()} Knowledge\n{content}")
                    self.logger.debug(f"Retrieved knowledge for keyword: {keyword} ({fname})")

        # ---- 2. Ranked matches for files not already included ----
        #  2a. SEMANTIC (embedding) search when an embedding server is available.
        #  2b. ELSE the dependency-free LEXICAL (BM25) ranker, so cloud/CLI
        #      deployments still get ranked retrieval (not keyword-only).
        cap = max(1, int(top_k))
        if user_query and self.embedding_client:
            if not self.index_built:
                self._build_vector_index()

            if self.vector_index:
                query_emb = self.embedding_client.embed_text(user_query, is_query=True)
                if query_emb:
                    results = []
                    for item in self.vector_index:
                        score = cosine_similarity(query_emb, item["embedding"])
                        if score > semantic_min_score:  # configurable relevance threshold
                            results.append((score, item))

                    if results:
                        results.sort(key=lambda x: x[0], reverse=True)
                        added = 0
                        for score, item in results:
                            if added >= cap:  # cap semantic chunks
                                break
                            if item["filename"] in seen_files:
                                continue  # already pulled in deterministically
                            filename = item["filename"].replace("_knowledge.md", "").title()
                            context_parts.append(f"## {filename} Knowledge (Semantic Match)\n{item['content']}")
                            seen_files.add(item["filename"])
                            added += 1
                        if added:
                            self.logger.info(f"Retrieved {added} semantic knowledge sections.")
        elif user_query:
            ranked = self._bm25_rank(user_query)
            added = 0
            for score, item in ranked:
                if added >= cap:
                    break
                if score < min_score:
                    break  # ranked desc — nothing below threshold remains
                if item["filename"] in seen_files:
                    continue
                filename = item["filename"].replace("_knowledge.md", "").title()
                context_parts.append(f"## {filename} Knowledge (Lexical Match)\n{item['content']}")
                seen_files.add(item["filename"])
                added += 1
            if added:
                self.logger.info(f"Retrieved {added} lexical knowledge sections.")

        # Record which files informed this retrieval (for "knowledge consulted").
        self.last_sources = list(seen_files)

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

    # ------------------------------------------------------------------
    # Conversation-memory recall (long-term memory)
    # ------------------------------------------------------------------
    def index_conversation_turn(self, text: str, meta: Optional[Dict[str, Any]] = None):
        """Add one evicted conversation turn to the recall index. Best-effort —
        never raises (a failure must not block history management)."""
        try:
            tokens = _rag_tokenize(text or "")
            if not tokens:
                return
            meta = meta or {}
            tf: Dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self.conversation_index.append({
                "content": text,
                "tf": tf,
                "len": len(tokens),
                "id": meta.get("id"),
                "role": meta.get("role"),
                "timestamp": meta.get("timestamp"),
            })
            for term in tf:
                self.conversation_df[term] = self.conversation_df.get(term, 0) + 1
            self.conversation_total_len += len(tokens)
            n = len(self.conversation_index)
            self.conversation_avg_len = (self.conversation_total_len / n) if n else 0.0
        except Exception as e:
            self.logger.debug(f"index_conversation_turn failed: {e}")

    def load_conversation_archive(self, path):
        """Rebuild the conversation recall index from a per-case archive jsonl
        (one evicted turn per line). Best-effort; called on case load."""
        try:
            p = Path(path)
            if not p.exists():
                return
            self.conversation_index = []
            self.conversation_df = {}
            self.conversation_total_len = 0
            self.conversation_avg_len = 0.0
            count = 0
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    self.index_conversation_turn(
                        rec.get("content", ""),
                        {"id": rec.get("id"), "role": rec.get("role"), "timestamp": rec.get("timestamp")},
                    )
                    count += 1
            if count:
                self.logger.info(f"Loaded {count} archived conversation turn(s) into the recall index.")
        except Exception as e:
            self.logger.debug(f"load_conversation_archive failed: {e}")

    def retrieve_conversation(self, user_query: str = "", max_tokens: int = 1500,
                              top_k: int = 3, min_score: float = 0.0) -> str:
        """Retrieve the most relevant EARLIER conversation turns (that were
        summarized / slid out of the live window) for the current query.

        Returns a formatted block (or "" when nothing relevant) and records
        ``last_conversation_sources`` for the Compliance "recalled" step. BM25 over
        the same machinery as the knowledge base; degrades silently to "".
        """
        self.last_conversation_sources = []
        if not user_query or not self.conversation_index:
            return ""
        ranked = self._bm25_over(
            user_query, self.conversation_index, self.conversation_df, self.conversation_avg_len
        )
        parts: List[str] = []
        sources: List[str] = []
        added = 0
        cap = max(1, int(top_k))
        for score, item in ranked:
            if added >= cap:
                break
            if score < min_score:
                break  # ranked desc — nothing below threshold remains
            role = item.get("role") or "message"
            ts = item.get("timestamp") or ""
            parts.append(f"### Earlier {role} turn ({ts})\n{item['content']}")
            sources.append(item.get("id") or ts or role)
            added += 1
        self.last_conversation_sources = sources
        if not parts:
            return ""
        full = "\n\n".join(parts)
        if len(full) // 4 > max_tokens:
            return full[:max_tokens * 4] + "\n\n... [Recalled conversation truncated for token safety] ..."
        return full

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
        self.lexical_index.clear()
        self.lexical_df.clear()
        self.lexical_avg_len = 0.0
        self.lexical_built = False
        self.last_sources = []
        self.logger.info("Knowledge file cache and vector/lexical indexes cleared")
    
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
