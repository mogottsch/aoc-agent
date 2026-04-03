from aoc_rl.dataset.manifest import AocTaskRecord, Split

TRAIN_MAX_YEAR = 2021
VALIDATION_YEAR = 2022
TEST_YEAR = 2023


def assign_default_split(year: int) -> Split:
    if year <= TRAIN_MAX_YEAR:
        return Split.TRAIN
    if year == VALIDATION_YEAR:
        return Split.VALIDATION
    if year == TEST_YEAR:
        return Split.TEST
    return Split.HOLDOUT


def with_default_split(record: AocTaskRecord) -> AocTaskRecord:
    if record.split != Split.UNASSIGNED:
        return record
    return record.model_copy(update={"split": assign_default_split(record.year)})
