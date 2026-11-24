from __future__ import annotations

import errno
import os
from pathlib import Path


class InstanceAlreadyRunningError(RuntimeError):
    """Dilemparkan jika proses bot lain masih aktif."""


class SingleInstanceLock:
    def __init__(self, lock_path: str = "logs/.bot_instance.lock") -> None:
        self.lock_path = Path(lock_path)
        self._acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError as exc:
            return exc.errno == errno.EPERM
        return True

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

        while True:
            try:
                fd = os.open(str(self.lock_path), flags, 0o600)
                try:
                    os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
                finally:
                    os.close(fd)
                self._acquired = True
                return
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise

                existing_pid = self._read_pid()
                if existing_pid is not None and self._is_pid_running(existing_pid):
                    raise InstanceAlreadyRunningError(
                        f"Instance bot sudah berjalan dengan PID {existing_pid}."
                    )

                try:
                    self.lock_path.unlink(missing_ok=True)
                except OSError:
                    raise InstanceAlreadyRunningError(
                        f"Lock file tidak dapat dibersihkan: {self.lock_path}"
                    )

    def _read_pid(self) -> int | None:
        try:
            return int(self.lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if self._acquired:
            try:
                self.lock_path.unlink(missing_ok=True)
            finally:
                self._acquired = False

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
