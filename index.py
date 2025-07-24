import asyncio
import json
import os
import time
import sys
import pathlib
import re
from typing import Dict, Any, Optional, Tuple, List, Set

from colorama import Fore, Style, init

init(autoreset=True)
script_directory = pathlib.Path(__file__).parent.resolve()
version = "1.0 HoyuFS re-coded"

def log(message): print(f"{Fore.CYAN}[LOG] {message}")
def debug(message): print(f"{Fore.WHITE}[DEBUG] {message}")
def warn(message): print(f"{Fore.YELLOW}[WARN] {message}")
def error(message): print(f"{Fore.RED}[ERROR] {message}")
def green(message): print(f"{Fore.GREEN}{Style.BRIGHT}{message}")
def bold(message): print(f"{Style.BRIGHT}{message}")

PACKET_TERMINATOR = b'\x1C'
MAX_BUFFER_SIZE = 16384
MAX_CHAT_MESSAGES = 100
CHAT_SPAM_DELAY = 2.0
SEND_TIMEOUT = 1.0
SHUTDOWN_TIMEOUT = 5.0
BANNED_IPS_FILE = os.path.join(script_directory, "banned_ips.json")
PLAYER_REAP_DELAY = 3.0

class Event:
    def __init__(self): self._callbacks = []
    def connect(self, callback): self._callbacks.append(callback)
    async def invoke(self, *args, **kwargs):
        tasks = [cb(*args, **kwargs) for cb in self._callbacks if asyncio.iscoroutinefunction(cb)]
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)

