"""
L2 Interlude Cryptography — Login (Blowfish + RSA) and Game (XOR stream cipher)

The L2 Blowfish is NON-STANDARD: it reads blocks in LITTLE-ENDIAN byte order
instead of the standard big-endian. This is critical for interop.
"""
from __future__ import annotations

import struct
from Crypto.Cipher import Blowfish as _Blowfish
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

# ============================================================================
# L2 BLOWFISH (Little-Endian variant)
# ============================================================================
# L2 uses standard Blowfish but with LE block reads.
# We implement this by byte-swapping each 4-byte word before/after standard BF.

class L2Blowfish:
    """L2-specific Blowfish with little-endian block reading."""

    def __init__(self, key: bytes):
        self._cipher = _Blowfish.new(key, _Blowfish.MODE_ECB)

    def _swap_endian_block(self, data: bytearray, offset: int):
        """Swap endianness of two 32-bit words in an 8-byte block."""
        # Reverse each 4-byte word within the 8-byte block
        data[offset:offset+4] = data[offset:offset+4][::-1]
        data[offset+4:offset+8] = data[offset+4:offset+8][::-1]

    def encrypt(self, data: bytearray, offset: int = 0, length: int = -1) -> bytearray:
        if length < 0:
            length = len(data) - offset
        for i in range(offset, offset + length, 8):
            block = bytearray(data[i:i+8])
            self._swap_endian_block(block, 0)
            encrypted = self._cipher.encrypt(bytes(block))
            block = bytearray(encrypted)
            self._swap_endian_block(block, 0)
            data[i:i+8] = block
        return data

    def decrypt(self, data: bytearray, offset: int = 0, length: int = -1) -> bytearray:
        if length < 0:
            length = len(data) - offset
        for i in range(offset, offset + length, 8):
            block = bytearray(data[i:i+8])
            self._swap_endian_block(block, 0)
            decrypted = self._cipher.decrypt(bytes(block))
            block = bytearray(decrypted)
            self._swap_endian_block(block, 0)
            data[i:i+8] = block
        return data


# ============================================================================
# LOGIN CRYPT (Blowfish + checksum + XOR pass)
# ============================================================================

STATIC_BLOWFISH_KEY = bytes([
    0x6B, 0x60, 0xCB, 0x5B, 0x82, 0xCE, 0x90, 0xB1,
    0xCC, 0x2B, 0x6C, 0x55, 0x6C, 0x6C, 0x6C, 0x6C
])


def login_checksum(data: bytearray, offset: int, size: int) -> bool:
    """Verify L2 login checksum. Last 4 bytes of data are the checksum."""
    chk = 0
    count = size - 4
    for i in range(offset, offset + count, 4):
        chk ^= struct.unpack_from("<I", data, i)[0]
    stored = struct.unpack_from("<I", data, offset + count)[0]
    return chk == stored


def append_checksum(data: bytearray, offset: int, size: int):
    """Compute and write L2 login checksum into the last 4 bytes."""
    chk = 0
    count = size - 4
    for i in range(offset, offset + count, 4):
        chk ^= struct.unpack_from("<I", data, i)[0]
    struct.pack_into("<I", data, offset + count, chk & 0xFFFFFFFF)


def enc_xor_pass(data: bytearray, offset: int, size: int, key: int):
    """Apply XOR pass for login Init packet encryption."""
    ecx = key
    pos = offset + 4  # skip first 4 bytes
    stop = offset + size - 8

    while pos < stop:
        edx = struct.unpack_from("<I", data, pos)[0]
        ecx = (ecx + edx) & 0xFFFFFFFF
        edx ^= ecx
        struct.pack_into("<I", data, pos, edx & 0xFFFFFFFF)
        pos += 4

    struct.pack_into("<I", data, pos, ecx & 0xFFFFFFFF)


def dec_xor_pass(data: bytearray, offset: int, size: int):
    """Reverse the XOR pass on a decrypted Init packet."""
    # Read the stored key from last 4 bytes before checksum area
    stop = offset + size - 8
    ecx = struct.unpack_from("<I", data, stop)[0]

    pos = stop - 4
    while pos >= offset + 4:
        edx = struct.unpack_from("<I", data, pos)[0]
        original = edx ^ ecx
        struct.pack_into("<I", data, pos, original & 0xFFFFFFFF)
        ecx = (ecx - original) & 0xFFFFFFFF
        pos -= 4


