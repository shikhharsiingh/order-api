from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import redis
import asyncio
import copy
import time
import os

class WebSocketManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify the domain from which you're serving your HTML
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=0, decode_responses=True)

websocket_manager = WebSocketManager()

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

@app.websocket("/ws/order_book")
async def order_book_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            snapshot = get_order_book_snapshot()
            await websocket.send_json({
                "type": "order_book_snapshot",
                "data": snapshot
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("WebSocket disconnected")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket_manager.connect(client_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(client_id)

async def send_trade_update(trade):
    await websocket_manager.broadcast({
        "type": "trade_update",
        "trade": trade
    })

async def send_to_client(order_id, trades):
    await websocket_manager.send_personal_message({
        "order_id": order_id,
        "trades": trades
    }, order_id)


@app.post("/place")
async def place(request: dict):
    try:
        quantity = int(request.get('quantity'))
        price = float(request.get('price'))
        side = int(request.get('side'))
    except (TypeError, ValueError):
        return {"error": "Invalid input"}, 400
    
    if quantity <= 0:
        return {"error": "Invalid quantity"}, 400
    if price <= 0 or (price * 100) % 1 != 0:
        print(price % 1)
        return {"error": "Invalid price"}, 400
    if side not in [1, -1]:
        return {"error": "Invalid side"}, 400

    # Get queue key

    queue_key, priority = get_queuekey_priority(price, side)

    # Add queue to priority zset
    if not redis_client.exists(queue_key):
        redis_client.zadd(str(side), {queue_key: priority}) #priority can be negative
    
    # Order preparation
    timestamp = time.time()
    order_id = str(side) + '_' + str(price) + '_' + str(timestamp)
    order = {
        'order_id': order_id,
        "quantity": quantity,
        "price": price,
        "side": side,
        "average_traded_price": 0,
        "traded_quantity": 0,
        "order_alive": 1,
        "timestamp": timestamp
    }

    #Push to queue
    redis_client.rpush(queue_key, order_id)
    redis_client.rpush("placed", order_id)
    #Add order to set
    redis_client.hset(order_id, mapping=order)

    # Match orders
    matching_engine(order)
    
    return {"order_id": order_id}, 200

def get_queuekey_priority(price, side):
    if side == 1:
        queue_key = f"s{price}"
        priority = price
    elif side == -1:
        queue_key = f"b{price}" #key price is always positive
        priority = -price
    return queue_key,priority

@app.post("/modify")
async def modify(request: dict):
    try:
        order_id = request.get('order_id')
        new_price = float(request.get('updated_price'))

        parts = order_id.split("_")
        side = int(parts[0])
        old_price = float(parts[1])

        # Validation
        if new_price <= 0 or (new_price * 100 % 1) != 0 or side not in [1, -1]:
            return {"error": "Invalid input"}, 400
        
        # Get queue key
        queue_key, _ = get_queuekey_priority(old_price, side)

        # Get order
        order = redis_client.hgetall(order_id)
        
        # Order validation
        if order['order_alive'] == '0':
            return {"error": "Order is no longer active"}, 404

        # Order preparation
        new_order = copy.deepcopy(order)
        new_order['price'] = new_price

        # Modify order
        redis_client.hset(order_id, key="price", value=new_price)

        # Remove key from previous queue
        redis_client.lrem(queue_key, 0, order_id)
        if(redis_client.llen(queue_key) == 0): #if queue is empty, remove queue from zset
            redis_client.zrem(str(side), queue_key)

        # Get new queue key
        queue_key, priority = get_queuekey_priority(new_price, side)
        
        # Add queue to priority zset
        redis_client.zadd(str(side), {queue_key: priority}) #priority can be negative
        redis_client.rpush(queue_key, order_id)

        return {"success": True}, 200
        
    except Exception as e:
        return {"error": str(e)}, 500

@app.post("/cancel")
async def cancel(request: dict):
    order_id = request.get('order_id')

    parts = order_id.split("_")
    side = int(parts[0])
    price = float(parts[1])

    # Get queue key
    queue_key, _ = get_queuekey_priority(price, side)

    # Get order
    order = redis_client.hgetall(order_id)
    
    # Order validation
    if order['order_alive'] == '0':
        return {"error": "Order is no longer active"}, 404

    redis_client.hset(order_id, key="order_alive", value='0')

    # Remove key from previous queue
    redis_client.lrem(queue_key, 1, order_id)
    if(redis_client.llen(queue_key) == 0):  #if queue is empty, remove queue from zset
        redis_client.zrem(str(side), queue_key)

    return {"success": True}, 200

def matching_engine(order):
    trades = []

    if order["side"] == 1:
        queues = redis_client.zrangebyscore("-1", -float('inf'), -order['price']) #Buy queues
    elif order["side"] == -1:
        queues = redis_client.zrangebyscore("1", 0.01, order['price']) #Sell queues
    for queue in queues:
        trades = process_queue(order, queue, order["side"])
        if order['quantity'] == order['traded_quantity']:
            break

    asyncio.create_task(send_to_client(order['order_id'], trades))

def process_queue(order, queue, side):
    trades = []
    while order['quantity'] > order['traded_quantity']:
        opposite_order_id = redis_client.lpop(queue)
        # print("opposite_id:", opposite_order_id)
        if not opposite_order_id:
            break

        # Get Opposite Order
        opposite_order = redis_client.hgetall(opposite_order_id)
        print("opposite_order:", opposite_order)
        # Processing opposite order
        opposite_order['quantity'] = int(opposite_order['quantity'])
        opposite_order['price'] = float(opposite_order['price'])
        opposite_order['side'] = int(opposite_order['side'])
        opposite_order['traded_quantity'] = int(opposite_order['traded_quantity'])
        opposite_order['average_traded_price'] = float(opposite_order['average_traded_price'])

        # Order validation
        if not opposite_order or not opposite_order['order_alive']:
            continue
        
        trade_quantity = min(order['quantity'] - order['traded_quantity'], opposite_order['quantity'] - opposite_order['traded_quantity'])
        trade_price = min(order['price'], opposite_order['price'])
        # Add trade to list
        trade_id = f"trade_{time.time()}"
        trade = {
            "trade_id" : trade_id,
            "buy_order_id": opposite_order['order_id'] if side==-1 else order['order_id'],
            "sell_order_id": order['order_id'] if side==-1 else opposite_order['order_id'],
            "quantity": trade_quantity,
            "price": trade_price
        }

        # Push trade to trades list
        redis_client.rpush("trades", trade_id)
        redis_client.hset(trade_id, mapping=trade)
        
        asyncio.create_task(send_trade_update(trade))
        trades.append(trade)
        post_trade_update_order(opposite_order, trade_quantity, trade_price) # Update opposite order
        post_trade_update_order(order, trade_quantity, trade_price) # Update order

        if opposite_order['quantity'] > opposite_order['traded_quantity']:
            redis_client.lpush(queue, opposite_order['order_id'])

    return trade_quantity, trade_price, trades

def post_trade_update_order(order, trade_quantity, trade_price):
    order['average_traded_price'] = (order['average_traded_price'] * order['traded_quantity'] + trade_quantity *  trade_price) / (trade_quantity + order['traded_quantity'])
    order['traded_quantity'] += trade_quantity
    redis_client.hset(order['order_id'], mapping=order)
    
    # Update queue
    if order['quantity'] == order['traded_quantity']:
        order['order_alive'] = 0
        redis_client.hset(order['order_id'], "order_alive", 0)
        queue, _ = get_queuekey_priority(order['price'], order['side'])
        redis_client.lrem(queue, 1, order['order_id'])
        if redis_client.llen(queue) == 0:
            redis_client.zrem(str(order["side"]), queue)

@app.post("/fetch")
async def fetch(request: dict):
    order_id = request.get('order_id')

    # Get order
    order = redis_client.hgetall(order_id)
    return {
            "order_price" : order["price"],
            "order_quantity" : order["quantity"],
            "average_traded_price" : order["average_traded_price"],
            "traded_quantity" : order["traded_quantity"],
            "order_alive": order["order_alive"]
            }, 200

@app.get("/orders")
async def get_all_orders():
    all_orders = []
    order_ids = redis_client.lrange("placed", 0, -1)
    for order_id in order_ids:
        order = redis_client.hgetall(order_id)
        if order:
            order['order_id'] = order_id
            all_orders.append(order)
    
    return {"orders": all_orders}

@app.get("/trades")
async def get_all_trades():
    all_trades = []
    trade_strings = redis_client.lrange("trades", 0, -1)
    for trade_string in trade_strings:
        trade = redis_client.hgetall(trade_string)
        all_trades.append(trade)
    return {"trades": all_trades}

# Add this new function to get the order book snapshot
def get_order_book_snapshot():
    sides = [-1, 1]
    # Get top 5 bid prices
    top5 = []
    for side in sides:
        side_prices = redis_client.zrevrange(side, 0, 4)
        sideorders = []
        for price in side_prices:
            quantity = sum(float(redis_client.hget(order_id, "quantity")) - float(redis_client.hget(order_id, "traded_quantity")) for order_id in redis_client.lrange(price, 0, -1))
            sideorders.append({"price": float(price[1:]), "quantity": quantity})
        top5.append(sideorders)
    
    print({"bids": top5[0], "asks": top5[1]})
    return {"bids": top5[0], "asks": top5[1]}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
