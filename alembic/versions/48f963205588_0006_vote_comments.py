"""0006_vote_comments

Revision ID: 48f963205588
Revises: 0005_guest_orders_prelim_ga
Create Date: 2026-06-24 21:26:57.437476

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = '48f963205588'
down_revision: Union[str, Sequence[str], None] = '0005_guest_orders_prelim_ga'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('vote_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('comment_text', sa.Text(), nullable=False),
    sa.Column('tenant_slug', sa.String(length=50), nullable=False),
    sa.Column('season_year', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vote_comments_candidate_id'), 'vote_comments', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_vote_comments_id'), 'vote_comments', ['id'], unique=False)
    op.create_index(op.f('ix_vote_comments_season_year'), 'vote_comments', ['season_year'], unique=False)
    op.create_index(op.f('ix_vote_comments_tenant_slug'), 'vote_comments', ['tenant_slug'], unique=False)
    op.create_index(op.f('ix_vote_comments_transaction_id'), 'vote_comments', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_vote_comments_user_id'), 'vote_comments', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_vote_comments_user_id'), table_name='vote_comments')
    op.drop_index(op.f('ix_vote_comments_transaction_id'), table_name='vote_comments')
    op.drop_index(op.f('ix_vote_comments_tenant_slug'), table_name='vote_comments')
    op.drop_index(op.f('ix_vote_comments_season_year'), table_name='vote_comments')
    op.drop_index(op.f('ix_vote_comments_id'), table_name='vote_comments')
    op.drop_index(op.f('ix_vote_comments_candidate_id'), table_name='vote_comments')
    op.drop_table('vote_comments')
