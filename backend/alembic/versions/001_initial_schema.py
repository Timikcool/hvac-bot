"""Initial schema with all models.

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("external_id", sa.String(255), unique=True, nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("preferred_brands", sa.String(500), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Admin users table
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), default="analyst"),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Conversations table
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("equipment_brand", sa.String(100), nullable=True),
        sa.Column("equipment_model", sa.String(100), nullable=True),
        sa.Column("equipment_serial", sa.String(100), nullable=True),
        sa.Column("system_type", sa.String(50), nullable=True),
        sa.Column("session_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_messages", sa.Integer(), default=0),
        sa.Column("resolution_status", sa.String(20), default="ongoing"),
        sa.Column("user_satisfaction_score", sa.Integer(), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(), default=dict),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # Messages table
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("confidence_level", sa.String(20), nullable=True),
        sa.Column("retrieval_scores", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("cited_sources", postgresql.JSONB(), nullable=True),
        sa.Column("safety_warnings", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("required_escalation", sa.Boolean(), default=False),
        sa.Column("contains_image", sa.Boolean(), default=False),
        sa.Column("image_type", sa.String(20), nullable=True),
        sa.Column("detected_intent", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("is_good_example", sa.Boolean(), nullable=True),
        sa.Column("annotation_notes", sa.Text(), nullable=True),
        sa.Column(
            "annotated_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("annotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    # Message retrievals table
    op.create_table(
        "message_retrievals",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.String(36), nullable=True),
        sa.Column("chunk_content", sa.Text(), nullable=False),
        sa.Column("chunk_metadata", postgresql.JSONB(), default=dict),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("was_used_in_response", sa.Boolean(), default=True),
        sa.Column("position_in_results", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_message_retrievals_message_id", "message_retrievals", ["message_id"])

    # Message feedback table
    op.create_table(
        "message_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feedback_type", sa.String(20), nullable=False),
        sa.Column("feedback_details", sa.Text(), nullable=True),
        sa.Column("correct_answer", sa.Text(), nullable=True),
        sa.Column("missing_information", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"])

    # Manuals table
    op.create_table(
        "manuals",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("brand", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("model_series", sa.String(100), nullable=True),
        sa.Column("system_type", sa.String(50), nullable=True),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("page_count", sa.Integer(), default=0),
        sa.Column("is_processed", sa.Boolean(), default=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(), default=dict),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_manuals_brand", "manuals", ["brand"])
    op.create_index("ix_manuals_model", "manuals", ["model"])

    # Manual chunks table
    op.create_table(
        "manual_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("manual_id", sa.String(36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_type", sa.String(50), nullable=False),
        sa.Column("page_numbers", postgresql.ARRAY(sa.Integer()), default=list),
        sa.Column("parent_section", sa.String(500), nullable=True),
        sa.Column("has_image_reference", sa.Boolean(), default=False),
        sa.Column("brand", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("system_type", sa.String(50), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), default=list),
        sa.Column("error_code", sa.String(20), nullable=True),
        sa.Column("vector_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_manual_chunks_manual_id", "manual_chunks", ["manual_id"])
    op.create_index("ix_manual_chunks_brand", "manual_chunks", ["brand"])
    op.create_index("ix_manual_chunks_model", "manual_chunks", ["model"])
    op.create_index("ix_manual_chunks_error_code", "manual_chunks", ["error_code"])

    # Manual images table
    op.create_table(
        "manual_images",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("manual_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_index", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_format", sa.String(10), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_type", sa.String(50), nullable=True),
        sa.Column("components_identified", postgresql.ARRAY(sa.Text()), default=list),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_manual_images_manual_id", "manual_images", ["manual_id"])

    # Retrieval quality metrics table
    op.create_table(
        "retrieval_quality_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("equipment_brand", sa.String(100), nullable=True),
        sa.Column("equipment_model", sa.String(100), nullable=True),
        sa.Column("query_intent", sa.String(50), nullable=True),
        sa.Column("total_queries", sa.Integer(), default=0),
        sa.Column("avg_top_retrieval_score", sa.Float(), nullable=True),
        sa.Column("avg_response_confidence", sa.Float(), nullable=True),
        sa.Column("queries_with_no_results", sa.Integer(), default=0),
        sa.Column("queries_requiring_escalation", sa.Integer(), default=0),
        sa.Column("positive_feedback_count", sa.Integer(), default=0),
        sa.Column("negative_feedback_count", sa.Integer(), default=0),
    )
    op.create_index("ix_retrieval_quality_metrics_date", "retrieval_quality_metrics", ["date"])
    op.create_index(
        "ix_retrieval_quality_metrics_brand",
        "retrieval_quality_metrics",
        ["equipment_brand"],
    )

    # Knowledge gaps table
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("query_pattern", sa.Text(), nullable=False),
        sa.Column("equipment_brand", sa.String(100), nullable=True),
        sa.Column("equipment_model", sa.String(100), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), default=1),
        sa.Column("sample_queries", postgresql.ARRAY(sa.Text()), default=list),
        sa.Column("avg_retrieval_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), default="identified"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(), default=dict),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_knowledge_gaps_brand", "knowledge_gaps", ["equipment_brand"])
    op.create_index("ix_knowledge_gaps_status", "knowledge_gaps", ["status"])

    # Experiments table
    op.create_table(
        "experiments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("variants", postgresql.JSONB(), nullable=False),
        sa.Column("traffic_allocation", postgresql.JSONB(), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_experiments_is_active", "experiments", ["is_active"])

    # Experiment exposures table
    op.create_table(
        "experiment_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant_name", sa.String(100), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("exposed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_experiment_exposures_experiment_id", "experiment_exposures", ["experiment_id"])
    op.create_index("ix_experiment_exposures_user_id", "experiment_exposures", ["user_id"])
    op.create_index("ix_experiment_exposures_conversation_id", "experiment_exposures", ["conversation_id"])

    # Experiment outcomes table
    op.create_table(
        "experiment_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant_name", sa.String(100), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_experiment_outcomes_experiment_id", "experiment_outcomes", ["experiment_id"])
    op.create_index("ix_experiment_outcomes_conversation_id", "experiment_outcomes", ["conversation_id"])


def downgrade() -> None:
    # Drop tables in reverse order of creation (respecting foreign keys)
    op.drop_table("experiment_outcomes")
    op.drop_table("experiment_exposures")
    op.drop_table("experiments")
    op.drop_table("knowledge_gaps")
    op.drop_table("retrieval_quality_metrics")
    op.drop_table("manual_images")
    op.drop_table("manual_chunks")
    op.drop_table("manuals")
    op.drop_table("message_feedback")
    op.drop_table("message_retrievals")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("admin_users")
    op.drop_table("users")
