EXPLORER_PAGE_SIZE_KEY = "explorer/samples_per_page"
DEFAULT_EXPLORER_PAGE_SIZE = 500
MIN_EXPLORER_PAGE_SIZE = 100
MAX_EXPLORER_PAGE_SIZE = 2000


def normalize_explorer_page_size(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_EXPLORER_PAGE_SIZE
    return min(max(parsed, MIN_EXPLORER_PAGE_SIZE), MAX_EXPLORER_PAGE_SIZE)


def load_explorer_page_size(settings) -> int:
    if settings is None:
        return DEFAULT_EXPLORER_PAGE_SIZE
    return normalize_explorer_page_size(
        settings.value(EXPLORER_PAGE_SIZE_KEY, DEFAULT_EXPLORER_PAGE_SIZE)
    )
