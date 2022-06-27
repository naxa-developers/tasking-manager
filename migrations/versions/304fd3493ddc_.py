"""empty message

Revision ID: 304fd3493ddc
Revises: 924a63857df4
Create Date: 2022-06-20 13:50:26.229142

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "304fd3493ddc"
down_revision = "924a63857df4"
branch_labels = None
depends_on = None


def upgrade():
    # Modify tsvector_update_trgigger to include project_name
    op.execute(
        """
        DROP TRIGGER IF EXISTS tsvectorupdate ON project_info;
        CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE ON project_info FOR EACH ROW EXECUTE PROCEDURE
        tsvector_update_trigger(text_searchable, "pg_catalog.english", project_id_str, name,
        short_description, description)
        """
    )
    # Upgrade existing text_searchable column inserting project_name
    op.execute(
        """
            UPDATE project_info
            SET text_searchable = to_tsvector('english', coalesce(project_id_str, '') || ' ' ||
            coalesce(name, '') || ' ' || coalesce(short_description, '') || ' ' ||
            coalesce(description, ''))
            """
    )


def downgrade():
    pass
