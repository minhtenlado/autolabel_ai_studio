"""Single background maintenance operation, serialized with inference/review."""

import json
import threading
from ..database.store import connect


class TaskManager:
    def __init__(self, runner):
        self.runner = runner
        self.thread = None

    def run(self, kind, operation, background=False):
        with self.runner.lock:
            if self.runner.busy() or self.runner.maintenance:
                raise RuntimeError(
                    "Đang có tác vụ. Chờ hoàn tất hoặc dừng job trước khi tiếp tục."
                )
            self.runner.maintenance = True
            try:
                with connect() as db:
                    tid = db.execute(
                        "INSERT INTO tasks(kind,state,message) VALUES(?,'running','Đang chuẩn bị…')",
                        (kind,),
                    ).lastrowid
            except Exception:
                self.runner.maintenance = False
                raise

        def progress(done, total, message):
            with connect() as db:
                db.execute(
                    "UPDATE tasks SET completed=?,total=?,message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (done, total, message, tid),
                )

        def execute():
            try:
                result = operation(progress)
                with connect() as db:
                    db.execute(
                        "UPDATE tasks SET state='completed',completed=total,result=?,message='Hoàn tất',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (json.dumps(result, ensure_ascii=False), tid),
                    )
                return result
            except Exception as exc:
                with connect() as db:
                    db.execute(
                        "UPDATE tasks SET state='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (str(exc)[:1500], tid),
                    )
                if not background:
                    raise
            finally:
                with self.runner.lock:
                    self.runner.maintenance = False

        if background:
            self.thread = threading.Thread(
                target=execute, daemon=True, name="workspace-task"
            )
            self.thread.start()
            return {"task_id": tid, "state": "running"}
        return execute()


def task_detail(tid=None):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM tasks "
            + ("WHERE id=?" if tid else "ORDER BY id DESC LIMIT 1"),
            (tid,) if tid else (),
        ).fetchone()
    if not row:
        return None
    value = dict(row)
    value["result"] = json.loads(value["result"]) if value["result"] else None
    return value
