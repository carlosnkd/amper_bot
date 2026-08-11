from crewai_tools import SerperDevTool

from backend import db

search_tool = SerperDevTool()

from crewai.tools import tool
from sqlalchemy import text
from yt_backend.db import SessionLocal

@tool
def query_database(sql_query: str) -> str:
    """
    Execute a SQL query against the database and return results.
    Input should be a valid SQL query string.
    Returns results as a list of dictionaries, or an error message.
    """
    print("SessionLocal is:", SessionLocal)
    print("Type of SessionLocal:", type(SessionLocal))

    db = SessionLocal()
    print("Type of db:", type(db))

    # db = SessionLocal()
    try:
        result = db.execute(text(sql_query))
        columns = result.keys()
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        if not rows:
            return "Query returned no results."
        return str(rows)
    except Exception as e:
        return f"Query failed with error: {str(e)}"
    finally:
        db.close()


@tool
def get_schema_info() -> str:
    """
    Get full database schema: table names, column names, and data types.
    Use this before writing any SQL query to understand the database structure.

    **Example of what `get_schema_info` now returns:**
            Table: calls
            - id (INTEGER)
            - agent_id (INTEGER)
            - duration_seconds (INTEGER)
            - created_at (DATETIME)
    """
    db = SessionLocal()
    try:
        tables = db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table';")
        ).fetchall()

        schema_parts = []
        for (table_name,) in tables:
            columns = db.execute(
                text(f"PRAGMA table_info({table_name});")
            ).fetchall()
            col_info = "\n".join(
                f"  - {col[1]} ({col[2]})" for col in columns
            )
            schema_parts.append(f"Table: {table_name}\n{col_info}")

        return "\n\n".join(schema_parts)
    except Exception as e:
        return f"Schema fetch failed: {str(e)}"
    finally:
        db.close()
