from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url")

with create_engine(url).connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
