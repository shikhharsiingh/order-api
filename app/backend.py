import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
import redis
from redis.exceptions import WatchError
import asyncio
import copy
from datetime import datetime
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
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))
r = redis.StrictRedis(host=redis_host, port=redis_port, db=0, decode_responses=True)

websocket_manager = WebSocketManager()

@app.on_event("startup")
def startup_function():
    r.flushall()
    r.set("order_number", 0)
    r.set("trade_number", 0)

@app.get("/")
async def read_index():
    # asyncio.create_task(post_trade_update())
    return FileResponse('static/index.html')

@app.websocket("/ws/order_book")
async def order_book_websocket(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connected")
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

async def send_message(websocket: WebSocket, trade):
    await websocket.send_json({
        "type": "trade_update",
        "trade": trade
    })
    print("sent trade update")

def handle_trade_updates(websocket: WebSocket):
    pubsub = r.pubsub()
    pubsub.subscribe("trade_updates")
    print("subscribed to trade_updates")
    
    async def listen():
        for message in pubsub.listen():
            if message['type'] == 'message':
                trade = r.hgetall(message['data'])
                
                await send_message(websocket, trade)

    # Run the listening task in the event loop
    asyncio.run(listen())

@app.websocket("/ws/trade_updates")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Run the handle_trade_updates in a background thread
    await run_in_threadpool(handle_trade_updates, websocket)

def get_queuekey_priority(price: float, side : int):
    if side == 1:
        queue_key = f"s{price}"
        priority = price
    elif side == -1:
        queue_key = f"b{price}" #key price is always positive
        priority = -price
    return queue_key, priority

@app.post("/place")
async def place(request: dict):
    try:
        quantity = int(request.get('quantity'))
    except (TypeError, ValueError):
        return {"error": "Invalid input for quantity"}, 400

    try:
        price = float(request.get('price'))
    except (TypeError, ValueError):
        return {"error": "Invalid input for price"}, 400

    try:
        side = int(request.get('side'))
    except (TypeError, ValueError):
        return {"error": "Invalid input for side"}, 400
    
    if quantity <= 0:
        return {"error": "Invalid quantity"}, 400
    if price <= 0 or (price * 100) % 1 != 0:
        return {"error": "Invalid price"}, 400
    if side not in [1, -1]:
        return {"error": "Invalid side"}, 400

    # Get queue key
    queue_key, priority = get_queuekey_priority(price, side)
    # print("here")
    while True:
        try:
            # Start pipeline
            with r.pipeline() as pipe:
                pipe.watch('push_lock', 'order_number') #Start watching
                order_id = pipe.get('order_number')
                if side == 1:
                    order_id = 's-order-' + order_id
                else:
                    order_id = 'b-order-' + order_id
                # print(order_id)
                pipe.multi() # Start buffering
                pipe.set('push_lock', '1') # Set lock
                
                now = datetime.now()
                # Order preparation
                order = {
                    'order_id': order_id,
                    "quantity": quantity,
                    "price": price,
                    "side": side,
                    "average_traded_price": 0,
                    "traded_quantity": 0,
                    "order_alive": 1,
                    "timestamp": now.strftime("%d/%m/%Y %H:%M:%S") + f":{now.microsecond // 1000:03}"
                }

                pipe.incr('order_number')

                # Add order to hash
                pipe.hset(order_id, mapping=order)

                # Push to respective price queue
                pipe.rpush("orders_queue", order_id) #This queue is an append only queue that contains all the orders placed in history

                # Add queue to priority zset
                if not r.exists(queue_key):
                    # print("executed")
                    pipe.zadd(str(side), {queue_key: priority}) #priority can be negative

                pipe.rpush(queue_key, order_id) #This is the queue key for the price level

                # Push to matching queue
                pipe.rpush("matching_queue", order_id)  #This is the queue that contains all the orders that are ready to be matched
                
                pipe.set('push_lock', '0') # Release lock
                pipe.execute() # Execute the transaction
                # print(r.lindex("matching_queue", 0))
            # Notify updates
            r.publish('match_updates', "new_match_order")
            print("Transaction successful, message published.")
            break

        except WatchError:
            print("Transaction failed, retrying...")
            break
    
    return {"order_id": order_id}, 200

@app.post("/modify")
async def modify(request: dict):
    try:
        order_id = request.get('order_id')
        new_price = float(request.get('updated_price'))

        # Validation
        if new_price <= 0 or (new_price * 100 % 1) != 0:
            return {"error": "Invalid price"}, 400
        
        # Get order
        order = r.hgetall(order_id)

        #Get relevant data
        side = int(order['side'])
        old_price = float(order['price'])

        # Get queue key
        queue_key, _ = get_queuekey_priority(old_price, side)

        # Order validation
        if order['order_alive'] == '0':
            return {"error": "Order is no longer active"}, 404

        # Order preparation
        new_order = copy.deepcopy(order)
        new_order['price'] = new_price

        # Start transaction
        while True:
            try:
                with r.pipeline() as pipe:
                    pipe.watch('push_lock') # If order if alread matched, it cannot be modified
                    pipe.multi() 
                    pipe.set('push_lock', '1')
                    # Set new price
                    pipe.hset(order_id, key="price", value=new_price)

                    # Remove key from previous queue
                    pipe.lrem(queue_key, 0, order_id)
                    if(pipe.llen(queue_key) == 0): #if queue is empty, remove queue from zset
                        pipe.zrem(str(side), queue_key)

                    # Get new queue key
                    queue_key, priority = get_queuekey_priority(new_price, side)
                    
                    # Add queue to priority zset
                    pipe.zadd(str(side), {queue_key: priority}) #priority can be negative
                    pipe.rpush(queue_key, order_id)

                    pipe.set('push_lock', '0')
                    pipe.execute() # Execute transaction
                break
            except WatchError:
                print("Transaction failed, retrying...")
                continue

        return {"success": True}, 200
        
    except Exception as e:
        return {"error": str(e)}, 500

@app.post("/cancel")
async def cancel(request: dict):
    order_id = request.get('order_id')
    
    # Get order
    order = r.hgetall(order_id)

    #Get relevant data
    side = int(order['side'])
    price = float(order['price'])

    # Get queue key
    queue_key, _ = get_queuekey_priority(price, side)

    # Order validation
    if order['order_alive'] == '0':
        return {"error": "Order is no longer active"}, 404

    with r.pipeline() as pipe:
        # pipe.watch(order_id) # If the order is matched, cannot cancel it
        pipe.multi() # Start transaction

        pipe.hset(order_id, key="order_alive", value='0')

        # Remove key from previous queue
        pipe.lrem(queue_key, 1, order_id)
        if(pipe.llen(queue_key) == 0):  #if queue is empty, remove queue from zset
            pipe.zrem(str(side), queue_key)
            
        pipe.execute() # Execute transaction

    return {"success": True}, 200

@app.post("/fetch")
async def fetch(request: dict):
    order_id = request.get('order_id')

    # Get order
    order = r.hgetall(order_id)
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
    order_ids = r.lrange("orders_queue", 0, -1)
    for order_id in order_ids:
        order = r.hgetall(order_id)
        if order:
            order['order_id'] = order_id
            all_orders.append(order)
    
    return {"orders": all_orders}

@app.get("/trades")
async def get_all_trades():
    all_trades = []
    trade_strings = r.lrange("trades", 0, -1)
    for trade_string in trade_strings:
        trade = r.hgetall(trade_string)
        all_trades.append(trade)
    return {"trades": all_trades}

# Add this new function to get the order book snapshot
def get_order_book_snapshot():
    sides = [-1, 1]
    # Get top 5 bid prices
    top5 = []
    for side in sides:
        side_prices = r.zrevrange(side, 0, 4)
        sideorders = []
        for price in side_prices:
            quantity = sum(float(r.hget(order_id, "quantity")) - float(r.hget(order_id, "traded_quantity")) for order_id in r.lrange(price, 0, -1))
            if quantity == 0:
                continue                        
            sideorders.append({"price": float(price[1:]), "quantity": quantity})
        top5.append(sideorders)
    
    return {"bids": top5[0], "asks": top5[1]}

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)
