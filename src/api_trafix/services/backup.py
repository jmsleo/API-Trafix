import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import redis.exceptions
from fastapi import UploadFile
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import async_session_maker, engine
from api_trafix.config.redis import get_redis
from api_trafix.config.settings import get_settings
from api_trafix.crud import backup as crud
from api_trafix.models import Backup, BackupStatus, User
from api_trafix.services.audit import log_action


logger = logging.getLogger(__name__)


class BackupError(Exception):
    pass


_lock = asyncio.Lock()


def _libpq_url() -> str:
    return get_settings().database_url.replace("+asyncpg", "", 1)


def _backup_dir() -> Path:
    path = Path(get_settings().backup_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _detect_format(data: bytes) -> str:
    if data[:5] == b"PGDMP":
        return "custom"
    return "plain"


def resolve_download_path(backup: Backup) -> Path:
    directory = _backup_dir()
    path = (directory / backup.filename).resolve()
    if path.parent != directory:
        raise BackupError("Path file backup tidak valid")
    return path


async def _flush_cache_and_sessions() -> None:
    try:
        r = await get_redis()
        for pattern in ("session:*", "cache:*"):
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    await r.delete(*keys)
                if cursor == 0:
                    break
    except (redis.exceptions.RedisError, OSError):
        pass


async def start_backup(db: AsyncSession, user: User) -> Backup:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{stamp}_{uuid.uuid4().hex[:8]}.dump"

    record = Backup(
        filename=filename,
        format="custom",
        size_bytes=0,
        progress=0,
        status=BackupStatus.RUNNING,
        created_by=user.id,
    )
    db.add(record)
    await db.commit()

    asyncio.create_task(_perform_backup(record.id, user.id))
    return record


async def run_daily_backup() -> Backup:
    """Create a backup record and kick off the dump without a user context.

    Used by the daily scheduler; ``created_by`` stays NULL and the audit log is
    skipped (there is no actor).
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"scheduled_{stamp}_{uuid.uuid4().hex[:8]}.dump"

    async with async_session_maker() as db:
        record = Backup(
            filename=filename,
            format="custom",
            size_bytes=0,
            progress=0,
            status=BackupStatus.RUNNING,
            created_by=None,
        )
        db.add(record)
        await db.commit()
        record_id = record.id

    asyncio.create_task(_perform_backup(record_id, None))
    logger.info("daily_backup: scheduled backup %s started", filename)
    return record


async def _perform_backup(backup_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    async with _lock, async_session_maker() as db:
            record = await crud.get_by_id(db, backup_id)
            if record is None:
                return
            user = await db.get(User, user_id) if user_id is not None else None
            await db.commit()
            filename = record.filename
            target = _backup_dir() / filename
            url = _libpq_url()
            timeout = get_settings().backup_restore_timeout_seconds

            try:
                with open(target, "wb") as out:
                    proc = await asyncio.create_subprocess_exec(
                        "pg_dump",
                        "-Fc",
                        "--no-password",
                        f"--dbname={url}",
                        stdout=out,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                        target.unlink(missing_ok=True)
                        record.status = BackupStatus.FAILED
                        record.error_message = f"Backup melebihi batas waktu {timeout} detik"
                        record.progress = 0
                        await db.commit()
                        if user is not None:
                            await log_action(
                                db, "backup", "create", user.id, user.role.value,
                                f"Backup melebihi batas waktu: {filename}",
                            )
                        return

                record.progress = 80
                await db.commit()

                if proc.returncode != 0:
                    err = (stderr or b"").decode(errors="replace")[-2000:]
                    target.unlink(missing_ok=True)
                    record.status = BackupStatus.FAILED
                    record.error_message = err or "pg_dump gagal"
                    record.progress = 0
                    await db.commit()
                    if user is not None:
                        await log_action(
                            db, "backup", "create", user.id, user.role.value,
                            f"Backup gagal: {filename}",
                        )
                    return

                size = target.stat().st_size
                if size == 0:
                    target.unlink(missing_ok=True)
                    record.status = BackupStatus.FAILED
                    record.error_message = "File backup kosong"
                    record.progress = 0
                    await db.commit()
                    if user is not None:
                        await log_action(
                            db, "backup", "create", user.id, user.role.value,
                            f"Backup gagal: {filename}",
                        )
                    return

                record.size_bytes = size
                record.status = BackupStatus.COMPLETED
                record.error_message = None
                record.progress = 100
                await db.commit()
                if user is not None:
                    await log_action(
                        db, "backup", "create", user.id, user.role.value,
                        f"Backup {filename} berhasil dibuat ({size} byte)",
                    )
            except Exception as exc:  # noqa: BLE001 - background task: any failure marks the backup FAILED
                target.unlink(missing_ok=True)
                record.status = BackupStatus.FAILED
                record.error_message = str(exc)[-2000:]
                record.progress = 0
                await db.commit()


async def import_upload(db: AsyncSession, user: User, upload: UploadFile) -> Backup:
    async with _lock:
        directory = _backup_dir()
        base_name = Path(upload.filename or "").name
        stem, suffix = Path(base_name).stem, Path(base_name).suffix
        if not stem:
            stem = f"upload_{uuid.uuid4().hex[:8]}"
            suffix = ".dump"
        final_name = f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
        target = directory / final_name

        max_bytes = get_settings().backup_upload_max_mb * 1024 * 1024
        total = 0
        detected = None
        try:
            with open(target, "wb") as f:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise BackupError(
                            f"File yang diunggah melebihi batas {get_settings().backup_upload_max_mb} MB"
                        )
                    if detected is None:
                        detected = _detect_format(chunk)
                    f.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise

        if total == 0:
            target.unlink(missing_ok=True)
            raise BackupError("File yang diunggah kosong")

        record = Backup(
            filename=final_name,
            format=detected or "plain",
            size_bytes=total,
            status=BackupStatus.COMPLETED,
            created_by=user.id,
        )
        db.add(record)
        await db.commit()
        await log_action(
            db, "backup", "upload", user.id, user.role.value,
            f"Backup {final_name} berhasil diunggah ({total} byte, format {record.format})",
        )
        return record


async def start_restore(db: AsyncSession, backup: Backup, user: User) -> Backup:
    if backup.status != BackupStatus.COMPLETED:
        raise BackupError("Tidak dapat memulihkan dari backup yang belum selesai")
    path = _backup_dir() / backup.filename
    if not path.is_file():
        raise BackupError("File backup tidak ditemukan pada disk")

    backup.status = BackupStatus.RUNNING
    backup.progress = 0
    await db.commit()

    asyncio.create_task(_perform_restore(backup.id, user.id))
    return backup


async def _perform_restore(backup_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with _lock, async_session_maker() as db:
        try:
            backup = await crud.get_by_id(db, backup_id)
            if backup is None:
                return
            user = await db.get(User, user_id)
            path = _backup_dir() / backup.filename
            if not path.is_file():
                backup.status = BackupStatus.FAILED
                backup.error_message = "File backup tidak ditemukan pada disk"
                await db.commit()
                return

            await db.commit()

            url = _libpq_url()
            timeout = get_settings().backup_restore_timeout_seconds

            async def _run(cmd: list[str]) -> tuple[int, bytes]:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise BackupError(f"Pemulihan melebihi batas waktu {timeout} detik") from None
                return proc.returncode, (stderr or stdout or b"")

            if backup.format == "custom":
                returncode, output = await _run(
                    [
                        "pg_restore",
                        "--no-password",
                        "--clean",
                        "--if-exists",
                        "--no-owner",
                        "--no-privileges",
                        f"--dbname={url}",
                        str(path),
                    ]
                )
                if returncode != 0:
                    raise BackupError(
                        output.decode(errors="replace")[-2000:] or "pg_restore failed"
                    )
            else:
                returncode, output = await _run(
                    [
                        "psql",
                        "--no-password",
                        f"--dbname={url}",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-q",
                        "-c",
                        "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
                    ]
                )
                if returncode != 0:
                    raise BackupError(
                        output.decode(errors="replace")[-2000:]
                        or "Failed to clear schema before restore"
                    )
                returncode, output = await _run(
                    [
                        "psql",
                        "--no-password",
                        f"--dbname={url}",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-q",
                        "-f",
                        str(path),
                    ]
                )
                if returncode != 0:
                    raise BackupError(
                        output.decode(errors="replace")[-2000:] or "psql restore failed"
                    )

            # --- restore subprocess succeeded ---
            now = datetime.now(UTC)
            snap_id = backup.id
            snap_filename = backup.filename
            snap_user_role = user.role.value if user is not None else None

            # Dispose the engine so stale connections from the old schema are
            # discarded; the next session will get a fresh connection.
            await engine.dispose()

            # Use a fresh session for the post-restore update.
            async with async_session_maker() as new_db:
                await new_db.execute(
                    update(Backup)
                    .where(Backup.id == snap_id)
                    .values(
                        status=BackupStatus.COMPLETED,
                        progress=100,
                        error_message=None,
                        last_restored_at=now,
                        last_restored_by=user_id,
                        updated_at=now,
                    )
                )
                await new_db.commit()

            await _flush_cache_and_sessions()

            async with async_session_maker() as audit_db:
                if user is not None:
                    await log_action(
                        audit_db,
                        "backup",
                        "restore",
                        user_id,
                        snap_user_role,
                        f"Database berhasil dipulihkan dari {snap_filename}",
                    )

        except BackupError as exc:
            async with async_session_maker() as fail_db:
                if user is not None:
                    await log_action(
                        fail_db,
                        "backup",
                        "restore",
                        user.id,
                        user.role.value,
                        f"Pemulihan gagal: {backup.filename}: {exc}",
                    )
                await fail_db.execute(
                    update(Backup)
                    .where(Backup.id == backup_id)
                    .values(
                        status=BackupStatus.FAILED,
                        error_message=str(exc),
                        progress=0,
                    )
                )
                await fail_db.commit()

        except Exception as exc:  # noqa: BLE001 - background task: any failure marks the restore FAILED
            try:
                async with async_session_maker() as fail_db:
                    await fail_db.execute(
                        update(Backup)
                        .where(Backup.id == backup_id)
                        .values(
                            status=BackupStatus.FAILED,
                            error_message=str(exc)[-2000:],
                            progress=0,
                        )
                    )
                    await fail_db.commit()
            except Exception:  # noqa: BLE001
                pass


async def delete_backup(db: AsyncSession, backup: Backup, user: User) -> None:
    async with _lock:
        path = _backup_dir() / backup.filename
        path.unlink(missing_ok=True)
        await db.delete(backup)
        await db.commit()
        await log_action(
            db, "backup", "delete", user.id, user.role.value,
            f"Backup {backup.filename} berhasil dihapus",
        )
