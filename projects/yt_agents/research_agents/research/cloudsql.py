from typing import Any, List, Dict

from asyncpg import Connection
from google.cloud.sql.connector import create_async_connector
from google.auth import default
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine


class CloudSQL:
    def __init__(self):
        self.credentials, self.project = default()

    async def connect(
        self, instanceName: str, userName: str, password: str, dbName: str
    ) -> None:
        try:
            self.connector = await create_async_connector(
                ip_type="PRIVATE", credentials=self.credentials
            )

            async def get_conn() -> Connection:
                conn: Connection = await self.connector.connect_async(
                    instanceName, "asyncpg", user=userName, password=password, db=dbName
                )
                return conn

            self.pool: AsyncEngine = create_async_engine(
                "postgresql+asyncpg://", async_creator=get_conn
            )
            print("CloudSQL connection established")
        except Exception as e:
            print(e)
            raise

    async def ping(self):
        try:
            async with self.pool.connect() as conn:
                await conn.execute(text("SELECT 1"))
                print("CloudSQL Server Pinged Successfully")
                return True
        except Exception as e:
            print(e)
            raise

    async def execute(
        self,
        query: str,
        records: List[Dict[str, Any]] = None,
        is_not_fetch: bool = False,
    ) -> None:
        """
        Execute a query on the Cloud SQL database.

        This method executes the provided SQL query on the Cloud SQL database. Optionally, it can execute the query with a list of records.

        Args:
            query (str): The SQL query to execute.
            records (List[Dict[str, Any]], optional): A list of records to execute the query with. Defaults to None.

        Returns:
            None
        """
        try:
            async with self.pool.connect() as conn:
                result = await conn.execute(text(query), records)
                if is_not_fetch:
                    await conn.commit()
                    return True
                result = result.mappings().all()
                return result
        except Exception as e:
            print(e)
            raise

    async def close(self):
        try:
            await self.connector.close_async()
            await self.pool.dispose()
            print("CloudSQL connection closed")
        except Exception:
            ...