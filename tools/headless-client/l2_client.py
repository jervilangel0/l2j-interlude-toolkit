"""
L2 Interlude Headless Client — Connects to login + game server via raw protocol.
No game client needed. Runs on macOS natively.
"""
from __future__ import annotations

import queue
import socket
import struct
import time
import threading
from typing import Callable, Optional

from l2_crypto import (
    LoginCrypt, GameCrypt,
    unscramble_modulus, build_rsa_public_key, rsa_encrypt_credentials,
)


def encode_string(s: str) -> bytes:
    """Encode string as UTF-16LE + null terminator."""
    return s.encode('utf-16-le') + b'\x00\x00'


def decode_string(data: bytearray, offset: int) -> tuple[str, int]:
    """Decode UTF-16LE null-terminated string. Returns (string, bytes_consumed)."""
    end = offset
    while end + 1 < len(data):
        if data[end] == 0 and data[end + 1] == 0:
            break
        end += 2
    s = data[offset:end].decode('utf-16-le', errors='replace')
    return s, end + 2 - offset


class L2LoginClient:
    """Handles the login server protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 2106):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.crypt = LoginCrypt()
        self.session_id = 0
        self.login_ok1 = 0
        self.login_ok2 = 0
        self.play_ok1 = 0
        self.play_ok2 = 0
        self.rsa_key = None
        self.servers = []

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.host, self.port))
        print(f"[LOGIN] Connected to {self.host}:{self.port}")

    def _recv_exact(self, n: int) -> bytes:
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def recv_packet(self) -> bytearray:
        header = self._recv_exact(2)
        length = struct.unpack("<H", header)[0] - 2
        data = bytearray(self._recv_exact(length))
        return data

    def send_packet(self, data: bytearray):
        encrypted = self.crypt.encrypt(data)
        length = len(encrypted) + 2
        self.sock.sendall(struct.pack("<H", length) + bytes(encrypted))

    def login(self, username: str, password: str) -> bool:
        """Full login sequence. Returns True on success."""
        self.connect()

        # Step 1: Receive Init (encrypted with static key)
        raw = self.recv_packet()
        self.crypt.decrypt_init(raw)

        opcode = raw[0]
        if opcode != 0x00:
            print(f"[LOGIN] Unexpected opcode: 0x{opcode:02X}")
            return False

        self.session_id = struct.unpack_from("<I", raw, 1)[0]
        protocol = struct.unpack_from("<I", raw, 5)[0]
        scrambled_modulus = bytes(raw[9:9+128])
        bf_key = bytes(raw[137+16:137+16+16])  # after 4 GG constants

        # Parse BF key position: 9 + 128 (modulus) + 16 (4 ints GG) = 153
        bf_key = bytes(raw[153:153+16])

        print(f"[LOGIN] Init: session=0x{self.session_id:08X}, protocol=0x{protocol:08X}")

        # Set up dynamic Blowfish
        self.crypt.set_key(bf_key)

        # Unscramble RSA
        modulus = unscramble_modulus(scrambled_modulus)
        self.rsa_key = build_rsa_public_key(modulus)

        # Step 2: Send AuthGameGuard
        pkt = bytearray(struct.pack("<BIiiii", 0x07, self.session_id, 0, 0, 0, 0))
        self.send_packet(pkt)

        # Step 3: Receive GGAuth
        raw = self.recv_packet()
        self.crypt.decrypt(raw)
        if raw[0] != 0x0B:
            print(f"[LOGIN] Expected GGAuth (0x0B), got 0x{raw[0]:02X}")
            return False
        print("[LOGIN] GGAuth OK")

        # Step 4: Send RequestAuthLogin (RSA encrypted credentials)
        ciphertext = rsa_encrypt_credentials(self.rsa_key, username, password)
        pkt = bytearray(b'\x00' + ciphertext)
        self.send_packet(pkt)

        # Step 5: Receive LoginOk or LoginFail
        raw = self.recv_packet()
        self.crypt.decrypt(raw)

        if raw[0] == 0x01:  # LoginFail
            reason = struct.unpack_from("<I", raw, 1)[0]
            print(f"[LOGIN] Login FAILED, reason: {reason}")
            return False

        if raw[0] != 0x03:  # LoginOk
            print(f"[LOGIN] Unexpected response: 0x{raw[0]:02X}")
            return False

        self.login_ok1 = struct.unpack_from("<I", raw, 1)[0]
        self.login_ok2 = struct.unpack_from("<I", raw, 5)[0]
        print(f"[LOGIN] LoginOk: key1=0x{self.login_ok1:08X}, key2=0x{self.login_ok2:08X}")

        # Step 6: Request Server List
        pkt = bytearray(struct.pack("<BII", 0x05, self.login_ok1, self.login_ok2))
        self.send_packet(pkt)

        # Step 7: Receive ServerList
        raw = self.recv_packet()
        self.crypt.decrypt(raw)

        if raw[0] != 0x04:
            print(f"[LOGIN] Expected ServerList (0x04), got 0x{raw[0]:02X}")
            return False

        server_count = raw[1]
        print(f"[LOGIN] Server list: {server_count} server(s)")

        offset = 3
        self.servers = []
        for i in range(server_count):
            sid = raw[offset]
            ip = f"{raw[offset+1]}.{raw[offset+2]}.{raw[offset+3]}.{raw[offset+4]}"
            port = struct.unpack_from("<I", raw, offset + 5)[0]
            cur_players = struct.unpack_from("<H", raw, offset + 11)[0]
            max_players = struct.unpack_from("<H", raw, offset + 13)[0]
            status = raw[offset + 15]
            self.servers.append({
                "id": sid, "ip": ip, "port": port,
                "players": cur_players, "max": max_players,
                "status": "UP" if status == 1 else "DOWN"
            })
            print(f"  Server {sid}: {ip}:{port} [{cur_players}/{max_players}] {self.servers[-1]['status']}")
            offset += 21

        return True

    def select_server(self, server_id: int = 1) -> bool:
        """Select a game server and get play keys."""
        pkt = bytearray(struct.pack("<BIIB", 0x02, self.login_ok1, self.login_ok2, server_id))
        self.send_packet(pkt)

        raw = self.recv_packet()
        self.crypt.decrypt(raw)

        if raw[0] == 0x06:  # PlayFail
            print(f"[LOGIN] PlayFail: {raw[1]}")
            return False

        if raw[0] != 0x07:  # PlayOk
            print(f"[LOGIN] Expected PlayOk (0x07), got 0x{raw[0]:02X}")
            return False

        self.play_ok1 = struct.unpack_from("<I", raw, 1)[0]
        self.play_ok2 = struct.unpack_from("<I", raw, 5)[0]
        print(f"[LOGIN] PlayOk: key1=0x{self.play_ok1:08X}, key2=0x{self.play_ok2:08X}")
        return True

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


class L2GameClient:
    """Handles the game server protocol."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.crypt: Optional[GameCrypt] = None
        self._crypt_enabled = False

        # Character state
        self.object_id = 0
        self.x = 0
        self.y = 0
        self.z = 0
        self.heading = 0
        self.name = ""
        self.level = 0
        self.characters = []

        # Packet handlers
        self._handlers: dict[int, Callable] = {}
        self._running = False
        self._recv_thread: Optional[threading.Thread] = None

        # Queue for geodata scan responses (GEODATA|... messages)
        self.geodata_queue: queue.Queue = queue.Queue()
        # Queue for generic system messages
        self.sys_messages: queue.Queue = queue.Queue(maxsize=100)

        # Register default handlers
        self._handlers[0x04] = self._handle_user_info
        self._handlers[0x01] = self._handle_move_to_location
        self._handlers[0x28] = self._handle_teleport
        self._handlers[0x47] = self._handle_stop_move
        self._handlers[0x61] = self._handle_validate_location
        self._handlers[0x76] = self._handle_set_to_location
        self._handlers[0x4A] = self._handle_creature_say

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.host, self.port))
        print(f"[GAME] Connected to {self.host}:{self.port}")

    def _recv_exact(self, n: int) -> bytes:
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def recv_packet(self) -> bytearray:
        header = self._recv_exact(2)
        length = struct.unpack("<H", header)[0] - 2
        if length <= 0:
            return bytearray()
        data = bytearray(self._recv_exact(length))

        if self.crypt:
            self.crypt.decrypt(data)

        return data

    def send_packet(self, data: bytearray):
        if self.crypt:
            data = bytearray(data)  # copy
            self.crypt.encrypt(data)

        length = len(data) + 2
        self.sock.sendall(struct.pack("<H", length) + bytes(data))

    # Base stats for the 9 starting classes (Human Fighter as default)
    # Format: {class_id: (race, STR, DEX, CON, INT, WIT, MEN)}
    BASE_STATS = {
        0x00: (0, 40, 30, 43, 21, 11, 25),  # Human Fighter
        0x0A: (0, 22, 21, 24, 41, 20, 39),  # Human Mystic
        0x12: (1, 36, 35, 36, 23, 14, 26),  # Elf Fighter
        0x19: (1, 21, 24, 25, 37, 23, 37),  # Elf Mystic
        0x1F: (2, 41, 30, 32, 25, 12, 26),  # Dark Elf Fighter
        0x26: (2, 23, 24, 23, 44, 19, 33),  # Dark Elf Mystic
        0x2C: (3, 40, 29, 45, 20, 10, 25),  # Orc Fighter
        0x31: (3, 27, 24, 31, 31, 15, 38),  # Orc Mystic
        0x35: (4, 39, 29, 45, 21, 10, 25),  # Dwarf Fighter
    }

    def _auth_to_game(self, login_name: str, login_ok1: int, login_ok2: int,
                       play_ok1: int, play_ok2: int) -> int:
        """Phase 1: ProtocolVersion → KeyPacket → AuthLogin → CharSelectInfo.
        Returns character count, or -1 on failure.
        """
        self.connect()

        # Step 1: Send ProtocolVersion (UNENCRYPTED)
        pkt = bytearray(struct.pack("<Bh", 0x00, 746))
        length = len(pkt) + 2
        self.sock.sendall(struct.pack("<H", length) + bytes(pkt))

        # Step 2: Receive KeyPacket (UNENCRYPTED)
        header = self._recv_exact(2)
        pkt_len = struct.unpack("<H", header)[0] - 2
        raw = bytearray(self._recv_exact(pkt_len))

        if raw[0] != 0x00:
            print(f"[GAME] Expected KeyPacket (0x00), got 0x{raw[0]:02X}")
            return -1

        ok_flag = raw[1]
        if ok_flag != 0x01:
            print(f"[GAME] KeyPacket rejected: flag={ok_flag}")
            return -1

        xor_key = bytes(raw[2:18])
        print(f"[GAME] KeyPacket received, XOR key: {xor_key.hex()}")

        # Initialize game crypt.
        # Server already called encrypt(KeyPacket) which set _isEnabled=true
        # on its side, so our crypt must also be enabled for AuthLogin to be
        # XOR-encrypted as the server expects.
        self.crypt = GameCrypt(xor_key)
        self.crypt._enabled = True

        # Step 3: Send AuthLogin
        pkt = bytearray(b'\x08')
        pkt.extend(encode_string(login_name.lower()))
        pkt.extend(struct.pack("<IIII", play_ok2, play_ok1, login_ok1, login_ok2))
        self.send_packet(pkt)

        # Step 4: Receive CharSelectInfo
        raw = self.recv_packet()
        if not raw or raw[0] != 0x13:
            print(f"[GAME] Expected CharSelectInfo (0x13), got 0x{raw[0]:02X}")
            if raw and raw[0] == 0x25:
                print("[GAME] ActionFailed — auth may have been rejected")
            return -1

        char_count = struct.unpack_from("<I", raw, 1)[0]
        print(f"[GAME] Character list: {char_count} character(s)")

        # Parse character names (simplified)
        self.characters = []
        offset = 5
        for i in range(char_count):
            try:
                name, consumed = decode_string(raw, offset)
                self.characters.append({"name": name, "slot": i})
                print(f"  [{i}] {name}")
                offset += consumed + 200  # rough skip past remaining char data
            except Exception:
                break

        return char_count

    def create_character(self, name: str, class_id: int = 0x00,
                         sex: int = 0, hair_style: int = 0,
                         hair_color: int = 0, face: int = 0) -> bool:
        """Create a new character on the current game server connection.
        Must be called after _auth_to_game() when char_count == 0.

        Sends NewCharacter (0x0E) → receives CharTemplates (0x17) →
        sends CharacterCreate (0x0B) → receives CharCreateOk (0x19) or CharCreateFail (0x1A).
        """
        # Look up base stats for the class
        if class_id not in self.BASE_STATS:
            print(f"[GAME] Unknown class_id 0x{class_id:02X}, using Human Fighter")
            class_id = 0x00
        race, str_, dex, con, int_, wit, men = self.BASE_STATS[class_id]

        # Step 1: Request character templates (optional but matches real client flow)
        pkt = bytearray(b'\x0E')
        self.send_packet(pkt)

        # Step 2: Receive CharTemplates (0x17) — just consume it
        raw = self.recv_packet()
        if raw and raw[0] == 0x17:
            print("[GAME] Received character templates")
        else:
            print(f"[GAME] Expected CharTemplates (0x17), got 0x{raw[0]:02X}" if raw else "[GAME] No response")
            # Continue anyway — some servers skip this

        # Step 3: Send CharacterCreate (0x0B)
        pkt = bytearray(b'\x0B')
        pkt.extend(encode_string(name))       # name (S)
        pkt.extend(struct.pack("<i", race))    # race (D)
        pkt.extend(struct.pack("<i", sex))     # sex (D)
        pkt.extend(struct.pack("<i", class_id))  # classId (D)
        pkt.extend(struct.pack("<i", int_))    # INT (D)
        pkt.extend(struct.pack("<i", str_))    # STR (D)
        pkt.extend(struct.pack("<i", con))     # CON (D)
        pkt.extend(struct.pack("<i", men))     # MEN (D)
        pkt.extend(struct.pack("<i", dex))     # DEX (D)
        pkt.extend(struct.pack("<i", wit))     # WIT (D)
        pkt.extend(struct.pack("<i", hair_style))  # hairStyle (D)
        pkt.extend(struct.pack("<i", hair_color))  # hairColor (D)
        pkt.extend(struct.pack("<i", face))    # face (D)
        self.send_packet(pkt)

        print(f"[GAME] Creating character '{name}' (class=0x{class_id:02X}, race={race})")

        # Step 4: Receive CharCreateOk (0x19) or CharCreateFail (0x1A)
        raw = self.recv_packet()
        if not raw:
            print("[GAME] No response to CharacterCreate")
            return False

        if raw[0] == 0x19:  # CharCreateOk
            print(f"[GAME] Character '{name}' created successfully!")

            # Server sends updated CharSelectInfo after creation
            raw = self.recv_packet()
            if raw and raw[0] == 0x13:
                char_count = struct.unpack_from("<I", raw, 1)[0]
                self.characters = []
                offset = 5
                for i in range(char_count):
                    try:
                        cname, consumed = decode_string(raw, offset)
                        self.characters.append({"name": cname, "slot": i})
                        offset += consumed + 200
                    except Exception:
                        break
                print(f"[GAME] Updated character list: {char_count} character(s)")
            return True

        if raw[0] == 0x1A:  # CharCreateFail
            reason = struct.unpack_from("<I", raw, 1)[0] if len(raw) >= 5 else -1
            reasons = {
                0: "creation failed",
                1: "too many characters (max 7)",
                2: "name already exists",
                3: "name too long or invalid",
                4: "creation not allowed",
            }
            print(f"[GAME] Character creation FAILED: {reasons.get(reason, f'reason={reason}')}")
            return False

        print(f"[GAME] Unexpected response to CharacterCreate: 0x{raw[0]:02X}")
        return False

    def _select_and_enter(self, char_slot: int = 0) -> bool:
        """Phase 3: CharSelect → CharSelected → EnterWorld → UserInfo."""
        # Select character
        pkt = bytearray(struct.pack("<BiHIII", 0x0D, char_slot, 0, 0, 0, 0))
        self.send_packet(pkt)

        # Receive CharSelected
        raw = self.recv_packet()
        if not raw:
            return False

        if raw[0] == 0x15:  # CharSelected
            offset = 1
            self.name, consumed = decode_string(raw, offset)
            offset += consumed
            self.object_id = struct.unpack_from("<I", raw, offset)[0]
            print(f"[GAME] Character selected: {self.name} (objectId={self.object_id})")

        # Send EnterWorld
        pkt = bytearray(b'\x03')
        self.send_packet(pkt)

        # Read initialization packets until we get UserInfo
        print("[GAME] Entering world, reading init packets...")
        deadline = time.time() + 10
        got_userinfo = False

        while time.time() < deadline:
            try:
                raw = self.recv_packet()
                if not raw:
                    continue

                opcode = raw[0]
                handler = self._handlers.get(opcode)
                if handler:
                    handler(raw)

                if opcode == 0x04:  # UserInfo
                    got_userinfo = True
                    break

            except socket.timeout:
                break

        if got_userinfo:
            print(f"[GAME] In world! Position: ({self.x}, {self.y}, {self.z})")
            return True

        print("[GAME] Entered world but didn't receive UserInfo yet")
        return True

    def enter_world(self, login_name: str, login_ok1: int, login_ok2: int,
                     play_ok1: int, play_ok2: int, char_slot: int = 0) -> bool:
        """Full game server login sequence (original API preserved)."""
        char_count = self._auth_to_game(login_name, login_ok1, login_ok2, play_ok1, play_ok2)
        if char_count < 0:
            return False
        if char_count == 0:
            print("[GAME] No characters! Create one in a regular client first.")
            return False
        return self._select_and_enter(char_slot)

    # ========================================================================
    # PACKET HANDLERS
    # ========================================================================

    def _handle_user_info(self, data: bytearray):
        """Parse UserInfo (opcode 0x04) — our own position and stats."""
        self.x = struct.unpack_from("<i", data, 1)[0]
        self.y = struct.unpack_from("<i", data, 5)[0]
        self.z = struct.unpack_from("<i", data, 9)[0]
        self.heading = struct.unpack_from("<i", data, 13)[0]

    def _handle_move_to_location(self, data: bytearray):
        """Parse CharMoveToLocation (opcode 0x01)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.object_id:
            # Update our destination (we're moving)
            pass

    def _handle_teleport(self, data: bytearray):
        """Parse TeleportToLocation (opcode 0x28)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.object_id:
            self.x = struct.unpack_from("<i", data, 5)[0]
            self.y = struct.unpack_from("<i", data, 9)[0]
            self.z = struct.unpack_from("<i", data, 13)[0]
            print(f"[GAME] Teleported to ({self.x}, {self.y}, {self.z})")

    def _handle_stop_move(self, data: bytearray):
        """Parse StopMove (opcode 0x47)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.object_id:
            self.x = struct.unpack_from("<i", data, 5)[0]
            self.y = struct.unpack_from("<i", data, 9)[0]
            self.z = struct.unpack_from("<i", data, 13)[0]
            self.heading = struct.unpack_from("<i", data, 17)[0]

    def _handle_validate_location(self, data: bytearray):
        """Parse ValidateLocation (opcode 0x61) — server position correction."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.object_id:
            self.x = struct.unpack_from("<i", data, 5)[0]
            self.y = struct.unpack_from("<i", data, 9)[0]
            self.z = struct.unpack_from("<i", data, 13)[0]
            self.heading = struct.unpack_from("<i", data, 17)[0]

    def _handle_set_to_location(self, data: bytearray):
        """Parse SetToLocation (opcode 0x76)."""
        obj_id = struct.unpack_from("<I", data, 1)[0]
        if obj_id == self.object_id:
            self.x = struct.unpack_from("<i", data, 5)[0]
            self.y = struct.unpack_from("<i", data, 9)[0]
            self.z = struct.unpack_from("<i", data, 13)[0]

    def _handle_creature_say(self, data: bytearray):
        """Parse CreatureSay (opcode 0x4A).
        Format: C(opcode) D(objectId) D(messageType) S(charName) S(text)
        Routes GEODATA| messages to geodata_queue for scan workers.
        """
        offset = 1
        # objectId (4 bytes)
        offset += 4
        # messageType (4 bytes)
        offset += 4
        # charName (UTF-16LE null-terminated)
        char_name, consumed = decode_string(data, offset)
        offset += consumed
        # text (UTF-16LE null-terminated)
        text, _ = decode_string(data, offset)

        if text.startswith("GEODATA|") or text.startswith("GEODATA_CHECK|"):
            self.geodata_queue.put(text)
        else:
            # Generic system message
            try:
                self.sys_messages.put_nowait(text)
            except queue.Full:
                pass  # drop old messages

    # ========================================================================
    # ACTIONS
    # ========================================================================

    def send_move(self, target_x: int, target_y: int, target_z: int):
        """Send movement request."""
        pkt = bytearray(struct.pack("<BiiiiiiI",
            0x01,
            target_x, target_y, target_z,
            self.x, self.y, self.z,
            1  # mouse click mode
        ))
        self.send_packet(pkt)

    def send_validate_position(self):
        """Send current position for server validation."""
        pkt = bytearray(struct.pack("<Biiiii",
            0x48,
            self.x, self.y, self.z,
            self.heading,
            0
        ))
        self.send_packet(pkt)

    def send_chat(self, message: str, chat_type: int = 0):
        """Send a chat message. type: 0=ALL, 1=SHOUT, 2=TELL, 3=PARTY."""
        pkt = bytearray(b'\x38')
        pkt.extend(encode_string(message))
        pkt.extend(struct.pack("<I", chat_type))
        self.send_packet(pkt)

    def send_admin_command(self, command: str):
        """Send a GM admin command (e.g. 'move_to 83000 148000 -3400')."""
        pkt = bytearray(b'\x5b')
        pkt.extend(encode_string(command))
        self.send_packet(pkt)
        print(f"[GAME] Admin: //{command}")

    def teleport_to(self, x: int, y: int, z: int):
        """Teleport using GM command."""
        self.send_admin_command(f"move_to {x} {y} {z}")

    def start_packet_loop(self):
        """Start background thread to receive and process packets."""
        self._running = True
        self._recv_thread = threading.Thread(target=self._packet_loop, daemon=True)
        self._recv_thread.start()

    def stop_packet_loop(self):
        self._running = False

    def _packet_loop(self):
        """Background packet processing loop."""
        self.sock.settimeout(1.0)
        while self._running:
            try:
                raw = self.recv_packet()
                if not raw:
                    continue
                opcode = raw[0]
                handler = self._handlers.get(opcode)
                if handler:
                    handler(raw)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[GAME] Packet loop error: {e}")
                break

    def close(self):
        self.stop_packet_loop()
        if self.sock:
            self.sock.close()
            self.sock = None


