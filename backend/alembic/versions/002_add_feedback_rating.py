"""Add rating column to message_feedback

Revision ID: 002_add_feedback_rating
Revises: 001_initial_schema
Create Date: 2026-01-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_feedback_rating'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add rating column
    op.add_column('message_feedback', sa.Column('rating', sa.Integer(), nullable=True))
    
    # Make feedback_type nullable (since we can now have just a rating)
    op.alter_column('message_feedback', 'feedback_type',
                    existing_type=sa.VARCHAR(20),
                    nullable=True)


def downgrade() -> None:
    # Remove rating column
    op.drop_column('message_feedback', 'rating')
    
    # Make feedback_type not nullable again
    op.alter_column('message_feedback', 'feedback_type',
                    existing_type=sa.VARCHAR(20),
                    nullable=False)


