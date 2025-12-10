from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import uuid

# --- CONSTANTES --- #
ERROR_INVALID_CLIENT_TYPE = "Type de client invalide."
ERROR_INVALID_SESSION = "Session ID invalide ou terminée."
ERROR_SPECTRE_ALREADY_CONNECTED = "Un Spectre est déjà connecté à cette session."

# --- CONFIGURATION --- #
app = FastAPI()

# --- Configuration CORS --- #
origins = ["*"]  # Autorise toutes les origines (À restreindre en production)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Stockage des Sessions --- #
active_sessions = {}

# --- Point d'entrée pour vérifier la santé du serveur --- #
@app.get("/")
def read_root():
    """Vérification de la santé du serveur et des sessions actives."""
    return {"status": "Nexus Protocol Server Running", "sessions_active": len(active_sessions)}

# --- GESTION DES WEBSOCKETS --- #

async def handle_player1_connection(websocket: WebSocket, session_id: str):
    """Gère la connexion du Joueur 1 et crée la session si nécessaire."""
    if session_id not in active_sessions:
        active_sessions[session_id] = {
            "player1": websocket,
            "spectre": None,
            "state": {"player_pos": [0, 0], "spectre_action": None}
        }
        print(f"Session {session_id} créée par Joueur 1.")
    else:
        active_sessions[session_id]["player1"] = websocket
        print(f"Joueur 1 reconnecté à la session {session_id}")

async def handle_spectre_connection(websocket: WebSocket, session_id: str):
    """Gère la connexion du Spectre à une session existante."""
    session = active_sessions.get(session_id)
    if session is None:
        await websocket.send_text(json.dumps({"type": "error", "message": ERROR_INVALID_SESSION}))
        return await websocket.close(code=1008)

    if session["spectre"] is not None:
        await websocket.send_text(json.dumps({"type": "error", "message": ERROR_SPECTRE_ALREADY_CONNECTED}))
        return await websocket.close(code=1008)

    session["spectre"] = websocket
    print(f"Spectre connecté à la session {session_id}")

    # Notifie le Joueur 1 que le Spectre est connecté
    if session["player1"]:
        await session["player1"].send_text(json.dumps({"type": "spectre_status", "status": "connected"}))

async def handle_client_messages(websocket: WebSocket, session_id: str, client_type: str):
    """Boucle pour la réception et l'envoi des messages entre clients et serveur."""
    session = active_sessions[session_id]
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if client_type == 'player1':
                # Met à jour la position du joueur et envoie au Spectre
                session["state"]["player_pos"] = message.get("player_pos", [0, 0])
                if session["spectre"]:
                    await session["spectre"].send_text(json.dumps({
                        "type": "player_state", 
                        "player_pos": session["state"]["player_pos"],
                        "health": message.get("health", 100)
                    }))
            elif client_type == 'spectre':
                # Envoie l'action du Spectre au Joueur 1
                action = message.get("action")
                data_action = message.get("data", {})
                if session["player1"]:
                    await session["player1"].send_text(json.dumps({
                        "type": "spectre_action", 
                        "action": action, 
                        "data": data_action
                    }))
    except WebSocketDisconnect:
        print(f"Client {client_type} déconnecté de la session {session_id}")
        if client_type == 'player1':
            await handle_player1_disconnection(session_id)
        elif client_type == 'spectre':
            await handle_spectre_disconnection(session_id)

async def handle_player1_disconnection(session_id: str):
    """Gère la déconnexion de Joueur 1."""
    session = active_sessions.pop(session_id, None)
    if session and session["spectre"]:
        await session["spectre"].send_text(json.dumps({"type": "game_over", "message": "Le joueur principal a quitté la partie."}))

async def handle_spectre_disconnection(session_id: str):
    """Gère la déconnexion du Spectre."""
    session = active_sessions.get(session_id)
    if session:
        session["spectre"] = None
        if session["player1"]:
            await session["player1"].send_text(json.dumps({"type": "spectre_status", "status": "disconnected"}))

@app.websocket("/ws/{session_id}/{client_type}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, client_type: str):
    """Endpoint principal pour la gestion des connexions WebSocket."""
    session_id = session_id.upper()

    # Validation du type de client
    if client_type not in ["player1", "spectre"]:
        print(f"Connexion rejetée: Type de client invalide '{client_type}'")
        return await websocket.close(code=1008)  # Code non valide

    # Accepte la connexion WebSocket
    await websocket.accept()

    if client_type == 'player1':
        await handle_player1_connection(websocket, session_id)
    elif client_type == 'spectre':
        await handle_spectre_connection(websocket, session_id)

    # Gère les messages du client
    await handle_client_messages(websocket, session_id, client_type)

# --- Démarrage du serveur (local uniquement) --- #
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