class ServerState:
    def __init__(self):
        self.players: Dict[str, Dict[str, Any]] = {}
        self.player_positions: Dict[str, List[Any]] = {}
        self.player_last_recv_time: Dict[str, float] = {}
        self.chat_messages: List[Dict[str, str]] = []
        self.last_msg_timestamps: Dict[str, float] = {}
        self.last_msg_contents: Dict[str, str] = {}
        self.disconnecting_players: Set[str] = set()
        self.PlaneTypes = ["C-400", "HC-400", "MC-400", "RL-42", "RL-72", "E-42", "XV-40", "PV-40", "InPerson", "4x4", "APC", "FuelTruck", "8x8", "Flatbed", "None"]
        self._default_state_template = {"Eng1":True, "Eng2":True, "Eng3":True, "Eng4":True, "GearDown":True, "SigL":True, "MainL":False, "VTOLAngle":0, "PV40Color":"0,0,0", "LiveryId":-1}
        self.banned_ips: Dict[str, str] = self._load_json_file(BANNED_IPS_FILE, {})

    def _load_json_file(self, file_path: str, default: Any) -> Any:
        if not os.path.exists(file_path):
            self._save_json_file(file_path, default); log(f"Created default file: {os.path.basename(file_path)}"); return default
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            warn(f"Could not load {file_path}: {e}. Starting with default."); return default
            
    def _save_json_file(self, file_path: str, data: Any):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
        except IOError as e: error(f"Could not save to {file_path}: {e}")

    def ban_ip(self, ip_address: str, reason: str):
        self.banned_ips[ip_address] = reason
        self._save_json_file(BANNED_IPS_FILE, self.banned_ips)
        log(f"IP address '{ip_address}' has been banned. Reason: {reason}")

    def unban_ip(self, ip_address: str) -> bool:
        if ip_address in self.banned_ips:
            del self.banned_ips[ip_address]
            self._save_json_file(BANNED_IPS_FILE, self.banned_ips)
            log(f"IP address '{ip_address}' has been unbanned."); return True
        return False

    def is_ip_banned(self, ip_address: str) -> Optional[str]: return self.banned_ips.get(ip_address)
    
    def add_chat_message(self, author: str, message: str):
        new_message = {"sender": author, "message": message}
        self.chat_messages.append(new_message)
        if len(self.chat_messages) > MAX_CHAT_MESSAGES: self.chat_messages.pop(0)

    def get_default_state(self) -> Dict[str, Any]: return self._default_state_template.copy()
    def add_player(self, username: str, writer: asyncio.StreamWriter, api_player: 'APIPlayer', addr: Tuple[str, int], plane_type: str):
        self.players[username] = {"writer": writer, "api_player": api_player, "address": addr}
        self.player_positions[username] = ["0,2000,0", plane_type, "0,0,0", self.get_default_state()]
        self.player_last_recv_time[username] = time.perf_counter(); self.disconnecting_players.discard(username)
    def remove_player_fully(self, username: str):
        self.players.pop(username, None); self.player_positions.pop(username, None)
        self.player_last_recv_time.pop(username, None); self.last_msg_timestamps.pop(username, None)
        self.last_msg_contents.pop(username, None); self.disconnecting_players.discard(username)
        log(f"Fully reaped player data for {username}.")
    def get_api_player(self, username: str) -> Optional['APIPlayer']:
        player_data = self.players.get(username)
        return player_data.get("api_player") if player_data else None
    def get_player_by_ip(self, ip_address: str) -> List['APIPlayer']:
        return [p_data["api_player"] for p_data in self.players.values() if p_data.get("address") and p_data["address"][0] == ip_address]
    def get_all_player_names(self) -> List[str]: return list(self.players.keys())
    def update_player_position(self, username: str, data: dict):
        ownBlock = data.get("PositionService")
        if not (ownBlock and isinstance(ownBlock, dict) and "Position" in ownBlock and "PlaneType" in ownBlock): return
        if not self._validate_vector3(ownBlock["Position"]) or not self._validate_plane_type(ownBlock["PlaneType"]): return
        player_data = self.player_positions.get(username)
        if not player_data: return
        old_position, old_rotation, persistent_state = player_data[0], player_data[2], player_data[3]
        old_recv_time = self.player_last_recv_time.get(username, time.perf_counter())
        incoming_state_update = ownBlock.get("State", {});
        if isinstance(incoming_state_update, dict):
            for key, value in incoming_state_update.items():
                if key in persistent_state and type(value) is type(persistent_state.get(key)):
                    if isinstance(value, str) and len(value) > 100: continue
                    persistent_state[key] = value
        new_rotation_str = ownBlock.get("Rotation", old_rotation)
        if not self._validate_vector3(new_rotation_str): new_rotation_str = old_rotation
        current_time = time.perf_counter(); self.player_last_recv_time[username] = current_time
        self.player_positions[username] = [ownBlock["Position"], ownBlock["PlaneType"], new_rotation_str, persistent_state, old_position, old_rotation, old_recv_time, current_time]
    def validate_chat_message(self, author: str, message: str) -> Tuple[bool, str]:
        if author not in self.last_msg_timestamps: self.last_msg_timestamps[author] = 0
        if author not in self.last_msg_contents: self.last_msg_contents[author] = ""
        if time.time() - self.last_msg_timestamps.get(author, 0) < CHAT_SPAM_DELAY: return False, "Bạn đang gửi tin nhắn quá nhanh!"
        if message.strip().lower() == self.last_msg_contents.get(author, "").strip().lower(): return False, "Không lặp lại tin nhắn giống nhau!"
        self.last_msg_timestamps[author] = time.time(); self.last_msg_contents[author] = message
        return True, ""
    def get_chat_string(self, count=40) -> str:
        formatted_lines = [f"[{msg['sender']}] {msg['message']}" for msg in self.chat_messages[-count:]]
        return "\n".join(formatted_lines)
    def _validate_vector3(self, v3: str) -> bool: return bool(re.match(r'^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$', str(v3)))
    def _validate_plane_type(self, pt: str) -> bool: return pt in self.PlaneTypes
    @staticmethod
    def validate_username(u: str) -> bool: return bool(re.match(r'^[a-zA-Z0-9_]{3,20}$', str(u)))

class APIPlayer:
    def __init__(self, username: str, writer: asyncio.StreamWriter, server_instance: 'Server'):
        self.Username = username; self._writer = writer; self._server = server_instance
    def IsConnected(self) -> bool: return not self._writer.is_closing()
    async def Kick(self, message="Bạn đã bị kick."):
        kick_message = {"Message": "Connection validated", "!!VoscriptPluginData": [f"PopupWindow(Đã ngắt kết nối khỏi máy chủ: {message},Đóng)"]}
        if not self._writer.is_closing():
            await self._server.send_data_unprotected(self._writer, kick_message); self._writer.close()