class LoginCrypt:
    """Handles login server encryption/decryption."""

    def __init__(self):
        self._static_bf = L2Blowfish(STATIC_BLOWFISH_KEY)
        self._dynamic_bf = None
        self._is_static = True

    def set_key(self, key: bytes):
        self._dynamic_bf = L2Blowfish(key)

    def decrypt_init(self, data: bytearray) -> bytearray:
        """Decrypt the Init packet (uses static key + XOR pass)."""
        self._static_bf.decrypt(data)
        dec_xor_pass(data, 0, len(data))
        return data

    def decrypt(self, data: bytearray) -> bytearray:
        """Decrypt a server packet (uses dynamic key)."""
        self._dynamic_bf.decrypt(data)
        return data

    def encrypt(self, data: bytearray) -> bytearray:
        """Encrypt a client packet (uses dynamic key + checksum)."""
        # Pad to multiple of 8
        pad_size = 8 - (len(data) % 8) if len(data) % 8 != 0 else 0
        # Add 4 for checksum + padding
        total_pad = pad_size + 4
        if (len(data) + total_pad) % 8 != 0:
            total_pad += 8 - ((len(data) + total_pad) % 8)
        data.extend(b'\x00' * total_pad)
        append_checksum(data, 0, len(data))
        self._dynamic_bf.encrypt(data)
        return data


# ============================================================================
# RSA KEY UNSCRAMBLING
# ============================================================================

def unscramble_modulus(scrambled: bytes) -> bytes:
    """Reverse the L2 RSA modulus scrambling.
    Input: 128-byte scrambled modulus from Init packet.
    Output: 128-byte unscrambled modulus (big-endian).
    """
    mod = bytearray(scrambled)

    # Reverse step 4: mod[0x40+i] ^= mod[i] for i in 0..0x3F
    for i in range(0x40):
        mod[0x40 + i] ^= mod[i]

    # Reverse step 3: mod[0x0D+i] ^= mod[0x34+i] for i in 0..3
    for i in range(4):
        mod[0x0D + i] ^= mod[0x34 + i]

    # Reverse step 2: mod[i] ^= mod[0x40+i] for i in 0..0x3F
    for i in range(0x40):
        mod[i] ^= mod[0x40 + i]

    # Reverse step 1: Swap bytes [0x00..0x03] with bytes [0x4D..0x50]
    mod[0x00:0x04], mod[0x4D:0x51] = mod[0x4D:0x51], mod[0x00:0x04]

    return bytes(mod)


def build_rsa_public_key(modulus: bytes):
    """Build an RSA public key from modulus bytes and exponent 65537."""
    # Convert modulus bytes (big-endian) to integer
    n = int.from_bytes(modulus, byteorder='big')
    e = 65537
    return RSA.construct((n, e))


def rsa_encrypt_credentials(pub_key, username: str, password: str) -> bytes:
    """Build and RSA-encrypt the 128-byte credential block."""
    block = bytearray(128)
    # Username at offset 0x5E (94), 14 bytes max
    user_bytes = username.encode('ascii')[:14]
    block[0x5E:0x5E + len(user_bytes)] = user_bytes
    # Password at offset 0x6C (108), 16 bytes max
    pass_bytes = password.encode('ascii')[:16]
    block[0x6C:0x6C + len(pass_bytes)] = pass_bytes
    # ncotp at offset 0x7C (124), 4 bytes LE, usually 0
    struct.pack_into("<I", block, 0x7C, 0)

    # RSA encrypt with no padding (raw RSA)
    # Convert block to integer, do modular exponentiation
    n = pub_key.n
    e = pub_key.e
    plaintext_int = int.from_bytes(bytes(block), byteorder='big')
    ciphertext_int = pow(plaintext_int, e, n)
    ciphertext = ciphertext_int.to_bytes(128, byteorder='big')
    return ciphertext


# ============================================================================
# GAME CRYPT (XOR Stream Cipher)
# ============================================================================

class GameCrypt:
    """L2 game server XOR stream cipher.
    Uses a 16-byte key with a rolling counter in bytes 8-11.
    First encrypt/decrypt call enables the cipher without processing.
    """

    def __init__(self, key: bytes):
        self._in_key = bytearray(key)   # decrypt server->client
        self._out_key = bytearray(key)  # encrypt client->server
        self._enabled = False

    def _advance_key(self, key: bytearray, size: int):
        """Advance the key counter (bytes 8-11 as LE uint32) by size."""
        old = struct.unpack_from("<I", key, 8)[0]
        new = (old + size) & 0xFFFFFFFF
        struct.pack_into("<I", key, 8, new)

    def decrypt(self, data: bytearray) -> bytearray:
        """Decrypt server->client data."""
        if not self._enabled:
            # Passthrough — no XOR, no key advance (matches server behavior)
            return data

        temp = 0
        for i in range(len(data)):
            temp2 = data[i] & 0xFF
            data[i] = (temp2 ^ self._in_key[i & 15] ^ temp) & 0xFF
            temp = temp2

        self._advance_key(self._in_key, len(data))
        return data

    def encrypt(self, data: bytearray) -> bytearray:
        """Encrypt client->server data."""
        if not self._enabled:
            # First call: enable but passthrough, no key advance (matches server)
            self._enabled = True
            return data

        temp = 0
        for i in range(len(data)):
            temp2 = data[i] & 0xFF
            temp = temp2 ^ self._out_key[i & 15] ^ temp
            data[i] = temp & 0xFF

        self._advance_key(self._out_key, len(data))
        return data
