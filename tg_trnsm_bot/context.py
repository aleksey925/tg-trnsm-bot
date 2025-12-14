from typing import Any, cast

from telegram.ext import CallbackContext, ContextTypes, ExtBot, JobQueue


class BotContext(CallbackContext[ExtBot[None], dict[str, Any], dict[str, Any], dict[str, Any]]):
    @property
    def job_queue(self) -> JobQueue[BotContext]:  # type: ignore[override]
        jq = self.application.job_queue
        if jq is None:
            raise RuntimeError("JobQueue is not configured")
        return cast(JobQueue["BotContext"], jq)


BotContextTypes = ContextTypes(context=BotContext)
