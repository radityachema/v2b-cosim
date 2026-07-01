class NetworkClass:
    def __init__(self, nodes, arcs, building_nodes, depot):
        self.nodes = nodes
        self.arcs = arcs
        self.building_nodes = building_nodes
        self.depot = depot

    def get_arc(self, i, j):
        return self.arcs[(i, j)]

    def get_building_nodes(self):
        return list(self.building_nodes)
