"""Add diagnostic flowcharts, terminology mappings, feedback corrections, and OpenClaw fields.

Revision ID: 003_add_diagnostic_and_improvement_tables
Revises: 002_add_feedback_rating
Create Date: 2026-02-24

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "003_add_diagnostic_and_improvement_tables"
down_revision = "002_add_feedback_rating"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- New tables ---

    op.create_table(
        "diagnostic_flowcharts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("equipment_brand", sa.String(100), nullable=True),
        sa.Column("equipment_model", sa.String(100), nullable=True),
        sa.Column("system_type", sa.String(50), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("usage_count", sa.Integer(), default=0),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("symptom_keywords", JSONB(), nullable=True),
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

    op.create_table(
        "diagnostic_steps",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "flowchart_id",
            UUID(as_uuid=False),
            sa.ForeignKey("diagnostic_flowcharts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("priority_weight", sa.Integer(), default=50, nullable=False),
        sa.Column("check_description", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("if_fail_action", sa.Text(), nullable=True),
        sa.Column("if_pass_action", sa.Text(), nullable=True),
        sa.Column("component", sa.String(100), nullable=True),
        sa.Column("tools_needed", sa.String(255), nullable=True),
        sa.Column("safety_warning", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("times_confirmed", sa.Integer(), default=0),
        sa.Column("times_corrected", sa.Integer(), default=0),
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

    op.create_table(
        "terminology_mappings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("textbook_term", sa.String(255), nullable=False),
        sa.Column("field_term", sa.String(255), nullable=False),
        sa.Column("context", sa.String(100), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("confirmed_by_count", sa.Integer(), default=0),
        sa.Column("is_active", sa.Boolean(), default=True),
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

    op.create_table(
        "feedback_corrections",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "message_id",
            UUID(as_uuid=False),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=False),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("correction_type", sa.String(30), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("corrected_text", sa.Text(), nullable=True),
        sa.Column("correction_data", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column(
            "flowchart_id",
            UUID(as_uuid=False),
            sa.ForeignKey("diagnostic_flowcharts.id", ondelete="SET NULL"),
            nullable=True,
        ),
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

    # --- Alter existing tables ---

    # Users: add OpenClaw platform fields
    op.add_column(
        "users",
        sa.Column("telegram_id", sa.String(100), unique=True, nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("whatsapp_id", sa.String(100), unique=True, nullable=True),
    )
    op.add_column(
        "users", sa.Column("platform_source", sa.String(30), nullable=True)
    )
    op.add_column(
        "users", sa.Column("experience_level", sa.String(30), nullable=True)
    )

    # Messages: add diagnostic tracking
    op.add_column(
        "messages",
        sa.Column(
            "diagnostic_flowchart_id",
            UUID(as_uuid=False),
            sa.ForeignKey("diagnostic_flowcharts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("terminology_corrections_applied", JSONB(), nullable=True),
    )

    # MessageFeedback: add correction type
    op.add_column(
        "message_feedback",
        sa.Column("correction_type", sa.String(30), nullable=True),
    )

    # --- Indexes ---
    op.create_index(
        "idx_flowcharts_symptom",
        "diagnostic_flowcharts",
        ["symptom"],
    )
    op.create_index(
        "idx_flowcharts_equipment",
        "diagnostic_flowcharts",
        ["equipment_brand", "equipment_model"],
    )
    op.create_index(
        "idx_steps_flowchart",
        "diagnostic_steps",
        ["flowchart_id"],
    )
    op.create_index(
        "idx_terminology_textbook",
        "terminology_mappings",
        ["textbook_term"],
    )
    op.create_index(
        "idx_corrections_status",
        "feedback_corrections",
        ["status"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_corrections_status")
    op.drop_index("idx_terminology_textbook")
    op.drop_index("idx_steps_flowchart")
    op.drop_index("idx_flowcharts_equipment")
    op.drop_index("idx_flowcharts_symptom")

    # Drop added columns
    op.drop_column("message_feedback", "correction_type")
    op.drop_column("messages", "terminology_corrections_applied")
    op.drop_column("messages", "diagnostic_flowchart_id")
    op.drop_column("users", "experience_level")
    op.drop_column("users", "platform_source")
    op.drop_column("users", "whatsapp_id")
    op.drop_column("users", "telegram_id")

    # Drop new tables
    op.drop_table("feedback_corrections")
    op.drop_table("terminology_mappings")
    op.drop_table("diagnostic_steps")
    op.drop_table("diagnostic_flowcharts")
