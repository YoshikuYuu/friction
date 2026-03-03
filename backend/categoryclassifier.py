from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Callable, List

import torch
import torch.nn as nn
from tqdm.auto import tqdm

from category import CategoryConfig


@dataclass
class ProbeTrainingResult:
    epochs: int
    samples: int
    final_loss: float
    losses: List[float]


class LinearProbe(nn.Module):
    def __init__(self,
                 input_dim: int,
                 hidden_dim: int = 8,
                 init_bias: float = -2.0):
        super().__init__()
        if hidden_dim < 1:
            raise ValueError("hidden_dim must be at least 1")

        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.classifier = nn.Sequential(
            nn.Linear(input_dim, hidden_dim, bias=False),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1, bias=True),
            nn.Sigmoid()
        )
        # Initialize bias to always predict negative
        nn.init.constant_(self.classifier[2].bias, init_bias)  # type: ignore

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        logits = self.classifier(embeddings)
        return logits


class CategoryClassifier:
    config: CategoryConfig

    def __init__(
        self,
        cfg: CategoryConfig,
        embed_fn: Callable[[List[str], bool], torch.Tensor],
        probe_rank: int = 8,
        decision_threshold: float = 0.5,
    ):
        self.config = cfg
        self.embed_fn = embed_fn
        self.probe_rank = probe_rank
        self.decision_threshold = decision_threshold

        self.probe: LinearProbe | None = None

    def _as_tensor(self, values) -> torch.Tensor:
        if isinstance(values, torch.Tensor):
            tensor = values
        else:
            tensor = torch.as_tensor(values)

        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)
        return tensor.float()

    def _ensure_probe(self, input_dim: int) -> None:
        if self.probe is None:
            self.probe = LinearProbe(input_dim=input_dim, hidden_dim=self.probe_rank)

    def update_definitions(self, positive: List[str], negative: List[str]) -> None:
        self.config.update_definitions(positive=positive, negative=negative)

    def train_probe(
        self,
        positive_texts: List[str],
        negative_texts: List[str],
        epochs: int = 4,
        batch_size: int = 32,
        learning_rate: float = 1e-2,
        weight_decay: float = 1e-4,
        show_progress: bool = True,
    ) -> ProbeTrainingResult:
        if not positive_texts or not negative_texts:
            raise ValueError("positive_texts and negative_texts must both be non-empty.")

        inputs = positive_texts + negative_texts
        labels = torch.cat(
            [
                torch.ones(len(positive_texts), dtype=torch.float32),
                torch.zeros(len(negative_texts), dtype=torch.float32),
            ]
        )

        with torch.no_grad():
            embeddings = self._as_tensor(self.embed_fn(inputs, False))

        if embeddings.ndim != 2:
            raise ValueError("Expected 2D embeddings tensor.")

        self._ensure_probe(input_dim=embeddings.size(-1))
        if self.probe is None:
            raise RuntimeError("Probe initialization failed.")

        optimizer = torch.optim.AdamW(
            self.probe.parameters(), lr=learning_rate, weight_decay=weight_decay
        )
        criterion = nn.BCEWithLogitsLoss()

        permutation = torch.randperm(embeddings.size(0))
        embeddings = embeddings[permutation]
        labels = labels[permutation]

        losses: List[float] = []
        self.probe.train()

        epoch_iterator = tqdm(
            range(epochs),
            desc=f"probe:{self.config.name}",
            unit="epoch",
            disable=not show_progress,
        )

        total_batches = max(1, math.ceil(embeddings.size(0) / batch_size))
        for epoch_index in epoch_iterator:
            epoch_loss = 0.0
            seen = 0

            batch_iterator = tqdm(
                range(0, embeddings.size(0), batch_size),
                total=total_batches,
                desc=f"epoch {epoch_index + 1}/{epochs}",
                unit="batch",
                leave=False,
                disable=not show_progress,
            )

            for start in batch_iterator:
                batch_embeddings = embeddings[start : start + batch_size]
                batch_labels = labels[start : start + batch_size]

                optimizer.zero_grad()
                logits = self.probe(batch_embeddings)
                loss = criterion(logits, batch_labels)
                loss.backward()
                optimizer.step()

                batch_size_now = batch_embeddings.size(0)
                epoch_loss += loss.item() * batch_size_now
                seen += batch_size_now

                if show_progress:
                    batch_iterator.set_postfix(loss=f"{loss.item():.4f}")

            mean_loss = epoch_loss / max(1, seen)
            losses.append(mean_loss)
            if show_progress:
                epoch_iterator.set_postfix(mean_loss=f"{mean_loss:.4f}")

        return ProbeTrainingResult(
            epochs=epochs,
            samples=int(embeddings.size(0)),
            final_loss=losses[-1],
            losses=losses,
        )

    @torch.no_grad()
    def score_text(self, text: str) -> float:
        if self.probe is None:
            return 0.0

        self.probe.eval()
        emb = self._as_tensor(self.embed_fn([text], True))
        logits = self.probe(emb)
        probs = torch.sigmoid(logits)
        return probs.squeeze().item()

    def matches(self, text: str) -> bool:
        score = self.score_text(text)
        return score >= self.decision_threshold

    def save(self, save_dir: str | Path) -> None:
        if self.probe is None:
            raise ValueError("Probe is not trained; cannot save.")

        path = Path(save_dir)
        path.mkdir(parents=True, exist_ok=True)

        state_path = path / "probe.pt"
        metadata_path = path / "metadata.json"

        torch.save(self.probe.state_dict(), state_path)

        metadata = {
            "name": self.config.name,
            "block_mode": self.config.block_mode,
            "initial_definition": self.config.initial_definition,
            "positive_definitions": self.config.positive_definitions,
            "negative_definitions": self.config.negative_definitions,
            "probe_rank": self.probe_rank,
            "decision_threshold": self.decision_threshold,
            "input_dim": self.probe.input_dim,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def load(self, save_dir: str | Path) -> None:
        path = Path(save_dir)
        metadata_path = path / "metadata.json"
        state_path = path / "probe.pt"

        if not metadata_path.exists() or not state_path.exists():
            raise FileNotFoundError(f"Missing probe files under {path}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        input_dim = int(metadata["input_dim"])
        self.probe_rank = int(metadata.get("probe_rank", self.probe_rank))
        self.decision_threshold = float(
            metadata.get("decision_threshold", self.decision_threshold)
        )

        self.probe = LinearProbe(input_dim=input_dim, hidden_dim=self.probe_rank)
        state_dict = torch.load(state_path, map_location="cpu")
        self.probe.load_state_dict(state_dict)
