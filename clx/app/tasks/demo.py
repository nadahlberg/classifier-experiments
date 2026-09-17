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


@app.task
def demo_chat_turn_run_task(thread_id: str) -> None:
    demo_service.demo_chat_turn_run(thread_id)


@app.task
def demo_chat_thread_title_generate_task(thread_id: str) -> None:
    demo_service.demo_chat_thread_title_generate(thread_id)
