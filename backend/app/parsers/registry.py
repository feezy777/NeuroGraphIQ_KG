from app.models.base import ResourceType
from app.parsers.aal3_parser import AAL3Parser
from app.parsers.allen_parser import AllenParser
from app.parsers.base_parser import BaseParser
from app.parsers.brainnetome_parser import BrainnetomeParser
from app.parsers.freesurfer_parser import FreeSurferParser
from app.parsers.hcp_mmp_parser import HCPMMPParser
from app.parsers.siibra_parser import SiibraParser
from app.parsers.terminology_parser import TerminologyParser

_PARSER_MAP: dict[str, type[BaseParser]] = {
    ResourceType.aal3: AAL3Parser,
    ResourceType.brainnetome: BrainnetomeParser,
    ResourceType.allen: AllenParser,
    ResourceType.freesurfer: FreeSurferParser,
    ResourceType.hcp_mmp: HCPMMPParser,
    ResourceType.julich_brain: SiibraParser,
    ResourceType.braininfo: TerminologyParser,
    ResourceType.interlex: TerminologyParser,
}


def resolve_parser_name(resource_type: str | ResourceType) -> str:
    """Parser name for DB row; does not instantiate parser (safe for resource_type=other)."""
    key = resource_type.value if isinstance(resource_type, ResourceType) else resource_type
    parser_cls = _PARSER_MAP.get(key)  # type: ignore[arg-type]
    if parser_cls is None:
        return f"{key}_parser"
    return parser_cls.PARSER_NAME


def get_parser(resource_type: str, task_id: str) -> BaseParser:
    parser_cls = _PARSER_MAP.get(resource_type)
    if parser_cls is None:
        raise ValueError(
            f"No parser registered for resource type: {resource_type!r}. "
            f"Supported: {', '.join(_PARSER_MAP.keys())}"
        )
    return parser_cls(task_id=task_id)


def list_parsers() -> list[dict[str, str]]:
    return [
        {"resource_type": rt, "parser_name": cls.PARSER_NAME}
        for rt, cls in _PARSER_MAP.items()
    ]
