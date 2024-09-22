import redis
import asyncio
import time
import os

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))
r = redis.StrictRedis(host=redis_host, port=redis_port, db=0, decode_responses=True)

def matching_engine():
    pub = r.pubsub()
    pub.subscribe('match_updates')

    for message in pub.listen():
        if message['type'] == 'message':
            process_order()

def process_order():
    order_id = r.lpop("matching_queue")
    order = r.hgetall(order_id)
    order["price"] = float(order["price"])
    order["quantity"] = int(order["quantity"])
    order["side"] = int(order["side"])
    order['traded_quantity'] = int(order['traded_quantity'])
    queues = get_matching_queues(order['side'], order['price'])
    # print(queues)
    if queues:
        process_queues(order, queues)

def get_matching_queues(side, price):
    if side == 1:
        return r.zrangebyscore("-1", -float('inf'), -price)
    elif side == -1:
        return r.zrangebyscore("1", 0.01, price)
    return []

def process_queues(order, queues):
    for queue in queues:
        process_queue(order, queue, order["side"])
        if order['quantity'] == order['traded_quantity']:
            break

def process_queue(order, queue, side):
    total_traded_quantity = 0
    while order['quantity'] > total_traded_quantity:
        opposite_order_id = r.lpop(queue)
        # print("opposite_id:", opposite_order_id)
        if not opposite_order_id:
            break

        # Get Opposite Order
        opposite_order = r.hgetall(opposite_order_id)

        # Processing opposite order
        opposite_order['quantity'] = int(opposite_order['quantity'])
        opposite_order['price'] = float(opposite_order['price'])
        opposite_order['traded_quantity'] = int(opposite_order['traded_quantity'])

        # Order validation
        if not opposite_order or not opposite_order['order_alive']:
            continue
        
        trade_quantity = min(order['quantity'] - order['traded_quantity'], opposite_order['quantity'] - opposite_order['traded_quantity'])
        trade_price = min(order['price'], opposite_order['price'])
        total_traded_quantity += trade_quantity

        # Push trade to trades list
        # Start transaction
        with r.pipeline() as pipe:
            # Create trade
            trade_number = r.get("trade_number")
            pipe.multi()
            trade_id = f"trade_{trade_number}"
            trade = {
                "trade_id" : trade_id,
                "buy_order_id": order['order_id'] if side == 1 else opposite_order['order_id'],
                "sell_order_id": order['order_id'] if side == -1 else opposite_order['order_id'],
                "quantity": trade_quantity,
                "price": trade_price,
                "time" : time.time()
            }
            pipe.incr("trade_number")
            pipe.rpush("trades", trade_id)
            pipe.hset(trade_id, mapping=trade)

            update_order(opposite_order, trade_quantity, trade_price)
            update_order(order, trade_quantity, trade_price)

            if opposite_order['quantity'] > total_traded_quantity:
                pipe.lpush(queue, opposite_order['order_id'])
            pipe.execute() # Execute transaction

        r.publish("trade_updates", trade_id) # Publish trade update
        print("trade_update:", trade_id)

def get_queuekey_priority(price: float, side : int):
    # print("price", price)
    # print("side", side)
    if side == 1:
        queue_key = f"s{price}"
        priority = price
    elif side == -1:
        queue_key = f"b{price}" #key price is always positive
        priority = -price
    return queue_key, priority

def update_order(order, trade_quantity, trade_price):
    order['traded_quantity'] = int(order['traded_quantity'])
    order['average_traded_price'] = float(order['average_traded_price'])
    order['quantity'] = int(order['quantity'])
    order['price'] = float(order['price'])

    order['average_traded_price'] = (order['average_traded_price'] * order['traded_quantity'] + trade_quantity *  trade_price) / (trade_quantity + order['traded_quantity'])
    order['traded_quantity'] += trade_quantity

    with r.pipeline() as pipe:
        pipe.multi()
        pipe.hset(order['order_id'], "traded_quantity", order['traded_quantity'])
        pipe.hset(order['order_id'], "average_traded_price", order['average_traded_price'])
        # Update queue
        if order['quantity'] == order['traded_quantity']:
            order['order_alive'] = 0
            pipe.hset(order['order_id'], "order_alive", 0)
            queue, _ = get_queuekey_priority(float(order['price']), int(order['side']))
            pipe.lrem(queue, 0, order['order_id'])
        pipe.execute()
if __name__ == "__main__":
    matching_engine()