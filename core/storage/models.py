import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class EntryModel(Base):
    __tablename__ = "entries"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False, index=True, unique=True)
    entry_type = Column(String, nullable=False, default="generic")
    content = Column(Text, default="")
    tags = Column(Text, default="[]")           # JSON list
    aliases = Column(Text, default="[]")        # JSON list
    metadata_json = Column(Text, default="{}")  # JSON object
    internal_refs = Column(Text, default="[]")  # JSON list
    scripts_json = Column(Text, default="[]")   # JSON list of ScriptAttachment dicts
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "entry_type": self.entry_type,
            "content": self.content,
            "tags": json.loads(self.tags or "[]"),
            "aliases": json.loads(self.aliases or "[]"),
            "metadata": json.loads(self.metadata_json or "{}"),
            "internal_refs": json.loads(self.internal_refs or "[]"),
            "scripts": json.loads(self.scripts_json or "[]"),
        }


class EdgeModel(Base):
    __tablename__ = "edges"

    id = Column(String, primary_key=True)
    source_id = Column(String, nullable=False, index=True)
    target_id = Column(String, nullable=False, index=True)
    relation = Column(String, nullable=False, default="wikilink")
    weight = Column(Float, default=1.0)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "weight": self.weight,
            "metadata": json.loads(self.metadata_json or "{}"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
