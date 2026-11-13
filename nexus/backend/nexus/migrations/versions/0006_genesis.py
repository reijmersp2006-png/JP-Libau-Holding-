"""Milestone E (Genesis): onderzoeksworkflows, Prediction Ledger (alleen toevoegen) en blinde beoordelingen.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13 17:30:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
APPEND_ONLY = ("predictions", "prediction_amendments", "prediction_outcomes")


def upgrade() -> None:
    op.create_table('research_workflows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trace_id', sa.String(length=40), nullable=False),
    sa.Column('subject', sa.String(length=32), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('requested_by', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('simulated', sa.Boolean(), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('messages', sa.JSON(), nullable=False),
    sa.Column('conclusion', sa.JSON(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('max_cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('eval_run', sa.String(length=40), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('finished_at', TS, nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trace_id'))
    for c in ('subject', 'status', 'eval_run', 'created_at'):
        op.create_index(f'ix_research_workflows_{c}', 'research_workflows', [c])

    op.create_table('predictions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pid', sa.String(length=40), nullable=False),
    sa.Column('agent', sa.String(length=32), nullable=False),
    sa.Column('provider', sa.String(length=24), nullable=True),
    sa.Column('model', sa.String(length=64), nullable=True),
    sa.Column('prompt_version', sa.String(length=32), nullable=False),
    sa.Column('subject', sa.String(length=32), nullable=False),
    sa.Column('outcome_def', sa.JSON(), nullable=False),
    sa.Column('probability', sa.Float(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('data_asof', TS, nullable=False),
    sa.Column('market_snapshot', sa.JSON(), nullable=False),
    sa.Column('horizon_end', TS, nullable=False),
    sa.Column('workflow_trace', sa.String(length=40), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=True),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pid'))
    for c in ('agent', 'subject', 'horizon_end', 'workflow_trace', 'created_at'):
        op.create_index(f'ix_predictions_{c}', 'predictions', [c])

    op.create_table('prediction_amendments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prediction_id', sa.Integer(), nullable=False),
    sa.Column('actor', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('change', sa.JSON(), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
    sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_prediction_amendments_prediction_id', 'prediction_amendments', ['prediction_id'])

    op.create_table('prediction_outcomes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prediction_id', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.Integer(), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('evaluator', sa.String(length=32), nullable=False),
    sa.Column('evaluated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prediction_id'))

    op.create_table('research_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=False),
    sa.Column('reviewer', sa.String(length=32), nullable=False),
    sa.Column('usefulness', sa.Integer(), nullable=False),
    sa.Column('errors_found', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['research_workflows.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'reviewer', name='uq_research_review'))
    op.create_index('ix_research_reviews_workflow_id', 'research_reviews', ['workflow_id'])

    # Alleen toevoegen, afgedwongen door de database zelf.
    dialect = op.get_bind().dialect.name
    for t in APPEND_ONLY:
        if dialect == 'sqlite':
            for o in ('UPDATE', 'DELETE'):
                op.execute(f"CREATE TRIGGER {t}_no_{o.lower()} BEFORE {o} ON {t} "
                           f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")
        elif dialect == 'postgresql':
            op.execute(f"CREATE OR REPLACE FUNCTION {t}_append_only() RETURNS trigger AS $$ BEGIN "
                       f"RAISE EXCEPTION '{t} is append-only'; END; $$ LANGUAGE plpgsql")
            op.execute(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {t} "
                       f"FOR EACH ROW EXECUTE FUNCTION {t}_append_only()")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for t in APPEND_ONLY:
        if dialect == 'sqlite':
            for o in ('update', 'delete'):
                op.execute(f"DROP TRIGGER IF EXISTS {t}_no_{o}")
        elif dialect == 'postgresql':
            op.execute(f"DROP TRIGGER IF EXISTS {t}_no_change ON {t}")
            op.execute(f"DROP FUNCTION IF EXISTS {t}_append_only()")
    op.drop_table('research_reviews')
    op.drop_table('prediction_outcomes')
    op.drop_table('prediction_amendments')
    op.drop_table('predictions')
    op.drop_table('research_workflows')
