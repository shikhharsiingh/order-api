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
import json
import numpy as np


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
r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)

websocket_manager = WebSocketManager()


@app.on_event("startup")
def startup_function():
    # r.flushall()
    r.set("order_number", "1")
    r.publish("startup", "startup_complete")


@app.get("/")
async def read_index():
    # asyncio.create_task(post_trade_update())
    return FileResponse("static/index.html")


@app.websocket("/ws/order_book")
async def order_book_websocket(websocket: WebSocket):
    await websocket.accept()

    await run_in_threadpool(handle_order_book_update, websocket)


def handle_order_book_update(websocket: WebSocket):
    print("WebSocket connected")
    pubsub = r.pubsub()
    pubsub.subscribe("order_book_snapshot")

    async def listen():
        try:
            for message in pubsub.listen():
                if message["type"] == "message":
                    # print(message["data"])
                    # Assuming message['data'] is already in JSON format
                    await websocket.send_json(
                        {
                            "type": "order_book_snapshot",
                            "data": json.loads(message["data"]),
                        }
                    )
                    # print("here")
        except Exception as e:
            print(f"Error while listening to pubsub: {e}")

    # Create and manage the listening task
    try:
        listen_task = listen()  # Keep the loop running
        asyncio.run(listen_task)

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    finally:
        # Cleanup tasks
        listen_task.cancel()  # Cancel the listening task
        pubsub.unsubscribe("order_book_snapshot")  # Unsubscribe when done
        print("Unsubscribed from pubsub and cleaned up resources.")


def handle_trade_updates(websocket: WebSocket):
    pubsub = r.pubsub()
    pubsub.subscribe("trade_updates")
    print("subscribed to trade_updates")

    async def listen():
        for message in pubsub.listen():
            if message["type"] == "message":

                await websocket.send_json(
                    {"type": "trade_update", "trades": json.loads(message["data"])}
                )

    # Run the listening task in the event loop
    asyncio.run(listen())


@app.websocket("/ws/trade_updates")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Run the handle_trade_updates in a background thread
    await run_in_threadpool(handle_trade_updates, websocket)


@app.post("/place")
async def place(request: dict):
    try:
        quantity = int(request.get("quantity"))
    except (TypeError, ValueError):
        return {"error": "Invalid input for quantity"}, 400

    try:
        price = float(request.get("price"))
        # price = np.round(price, 2)
        # print(price, price % 0.01)
    except (TypeError, ValueError):
        return {"error": "Invalid input for price"}, 400

    try:
        side = int(request.get("side"))
    except (TypeError, ValueError):
        return {"error": "Invalid input for side"}, 400

    if quantity <= 0:
        return {"error": "Invalid quantity"}, 400
    if price <= 0 or (price % 0.01) < 1e-15:
        print()
        return {"error": "Invalid price"}, 400
    if side not in [1, -1]:
        return {"error": "Invalid side"}, 400

    while True:
        try:
            # Start pipeline
            order_id = r.get("order_number")
            with r.pipeline() as pipe:
                pipe.incr("order_number")
                order_id = side * int(order_id)  # If positive, order is sell , else buy

                # Order preparation
                order = {
                    "order_id": str(order_id),
                    "price": price,
                    "quantity": quantity,
                    "side": side,
                    "average_traded_price": 0,
                    "traded_quantity": 0,
                    "order_alive": 1,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                }

                # Heavy Command 1
                pipe.hset(str(order_id), mapping=order)

                # Heavy command 2
                pipe.xadd(
                    "match_orders", {"order": json.dumps(order)}, "*"
                )  # Publish to orders queue
                pipe.rpush("orders_queue", order_id)
                pipe.execute()  # Execute the transaction
            print("Transaction successful, message published.")
            break

        except WatchError:
            print("Transaction failed, retrying...")
            break

    return {"order_id": order_id}, 200


@app.post("/modify")
async def modify(request: dict):
    try:
        order_id = request.get("order_id")
        new_price = float(request.get("updated_price"))

        # Validation
        if new_price <= 0 or (new_price * 100 % 1) != 0:
            return {"error": "Invalid price"}, 400

        # Order validation
        if r.hget(order_id, "order_alive") == "0":
            return {"error": "Order is no longer active"}, 404

        old_price = r.hget(order_id, "price")

        # Start transaction
        while True:
            try:
                with r.pipeline() as pipe:
                    pipe.watch(order_id)
                    pipe.hset(
                        order_id,
                        mapping={
                            "price": str(new_price),
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    )
                    pipe.xadd(
                        "modify_orders",
                        {
                            "id": order_id,
                            "old_price": old_price,
                            "new_price": str(new_price),
                        },
                    )
                    pipe.execute()  # Execute transaction
                break
            except WatchError:
                print("Transaction failed, retrying...")
                continue

        return {"success": True}, 200

    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/cancel")
async def cancel(request: dict):
    order_id = request.get("order_id")

    # Order validation
    if r.hget(order_id, "order_alive") == "0":
        return {"error": "Order is no longer active"}, 404

    with r.pipeline() as pipe:
        pipe.watch(order_id)  # If the order is matched, cannot cancel it
        # Start transaction
        pipe.hset(order_id, key="order_alive", value="0")
        pipe.xadd("cancel_orders", {"order_id": order_id})
        pipe.execute()  # Execute transaction

    return {"success": True}, 200


@app.post("/fetch")
async def fetch(request: dict):
    order_id = request.get("order_id")

    # Get order
    order = r.hgetall(order_id)
    return {
        "order_price": order["price"],
        "order_quantity": order["quantity"],
        "average_traded_price": order["average_traded_price"],
        "traded_quantity": order["traded_quantity"],
        "order_alive": order["order_alive"],
    }, 200


@app.get("/orders")
async def get_all_orders():
    all_orders = []
    order_ids = r.lrange("orders_queue", 0, -1)
    for order_id in order_ids:
        order = r.hgetall(order_id)
        if order:
            order["order_id"] = order_id
            all_orders.append(order)

    return {"orders": all_orders}


@app.get("/trades")
async def get_all_trades():
    trades = []
    response = r.lrange("trades", 0, -1)
    if response:
        with r.pipeline() as pipe:
            for trade_id in response:
                pipe.hgetall(trade_id)
            trades = pipe.execute()
    return {"trades": json.dumps(trades)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
