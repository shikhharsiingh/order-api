import os
import asyncio
from datetime import datetime
import uuid
from assets.heap_of_queues import HeapOfQueues
from functools import lru_cache
import redis.asyncio as aioredis
import json
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))

# Initialize the Redis client
r = aioredis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)

# Initialize the matching queues
order_book = {1: HeapOfQueues(), -1: HeapOfQueues()}  # Buy side  # Sell side


async def init_consumer_group():
    try:
        await asyncio.gather(
            r.xgroup_create("match_orders", "match_group", id="0", mkstream=True),
            r.xgroup_create("cancel_orders", "cancel_group", id="0", mkstream=True),
            r.xgroup_create("modify_orders", "modify_group", id="0", mkstream=True),
        )
        logger.info("Consumer groups created.")
    except aioredis.ResponseError as e:
        if str(e).startswith("NOGROUP"):
            logger.info("Consumer group already exists.")
        else:
            logger.error(f"Error creating consumer group: {e}")


async def recover_order_book():
    """Recover the order book from Redis if required"""
    # Add logic to recreate the heap of queues from Redis, if necessary
    pass


@app.on_event("startup")
async def startup_event():
    await r.flushall()
    pubsub = r.pubsub()
    await pubsub.subscribe("startup")

    async def listen_for_startup_complete():
        try:
            async with asyncio.timeout(30):  # 30 seconds timeout
                async for message in pubsub.listen():
                    if (
                        message["type"] == "message"
                        and message["data"] == "startup_complete"
                    ):
                        return True
        except asyncio.TimeoutError:
            logger.warning("Startup listener timed out after 30 seconds")
            return False

    if await listen_for_startup_complete():
        await init_consumer_group()
        asyncio.create_task(read_modify_requests())
        asyncio.create_task(read_delete_requests())
        asyncio.create_task(matching_engine())
        asyncio.create_task(get_order_book_snapshot())
        logger.info("Startup complete and all tasks are initialized.")


async def read_modify_requests():
    while True:
        try:
            response = await r.xreadgroup(
                "modify_group", "consumer_1", {"modify_orders": ">"}, count=100
            )
            if response:

                for _, orders in response:
                    await process_modify_orders(orders)
        except Exception as e:
            logger.error(f"Error in read_modify_requests: {e}")
        await asyncio.sleep(0.01)


async def process_modify_orders(orders):
    async with r.pipeline(transaction=True) as pipe:
        for message_id, order_data in orders:
            side, old_price, new_price = await r.hmget(
                order_data["order_id"], ["side", "price", "new_price"]
            )
            side, old_price, new_price = int(side), float(old_price), float(new_price)
            order_book[side].remove_item_from_priority(old_price)
            order_book[side].push_to_priority(new_price, order_data["order_id"])
            pipe.xack("modify_orders", "modify_group", message_id)
        await pipe.execute()


async def read_delete_requests():
    while True:
        try:
            response = await r.xreadgroup(
                "cancel_group", "consumer_1", {"cancel_orders": ">"}, count=100
            )
            if response:

                for _, orders in response:
                    await process_delete_orders(orders)
        except Exception as e:
            logger.error(f"Error in read_delete_requests: {e}")
        await asyncio.sleep(0.01)


async def process_delete_orders(orders):
    async with r.pipeline(transaction=True) as pipe:
        for message_id, order_data in orders:
            price, side = await r.hmget(order_data["order_id"], ["price", "side"])
            price, side = float(price), int(side)
            order_book[side].remove_item_from_priority(price)
            pipe.xack("cancel_orders", "cancel_group", message_id)
        await pipe.execute()


async def matching_engine():
    while True:

        response = await r.xreadgroup(
            "match_group", "consumer_1", {"match_orders": ">"}, count=100
        )
        if response:

            for _, orders in response:
                for message_id, order_data in orders:
                    order = json.loads(order_data["order"])
                    await process_order(order)
                    await r.xack("match_orders", "match_group", message_id)

        await asyncio.sleep(0.01)


def get_average_traded_price(pq_pair):
    trade_value = sum(price * quantity for price, quantity in pq_pair)
    total_quantity = sum(quantity for _, quantity in pq_pair)
    return round(trade_value / total_quantity, 2) if total_quantity else 0


async def update_order(
    pipe, order_id, order_alive, average_traded_price, traded_quantity
):
    await pipe.hmset(
        order_id,
        {
            "order_alive": str(order_alive),
            "average_traded_price": str(average_traded_price),
            "traded_quantity": str(traded_quantity),
        },
    )


