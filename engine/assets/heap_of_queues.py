import heapq
from collections import deque
from decimal import Decimal, ROUND_HALF_UP
import numpy as np


def to_decimal(value):
    return Decimal(value).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


class HeapOfQueues:
    def __init__(self):
        self.heap = []
        self.queues = {}

    def push_to_priority(self, priority, item, direction="right"):
        if priority == 0:
            raise ValueError("priority cannot be equal to 0.")
        # priority = np.round(priority, 2)
        if priority not in self.queues:
            self.queues[np.round(priority, 2)] = deque()
            heapq.heappush(self.heap, priority)

        if direction == "left":
            self.queues[priority].appendleft(item)
        else:
            self.queues[priority].append(item)

    def pop_from_priority(self, priority, direction="left"):
        # priority = np.round(priority, 2)
        # print(self.queues[priority])
        if priority not in self.queues.keys() or not self.queues[priority]:
            return None

        item = (
            self.queues[priority].popleft()
            if direction == "left"
            else self.queues[priority].pop()
        )
        if not self.queues[priority]:
            del self.queues[priority]
            self.heap.remove(priority)
            heapq.heapify(self.heap)
        return item

    def pop_from_top(self):
        if not self.heap:
            raise IndexError("pop from an empty heap of queues")

        while self.heap:
            priority = heapq.heappop(self.heap)
            if priority in self.queues and self.queues[priority]:
                item = self.queues[priority].popleft()
                if self.queues[priority]:
                    heapq.heappush(self.heap, priority)
                else:
                    del self.queues[priority]
                return priority, item
            else:
                del self.queues[priority]

        raise IndexError("All queues are empty")

    def remove_item_from_priority(self, priority, item):
        """Remove a specific item from the queue of a given priority. If the queue becomes empty, delete it."""
        if priority not in self.queues:
            raise ValueError(f"No queue found for priority {priority}")
        # priority = np.round(priority, 2)
        try:
            self.queues[priority].remove(item)
        except ValueError:
            raise ValueError(
                f"Item {item} not found in the queue for priority {priority}"
            )

        # If the queue is empty after removing the item, delete the queue and remove priority from the heap
        if not self.queues[priority]:
            del self.queues[priority]
            self.heap.remove(priority)
            heapq.heapify(self.heap)
        return f"Item {item} removed from queue with priority {priority}"

    def get_queues_until_priority(self, max_priority):
        """Get all queues with priorities less than or equal to max_priority."""
        result = []
        for priority in self.heap:
            if priority <= max_priority:
                result.append(priority)
            else:
                break
        return result

    def print_heap(self):
        """Print the complete heap."""
        print("Complete Heap:")
        for priority in self.heap:
            print(f"priority: {priority}, Queue: {self.queues[priority]}")

    def get_top_k_priorities(self, k):
        """Return the top k priorities from the heap."""
        return heapq.nsmallest(k, self.heap)

    def get_elements_from_priority(self, priority):
        """Return all elements in the queue for a given priority without popping them."""
        if priority not in self.queues:
            return []
        return list(self.queues[priority])


if __name__ == "__main__":
    # Example Usage
    hq = HeapOfQueues()

    hq.push_to_priority(1, "task1")
    hq.push_to_priority(3, "task2")
    hq.push_to_priority(2, "task3")

    hq.push_to_priority(1, "task4", direction="right")
    hq.push_to_priority(1, "task5", direction="left")

    try:
        hq.push_to_priority(0, "invalid_task")
    except ValueError as e:
        print(e)

    print(hq.pop_from_top())  # (1, 'task5')
    print(hq.pop_from_priority(1, direction="right"))  # (1, 'task4')
    print(hq.pop_from_top())  # (2, 'task3')
    print(hq.pop_from_top())  # (3, 'task2')

    # Removing specific items
    hq.push_to_priority(1, "task6")
    hq.push_to_priority(1, "task7")

    print(hq.remove_item_from_priority(1, "task6"))  # Remove 'task6' from priority 1
    print(
        hq.remove_item_from_priority(1, "task7")
    )  # Remove 'task7' from priority 1, which should delete the queue

    # New function usage examples
    hq.push_to_priority(1, "task8")
    hq.push_to_priority(2, "task9")
    hq.push_to_priority(3, "task10")
    hq.push_to_priority(4, "task11")

    print(hq.get_top_k_priorities(3))  # [1, 2, 3]
    print(hq.get_elements_from_priority(2))  # ['task9']
