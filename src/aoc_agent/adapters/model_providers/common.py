from aoc_agent.adapters.model_types import AvailableModel


def extract_model_items(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        msg = "Provider returned an unsupported models payload"
        raise TypeError(msg)
    data = payload.get("data")
    if isinstance(data, list):
        return data
    items = payload.get("models")
    if isinstance(items, list):
        return items
    msg = "Provider returned a models payload without a model list"
    raise ValueError(msg)


def parse_openai_model_item(item: object) -> AvailableModel:
    if not isinstance(item, dict):
        msg = "Provider returned a malformed model entry"
        raise TypeError(msg)
    model_id = read_string(item, "id") or read_string(item, "name")
    if model_id is None:
        msg = "Provider returned a model entry without an id"
        raise ValueError(msg)
    return AvailableModel(
        id=model_id,
        name=read_string(item, "name"),
        owned_by=read_string(item, "owned_by"),
        context_length=read_context_length(item),
    )


def parse_google_model_item(item: object) -> AvailableModel:
    if not isinstance(item, dict):
        msg = "Provider returned a malformed model entry"
        raise TypeError(msg)
    name = read_string(item, "name")
    if name is None:
        msg = "Provider returned a model entry without a name"
        raise ValueError(msg)
    model_id = name.split("/")[-1]
    return AvailableModel(
        id=model_id,
        name=read_string(item, "displayName") or model_id,
        owned_by="google",
        context_length=coerce_int(item.get("inputTokenLimit")),
    )


def read_string(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None


def read_context_length(data: dict[str, object]) -> int | None:
    direct = coerce_int(data.get("context_length"))
    if direct is not None:
        return direct
    top_provider = data.get("top_provider")
    if not isinstance(top_provider, dict):
        return None
    return coerce_int(top_provider.get("context_length"))


def coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