def full_connect(username: str, password: str,
                 login_host: str = "127.0.0.1", login_port: int = 2106,
                 char_slot: int = 0) -> Optional[L2GameClient]:
    """Complete login -> game server connection. Returns a connected game client."""

    # Login
    login = L2LoginClient(login_host, login_port)
    if not login.login(username, password):
        login.close()
        return None

    if not login.servers:
        print("[ERROR] No game servers available")
        login.close()
        return None

    server = login.servers[0]
    if not login.select_server(server["id"]):
        login.close()
        return None

    # Save session keys
    login_ok1 = login.login_ok1
    login_ok2 = login.login_ok2
    play_ok1 = login.play_ok1
    play_ok2 = login.play_ok2

    login.close()
    time.sleep(0.5)

    # Game server
    game = L2GameClient(server["ip"], server["port"])
    if not game.enter_world(username, login_ok1, login_ok2, play_ok1, play_ok2, char_slot):
        game.close()
        return None

    return game


def full_connect_or_create(username: str, password: str,
                            char_name: str = "",
                            class_id: int = 0x00,
                            login_host: str = "127.0.0.1", login_port: int = 2106,
                            char_slot: int = 0) -> Optional[L2GameClient]:
    """Login → game auth → create character if needed → enter world.

    If the account has no characters, creates one with the given name and class.
    If char_name is empty, uses the username as character name.
    """
    if not char_name:
        char_name = username

    # Phase 1: Login server
    print(f"[{username}] Step 1: Connecting to login server...")
    login = L2LoginClient(login_host, login_port)
    if not login.login(username, password):
        login.close()
        return None

    if not login.servers:
        print(f"[{username}] ERROR: No game servers available")
        login.close()
        return None

    server = login.servers[0]
    print(f"[{username}] Step 2: Selecting server {server['id']} ({server['ip']}:{server['port']})...")
    if not login.select_server(server["id"]):
        login.close()
        return None

    login_ok1 = login.login_ok1
    login_ok2 = login.login_ok2
    play_ok1 = login.play_ok1
    play_ok2 = login.play_ok2
    print(f"[{username}] Step 2: PlayOk received")

    login.close()
    time.sleep(0.5)

    # Phase 2: Game server
    print(f"[{username}] Step 3: Connecting to game server {server['ip']}:{server['port']}...")
    game = L2GameClient(server["ip"], server["port"])
    char_count = game._auth_to_game(username, login_ok1, login_ok2, play_ok1, play_ok2)
    if char_count < 0:
        game.close()
        return None

    if char_count == 0:
        print(f"[{username}] Step 4: Creating character '{char_name}'...")
        if not game.create_character(char_name, class_id=class_id):
            game.close()
            return None

    print(f"[{username}] Step 5: Entering world...")
    if not game._select_and_enter(char_slot):
        game.close()
        return None

    return game
