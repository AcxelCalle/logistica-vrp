import streamlit as st
import folium
from streamlit_folium import st_folium
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import osmnx as ox
import networkx as nx
import math

# Configuración de la página en modo ancho
st.set_page_config(page_title="Simulador de Ruta B2B", layout="wide")

# --- 1. CARGA DEL GRAFO VIAL EN MEMORIA CACHÉ ---
@st.cache_resource
def cargar_grafo():
    # Se ejecuta una sola vez al arrancar para no ralentizar la aplicación
    return ox.load_graphml("lima_centro.graphml")

G = cargar_grafo()

# --- 2. MEMORIA DE LA APLICACIÓN ---
if "puntos_visita" not in st.session_state:
    st.session_state.puntos_visita = []

# Depósito fijo: Centro de Lima (Plaza de Armas)
DEPOT_COORD = (-12.046374, -77.029980)

# --- 3. FUNCIONES MATEMÁTICAS Y DE BÚSQUEDA ---
def calcular_distancia(p1, p2):
    # Distancia Euclidiana simple escalada para el rango de OR-Tools
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2) * 100000 

def encontrar_nodo_cercano(grafo, lat_objetivo, lon_objetivo):
    # Algoritmo ligero para ubicar la intersección vial más cercana en el grafo
    nodo_cercano = None
    distancia_minima = float('inf')
    for nodo, datos in grafo.nodes(data=True):
        distancia = (datos['y'] - lat_objetivo)**2 + (datos['x'] - lon_objetivo)**2
        if distancia < distancia_minima:
            distancia_minima = distancia
            nodo_cercano = nodo
    return nodo_cercano

# --- 4. MOTOR DE OPTIMIZACIÓN (OR-TOOLS) ---
def resolver_vrp(nodos):
    matriz = []
    for i in range(len(nodos)):
        fila = []
        for j in range(len(nodos)):
            fila.append(int(calcular_distancia(nodos[i], nodos[j])))
        matriz.append(fila)

    data = {
        "distance_matrix": matriz,
        "num_vehicles": 1, 
        "depot": 0
    }

    manager = pywrapcp.RoutingIndexManager(len(data["distance_matrix"]), data["num_vehicles"], data["depot"])
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data["distance_matrix"][from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    solution = routing.SolveWithParameters(search_parameters)
    
    ruta_optima = []
    if solution:
        index = routing.Start(0)
        while not routing.IsEnd(index):
            ruta_optima.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        ruta_optima.append(manager.IndexToNode(index))
    return ruta_optima

# --- 5. PROCESAMIENTO PREVIO A LA UI ---
# Si ya se seleccionaron los 5 puntos, calculamos la secuencia antes de pintar las columnas
orden_optimo = None
todos_los_nodos = []
if len(st.session_state.puntos_visita) == 5:
    todos_los_nodos = [DEPOT_COORD] + st.session_state.puntos_visita
    orden_optimo = resolver_vrp(todos_los_nodos)

# --- 6. INTERFAZ DE USUARIO ---
st.title("Panel de Optimización Logística B2B")
st.markdown("1. Haz clic en el mapa para agregar hasta 5 puntos de entrega.\n2. El depósito central (rojo) está fijo.\n3. Al llegar a 5 puntos, la IA calculará la ruta óptima siguiendo las calles.")

col1, col2 = st.columns([2, 1])

with col1:
    # Preparar el mapa base
    mapa = folium.Map(location=DEPOT_COORD, zoom_start=13, tiles='CartoDB positron')
    
    # Dibujar depósito
    folium.Marker(DEPOT_COORD, tooltip="Depósito Central", icon=folium.Icon(color="red", icon="home")).add_to(mapa)

    # Dibujar puntos seleccionados
    for idx, punto in enumerate(st.session_state.puntos_visita):
        folium.Marker(punto, tooltip=f"Entrega {idx+1}", icon=folium.Icon(color="blue", icon="info-sign")).add_to(mapa)

    # Trazar las calles si la ruta ya fue optimizada
    if orden_optimo:
        ruta_ordenada = [todos_los_nodos[i] for i in orden_optimo]
        
        # Iterar por cada tramo del circuito
        for i in range(len(ruta_ordenada) - 1):
            punto_origen = ruta_ordenada[i]
            punto_destino = ruta_ordenada[i+1]
            
            nodo_o = encontrar_nodo_cercano(G, punto_origen[0], punto_origen[1])
            nodo_d = encontrar_nodo_cercano(G, punto_destino[0], punto_destino[1])
            
            try:
                # Enrutamiento con Dijkstra sobre el grafo de calles de Lima
                camino_calle = nx.shortest_path(G, nodo_o, nodo_d, weight='length')
                coords_calle = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in camino_calle]
                
                # Dibujar tramo adaptado a las avenidas
                folium.PolyLine(coords_calle, color="green", weight=4, opacity=0.8).add_to(mapa)
                
            except nx.NetworkXNoPath:
                # Línea de contingencia si hay tramos aislados en el mapa estático
                folium.PolyLine([punto_origen, punto_destino], color="red", dash_array="5, 5", weight=2).add_to(mapa)

    # Renderizar mapa interactivo
    salida_mapa = st_folium(mapa, width=800, height=500, return_on_hover=False)

    # Capturar clics (si hay menos de 5 puntos)
    if len(st.session_state.puntos_visita) < 5 and salida_mapa.get("last_clicked"):
        lat = salida_mapa["last_clicked"]["lat"]
        lon = salida_mapa["last_clicked"]["lng"]
        nuevo_punto = (lat, lon)
        
        if nuevo_punto not in st.session_state.puntos_visita:
            st.session_state.puntos_visita.append(nuevo_punto)
            st.rerun() 

with col2:
    st.subheader("Estado de la Flota")
    st.write(f"Puntos seleccionados: {len(st.session_state.puntos_visita)} / 5")
    
    if orden_optimo:
        st.success("¡Ruta optimizada generada!")
        st.write("Secuencia de visita sugerida:")
        for paso, indice_nodo in enumerate(orden_optimo[1:-1]):
            st.write(f"**{paso + 1}.** Entrega {indice_nodo}")
            
    if st.button("Limpiar Mapa", type="primary"):
        st.session_state.puntos_visita = []
        st.rerun()