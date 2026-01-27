"""A/B testing service for RAG experiments.

Enables testing different configurations:
- Embedding models
- Retrieval strategies (k, reranking)
- Prompt templates
- Model parameters
"""

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.experiment import Experiment, ExperimentExposure, ExperimentOutcome


@dataclass
class VariantConfig:
    """Configuration for an experiment variant."""

    name: str
    config: dict[str, Any]
    description: str = ""


@dataclass
class ExperimentResult:
    """Results from an experiment analysis."""

    experiment_id: str
    experiment_name: str
    variants: dict[str, dict[str, Any]]  # variant_name -> metrics
    winner: str | None
    confidence: float
    sample_sizes: dict[str, int]
    is_significant: bool


class ABTestingService:
    """Service for managing A/B experiments on RAG pipeline.

    Supports:
    - Creating and managing experiments
    - Assigning users/conversations to variants
    - Recording outcomes
    - Analyzing results with statistical significance
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._experiment_cache: dict[str, Experiment] = {}

    async def create_experiment(
        self,
        name: str,
        variants: list[VariantConfig],
        traffic_allocation: dict[str, float] | None = None,
        description: str = "",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        created_by: str | None = None,
    ) -> Experiment:
        """Create a new A/B experiment.

        Args:
            name: Experiment name
            variants: List of variant configurations
            traffic_allocation: Percentage allocation per variant (must sum to 1.0)
            description: Experiment description
            start_date: When experiment starts (defaults to now)
            end_date: When experiment ends (optional)
            created_by: Admin user ID

        Returns:
            Created experiment
        """
        # Build variants dict
        variants_dict = {v.name: {"config": v.config, "description": v.description} for v in variants}

        # Default to equal allocation
        if traffic_allocation is None:
            allocation = 1.0 / len(variants)
            traffic_allocation = {v.name: allocation for v in variants}

        # Validate allocation sums to 1.0
        total_allocation = sum(traffic_allocation.values())
        if abs(total_allocation - 1.0) > 0.01:
            raise ValueError(f"Traffic allocation must sum to 1.0, got {total_allocation}")

        experiment = Experiment(
            name=name,
            description=description,
            variants=variants_dict,
            traffic_allocation=traffic_allocation,
            start_date=start_date or datetime.utcnow(),
            end_date=end_date,
            is_active=True,
            created_by=created_by,
        )

        self.db.add(experiment)
        await self.db.commit()
        await self.db.refresh(experiment)

        return experiment

    async def get_active_experiments(self) -> list[Experiment]:
        """Get all active experiments."""
        now = datetime.utcnow()
        query = select(Experiment).where(
            and_(
                Experiment.is_active == True,  # noqa: E712
                Experiment.start_date <= now,
                (Experiment.end_date.is_(None)) | (Experiment.end_date >= now),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_experiment(self, experiment_id: str) -> Experiment | None:
        """Get experiment by ID."""
        result = await self.db.execute(
            select(Experiment).where(Experiment.id == experiment_id)
        )
        return result.scalar_one_or_none()

    async def get_variant_for_user(
        self,
        experiment_id: str,
        user_id: str | None,
        conversation_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """Get the variant assignment for a user/conversation.

        Uses consistent hashing to ensure same user always gets same variant.

        Args:
            experiment_id: Experiment ID
            user_id: Optional user ID (for logged-in users)
            conversation_id: Conversation ID (fallback for anonymous)

        Returns:
            Tuple of (variant_name, variant_config)
        """
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Check for existing exposure
        identifier = user_id or conversation_id
        existing = await self.db.execute(
            select(ExperimentExposure).where(
                and_(
                    ExperimentExposure.experiment_id == experiment_id,
                    (ExperimentExposure.user_id == user_id) if user_id
                    else (ExperimentExposure.conversation_id == conversation_id),
                )
            )
        )
        existing_exposure = existing.scalar_one_or_none()

        if existing_exposure:
            variant_name = existing_exposure.variant_name
            variant_config = experiment.variants[variant_name]["config"]
            return variant_name, variant_config

        # Assign new variant using consistent hashing
        variant_name = self._assign_variant(experiment, identifier)
        variant_config = experiment.variants[variant_name]["config"]

        # Record exposure
        exposure = ExperimentExposure(
            experiment_id=experiment_id,
            variant_name=variant_name,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        self.db.add(exposure)
        await self.db.commit()

        return variant_name, variant_config

    async def record_outcome(
        self,
        experiment_id: str,
        conversation_id: str,
        metrics: dict[str, Any],
    ) -> ExperimentOutcome:
        """Record outcome metrics for an experiment exposure.

        Args:
            experiment_id: Experiment ID
            conversation_id: Conversation ID
            metrics: Outcome metrics (e.g., retrieval_score, confidence, feedback)

        Returns:
            Created outcome record
        """
        # Get the variant this conversation was exposed to
        exposure = await self.db.execute(
            select(ExperimentExposure).where(
                and_(
                    ExperimentExposure.experiment_id == experiment_id,
                    ExperimentExposure.conversation_id == conversation_id,
                )
            )
        )
        exp = exposure.scalar_one_or_none()

        if not exp:
            raise ValueError(f"No exposure found for conversation {conversation_id}")

        outcome = ExperimentOutcome(
            experiment_id=experiment_id,
            variant_name=exp.variant_name,
            conversation_id=conversation_id,
            metrics=metrics,
        )

        self.db.add(outcome)
        await self.db.commit()
        await self.db.refresh(outcome)

        return outcome

    async def analyze_experiment(
        self,
        experiment_id: str,
        metric_name: str = "confidence_score",
    ) -> ExperimentResult:
        """Analyze experiment results.

        Calculates metrics per variant and determines statistical significance.

        Args:
            experiment_id: Experiment ID
            metric_name: Primary metric to compare

        Returns:
            ExperimentResult with analysis
        """
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Get all outcomes
        outcomes_query = select(ExperimentOutcome).where(
            ExperimentOutcome.experiment_id == experiment_id
        )
        result = await self.db.execute(outcomes_query)
        outcomes = result.scalars().all()

        # Group by variant
        variant_metrics: dict[str, list[float]] = {
            name: [] for name in experiment.variants.keys()
        }
        variant_outcomes: dict[str, list[dict]] = {
            name: [] for name in experiment.variants.keys()
        }

        for outcome in outcomes:
            if outcome.variant_name in variant_metrics:
                variant_outcomes[outcome.variant_name].append(outcome.metrics)
                if metric_name in outcome.metrics:
                    variant_metrics[outcome.variant_name].append(
                        outcome.metrics[metric_name]
                    )

        # Calculate statistics per variant
        variant_stats = {}
        sample_sizes = {}

        for variant_name, values in variant_metrics.items():
            sample_sizes[variant_name] = len(values)
            if values:
                variant_stats[variant_name] = {
                    "mean": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                    "std": self._calculate_std(values),
                }

                # Calculate additional metrics from full outcomes
                all_outcomes = variant_outcomes[variant_name]
                variant_stats[variant_name]["positive_feedback_rate"] = self._calculate_rate(
                    all_outcomes, "feedback", "helpful"
                )
                variant_stats[variant_name]["escalation_rate"] = self._calculate_rate(
                    all_outcomes, "required_escalation", True
                )
            else:
                variant_stats[variant_name] = {
                    "mean": 0,
                    "min": 0,
                    "max": 0,
                    "count": 0,
                    "std": 0,
                }

        # Determine winner and significance
        winner, confidence, is_significant = self._determine_winner(
            variant_stats, metric_name
        )

        return ExperimentResult(
            experiment_id=experiment_id,
            experiment_name=experiment.name,
            variants=variant_stats,
            winner=winner,
            confidence=confidence,
            sample_sizes=sample_sizes,
            is_significant=is_significant,
        )

    async def end_experiment(
        self,
        experiment_id: str,
        apply_winner: bool = False,
    ) -> Experiment:
        """End an experiment.

        Args:
            experiment_id: Experiment ID
            apply_winner: If True, returns the winning variant config

        Returns:
            Updated experiment
        """
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment.is_active = False
        experiment.end_date = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(experiment)

        return experiment

    async def get_experiment_exposures_count(
        self,
        experiment_id: str,
    ) -> dict[str, int]:
        """Get exposure counts per variant."""
        query = (
            select(
                ExperimentExposure.variant_name,
                func.count(ExperimentExposure.id).label("count"),
            )
            .where(ExperimentExposure.experiment_id == experiment_id)
            .group_by(ExperimentExposure.variant_name)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return {row.variant_name: row.count for row in rows}

    def _assign_variant(self, experiment: Experiment, identifier: str) -> str:
        """Assign a variant using consistent hashing.

        Ensures same identifier always gets same variant.
        """
        # Create deterministic hash
        hash_input = f"{experiment.id}:{identifier}"
        hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)

        # Map to [0, 1) range
        normalized = (hash_value % 10000) / 10000.0

        # Find variant based on allocation
        cumulative = 0.0
        for variant_name, allocation in experiment.traffic_allocation.items():
            cumulative += allocation
            if normalized < cumulative:
                return variant_name

        # Fallback to last variant (shouldn't happen with valid allocation)
        return list(experiment.traffic_allocation.keys())[-1]

    def _calculate_std(self, values: list[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5

    def _calculate_rate(
        self,
        outcomes: list[dict],
        key: str,
        positive_value: Any,
    ) -> float:
        """Calculate rate of positive outcomes."""
        if not outcomes:
            return 0.0

        positive_count = sum(1 for o in outcomes if o.get(key) == positive_value)
        return positive_count / len(outcomes)

    def _determine_winner(
        self,
        variant_stats: dict[str, dict[str, Any]],
        metric_name: str,
    ) -> tuple[str | None, float, bool]:
        """Determine winning variant with confidence.

        Uses a simple z-test for significance.
        Returns (winner_name, confidence, is_significant)
        """
        if len(variant_stats) < 2:
            return None, 0.0, False

        # Get variants with data
        valid_variants = {
            name: stats for name, stats in variant_stats.items() if stats["count"] > 0
        }

        if len(valid_variants) < 2:
            return None, 0.0, False

        # Find best variant by mean
        sorted_variants = sorted(
            valid_variants.items(),
            key=lambda x: x[1]["mean"],
            reverse=True,
        )

        best_name, best_stats = sorted_variants[0]
        second_name, second_stats = sorted_variants[1]

        # Check if we have enough samples for significance
        min_samples = 30
        if best_stats["count"] < min_samples or second_stats["count"] < min_samples:
            return best_name, 0.0, False

        # Simple z-test
        diff = best_stats["mean"] - second_stats["mean"]
        pooled_se = (
            (best_stats["std"] ** 2 / best_stats["count"])
            + (second_stats["std"] ** 2 / second_stats["count"])
        ) ** 0.5

        if pooled_se == 0:
            return best_name, 0.0, False

        z_score = diff / pooled_se

        # Approximate confidence from z-score
        # z=1.96 -> 95% confidence, z=2.58 -> 99% confidence
        if z_score >= 2.58:
            confidence = 0.99
            is_significant = True
        elif z_score >= 1.96:
            confidence = 0.95
            is_significant = True
        elif z_score >= 1.65:
            confidence = 0.90
            is_significant = False
        else:
            confidence = 0.5 + (z_score * 0.2)  # Rough approximation
            is_significant = False

        return best_name, confidence, is_significant


# Pre-defined experiment templates
EXPERIMENT_TEMPLATES = {
    "retrieval_k": {
        "name": "Retrieval K Parameter Test",
        "description": "Test different values of k for initial retrieval",
        "variants": [
            VariantConfig("k_10", {"retrieval_k": 10}, "10 documents"),
            VariantConfig("k_20", {"retrieval_k": 20}, "20 documents"),
            VariantConfig("k_30", {"retrieval_k": 30}, "30 documents"),
        ],
    },
    "reranking": {
        "name": "Reranking Strategy Test",
        "description": "Test with and without reranking",
        "variants": [
            VariantConfig("no_rerank", {"use_reranking": False}, "No reranking"),
            VariantConfig("rerank", {"use_reranking": True}, "With reranking"),
        ],
    },
    "embedding_model": {
        "name": "Embedding Model Comparison",
        "description": "Compare different embedding models",
        "variants": [
            VariantConfig(
                "voyage_2",
                {"embedding_model": "voyage-2"},
                "Voyage AI v2",
            ),
            VariantConfig(
                "voyage_large",
                {"embedding_model": "voyage-large-2"},
                "Voyage AI Large v2",
            ),
        ],
    },
    "prompt_template": {
        "name": "Prompt Template Test",
        "description": "Test different prompt templates for generation",
        "variants": [
            VariantConfig(
                "concise",
                {"prompt_style": "concise"},
                "Concise responses",
            ),
            VariantConfig(
                "detailed",
                {"prompt_style": "detailed"},
                "Detailed responses",
            ),
        ],
    },
}


async def create_experiment_from_template(
    db_session: AsyncSession,
    template_name: str,
    created_by: str | None = None,
) -> Experiment:
    """Create an experiment from a predefined template."""
    if template_name not in EXPERIMENT_TEMPLATES:
        raise ValueError(f"Unknown template: {template_name}")

    template = EXPERIMENT_TEMPLATES[template_name]
    service = ABTestingService(db_session)

    return await service.create_experiment(
        name=template["name"],
        description=template["description"],
        variants=template["variants"],
        created_by=created_by,
    )