async def execute_transaction(order, average_traded_price, remaining_quantity, trades):
    async with r.pipeline(transaction=True) as pipe:
        # Update order
        total_traded_quantity = order["quantity"] - remaining_quantity
        await update_order(
            pipe,
            order["order_id"],
            int(total_traded_quantity < order["quantity"]),
            average_traded_price,
            total_traded_quantity,
        )
        timestamp = datetime.now().isoformat()
        trade_updates = [
            {
                "order_id": order["order_id"],
                "trade_quantity": total_traded_quantity,
                "average_traded_price": average_traded_price,
                "timestamp": timestamp,
            }
        ]
        trade_ids = []
        for price, queue_trades in trades.items():
            for id, (quant, avg_price, alive) in queue_trades.items():
                # Update opposite orders
                await update_order(
                    pipe,
                    order_id=id,
                    order_alive=alive,
                    average_traded_price=avg_price,
                    traded_quantity=quant,
                )

                # Create trade
                trade_id = str(uuid.uuid4())
                await pipe.hset(
                    trade_id,
                    mapping={
                        "trade_id": trade_id,
                        "buy_id": order["order_id"] if order["side"] == -1 else id,
                        "sell_id": order["order_id"] if order["side"] == 1 else id,
                        "price": str(price),
                        "quantity": str(quant),
                        "timestamp": timestamp,
                    },
                )
                trade_ids.append(trade_id)
                trade_updates.append(
                    {
                        "order_id": id,
                        "trade_quantity": quant,
                        "average_traded_price": avg_price,
                        "timestamp": timestamp,
                    }
                )
        await pipe.lpush("trades", *trade_ids)
        await pipe.publish(
            "trade_updates", json.dumps(trade_updates)
        )  # Send notification
        await pipe.execute()  # Execute transaction


async def process_order(order):
    # Get opposite queue info
    opp_side = -order["side"]
    opp_priority = opp_side * order["price"]
    priorities = order_book[opp_side].get_queues_until_priority(opp_priority)

    pq_pair = [(order["price"], order["traded_quantity"])]
    trades = {}
    remaining_quantity = order["quantity"] - order["traded_quantity"]
    if len(priorities) != 0:
        for priority in priorities:
            queue_price = min(order["price"], priority * opp_side)  # fair comparison
            queue_quantity, queue_trades = await process_priority_queue(
                remaining_quantity, priority, opp_side
            )
            pq_pair.append((queue_price, queue_quantity))
            trades[queue_price] = queue_trades
            remaining_quantity -= queue_quantity
            if remaining_quantity == 0:
                break
        average_traded_price = get_average_traded_price(pq_pair)
        asyncio.create_task(
            execute_transaction(order, average_traded_price, remaining_quantity, trades)
        )
        if remaining_quantity != 0:
            order_book[order["side"]].push_to_priority(
                priority=order["price"] * order["side"], item=order["order_id"]
            )
    else:
        order_book[order["side"]].push_to_priority(
            priority=order["price"] * order["side"], item=order["order_id"]
        )


async def process_priority_queue(remaining_quantity, priority, opp_side):
    print("priority:", priority)
    total_traded_quantity = 0
    queue_trades = {}
    while total_traded_quantity < remaining_quantity:

        # Get the order_id of the next opposite order to process
        opposite_order_id = order_book[opp_side].pop_from_priority(priority=priority)
        if not opposite_order_id:  # If the queue was empty, stop
            break

        # Unpack opposite order details and convert to relevant types
        opp_quantity, opp_traded_quantity, opp_avg_price, opp_alive = await r.hmget(
            opposite_order_id,
            ["quantity", "traded_quantity", "average_traded_price", "order_alive"],
        )
        opp_quantity, opp_traded_quantity, opp_alive = map(
            int, (opp_quantity, opp_traded_quantity, opp_alive)
        )
        opp_avg_price = float(opp_avg_price)
        print(opp_quantity, opp_traded_quantity, opp_avg_price, opp_alive)
        # If the order is already cancelled, stop, cannot match
        if not opp_alive:
            continue

        # Match
        trade_quantity = min(remaining_quantity, opp_quantity - opp_traded_quantity)
        total_traded_quantity += trade_quantity
        print(trade_quantity, total_traded_quantity, total_traded_quantity)

        # Calculate opposite order's new data
        new_opp_traded_quantity = opp_traded_quantity + trade_quantity
        new_opp_avg_price = round(
            (opp_avg_price * opp_traded_quantity + priority * opp_side * trade_quantity)
            / new_opp_traded_quantity,
            2,
        )

        is_alive = opp_quantity != new_opp_traded_quantity
        if is_alive:
            order_book[opp_side].push_to_priority(
                priority=priority, direction="left", item=opposite_order_id
            )

        queue_trades[opposite_order_id] = (
            new_opp_traded_quantity,
            new_opp_avg_price,
            int(is_alive),
        )
        print(queue_trades)

    return total_traded_quantity, queue_trades


async def create_order_book_snapshot():
    snapshot = {"bids": [], "asks": []}

    for side, book_key in zip([-1, 1], ["bids", "asks"]):
        for price in order_book[side].get_top_k_priorities(5):
            # Get all order IDs for the current price
            order_ids = order_book[side].get_elements_from_priority(price)

            # Use a Redis pipeline to fetch quantities for all order IDs at once
            pipeline = r.pipeline()
            for order_id in order_ids:
                pipeline.hmget(order_id, ["quantity", "traded_quantity"])

            # Execute the pipeline and gather results
            quantities = await pipeline.execute()

            # Calculate total quantity for the current price
            quantity = sum(
                int(q[0]) - int(q[1])
                for q in quantities
                if q[0] is not None and q[1] is not None
            )

            if quantity > 0:
                snapshot[book_key].append(
                    {"price": abs(float(price * side)), "quantity": quantity}
                )

    return snapshot


async def get_order_book_snapshot():
    while True:
        # try:
        snapshot = await create_order_book_snapshot()  # Call the function directly
        await r.publish("order_book_snapshot", json.dumps(snapshot))
        # except Exception as e:
        # logger.error(f"Error in get_order_book_snapshot: {e}")
        await asyncio.sleep(1)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
