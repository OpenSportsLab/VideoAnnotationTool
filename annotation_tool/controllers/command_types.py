from enum import Enum, auto


class CmdType(Enum):
    """Command types recorded in the undo/redo history."""

    ANNOTATION_CONFIRM = auto()
    BATCH_ANNOTATION_CONFIRM = auto()

    SMART_ANNOTATION_RUN = auto()
    BATCH_SMART_ANNOTATION_RUN = auto()

    SCHEMA_ADD_CAT = auto()
    SCHEMA_DEL_CAT = auto()
    SCHEMA_REN_CAT = auto()

    SCHEMA_ADD_LBL = auto()
    SCHEMA_DEL_LBL = auto()
    SCHEMA_REN_LBL = auto()

    LOC_EVENT_ADD = auto()
    LOC_EVENT_DEL = auto()
    LOC_EVENT_MOD = auto()

    DESC_EDIT = auto()

    DENSE_EVENT_ADD = auto()
    DENSE_EVENT_DEL = auto()
    DENSE_EVENT_MOD = auto()
