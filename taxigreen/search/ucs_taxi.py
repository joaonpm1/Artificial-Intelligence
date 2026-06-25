import heapq

class UCSTaxi:
    def __init__(self, graph):
        self.graph = graph

    def search(self, start, goal):
        if start not in self.graph or goal not in self.graph:
            return None, float("inf"), 0

        pq = [(0.0, start)]
        came_from = {}
        best_cost = {start: 0.0}
        expanded = 0

        while pq:
            cost, current = heapq.heappop(pq)

            if cost > best_cost.get(current, float("inf")):
                continue

            expanded += 1

            if current == goal:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path, cost, expanded

            for neighbor in self.graph.neighbors(current):
                edge_cost = self.graph[current][neighbor].get("weight", 1.0)
                new_cost = cost + edge_cost

                if new_cost < best_cost.get(neighbor, float("inf")):
                    best_cost[neighbor] = new_cost
                    came_from[neighbor] = current
                    heapq.heappush(pq, (new_cost, neighbor))

        return None, float("inf"), expanded
