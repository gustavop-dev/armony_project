"""Donde debe quedarse el scroll del hilo: la decision, sin Qt.

Tres modos:
    seguir  -> pegado al final: lo nuevo entra y se ve (estado normal).
    libre   -> subiste a releer: no se mueve de donde lo dejaste.
    anclado -> hay una respuesta que estas leyendo: su borde de arriba se queda
               fijo arriba del panel, crezca lo que crezca, y llegue lo que
               llegue por debajo.

El anclado es lo que arregla que el texto "se corra": antes, cada burbuja nueva
(incluido el texto provisional del entrevistador) empujaba hacia arriba la
respuesta que se estaba leyendo. Ahora lo nuevo cae debajo sin mover nada y
solo se avisa ("nuevo ↓"). Para que la respuesta pueda quedarse arriba aunque
aun sea corta, el contenido se alarga por debajo lo necesario (como ChatGPT,
que sube tu pregunta arriba y deja hueco para la respuesta).

Las coordenadas son las de la barra de scroll de Qt: valor = cuanto se ha
bajado, maximo = cuanto se puede bajar, y = posicion dentro del contenido.
"""

SEGUIR = "seguir"
LIBRE = "libre"
ANCLADO = "anclado"


class FeedAnchor:
    def __init__(self, margen_final=8, margen_ancla=12):
        self.margen_final = margen_final    # tolerancia para "estoy al final"
        self.margen_ancla = margen_ancla    # aire por encima de lo anclado
        self.modo = SEGUIR
        self.objetivo = None                # valor guardado en modo libre
        self.ancla_y = None                 # y de lo anclado, en el contenido
        self.nuevo_abajo = False            # hay algo sin ver por debajo

    # -- cambios de modo ------------------------------------------------------
    def anclar(self):
        """Empieza una respuesta: a partir de ahora manda ella."""
        self.modo = ANCLADO
        self.ancla_y = None                 # se sabra al maquetar
        self.nuevo_abajo = False

    def ubicar(self, y):
        """Posicion actual de lo anclado (cambia si se poda lo de arriba).
        None = ya no existe: se suelta sin mover la vista."""
        if self.modo != ANCLADO:
            return
        if y is None:
            self.modo = LIBRE
            self.ancla_y = None
            return
        self.ancla_y = y

    def anotar(self, valor, maximo):
        """Antes de repintar. Anclado no se toca: estar abajo del todo porque la
        respuesta es corta no significa que quieras seguir el final."""
        if self.modo != ANCLADO:
            self._por_posicion(valor, maximo)

    def movido_a_mano(self, valor, maximo):
        """Rueda, arrastre de la barra o gesto: la persona manda, se suelta."""
        self._por_posicion(valor, maximo)

    def ir_al_final(self):
        self.modo = SEGUIR
        self.ancla_y = None
        self.objetivo = None
        self.nuevo_abajo = False

    def contenido_nuevo(self):
        """Entro algo al hilo. Si no se esta siguiendo el final, queda sin ver."""
        if self.modo != SEGUIR:
            self.nuevo_abajo = True

    def _por_posicion(self, valor, maximo):
        self.ancla_y = None
        if valor >= maximo - self.margen_final:
            self.modo = SEGUIR
            self.nuevo_abajo = False
        else:
            self.modo = LIBRE
        self.objetivo = valor

    # -- lo que hay que aplicar ------------------------------------------------
    def _valor_ancla(self):
        return max(0, self.ancla_y - self.margen_ancla)

    def alto_minimo(self, alto_visible):
        """Alto que debe tener el contenido para poder dejar lo anclado arriba."""
        if self.modo == ANCLADO and self.ancla_y is not None:
            return self._valor_ancla() + alto_visible
        return 0

    def valor(self, maximo):
        """Donde debe quedar la barra de scroll."""
        if self.modo == ANCLADO:
            if self.ancla_y is None:
                return maximo               # aun sin maquetar: como siempre
            return min(self._valor_ancla(), maximo)
        if self.modo == LIBRE and self.objetivo is not None:
            return min(self.objetivo, maximo)
        return maximo
