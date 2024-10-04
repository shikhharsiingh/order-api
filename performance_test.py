import asyncio
import aiohttp
import random
import time
import argparse


BASE_URL = "http://localhost:8000"
NUM_REQUESTS = 1000
DURATION = 1  # 1 second


def parse_arguments():
    parser = argparse.ArgumentParser(description="Performance test for order-api")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0,
        help="Time to sleep between test cases in seconds",
    )
    return parser.parse_args()


async def place_order():
    async with aiohttp.ClientSession() as session:
        data = {
            "quantity": random.randint(1, 100),
            "price": round(random.uniform(0.01, 1000.00), 2),
            "side": random.choice([-1, 1]),
        }
        async with session.post(f"{BASE_URL}/place", json=data) as response:
            return await response.json()


async def cancel_order(order_id):
    async with aiohttp.ClientSession() as session:
        data = {"order_id": order_id}
        async with session.post(f"{BASE_URL}/cancel", json=data) as response:
            return await response.json()


async def modify_order(order_id):
    async with aiohttp.ClientSession() as session:
        data = {
            "order_id": order_id,
            "updated_price": round(random.uniform(0.01, 1000.00), 2),
        }
        async with session.post(f"{BASE_URL}/modify", json=data) as response:
            return await response.json()


async def run_test(sleep_time):
    start_time = time.time()
    tasks = []
    order_ids = []

    for _ in range(NUM_REQUESTS):
        action = random.choice(["place", "cancel", "modify"])
        if action == "place":
            tasks.append(asyncio.create_task(place_order()))
        elif action == "cancel" and order_ids:
            order_id = random.choice(order_ids)
            tasks.append(asyncio.create_task(cancel_order(order_id)))
        elif action == "modify" and order_ids:
            order_id = random.choice(order_ids)
            tasks.append(asyncio.create_task(modify_order(order_id)))

        await asyncio.sleep(sleep_time)  # Add sleep between test cases

    results = await asyncio.gather(*tasks)

    for result in results:
        if "order_id" in result:
            order_ids.append(result["order_id"])

    end_time = time.time()
    elapsed_time = end_time - start_time
    requests_per_second = NUM_REQUESTS / elapsed_time

    print(f"Completed {NUM_REQUESTS} requests in {elapsed_time:.2f} seconds")
    print(f"Requests per second: {requests_per_second:.2f}")


if __name__ == "__main__":
    args = parse_arguments()
    asyncio.run(run_test(args.sleep))
