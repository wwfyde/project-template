import asyncio
from statistics import mode

from agents import Agent, Runner
from dotenv import find_dotenv, load_dotenv

_ = load_dotenv(find_dotenv())


agent = Agent(
    name="History Tutor",
    model="gpt-6.1-terra",
    instructions="You answer history questions clearly and concisely.",
)


async def main() -> None:
    result = await Runner.run(agent, "When did the Roman Empire fall?")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
