"""Lokalisasi pesan validasi Pydantic agar respons API menggunakan Bahasa Indonesia.

Pesan yang diterjemahkan hanyalah nilai (value) dari `errors[].msg`, tanpa mengubah
struktur maupuan kunci (key) dari respons yang dikirim.
"""

from __future__ import annotations

import re
from typing import Any

# Pesan bawaan (constraint) Pydantic v2 diterjemahkan berdasarkan `type`-nya.
_CONSTRAINT_MESSAGES: dict[str, str] = {
    "missing": "Kolom ini wajib diisi",
    "extra_forbidden": "Input tidak boleh mengandung data tambahan",
    "string_type": "Nilai harus berupa teks",
    "string_too_short": "Panjang minimal adalah {0} karakter",
    "string_too_long": "Panjang maksimal adalah {1} karakter",
    "string_pattern_mismatch": "Format tidak sesuai dengan ketentuan",
    "string_unicode": "Nilai harus berupa teks",
    "int_type": "Nilai harus berupa angka",
    "int_parsing": "Nilai harus berupa angka",
    "int_ge": "Nilai harus lebih besar dari atau sama dengan {2}",
    "int_le": "Nilai harus lebih kecil dari atau sama dengan {2}",
    "greater_than": "Nilai harus lebih besar dari {2}",
    "greater_than_equal": "Nilai harus lebih besar dari atau sama dengan {2}",
    "less_than": "Nilai harus lebih kecil dari {2}",
    "less_than_equal": "Nilai harus lebih kecil dari atau sama dengan {2}",
    "literal_error": "Nilai harus salah satu dari pilihan yang tersedia",
    "enum": "Nilai bukan pilihan yang valid",
    "finite_number": "Nilai harus berupa angka yang valid",
    "url_parsing": "URL tidak valid",
    "email_type": "Format email tidak valid",
    "uuid_type": "Format ID (UUID) tidak valid",
    "date_type": "Format tanggal tidak valid",
    "datetime_type": "Format tanggal waktu tidak valid",
    "bool_type": "Nilai harus berupa nilai boolean",
    "decimal_type": "Nilai harus berupa angka",
    "list_type": "Nilai harus berupa daftar (array)",
    "float_type": "Nilai harus berupa angka",
    "union_tag_invalid": "Nilai tidak valid",
    "model_type": "Data tidak valid",
}

# Pesan dari validator manual (ValueError) yang muncul sebagai
# "Value error, <pesan>" pada errors[].msg. Diterjemahkan berdasarkan teks aslinya.
_VALUE_ERROR_MESSAGES: dict[str, str] = {
    "Password must contain an uppercase letter": "Password harus mengandung huruf kapital",
    "Password must contain a lowercase letter": "Password harus mengandung huruf kecil",
    "Password must contain a digit": "Password harus mengandung angka",
    "Password must not be the same as the username": "Password tidak boleh sama dengan username",
    "A shift crossing midnight must finish after midnight (finish < start)": "Shift yang melewati tengah malam harus selesai setelah tengah malam (selesai < mulai)",
    "A non-crossing shift must finish after it starts": "Shift yang tidak melewati tengah malam harus selesai setelah waktu mulainya",
    "end_time must be after start_time": "waktu selesai (end_time) harus setelah waktu mulai (start_time)",
    "available_capacity must not exceed total_capacity": "kapasitas tersedia (available_capacity) tidak boleh melebihi kapasitas total (total_capacity)",
    "exit_time must not be before entry_time": "waktu keluar (exit_time) tidak boleh sebelum waktu masuk (entry_time)",
    "Completed transactions require exit_time, exit_gate_id, exit_shift_id and exit_operator_id": "Transaksi yang selesai membutuhkan exit_time, exit_gate_id, exit_shift_id, dan exit_operator_id",
    "police_number and vehicle_type_id must be provided together": "police_number dan vehicle_type_id harus diisi bersamaan",
    'time must be in "HH:MM" 24-hour format': 'waktu harus dalam format "HH:MM" 24 jam',
}

# Pola pesan ValueError yang bersifat parametrik (mengandung nilai dinamis).
_VALUE_ERROR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^invalid timezone: (.+)$", re.IGNORECASE), r"zona waktu tidak valid: \1"),
]


def _translate_value_error(msg: str) -> str | None:
    prefix = "Value error, "
    if msg.startswith(prefix):
        inner = msg[len(prefix):]
        translated = _VALUE_ERROR_MESSAGES.get(inner)
        if translated is not None:
            return translated
        for pattern, replacement in _VALUE_ERROR_PATTERNS:
            matched = pattern.match(inner)
            if matched:
                return re.sub(pattern, replacement, inner)
    return _VALUE_ERROR_MESSAGES.get(msg)


def _format_constraint(error_type: str, ctx: dict[str, Any] | None) -> str | None:
    template = _CONSTRAINT_MESSAGES.get(error_type)
    if template is None:
        return None
    per_min = str(ctx.get("min_length", "")) if ctx else ""
    per_max = str(ctx.get("max_length", "")) if ctx else ""
    value = str(ctx.get("ge", "") if ctx is not None and "ge" in ctx
                 else ctx.get("gt", "") if ctx is not None and "gt" in ctx
                 else ctx.get("le", "") if ctx is not None and "le" in ctx
                 else ctx.get("lt", "") if ctx is not None and "lt" in ctx
                 else "") if ctx else ""
    return template.format(per_min, per_max, value)


def localize_pydantic_error(error: dict[str, Any]) -> str:
    """Menerjemahkan `msg` dari satu error validasi Pydantic.

    Mengembalikan pesan terjemahan bila pola dikenali, selain itu mengembalikan
    pesan asli agar respons tetap aman (tidak pernah memodifikasi struktur).
    """
    error_type = str(error.get("type", ""))
    msg = str(error.get("msg", ""))
    ctx = error.get("ctx")

    translated = _translate_value_error(msg)
    if translated is not None:
        return translated

    translated = _format_constraint(error_type, ctx if isinstance(ctx, dict) else None)
    if translated is not None:
        return translated

    return msg
