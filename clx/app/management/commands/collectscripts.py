from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from clx.app.exceptions import ApplicationError
from clx.app.scripts import scripts_dirs
from clx.app.services.scripts import scripts_collect


class Command(BaseCommand):
    help = "Compile every {% script %} block in the templates into a bundle."
    requires_system_checks = ()

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Recompile whenever a template changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["watch"]:
            self.collect(fatal=True)
            return

        self.collect(fatal=False)
        from watchfiles import watch

        for _ in watch(*scripts_dirs()):
            self.collect(fatal=False)

    def collect(self, *, fatal: bool) -> None:
        try:
            output, count = scripts_collect()
        except ApplicationError as error:
            if fatal:
                raise CommandError(str(error)) from error
            self.stderr.write(str(error))
            return
        self.stdout.write(f"{count} script blocks -> {output}")
