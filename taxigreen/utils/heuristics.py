from geopy.distance import geodesic

def heuristic(graph, node, goal):
    node_coords = (graph.nodes[node]['latitude'], graph.nodes[node]['longitude'])
    goal_coords = (graph.nodes[goal]['latitude'], graph.nodes[goal]['longitude'])
    return geodesic(node_coords, goal_coords).kilometers
