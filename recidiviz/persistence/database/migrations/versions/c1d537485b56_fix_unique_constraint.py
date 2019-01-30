"""fix_unique_constraint

Revision ID: c1d537485b56
Revises: 997ed5aca81f
Create Date: 2019-01-30 10:15:25.202174

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d537485b56'
down_revision = '997ed5aca81f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_unique_constraint(None, 'dc_facility_aggregate', ['fips', 'report_date', 'report_granularity'])
    op.add_column('ky_county_aggregate', sa.Column('facility_name', sa.String(length=255), nullable=True))
    op.drop_column('ky_county_aggregate', 'county_name')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('ky_county_aggregate', sa.Column('county_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True))
    op.drop_column('ky_county_aggregate', 'facility_name')
    op.drop_constraint(None, 'dc_facility_aggregate', type_='unique')
    # ### end Alembic commands ###