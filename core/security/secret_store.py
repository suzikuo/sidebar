import base64
import ctypes
import os
from ctypes import wintypes


PROTECTED_SECRET_PREFIX = "dpapi:v1:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretProtectionError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def is_protected_secret(value: str) -> bool:
    return str(value or "").startswith(PROTECTED_SECRET_PREFIX)


def protect_secret(value: str) -> str:
    secret = str(value or "")
    if not secret or is_protected_secret(secret):
        return secret
    encrypted = _crypt_protect(secret.encode("utf-8"))
    return PROTECTED_SECRET_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_secret(value: str) -> str:
    protected = str(value or "")
    if not protected or not is_protected_secret(protected):
        return protected

    encoded = protected[len(PROTECTED_SECRET_PREFIX) :]
    try:
        encrypted = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretProtectionError("Protected secret is not valid base64 data.") from exc

    try:
        return _crypt_unprotect(encrypted).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretProtectionError("Protected secret did not contain valid UTF-8.") from exc


def _require_windows():
    if os.name != "nt":
        raise SecretProtectionError("Windows DPAPI is only available on Windows.")


def _input_blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    return blob, buffer


def _blob_bytes(blob: _DataBlob) -> bytes:
    if not blob.pbData or not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _crypt_protect(data: bytes) -> bytes:
    _require_windows()
    input_blob, input_buffer = _input_blob(data)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32

    result = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "AgileTiles",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = input_buffer
    if not result:
        raise SecretProtectionError(str(ctypes.WinError()))

    try:
        return _blob_bytes(output_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    _require_windows()
    input_blob, input_buffer = _input_blob(data)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32

    result = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = input_buffer
    if not result:
        raise SecretProtectionError(str(ctypes.WinError()))

    try:
        return _blob_bytes(output_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
