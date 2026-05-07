"""Run the court scraper against the live site for the last 7 days."""
import asyncio
from datetime import date, timedelta
from foreclosure_bot.court_scraper import CourtScraper
from foreclosure_bot.config import Settings


async def main():
    s = Settings()
    scraper = CourtScraper(user_agent=s.court_user_agent)
    end = date.today()
    start = end - timedelta(days=7)
    n = 0
    async for case in scraper.discover_cases(start, end, set()):
        print(case)
        n += 1
        if n >= 3:
            break
    print(f"discovered {n} cases")


if __name__ == "__main__":
    asyncio.run(main())
