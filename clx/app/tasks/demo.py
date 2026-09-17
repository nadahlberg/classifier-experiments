from clx.app.services import demo as demo_service
from clx.celery import app


@app.task
def demo_heartbeat_task() -> None:
    demo_service.demo_heartbeat()


@app.task
def demo_job_execute_task(job_id: str) -> None:
    demo_service.demo_job_execute(job_id)


@app.task
def demo_docket_reindex_task() -> None:
    demo_service.demo_docket_reindex()