class TFSMPAPI:
    def __init__(self, server_instance: 'Server'):
        self._server = server_instance; self.PlayerConnected = Event(); self.PlayerDisconnected = Event(); self.DataReceived = Event()
    @property
    def PlayerData(self) -> Dict[str, List[Any]]: return self._server.state.player_positions
    @property
    def Players(self) -> Dict[str, Dict[str, Any]]: return self._server.state.players
    def GetAPIPlayer(self, username: str) -> Optional[APIPlayer]: return self._server.state.get_api_player(username)

class PluginManager:
    def __init__(self, api_instance: TFSMPAPI): self.api = api_instance
    async def LoadAllPlugins(self):
        totalPlugins, successPlugins = 0, 0
        pluginsFolder = os.path.join(script_directory, "ServersidePlugins")
        if not os.path.exists(pluginsFolder): os.makedirs(pluginsFolder)
        plugin_list = [d for d in os.listdir(pluginsFolder) if os.path.isdir(os.path.join(pluginsFolder, d)) and not d.startswith("!_")]
        if not plugin_list: debug("No plugins found to load."); return
        for pluginFolder in plugin_list:
            debug(f"Loading plugin {pluginFolder}..."); totalPlugins += 1
            mainscript = os.path.join(pluginsFolder, pluginFolder, "main.py")
            if not os.path.exists(mainscript): error(f"Failed to load plugin {pluginFolder}: No main.py."); continue
            try:
                with open(mainscript, "r", encoding='utf-8') as pf: plugincontent = pf.read()
                globals_dict = {"PrimaryAPI": self.api, "FilePath": os.path.join(pluginsFolder, pluginFolder)}
                await asyncio.to_thread(exec, plugincontent, globals_dict); successPlugins += 1
            except Exception as e: error(f"Failed to execute plugin {pluginFolder}: {e}")
        green(f"{successPlugins}/{totalPlugins} plugins loaded successfully.")

