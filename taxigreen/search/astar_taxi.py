import heapq
from utils.heuristics import heuristic

class AStarTaxi:
    def __init__(self, graph):
        self.graph = graph

    def search(self, start, goal):
        if start not in self.graph or goal not in self.graph:
            return None, float("inf"), 0

        open_set = []
        heapq.heappush(open_set, (0.0, start))
        came_from = {}

        g_score = {n: float("inf") for n in self.graph.nodes}
        f_score = {n: float("inf") for n in self.graph.nodes}

        g_score[start] = 0.0
        f_score[start] = heuristic(self.graph, start, goal)

        expanded = 0

        while open_set:
            _, current = heapq.heappop(open_set)
            expanded += 1

            if current == goal:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()

                cost = 0.0
                for i in range(len(path) - 1):
                    cost += self.graph[path[i]][path[i + 1]]["weight"]

                return path, cost, expanded

            for neighbor in self.graph.neighbors(current):
                edge_cost = self.graph[current][neighbor].get("weight", 1.0)
                tentative_g = g_score[current] + edge_cost

                if tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + heuristic(self.graph, neighbor, goal)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return None, float("inf"), expanded
