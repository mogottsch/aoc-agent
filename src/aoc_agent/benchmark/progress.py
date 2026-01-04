from dataclasses import dataclass, field

from rich.table import Table


@dataclass
class ModelProgress:
    total: int = 0
    completed: int = 0
    saved: int = 0
    infra_error: int = 0


@dataclass
class ProgressTracker:
    models: dict[str, ModelProgress] = field(default_factory=dict)

    def init_model(self, model_id: str, total_tasks: int) -> None:
        self.models[model_id] = ModelProgress(total=total_tasks)

    def record_result(self, model_id: str, *, saved: bool) -> None:
        prog = self.models[model_id]
        prog.completed += 1
        if saved:
            prog.saved += 1
        else:
            prog.infra_error += 1

    def build_table(self) -> Table:
        table = Table(title="Benchmark Progress", expand=False)
        table.add_column("Model", style="cyan", no_wrap=True)
        table.add_column("Progress", justify="right")
        table.add_column("✅ Saved", justify="right", style="green")
        table.add_column("❌ Infra", justify="right", style="red")

        for model_id, prog in sorted(self.models.items()):
            table.add_row(
                model_id,
                f"{prog.completed}/{prog.total}",
                str(prog.saved),
                str(prog.infra_error),
            )
        return table
