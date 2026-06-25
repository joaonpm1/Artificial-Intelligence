from datetime import datetime

class Pedido:
    def __init__(self, id, origem, destino, n_passageiros,
                 prioridade, hora_pedido, prefere_verde=False):
        self.id = id
        self.origem = origem
        self.destino = destino
        self.n_passageiros = n_passageiros

        # prioridade: 0 = normal, 1 = premium
        self.prioridade = int(prioridade)
        self.is_premium = (self.prioridade == 1)

        self.prefere_verde = prefere_verde

        if isinstance(hora_pedido, str):
            self.hora_pedido = datetime.fromisoformat(hora_pedido)
        else:
            self.hora_pedido = hora_pedido

    def __repr__(self):
        tipo = "premium" if self.is_premium else "normal"
        return f"Pedido({self.id}, {self.origem}->{self.destino}, {tipo})"
