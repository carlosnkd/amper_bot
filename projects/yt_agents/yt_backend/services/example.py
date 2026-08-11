import asyncio
from yt_backend.services.bot.summary import Summary


async def run_query(query):
    summaryClass = Summary()
    summary = await summaryClass.generate_summary("", query)
    return summary


if __name__ == "__main__":
    result = asyncio.run(
        run_query("What is the current weather in my location?")
    )
    print(result)