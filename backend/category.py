import torch
import torch.nn.functional as F
from typing import List, Callable

BLOCKMODE_STRICT = "strict"
BLOCKMODE_WARN = "warn"

class CategoryConfig:
    """Configuration for a category, including its name and definitions."""
    name: str
    initial_definition: str
    block_mode: str
    positive_definitions: List[str]
    negative_definitions: List[str]

    def __init__(self,
                 name: str,
                 initial_definition: str, 
                 block_mode: str):
        self.name = name
        self.initial_definition = initial_definition.strip()
        self.block_mode = block_mode
        self.positive_definitions = [initial_definition]
        self.negative_definitions = []

    def update_definitions(self, positive: List[str], negative: List[str]) -> None:
        self.positive_definitions = [text.strip() for text in positive if text.strip()]
        self.negative_definitions = [text.strip() for text in negative if text.strip()]
        if self.initial_definition not in self.positive_definitions:
            self.positive_definitions = [self.initial_definition] + self.positive_definitions

class Category:
    """A category of webpages defined by a simple semantic classifier.
    """
    config: CategoryConfig
    negative_embeddings: torch.Tensor
    positive_embeddings: torch.Tensor
    boundary_q: float = 0.9
    closeness_q: float = 0.1
    member_sim_th: float
    boundary: float

    def __init__(self,
                 cfg: CategoryConfig,
                 embed_fn: Callable[[List[str]], torch.Tensor]):
        self.config = cfg
        self.embed_fn = embed_fn

        self._refresh_embeddings_and_thresholds()

    def _refresh_embeddings_and_thresholds(self) -> None:

        pos_defs = self.config.positive_definitions
        neg_defs = self.config.negative_definitions

        self.positive_embeddings = self.embed_fn(pos_defs)
        if neg_defs:
            self.negative_embeddings = self.embed_fn(neg_defs)
        

        max_member_similarities = self._get_max_member_similarities()
        max_negative_similarities = self._get_min_negative_distances()
        
        boundaries = max_member_similarities - max_negative_similarities 
        self.boundary = torch.quantile(boundaries, self.boundary_q).item()
        self.member_sim_th = torch.quantile(max_member_similarities, self.closeness_q).item()

    def update_definitions(self, positive: List[str], negative: List[str]) -> None:
        self.config.update_definitions(positive=positive, negative=negative)
        self._refresh_embeddings_and_thresholds()
    
    def _get_max_member_similarities(self) -> torch.Tensor:
        """Computes the maximum cosine similarity for each positive embedding
        with respect to other positive embeddings."""
        if len(self.config.positive_definitions) < 2:
            return torch.tensor([0.05])  # Default low similarity if only one positive definition
        
        member_cosine_sim = F.cosine_similarity(
            self.positive_embeddings.unsqueeze(0),  # (1, P, D)
            self.positive_embeddings.unsqueeze(1),  # (P, 1, D)
            dim=-1
        ) # (P, P) matrix of cosine similarities among positives
        member_cosine_sim.fill_diagonal_(float('-inf')) # ignore self-similarity
        # max similarity to other positives for each positive
        max_member_cosine_sim, _ = member_cosine_sim.max(dim=1)
        return max_member_cosine_sim

    def _get_min_negative_distances(self) -> torch.Tensor:
        """Computes the maximum cosine similarity of each positive embedding to the nearest negative embedding."""
        if not self.config.negative_definitions:
            return torch.zeros(len(self.config.positive_definitions))  # No negatives, so return 0 similarity

        negative_similarities = F.cosine_similarity(
            self.positive_embeddings.unsqueeze(1),  # (P, 1, D)
            self.negative_embeddings.unsqueeze(0),  # (1, N, D)
            dim=-1,
        )  # (P, N) matrix of cosine similarities to negatives
        max_negative_similarities, _ = negative_similarities.max(dim=1)
        return max_negative_similarities

    def matches(self, text: str) -> bool:
        """Checks if a given text is classified as inside the category."""
        emb = self.embed_fn([text]).squeeze()

        max_pos_sim = F.cosine_similarity(
            emb, # (D,)
            self.positive_embeddings, # (P, D)
            dim=-1
        ).max().item()

        max_neg_sim = F.cosine_similarity(
            emb, # (D,)
            self.negative_embeddings, # (N, D)
            dim=-1
        ).max().item() if self.config.negative_definitions else 0.0
        
        sim_diff = max_pos_sim - max_neg_sim
        print(f"Debug: text='{text}', max_pos_sim={max_pos_sim:.4f}, max_neg_sim={max_neg_sim:.4f}, sim_diff={sim_diff:.4f}, member_sim_th={self.member_sim_th:.4f}, boundary={self.boundary:.4f}")
        return (max_pos_sim >= self.member_sim_th) and (sim_diff >= self.boundary)

