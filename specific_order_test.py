import asyncio
import aiohttp
import time

BASE_URL = "http://localhost:8000"


async def place_order(quantity, price, side):
    async with aiohttp.ClientSession() as session:
        data = {
            "quantity": quantity,
            "price": price,
            "side": side,
        }
        async with session.post(f"{BASE_URL}/place", json=data) as response:
            return await response.json()


async def run_specific_test():
    orders = [
        {"price": 50.07, "quantity": 97, "side": -1},
        {"price": 450.07, "quantity": 25, "side": -1},
        {"price": 327.45, "quantity": 66, "side": 1},
        {"price": 118.78, "quantity": 32, "side": 1},
        {"price": 91.59, "quantity": 75, "side": 1},
        {"price": 45.22, "quantity": 48, "side": 1},
        {"price": 171.53, "quantity": 53, "side": -1},
        {"price": 866.86, "quantity": 23, "side": 1},
        {"price": 718.76, "quantity": 72, "side": -1},
        {"price": 190.94, "quantity": 73, "side": -1},
        {"price": 781.65, "quantity": 88, "side": 1},
        {"price": 642.21, "quantity": 90, "side": 1},
        {"price": 864.63, "quantity": 10, "side": -1},
        {"price": 628.02, "quantity": 31, "side": -1},
        {"price": 753.49, "quantity": 42, "side": -1},
        {"price": 247.79, "quantity": 19, "side": -1},
        {"price": 293.25, "quantity": 93, "side": 1},
        {"price": 609.16, "quantity": 16, "side": 1},
        {"price": 289.83, "quantity": 75, "side": -1},
        {"price": 995.79, "quantity": 40, "side": 1},
        {"price": 343.36, "quantity": 52, "side": 1},
        {"price": 165.33, "quantity": 9, "side": 1},
        {"price": 91.83, "quantity": 95, "side": -1},
        {"price": 895.04, "quantity": 80, "side": 1},
        {"price": 281.33, "quantity": 18, "side": 1},
        {"price": 27.28, "quantity": 46, "side": 1},
        {"price": 631.49, "quantity": 46, "side": 1},
        {"price": 562.54, "quantity": 78, "side": 1},
        {"price": 203.46, "quantity": 8, "side": 1},
        {"price": 653.15, "quantity": 42, "side": 1},
        {"price": 661.13, "quantity": 36, "side": -1},
        {"price": 593.04, "quantity": 4, "side": 1},
        {"price": 193.98, "quantity": 40, "side": -1},
        {"price": 286.94, "quantity": 97, "side": -1},
        {"price": 747.9, "quantity": 29, "side": -1},
        {"price": 886.55, "quantity": 52, "side": -1},
        {"price": 910.28, "quantity": 75, "side": 1},
        {"price": 833.43, "quantity": 16, "side": 1},
        {"price": 658.28, "quantity": 40, "side": -1},
        {"price": 583.35, "quantity": 2, "side": 1},
        {"price": 13.2, "quantity": 35, "side": 1},
        {"price": 401.59, "quantity": 47, "side": -1},
        {"price": 729.39, "quantity": 21, "side": -1},
        {"price": 100.53, "quantity": 18, "side": -1},
        {"price": 345.21, "quantity": 59, "side": 1},
        {"price": 583.78, "quantity": 53, "side": -1},
        {"price": 493.5, "quantity": 96, "side": -1},
        {"price": 709.35, "quantity": 29, "side": -1},
        {"price": 66.44, "quantity": 56, "side": 1},
        {"price": 177.15, "quantity": 77, "side": -1},
        {"price": 393.2, "quantity": 40, "side": 1},
        {"price": 216.45, "quantity": 87, "side": 1},
        {"price": 107.51, "quantity": 52, "side": 1},
        {"price": 204.5, "quantity": 16, "side": -1},
        {"price": 686.71, "quantity": 85, "side": 1},
        {"price": 521.5, "quantity": 33, "side": -1},
        {"price": 415.28, "quantity": 95, "side": -1},
        {"price": 18.55, "quantity": 37, "side": 1},
        {"price": 41.29, "quantity": 89, "side": -1},
        {"price": 678.7, "quantity": 41, "side": 1},
        {"price": 397.3, "quantity": 83, "side": 1},
        {"price": 55.7, "quantity": 57, "side": 1},
        {"price": 858.49, "quantity": 10, "side": 1},
        {"price": 518.1, "quantity": 73, "side": -1},
        {"price": 167.94, "quantity": 37, "side": -1},
        {"price": 467.57, "quantity": 41, "side": -1},
        {"price": 991.3, "quantity": 1, "side": 1},
        {"price": 819.97, "quantity": 42, "side": -1},
        {"price": 888.69, "quantity": 57, "side": -1},
        {"price": 489.82, "quantity": 65, "side": -1},
        {"price": 491.02, "quantity": 98, "side": 1},
        {"price": 89.53, "quantity": 87, "side": 1},
        {"price": 124.92, "quantity": 55, "side": -1},
        {"price": 962.81, "quantity": 21, "side": -1},
        {"price": 351.69, "quantity": 11, "side": -1},
        {"price": 410.81, "quantity": 20, "side": 1},
        {"price": 996.25, "quantity": 16, "side": -1},
        {"price": 373.54, "quantity": 32, "side": 1},
        {"price": 932.82, "quantity": 6, "side": 1},
        {"price": 44.68, "quantity": 99, "side": -1},
        {"price": 523.86, "quantity": 98, "side": -1},
        {"price": 472.3, "quantity": 8, "side": -1},
        {"price": 306.57, "quantity": 7, "side": 1},
        {"price": 992.35, "quantity": 70, "side": -1},
        {"price": 693.46, "quantity": 34, "side": -1},
        {"price": 755.23, "quantity": 46, "side": -1},
        {"price": 157.88, "quantity": 78, "side": -1},
        {"price": 457.34, "quantity": 72, "side": 1},
        {"price": 971.8, "quantity": 54, "side": -1},
        {"price": 95.96, "quantity": 68, "side": 1},
        {"price": 906.17, "quantity": 96, "side": 1},
        {"price": 701.02, "quantity": 58, "side": -1},
        {"price": 957.2, "quantity": 74, "side": 1},
        {"price": 849.05, "quantity": 96, "side": 1},
        {"price": 373.55, "quantity": 4, "side": 1},
        {"price": 498.91, "quantity": 81, "side": 1},
    ]

    for i, order in enumerate(orders, 1):
        result = await place_order(
            order["quantity"], round(order["price"], 2), order["side"]
        )
        # time.sleep(0.5)
        print(f"Order {i} placed: {result}")


if __name__ == "__main__":
    asyncio.run(run_specific_test())
