import asyncio
from backend import place
import fakeredis

# Replace the real Redis client with a fake one
redis_client = fakeredis.FakeStrictRedis()

async def test_matching_engine():
    # Place some sample orders
    order1 = await place({"quantity": 10, "price": 100, "side": -1})
    
    # print('--------------------------------')
    order2 = await place({"quantity": 5, "price": 101, "side": 1})

    order3 = await place({"quantity": 2, "price": 99, "side": -1})

    # Manually trigger the matching engine for each order
    # await matching_engine(order1)
    # await matching_engine(order2)
    # await matching_engine(order3)

    # Check the results
    # print("Order 1:", redis_client.hgetall(order1[0]['order_id']))
    # print("Order 2:", redis_client.hgetall(order2[0]['order_id']))
    # print("Order 3:", redis_client.hgetall(order3[0]['order_id']))

    # Check trades
    # trades = redis_client.lrange("trades", 0, -1)
    # print("Trades:", trades)

if __name__ == "__main__":
    asyncio.run(test_matching_engine())
