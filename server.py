# server.py (FastAPI + WebSockets pour l'architecture Spectre)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import uuid
import os

app = FastAPI()

# --- Configuration CORS (Crucial pour le déploiement Cloud) ---
# Ceci autorise les connexions depuis différentes origines web/clients.
origins = [
    "*", # Autoriser toutes les origines pour la flexibilité, à limiter en production
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Stockage des Sessions de Jeu Actives ---
# Clé : Session ID (ex: "NX-1234")
# Valeur : Dictionnaire contenant les WebSockets et l'état
active_sessions = {}
# Structure de active_sessions[session_id] :
# { 
#   "player1": WebSocket (ou None), 
#   "spectre": WebSocket (ou None), 
#   "state": {
#     "player_pos": [0, 0], 
#     "spectre_action": None 
#   }
# }

# --- Endpoint Racine (Test de Santé) ---
@app.get("/")
def read_root():
    """Endpoint simple pour vérifier que le serveur fonctionne."""
    return {"status": "Nexus Protocol Server Running", "sessions_active": len(active_sessions)}

# --- Gestionnaire de Connexion WebSocket ---

@app.websocket("/ws/{session_id}/{client_type}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, client_type: str):
    """
    client_type doit être 'player1' ou 'spectre'.
    """
    
    session_id = session_id.upper()
    
    # 1. Validation de l'ID et du Type
    if client_type not in ["player1", "spectre"]:
        print(f"Connexion rejetée: Type de client invalide '{client_type}'")
        return await websocket.close(code=1008) # Code non valide
        
    # --- Début de la connexion ---
    await websocket.accept()
    
    # 2. Gestion de la nouvelle session (si 'player1' arrive)
    if client_type == 'player1':
        if session_id not in active_sessions:
            active_sessions[session_id] = {
                "player1": websocket, 
                "spectre": None, 
                "state": {"player_pos": [0, 0], "spectre_action": None}
            }
            print(f"Session {session_id} créée par Joueur 1.")
        else:
            # Reconnexion du joueur 1 ou session existante
            active_sessions[session_id]["player1"] = websocket
            print(f"Joueur 1 reconnecté à la session {session_id}")
            
    # 3. Gestion de la connexion du Spectre
    elif client_type == 'spectre':
        if session_id not in active_sessions:
            # La session doit exister si le Spectre veut rejoindre
            await websocket.send_text(json.dumps({"type": "error", "message": "Session ID invalide ou terminée."}))
            return await websocket.close(code=1008)
            
        session = active_sessions[session_id]
        if session["spectre"] is not None:
            await websocket.send_text(json.dumps({"type": "error", "message": "Un Spectre est déjà connecté à cette session."}))
            return await websocket.close(code=1008)
            
        session["spectre"] = websocket
        print(f"Spectre connecté à la session {session_id}")
        
        # Notifie le Joueur 1 que le Spectre est là
        if session["player1"]:
            await session["player1"].send_text(json.dumps({"type": "spectre_status", "status": "connected"}))

    # --- Boucle de réception des messages ---
    try:
        session = active_sessions[session_id]
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Message du Joueur 1 (Mise à jour de l'état)
            if client_type == 'player1':
                # Enregistre la position et l'état pour le Spectre
                session["state"]["player_pos"] = message.get("player_pos", [0, 0])
                
                # Transmet l'état (position) au Spectre s'il est connecté
                if session["spectre"]:
                    await session["spectre"].send_text(json.dumps({
                        "type": "player_state", 
                        "player_pos": session["state"]["player_pos"],
                        "health": message.get("health", 100) # Ex: transmet d'autres infos
                    }))

            # Message du Spectre (Action à transmettre au Joueur 1)
            elif client_type == 'spectre':
                action = message.get("action")
                data_action = message.get("data", {})
                
                # Transmet l'action au Joueur 1
                if session["player1"]:
                    await session["player1"].send_text(json.dumps({
                        "type": "spectre_action", 
                        "action": action, 
                        "data": data_action
                    }))
                    
    # --- Gestion de la déconnexion ---
    except WebSocketDisconnect:
        print(f"Client {client_type} déconnecté de la session {session_id}")
        
        # Tente de récupérer la session avant suppression
        session = active_sessions.get(session_id)
        if session:
            
            if client_type == 'player1':
                # Si J1 se déconnecte, on termine la session et on notifie J2
                print(f"Session {session_id} terminée (Joueur 1 déconnecté).")
                if session["spectre"]:
                    await session["spectre"].send_text(json.dumps({"type": "game_over", "message": "Le joueur principal a quitté la partie."}))
                # Supprime la session
                active_sessions.pop(session_id, None)
                
            elif client_type == 'spectre':
                # Si J2 se déconnecte, on le supprime de la session et on notifie J1
                session["spectre"] = None
                if session["player1"]:
                    await session["player1"].send_text(json.dumps({"type": "spectre_status", "status": "disconnected"}))
    
    except Exception as e:
        print(f"Erreur inattendue dans la session {session_id} ({client_type}): {e}")
        
        # En cas d'erreur critique, on nettoie la session si possible
        if session_id in active_sessions:
            if client_type == 'player1':
                 active_sessions.pop(session_id, None)
            elif client_type == 'spectre':
                if session_id in active_sessions:
                    active_sessions[session_id]["spectre"] = None

# --- Point d'entrée pour le développement local ---
if __name__ == "__main__":
    import uvicorn
    # Le port 8000 est le standard pour les tests FastAPI
    # Utilisez --reload pour redémarrer le serveur à chaque modification
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
