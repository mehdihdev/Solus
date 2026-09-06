"""Document wrappers preserve the existing mechanical graph's stable identities."""

from solus_api.connectors.contracts import Domain, EntityOut, RelationOut


def document_root(document_id: str, name: str | None = None) -> EntityOut:
    return EntityOut(
        source_key=f"{document_id}:document",
        type="cad_document",
        domain=Domain.MECHANICAL,
        name=(name or document_id)[:512],
        properties={"document_id": document_id},
    )


def document_contains(
    root: EntityOut, entities: list[EntityOut], relations: list[RelationOut]
) -> list[RelationOut]:
    """Wrap top-level assemblies/parts, retaining every existing part_of edge."""
    parented = {edge.from_key for edge in relations if edge.type == "part_of"}
    parented.update(edge.to_key for edge in relations if edge.type == "contains")
    return [
        RelationOut(from_key=root.source_key, to_key=node.source_key, type="contains")
        for node in entities
        if node.source_key not in parented
    ]
