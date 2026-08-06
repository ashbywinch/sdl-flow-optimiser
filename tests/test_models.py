"""Model catalog: schema creates on SQLite and round-trips the core joins."""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sdl_flow_optimiser.models import (
    AssistantCall,
    Base,
    Event,
    Project,
    Session,
    ToolExecution,
)


def test_schema_creates_and_round_trips():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        project = Project(slug="houses", path="/home/ashby/Documents/code/houses", kind="main")
        db.add(project)
        db.flush()

        session = Session(
            id="019fc73f-1c0b-7000-a364-14c006f482ee",
            project_id=project.id,
            title="Fix architecture tests path matching",
            title_source="auto",
            started_at_ms=1_000,
            ended_at_ms=5_000,
            exit_reason="sigterm",
            file_path="/home/ashby/.omp/agent/sessions/houses/session.jsonl",
            file_sha256="abc123",
            parsed_at_ms=6_000,
        )
        db.add(session)
        db.flush()

        db.add(Event(session_id=session.id, seq=0, type="message", ts_ms=1_100, raw_json={"role": "user"}))
        db.add(
            ToolExecution(
                session_id=session.id,
                tool_call_id="call_00_abc",
                tool_name="read",
                intent="Reading the design doc",
                args_json={"path": "docs/TECHSPEC.md"},
                started_at_ms=1_200,
                finished_at_ms=1_300,
                wall_time_ms=100,
                is_error=False,
            )
        )
        db.add(
            AssistantCall(
                session_id=session.id,
                ts_ms=1_200,
                model="opencode-go/deepseek-v4-flash",
                duration_ms=500,
                tokens_in=10,
                tokens_out=5,
                cache_read=0,
                cache_write=0,
                cost_usd=Decimal("0.0001888544"),
                stop_reason="toolUse",
                interrupted=False,
            )
        )
        db.commit()

    with session_factory() as db:
        assert db.query(Session).one().title == "Fix architecture tests path matching"
        assert db.query(Event).one().raw_json == {"role": "user"}
        assert db.query(ToolExecution).one().intent == "Reading the design doc"
        assert db.query(AssistantCall).one().cost_usd == Decimal("0.0001888544")
        # the session → events relationship resolves
        assert [e.type for e in db.query(Session).one().events] == ["message"]


def test_json_variant_is_jsonb_on_postgres_dialect():
    from sqlalchemy.dialects import postgresql

    from sdl_flow_optimiser.models.base import JSON_VARIANT

    compiled = JSON_VARIANT.compile(dialect=postgresql.dialect())
    assert compiled == "JSONB"
