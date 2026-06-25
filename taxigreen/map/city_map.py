import json
import networkx as nx
from geopy.distance import geodesic
import matplotlib.pyplot as plt
import random



TRAFIC_LEVEL= {
    "low": 1.0,
    "medium": 1.1,
    "high": 1.15
}

WEATHER_LEVEL = {
    "sun": 1.0,     # tempo limpo
    "rain": 1.05,    # chuva → ligeiro aumento de tempo/custo
    "fog": 1.15,     # nevoeiro → mais lento
    "storm": 1.2    # tempestade
}




class CityMap:
    def __init__(self, json_path):
        self.json_path = json_path
        self.graph = nx.Graph()
        self.cached_weather = {}



    @staticmethod
    def dist(coord1, coord2):
        return geodesic(coord1, coord2).kilometers
    
    def get_traffic_multiplier(self, node_id, hora=None):
        """
        Devolve o fator de trânsito para um nó, ajustado à hora do dia.
        """
        base_level = self.graph.nodes[node_id].get("traffic_level", "medium")
        base = TRAFIC_LEVEL.get(base_level, 1.0)

        if hora is None:
            return base

        h = hora.hour

        #   - horas de ponta 7–9 e 17–19 → mais trânsito
        #   - madrugada 0–6 → menos trânsito
        if 7 <= h < 9 or 17 <= h < 19:
            return base * 1.10      # reforça o trânsito
        elif 0 <= h < 6:
            return max(base * 0.9, 1.0) #nunca a baixo de 1.0
        else:
            return base            # base normal
        

    def determinar_condicao_meteo(self, node_id, hora=None):
        """
        Determina a condição meteorológica com probabilidade dependente da estação,
        mas mantém a condição igual para todos os pedidos dentro da mesma hora.
        """
        if hora is None:
            return "sun"

        chave_hora = (node_id, hora.year, hora.month, hora.day, hora.hour)

        # Se já calculámos a condição nesta hora → devolve a mesma
        if chave_hora in self.cached_weather:
            return self.cached_weather[chave_hora]

        # Senão → calcular nova (a lógica que já tens)
        m = hora.month

        if m in (6, 7, 8):        # Verão
            probs = {"sun": 0.70, "rain": 0.20, "fog": 0.10, "storm": 0.00}
        elif m in (12, 1, 2):     # Inverno
            probs = {"sun": 0.20, "rain": 0.60, "fog": 0.15, "storm": 0.05}
        elif m in (3, 4, 5):      # Primavera
            probs = {"sun": 0.50, "rain": 0.35, "fog": 0.15, "storm": 0.00}
        else:                     # Outono
            probs = {"sun": 0.40, "rain": 0.45, "fog": 0.10, "storm": 0.05}

        condicoes = list(probs.keys())
        pesos = list(probs.values())

        cond_meteo = random.choices(condicoes, pesos, k=1)[0]

        # Guardar na cache
        self.cached_weather[chave_hora] = cond_meteo

        return cond_meteo




    def get_weather_multiplier(self, cond_meteo=None):
        """
        Converte a condição meteorológica (sun/rain/fog/storm) num fator numérico.
        """
        if cond_meteo is None:
            return 1.0
        return WEATHER_LEVEL.get(cond_meteo, 1.0)



    def load_city(self, trafico, hora=None):
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # criar nós
        for zone in data:
            self.graph.add_node(
                zone["id"],
                latitude=zone["latitude"],
                longitude=zone["longitude"],
                posicao=(zone["latitude"], zone["longitude"]),
                station=zone.get("station", False),
                traffic_level=zone.get("traffic_level", "medium")
            )

        if trafico:
            for zone in data:
                z1 = zone["id"]
                coord1 = (zone["latitude"], zone["longitude"])

                for z2 in zone["accessible_zones"]:
                    dest = next(z for z in data if z["id"] == z2)
                    coord2 = (dest["latitude"], dest["longitude"])

                    # km físicos
                    d = self.dist(coord1, coord2)

                    # trânsito dependente da zona + hora
                    trafic_multiplier = self.get_traffic_multiplier(z2, hora)

                    # meteorologia específica para o nó de destino z2
                    cond_meteo = self.determinar_condicao_meteo(z2, hora)
                    weather_factor = self.get_weather_multiplier(cond_meteo)

                    # custo final = distância × trânsito × meteo
                    time_cost = d * trafic_multiplier * weather_factor

                    self.graph.add_edge(
                        z1, z2,
                        weight=time_cost,
                        distance=d,
                        traffic_factor=trafic_multiplier,
                        weather_factor=weather_factor,
                        weather=cond_meteo
                    )
        else:
            # sem trânsito/meteos → só distância real
            for zone in data:
                z1 = zone["id"]
                coord1 = (zone["latitude"], zone["longitude"])

                for z2 in zone["accessible_zones"]:
                    dest = next(z for z in data if z["id"] == z2)
                    coord2 = (dest["latitude"], dest["longitude"])

                    d = self.dist(coord1, coord2)

                    self.graph.add_edge(
                        z1, z2,
                        weight=d,
                        distance=d,
                        traffic_factor=1.0,
                        weather_factor=1.0,
                        weather="sun"
                    )

        return self.graph

    
    
    def desenhar_grafo(self):
        plt.figure(figsize=(10, 8))
        

        pos = nx.get_node_attributes(self.graph, 'posicao') 
        nx.draw_networkx_nodes(self.graph, pos, node_size=50, node_color='blue')
      
        station_nodes = [node for node, attr in self.graph.nodes(data=True) if attr.get('station')]
        nx.draw_networkx_nodes(self.graph, pos, nodelist=station_nodes, node_size=100, node_color='green', label='Stations')
        
        nx.draw_networkx_edges(self.graph, pos, alpha=0.5, edge_color='gray')


        nx.draw_networkx_labels(
                    self.graph, 
                    pos, 
                    font_size=8, 
                    font_color='black',
                    font_weight='bold'
                )

        plt.title("Grafo da Cidade - Estrutura de Rotas")
        plt.show()