class Server:
    def __init__(self, config: Dict[str, Any]):
        self.config = config; self.host = config.get("hostAddress", "0.0.0.0"); self.port = config.get("hostPort", 12345)
        self.update_interval = config.get("updateInterval", 0.05); self.state = ServerState()
        self.api = TFSMPAPI(self); self.plugin_manager = PluginManager(self.api)
        self._tcp_server: Optional[asyncio.Server] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._reaper_task: Optional[asyncio.Task] = None

    async def start(self):
        bold(f"TFS Multiplayer Server v{version}\n"); debug("Setting up serverside plugins...")
        await self.plugin_manager.LoadAllPlugins()
        self._tcp_server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self._reaper_task = asyncio.create_task(self._reap_disconnected_players_loop())
        self._polling_task = asyncio.create_task(self._data_polling_loop())
        green(f"TCP Server configured on {self.host}:{self.port}")
        await self._tcp_server.serve_forever()

    async def shutdown(self):
        log("Shutting down server gracefully...")
        if self._tcp_server and self._tcp_server.is_serving():
            self._tcp_server.close(); await self._tcp_server.wait_closed(); log("TCP server closed.")
        tasks_to_cancel = [t for t in [self._polling_task, self._reaper_task] if t and not t.done()]
        for task in tasks_to_cancel: task.cancel()
        if tasks_to_cancel:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks_to_cancel, return_exceptions=True), timeout=SHUTDOWN_TIMEOUT)
                log("Background tasks cancelled.")
            except asyncio.TimeoutError: warn(f"Timed out waiting for tasks to cancel.")
        kick_tasks = [p["api_player"].Kick("Server is shutting down.") for p in self.state.players.values()]
        if kick_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*kick_tasks, return_exceptions=True), timeout=SHUTDOWN_TIMEOUT)
                log(f"Kicked {len(kick_tasks)} players.")
            except asyncio.TimeoutError: warn(f"Timed out trying to kick players.")
        log("Graceful shutdown complete.")

    async def send_data_unprotected(self, writer: asyncio.StreamWriter, data_dict: dict):
        if writer.is_closing(): return
        try: message = json.dumps(data_dict).encode('utf-8') + PACKET_TERMINATOR; writer.write(message); await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError): pass

    async def send_data(self, username: str, writer: asyncio.StreamWriter, data_dict: dict):
        if writer.is_closing(): return
        try:
            message = json.dumps(data_dict).encode('utf-8') + PACKET_TERMINATOR
            writer.write(message); await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            warn(f"Network error for {username} ({type(e).__name__}). Scheduling cleanup."); asyncio.create_task(self._force_cleanup_player(username))
        except Exception as e: error(f"Unexpected error in send_data for {username}: {e}")

    async def _force_cleanup_player(self, username: str):
        player_data = self.state.players.get(username)
        if player_data:
            warn(f"Force cleaning up unresponsive player: {username}")
            writer, api_player = player_data['writer'], player_data['api_player']
            await self._cleanup_client(username, writer, api_player)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername'); log(f"Incoming connection from {addr[0]}")
        username = None; api_player = None
        try:
            username, api_player = await self._authenticate_client(reader, writer, addr)
            await self._client_loop(username, reader, writer)
        except (ConnectionResetError, asyncio.IncompleteReadError, BrokenPipeError, ConnectionAbortedError, asyncio.TimeoutError, json.JSONDecodeError, OSError) as e:
            error_source = f"{username or addr[0]}"
            if isinstance(e, ConnectionAbortedError): warn(f"Connection from {error_source} aborted.")
            else: log(f"Connection with {error_source} lost: {type(e).__name__}")
        finally: await self._cleanup_client(username, writer, api_player)
    
    async def _authenticate_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, addr: Tuple[str, int]) -> Tuple[str, APIPlayer]:
        try: first_packet = await asyncio.wait_for(reader.readuntil(PACKET_TERMINATOR), timeout=10.0)
        except asyncio.TimeoutError: raise ConnectionAbortedError("Client did not send initial data in time.")
        
        first_data = json.loads(first_packet.rstrip(PACKET_TERMINATOR))
        username, plane_type = first_data.get("Username"), first_data.get("PlaneType"); ip_address = addr[0]

        ip_ban_reason = self.state.is_ip_banned(ip_address)
        if ip_ban_reason:
            kick_message = f"Địa chỉ IP của bạn đã bị cấm. Lý do: {ip_ban_reason}"
            await self.send_data_unprotected(writer, {"!!VoscriptPluginData":[f"PopupWindow({kick_message},Đóng)"]})
            raise ConnectionAbortedError(f"Banned IP '{ip_address}' tried to connect. Reason: {ip_ban_reason}")
        
        if not username or not self.state.validate_username(username):
            await self.send_data_unprotected(writer, {"!!VoscriptPluginData":["PopupWindow(Ngắt kết nối: Tên người dùng không hợp lệ.,Đóng)"]}); raise ConnectionAbortedError("Invalid username")
        if username in self.state.players:
            await self.send_data_unprotected(writer, {"!!VoscriptPluginData":["PopupWindow(Ngắt kết nối: Tên người dùng này đã có người chơi.,Đóng)"]}); raise ConnectionAbortedError("Username already online")
        if not plane_type or not self.state._validate_plane_type(plane_type): raise ConnectionAbortedError("Invalid plane type")
        
        api_player = APIPlayer(username, writer, self); self.state.add_player(username, writer, api_player, addr, plane_type)
        log(f"Connection from {addr[0]} accepted as {username}")
        welcome_msg = {"Message": "Connection validated", "!!VoscriptPluginData": ["PopupWindow(Chào mừng đến với server!,Đóng)"]}
        await self.send_data_unprotected(writer, welcome_msg)
        asyncio.create_task(self.api.PlayerConnected.invoke(api_player)); return username, api_player
    
    async def _client_loop(self, username: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        buffer = b""
        while not writer.is_closing():
            if username in self.state.disconnecting_players: break
            data = await asyncio.wait_for(reader.read(4096), timeout=60.0)
            if not data: break
            buffer += data
            if len(buffer) > MAX_BUFFER_SIZE: raise ConnectionAbortedError("Buffer size limit exceeded.")
            while PACKET_TERMINATOR in buffer:
                packet, buffer = buffer.split(PACKET_TERMINATOR, 1); await self._process_incoming_packet(username, packet)
    
    async def _cleanup_client(self, username: Optional[str], writer: asyncio.StreamWriter, api_player: Optional[APIPlayer]):
        if username and username in self.state.players and username not in self.state.disconnecting_players:
            log(f"Player {username} disconnected. Scheduling for reaping.")
            self.state.disconnecting_players.add(username)
            if api_player: asyncio.create_task(self.api.PlayerDisconnected.invoke(api_player))
        if not writer.is_closing():
            try: writer.close(); await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError, OSError): pass
    
    async def _process_incoming_packet(self, username: str, packet: bytes):
        if username not in self.state.players: return
        try: data = json.loads(packet)
        except json.JSONDecodeError: warn(f"Received malformed JSON from {username}."); return
        if "PositionService" in data:
            self.state.update_player_position(username, data)
            player_api = self.state.get_api_player(username)
            if player_api: asyncio.create_task(self.api.DataReceived.invoke(player_api, self.state.player_positions.get(username)))
        if "ChatService" in data:
            chat_block = data.get("ChatService")
            if chat_block and isinstance(chat_block, dict) and "Pending" in chat_block:
                await self.handle_chat_message(username, str(chat_block["Pending"]))
    
    async def handle_chat_message(self, author: str, message_raw: str):
        message_clean = message_raw[:150].strip()
        if not message_clean: return
        is_valid, error_msg = self.state.validate_chat_message(author, message_clean)
        if is_valid:
            log(f"CHAT: [{author}] {message_clean}"); self.state.add_chat_message(author, message_clean)
        else:
            player_data = self.state.players.get(author)
            if player_data and not player_data["writer"].is_closing():
                error_chat_string = f"[Server] Lỗi: {error_msg}\n" + self.state.get_chat_string()
                error_packet = {"ChatService": {"Chat": error_chat_string}}
                await self.send_data_unprotected(player_data["writer"], error_packet)

    async def _broadcast_packet(self, data_dict: dict):
        players_snapshot = list(self.state.players.items())
        tasks = [self.send_data(username, player_data['writer'], data_dict) for username, player_data in players_snapshot]
        if tasks: await asyncio.gather(*tasks)

    async def _data_polling_loop(self):
        while True:
            await asyncio.sleep(self.update_interval)
            try:
                if not self.state.players: continue
                service_block = {
                    "PlayerService": {"Players": self.state.get_all_player_names()},
                    "PositionService": {"Positions": self.state.player_positions, "TimestampFormatted": time.strftime("%H:%M:%S"), "TimestampEpoch": time.mktime(time.localtime()), "CurrentServerTime": time.perf_counter()},
                    "ChatService": {"Chat": self.state.get_chat_string()}
                }; await self._broadcast_packet(service_block)
            except Exception as e: error(f"CRITICAL Error in data_polling_loop: {e}")
    
    async def _reap_disconnected_players_loop(self):
        await asyncio.sleep(PLAYER_REAP_DELAY)
        while True:
            await asyncio.sleep(PLAYER_REAP_DELAY)
            if not self.state.disconnecting_players: continue
            players_to_reap = list(self.state.disconnecting_players)
            log(f"Reaper task running. Found {len(players_to_reap)} players to reap.")
            for username in players_to_reap: self.state.remove_player_fully(username)

async def main():
    config_path = os.path.join(script_directory, "config.json")
    if not os.path.exists(config_path):
        print(f"{Fore.RED}[ERROR] No config.json found!"); sys.exit(1)
    try:
        with open(config_path, 'r', encoding='utf-8') as f: settings = json.load(f)
    except json.JSONDecodeError:
        print(f"{Fore.RED}[ERROR] Corrupted config.json!"); sys.exit(1)
    
    server = Server(settings)
    try:
        await server.start()
    except KeyboardInterrupt:
        log("Shutdown initiated by user (Ctrl+C).")
    finally:
        log("Calling shutdown routine...")
        await server.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass