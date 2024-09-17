# order-api

This is an implementation of an order book with a simple UI and WebSocket-based real-time updates.

## Features

- FastAPI backend with WebSocket support
- Redis-based order book implementation
- Real-time order book updates
- Order placement, modification, and cancellation
- Trade matching engine
- WebSocket-based client communication

## API Endpoints

- `POST /place`: Place a new order
- `POST /modify`: Modify an existing order
- `POST /cancel`: Cancel an existing order
- `POST /fetch`: Fetch details of a specific order
- `GET /orders`: Get all orders
- `GET /trades`: Get all trades

## WebSocket Endpoints

- `/ws/order_book`: Real-time order book updates
- `/ws/{client_id}`: Client-specific WebSocket connection

## Setup

1. Install dependencies (FastAPI, Redis, etc.)
2. Set up a Redis server
3. Configure Redis connection in the environment variables:
   - `REDIS_HOST` (default: "localhost")
   - `REDIS_PORT` (default: 6379)

## Running the Application

python backend.py  
The server will start on `http://0.0.0.0:8000`.

## Frontend

A simple HTML/JavaScript frontend is provided in the `static` directory.

## Note

This project is a basic implementation and may require additional security measures and optimizations for production use.
